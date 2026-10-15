"""Token metering: provider usage capture, estimates, attribution and the usage dashboard."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.llm import ChatMessage, EmbeddingSpec, LLMError, LLMGateway
from app.llm.gateway import FallbackChatClient
from app.llm.mock import MockEmbeddingClient, MockRerankClient
from app.llm.openai_compat import HttpCaller, OpenAIChatClient, OpenAIEmbeddingClient
from app.llm.usage import (
    UsageEvent,
    UsageReport,
    count_tokens,
    current_scope,
    estimate_tokens,
    iterate_in_scope,
    usage_scope,
)
from app.models import LlmUsage
from app.services.analytics.aggregator import AnalyticsAggregator
from app.services.usage import DbUsageRecorder
from tests.conftest import auth
from tests.test_chat_api import ScriptedChat, answerable, ask, chat, corpus, new_conversation
from tests.test_indexing import me, pipeline

__all__ = ["answerable", "chat", "corpus", "pipeline"]

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
SPEC = EmbeddingSpec(model="emb", dim=4, base_url="http://llm/v1")
MESSAGES = [
    ChatMessage(role="system", content="你是助手"),
    ChatMessage(role="user", content="你好"),
]


class ListRecorder:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> None:
        self.events.append(event)


def caller(handler: Any) -> HttpCaller:
    return HttpCaller(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        "http://llm/v1",
        api_key="k",
        timeout=5.0,
        max_retries=0,
        backoff_seconds=0.001,
    )


def sse(*events: dict[str, Any]) -> httpx.Response:
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def delta(text: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": {"content": text}}]}


def gateway(chat: Any, recorder: ListRecorder, embedding: Any = MockEmbeddingClient) -> LLMGateway:
    return LLMGateway(
        default_embedding=SPEC,
        embedding_factory=embedding,
        reranker=MockRerankClient(),
        chat=chat,
        recorder=recorder,
    )


async def collect(stream: AsyncIterator[str]) -> str:
    return "".join([t async for t in stream])


async def test_stream_records_provider_usage_and_scope() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        return sse(delta("你"), delta("好"), {"choices": [], "usage": usage})

    recorder = ListRecorder()
    gw = gateway(OpenAIChatClient(caller(handler), "qwen-plus"), recorder)
    with usage_scope(org_id="o1", user_id="u1", feature="assistant", stage="generate"):
        assert await collect(gw.stream(MESSAGES)) == "你好"

    assert bodies[0]["stream_options"] == {"include_usage": True}
    (event,) = recorder.events
    assert (event.kind, event.model, event.status) == ("chat", "qwen-plus", "ok")
    assert (event.prompt_tokens, event.completion_tokens, event.total_tokens) == (11, 7, 18)
    assert not event.estimated and not event.fallback and event.first_token_ms is not None
    assert (event.scope.org_id, event.scope.user_id) == ("o1", "u1")
    assert (event.scope.feature, event.scope.stage) == ("assistant", "generate")


async def test_stream_without_usage_is_estimated() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return sse(delta("年假"), delta("5 天"))

    recorder = ListRecorder()
    client = OpenAIChatClient(caller(handler), "local", stream_usage=False)
    with usage_scope(org_id="o1"):
        await collect(gateway(client, recorder).stream(MESSAGES))

    assert "stream_options" not in bodies[0]
    (event,) = recorder.events
    assert event.estimated and event.completion_tokens == estimate_tokens("年假5 天")
    assert event.prompt_tokens > 0 and event.total_tokens == (
        event.prompt_tokens + event.completion_tokens
    )


async def test_fallback_model_is_recorded() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad"})

    def backup(request: httpx.Request) -> httpx.Response:
        return sse(delta("ok"), {"choices": [], "usage": {"prompt_tokens": 3, "total_tokens": 4}})

    recorder = ListRecorder()
    chat = FallbackChatClient(
        OpenAIChatClient(caller(broken), "primary"), OpenAIChatClient(caller(backup), "backup")
    )
    with usage_scope(org_id="o1"):
        assert await collect(gateway(chat, recorder).stream(MESSAGES)) == "ok"
    (event,) = recorder.events
    assert event.model == "backup" and event.fallback and event.total_tokens == 4


async def test_cancelled_stream_is_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return sse(delta("一"), delta("二"), delta("三"))

    recorder = ListRecorder()
    with usage_scope(org_id="o1"):
        stream = gateway(OpenAIChatClient(caller(handler), "m"), recorder).stream(MESSAGES)
        assert await anext(stream) == "一"
        await stream.aclose()
    (event,) = recorder.events
    assert event.status == "cancelled" and event.estimated


async def test_embedding_usage_is_summed_over_batches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        data = [{"index": i, "embedding": [1.0, 0.0, 0.0, 0.0]} for i in range(len(texts))]
        tokens = 3 * len(texts)
        return httpx.Response(
            200, json={"data": data, "usage": {"prompt_tokens": tokens, "total_tokens": tokens}}
        )

    recorder = ListRecorder()

    def factory(spec: EmbeddingSpec) -> OpenAIEmbeddingClient:
        return OpenAIEmbeddingClient(caller(handler), spec, batch_size=2, concurrency=2)

    gw = gateway(OpenAIChatClient(caller(handler), "m"), recorder, embedding=factory)
    with usage_scope(org_id="o1", feature="indexing"):
        vectors = await gw.embedding().embed(["a", "b", "c", "d", "e"])
    assert len(vectors) == 5
    (event,) = recorder.events
    assert (event.kind, event.input_count, event.total_tokens) == ("embedding", 5, 15)
    assert not event.estimated and event.scope.feature == "indexing"


async def test_failing_rerank_degrades_and_records_error() -> None:
    class Down:
        model = "rr"

        async def rerank(self, query: str, documents: Sequence[str], top_n: int | None = None):  # type: ignore[no-untyped-def]
            raise LLMError("down")

    recorder = ListRecorder()
    gw = gateway(OpenAIChatClient(caller(lambda r: sse()), "m"), recorder)
    gw.reranker = Down()
    with usage_scope(org_id="o1"):
        results = await gw.rerank("年假", ["甲", "乙"], top_n=1)
    assert [r.index for r in results] == [0]
    (event,) = recorder.events
    assert (event.kind, event.status, event.input_count) == ("rerank", "error", 2)


async def test_scope_rules_and_no_leak_from_generators() -> None:
    with usage_scope(org_id="o1", user_id="u1", feature="open_api"):
        with usage_scope(feature="assistant", stage="rewrite"):
            inner = current_scope()
        assert (inner.feature, inner.stage, inner.user_id) == ("open_api", "rewrite", "u1")
        assert current_scope().stage is None

        seen: list[str | None] = []

        async def produce() -> AsyncIterator[int]:
            for i in range(2):
                seen.append(current_scope().stage)
                yield i

        with usage_scope(stage="generate"):
            scoped = current_scope()
        async for _ in iterate_in_scope(produce(), scoped):
            assert current_scope().stage is None
        assert seen == ["generate", "generate"]
    assert current_scope().org_id is None


async def test_chat_usage_is_attributed_and_shown_on_dashboard(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    chat: ScriptedChat,
    answerable: Settings,
    engine: AsyncEngine,
    llm_gateway: LLMGateway,
    settings: Settings,
) -> None:
    # Written on close: the SQLite test engine has a single connection.
    recorder = DbUsageRecorder(create_session_factory(engine), flush_seconds=3600)
    llm_gateway.recorder = recorder
    carol = await me(api, CAROL)
    conv = await new_conversation(api, CAROL)
    chat.answer = "员工入职满一年后享有 5 天带薪年假[1]。"
    done = (await ask(api, CAROL, conv["id"], "年假有几天？"))["done"]
    await recorder.aclose()

    async with create_session_factory(engine)() as session:
        rows = list((await session.execute(select(LlmUsage))).scalars())
    assert rows and {r.user_id for r in rows} == {carol["id"]}
    assert {r.org_id for r in rows} == {carol["org_id"]}
    assert {r.feature for r in rows} == {"assistant"}
    assert {"rewrite", "retrieval", "generate"} <= {r.stage for r in rows}
    assert {"chat", "embedding", "rerank"} <= {r.kind for r in rows}
    (generated,) = [r for r in rows if r.stage == "generate"]
    assert generated.message_id == done["message_id"] and generated.conversation_id == conv["id"]
    assert generated.status == "ok" and generated.total_tokens > 0
    total = sum(r.total_tokens for r in rows)

    await AnalyticsAggregator(create_session_factory(engine), settings).run_once(1)
    resp = await api.get("/api/v1/analytics/llm-usage", headers=ALICE)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["calls"] == len(rows) and body["summary"]["total_tokens"] == total
    assert body["summary"]["users"] == 1 and body["users_total"] == 1
    (user,) = body["users"]
    assert user["user_id"] == carol["id"] and user["username"] == "carol"
    assert user["assistant_tokens"] == total and not user["is_service"]
    assert [f["feature"] for f in body["by_feature"]] == ["assistant"]
    assert {m["kind"] for m in body["by_model"]} >= {"chat", "embedding", "rerank"}
    assert sum(d["total_tokens"] for d in body["daily"]) == total

    only = await api.get("/api/v1/analytics/llm-usage", params={"user_id": "nobody"}, headers=ALICE)
    assert only.json()["summary"]["calls"] == 0 and only.json()["users"] == []

    # analytics:view alone (kb_editor) does not reveal per-person consumption.
    assert (await api.get("/api/v1/analytics/llm-usage", headers=BOB)).status_code == 403
    assert (await api.get("/api/v1/analytics/llm-usage", headers=CAROL)).status_code == 403


async def test_unattributed_events_are_dropped(engine: AsyncEngine) -> None:
    recorder = DbUsageRecorder(create_session_factory(engine), flush_seconds=0)
    recorder.record(UsageEvent(kind="chat", model="m", scope=current_scope()))
    assert await recorder.flush() == 0


@pytest.mark.parametrize(
    ("text", "expected"), [("", 0), ("年假五天", 4), ("hello world", 3), ("年假 5 days", 4)]
)
def test_estimate_tokens(text: str, expected: int) -> None:
    assert estimate_tokens(text) == expected


def test_total_only_usage_counts_as_input() -> None:
    count = count_tokens([UsageReport("qwen3-rerank", {"total_tokens": 46})], prompt_estimate=9)
    assert (count.prompt, count.completion, count.total, count.estimated) == (46, 0, 46, False)
