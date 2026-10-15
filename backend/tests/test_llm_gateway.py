import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.llm import ChatMessage, EmbeddingSpec, LLMError, LLMGateway, build_mock_gateway
from app.llm.gateway import FallbackChatClient
from app.llm.mock import MockChatClient, MockEmbeddingClient, MockRerankClient
from app.llm.openai_compat import (
    HttpCaller,
    OpenAIChatClient,
    OpenAIEmbeddingClient,
    OpenAIRerankClient,
)

Handler = (
    Callable[[httpx.Request], httpx.Response]
    | Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
)
SPEC = EmbeddingSpec(model="emb", dim=4, base_url="http://llm/v1")


def caller(handler: Handler, *, retries: int = 2, timeout: float = 5.0) -> HttpCaller:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpCaller(
        http,
        "http://llm/v1",
        api_key="k",
        timeout=timeout,
        max_retries=retries,
        backoff_seconds=0.001,
    )


def embeddings_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {"index": i, "embedding": [float(len(t)), 0.0, 0.0, 1.0]}
        for i, t in enumerate(body["input"])
    ]
    return httpx.Response(200, json={"data": list(reversed(data))})


async def test_embedding_batches_preserve_order_and_cap_concurrency() -> None:
    in_flight = peak = 0
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        requests.append(json.loads(request.content))
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return embeddings_response(request)

    client = OpenAIEmbeddingClient(
        caller(handler),
        SPEC,
        batch_size=2,
        concurrency=2,
        send_dimensions=True,
    )
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    vectors = await client.embed(texts)
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert [len(r["input"]) for r in requests] == [2, 2, 1]
    assert all(r["model"] == "emb" and r["dimensions"] == 4 for r in requests)
    assert peak == 2
    assert await client.embed([]) == []


async def test_embedding_dimension_mismatch_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    client = OpenAIEmbeddingClient(caller(handler), SPEC, batch_size=8, concurrency=1)
    with pytest.raises(LLMError, match="dim 2"):
        await client.embed(["x"])


async def test_retries_transient_errors_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused")
        if calls == 2:
            return httpx.Response(503, text="busy")
        return embeddings_response(request)

    client = OpenAIEmbeddingClient(caller(handler), SPEC, batch_size=8, concurrency=1)
    assert len(await client.embed(["x"])) == 1
    assert calls == 3


async def test_gives_up_after_retries_and_skips_retry_on_client_errors() -> None:
    calls = 0

    def unavailable(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502)

    with pytest.raises(LLMError) as exc:
        await caller(unavailable, retries=2).post_json("/embeddings", {})
    assert exc.value.retryable and calls == 3

    calls = 0

    def bad_request(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad model")

    with pytest.raises(LLMError, match="bad model") as exc:
        await caller(bad_request).post_json("/embeddings", {})
    assert not exc.value.retryable and calls == 1


async def test_timeout_is_enforced_per_call() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(LLMError, match="ReadTimeout"):
        await caller(slow, retries=1).post_json("/rerank", {})


async def test_rerank_parses_cohere_and_tei_formats() -> None:
    def cohere(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["top_n"] == 2 and body["documents"] == ["a", "b", "c"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.5},
                ]
            },
        )

    results = await OpenAIRerankClient(caller(cohere), "rr").rerank("q", ["a", "b", "c"], top_n=2)
    assert [(r.index, r.score) for r in results] == [(2, 0.9), (0, 0.5)]

    def tei(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 1, "score": 0.1}, {"index": 0, "score": 0.7}])

    results = await OpenAIRerankClient(caller(tei), "rr").rerank("q", ["a", "b"])
    assert [r.index for r in results] == [0, 1]


async def test_rerank_dashscope_path_and_instruct() -> None:
    def dashscope(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/reranks"
        body = json.loads(request.content)
        assert body["model"] == "qwen3-rerank" and body["instruct"] == "Find answers."
        return httpx.Response(
            200,
            json={
                "object": "list",
                "results": [{"index": 1, "relevance_score": 0.8}],
                "model": "qwen3-rerank",
                "usage": {"total_tokens": 9},
            },
        )

    client = OpenAIRerankClient(
        caller(dashscope), "qwen3-rerank", path="reranks", instruct="Find answers."
    )
    results = await client.rerank("q", ["a", "b"], top_n=1)
    assert [(r.index, r.score) for r in results] == [(1, 0.8)]


async def test_chat_complete_and_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["stream"]:
            chunks = [{"choices": [{"delta": {"content": c}}]} for c in "你好"]
            sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        assert body["temperature"] == 0.1 and "max_tokens" not in body
        return httpx.Response(
            200,
            json={
                "model": "chat",
                "choices": [{"message": {"content": "答"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 3},
            },
        )

    client = OpenAIChatClient(caller(handler), "chat")
    messages = [ChatMessage(role="user", content="hi")]
    result = await client.complete(messages, temperature=0.1, max_tokens=None)
    assert result.content == "答" and result.usage == {"total_tokens": 3}
    assert [t async for t in client.stream(messages)] == ["你", "好"]


async def test_chat_extra_body_and_reasoning_stream() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "想"}}]},
            {"choices": [{"delta": {"content": None, "reasoning_content": "想"}}]},
            {"choices": [{"delta": {"content": "答"}}]},
            {"choices": [], "usage": {"total_tokens": 48}},
        ]
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    client = OpenAIChatClient(
        caller(handler), "deepseek", extra_body={"enable_thinking": False, "model": "ignored"}
    )
    tokens = [t async for t in client.stream([ChatMessage(role="user", content="hi")])]
    assert tokens == ["答"]
    assert bodies[0]["enable_thinking"] is False and bodies[0]["model"] == "deepseek"


class BrokenChat(MockChatClient):
    async def complete(self, messages: Any, **options: Any) -> Any:
        raise LLMError("down")

    async def stream(self, messages: Any, **options: Any) -> Any:
        raise LLMError("down")
        yield ""  # pragma: no cover


async def test_chat_fallback_and_rerank_degradation(settings: Settings) -> None:
    chat = FallbackChatClient(BrokenChat("primary"), MockChatClient("backup"))
    messages = [ChatMessage(role="user", content="问题")]
    assert (await chat.complete(messages)).model == "backup"
    assert "".join([t async for t in chat.stream(messages)]).startswith("[mock]")

    class BrokenRerank(MockRerankClient):
        async def rerank(self, query: str, documents: Any, top_n: int | None = None) -> Any:
            raise LLMError("down")

    gateway = LLMGateway(
        default_embedding=SPEC,
        embedding_factory=MockEmbeddingClient,
        reranker=BrokenRerank(),
        chat=chat,
    )
    degraded = await gateway.rerank("q", ["a", "b", "c"], top_n=2)
    assert [(r.index, r.score) for r in degraded] == [(0, 0.0), (1, 0.0)]
    with pytest.raises(LLMError):
        await gateway.rerank("q", ["a"], degrade=False)


async def test_mock_gateway_is_deterministic_and_caches_clients(settings: Settings) -> None:
    gateway = build_mock_gateway(settings.model_copy(update={"embedding_dim": 8}))
    client = gateway.embedding()
    assert gateway.embedding(gateway.default_embedding) is client
    a, b = await client.embed(["同一段文本", "同一段文本"])
    assert a == b and len(a) == 8
    other = gateway.embedding(EmbeddingSpec(model="m2", dim=3, base_url="x"))
    assert len((await other.embed(["x"]))[0]) == 3
    ranked = await gateway.rerank("知识库", ["知识库平台", "天气"])
    assert ranked[0].index == 0
