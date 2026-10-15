"""Single entry point for every model call. Model names, dimensions and URLs come from config."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx

from app.core.config import Settings
from app.llm.base import (
    ChatClient,
    ChatMessage,
    ChatResult,
    EmbeddingClient,
    EmbeddingSpec,
    LLMError,
    RerankClient,
    RerankResult,
)
from app.llm.instrumented import (
    InstrumentedChatClient,
    InstrumentedEmbeddingClient,
    InstrumentedRerankClient,
)
from app.llm.mock import MockChatClient, MockEmbeddingClient, MockRerankClient
from app.llm.openai_compat import (
    HttpCaller,
    OpenAIChatClient,
    OpenAIEmbeddingClient,
    OpenAIRerankClient,
)
from app.llm.routing import ChatFactory, ChatRoute, ChatTarget
from app.llm.usage import (
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_RERANK,
    UsageEvent,
    UsageRecorder,
    UsageReport,
    collect_usage,
    count_tokens,
    current_scope,
    estimate_messages,
    estimate_tokens,
)

logger = logging.getLogger(__name__)

EmbeddingFactory = Callable[[EmbeddingSpec], EmbeddingClient]


class FallbackChatClient:
    """Uses `fallback` when `primary` fails (for streams: only before the first token)."""

    def __init__(self, primary: ChatClient, fallback: ChatClient) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def model(self) -> str:
        return self.primary.model

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        try:
            return await self.primary.complete(messages, **options)
        except LLMError as exc:
            logger.warning("chat_fallback", extra={"model": self.primary.model, "error": str(exc)})
            return await self.fallback.complete(messages, **options)

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        started = False
        try:
            async for token in self.primary.stream(messages, **options):
                started = True
                yield token
            return
        except LLMError as exc:
            if started:
                raise
            logger.warning("chat_fallback", extra={"model": self.primary.model, "error": str(exc)})
        async for token in self.fallback.stream(messages, **options):
            yield token


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


class _Meter:
    """Collects usage reports of one call and emits a UsageEvent to the gateway's recorder."""

    def __init__(self, gateway: "LLMGateway", kind: str, model: str, input_count: int) -> None:
        self.gateway = gateway
        self.kind = kind
        self.model = model
        self.input_count = input_count
        self.reports: list[UsageReport] = []
        self.started = time.perf_counter()
        # Captured when the call starts: streams may be finalized from another context.
        self.scope = current_scope()

    def emit(
        self,
        status: str,
        prompt_estimate: int,
        completion_estimate: int = 0,
        first_token_ms: int | None = None,
    ) -> None:
        recorder = self.gateway.recorder
        if recorder is None:
            return
        tokens = count_tokens(self.reports, prompt_estimate, completion_estimate)
        served = tokens.models[-1] if tokens.models else self.model
        try:
            recorder.record(
                UsageEvent(
                    kind=self.kind,
                    model=served,
                    scope=self.scope,
                    prompt_tokens=tokens.prompt,
                    completion_tokens=tokens.completion,
                    total_tokens=tokens.total,
                    estimated=tokens.estimated,
                    input_count=self.input_count,
                    latency_ms=_elapsed_ms(self.started),
                    first_token_ms=first_token_ms,
                    status=status,
                    fallback=served != self.model,
                )
            )
        except Exception:
            logger.exception("llm_usage_record_failed")


class _MeteredEmbedding:
    def __init__(self, inner: EmbeddingClient, gateway: "LLMGateway") -> None:
        self.inner = inner
        self.gateway = gateway

    @property
    def spec(self) -> EmbeddingSpec:
        return self.inner.spec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        meter = _Meter(self.gateway, KIND_EMBEDDING, self.inner.spec.model, len(texts))
        status = "error"
        try:
            with collect_usage(meter.reports):
                vectors = await self.inner.embed(texts)
            status = "ok"
            return vectors
        finally:
            if texts:
                meter.emit(status, sum(estimate_tokens(t) for t in texts))


class LLMGateway:
    def __init__(
        self,
        *,
        default_embedding: EmbeddingSpec,
        embedding_factory: EmbeddingFactory,
        reranker: RerankClient,
        chat: ChatClient,
        http: httpx.AsyncClient | None = None,
        recorder: UsageRecorder | None = None,
    ) -> None:
        self.default_embedding = default_embedding
        self._embedding_factory = embedding_factory
        self._embeddings: dict[EmbeddingSpec, EmbeddingClient] = {}
        self.reranker = reranker
        self.chat = chat
        self._http = http
        self.recorder = recorder
        # Set when the chat model is routed from the model admin page (see app.llm.routing).
        self.chat_refresh: Callable[[], Awaitable[None]] | None = None

    @property
    def http(self) -> httpx.AsyncClient | None:
        return self._http

    async def _refresh_chat(self) -> None:
        if self.chat_refresh is None:
            return
        try:
            await self.chat_refresh()
        except Exception:
            logger.exception("chat_refresh_failed")

    def embedding(self, spec: EmbeddingSpec | None = None) -> EmbeddingClient:
        """Client for `spec` (an index generation may pin a model other than the default)."""
        spec = spec or self.default_embedding
        client = self._embeddings.get(spec)
        if client is None:
            client = self._embeddings[spec] = _MeteredEmbedding(self._embedding_factory(spec), self)
        return client

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int | None = None,
        *,
        degrade: bool = True,
    ) -> list[RerankResult]:
        """With `degrade`, a failing reranker keeps the input order (scores are 0)."""
        if not documents:
            return []
        meter = _Meter(self, KIND_RERANK, self.reranker.model, len(documents))
        query_tokens = estimate_tokens(query)
        estimate = sum(query_tokens + estimate_tokens(d) for d in documents)
        try:
            with collect_usage(meter.reports):
                results = await self.reranker.rerank(query, documents, top_n)
        except LLMError as exc:
            meter.emit("error", estimate)
            if not degrade:
                raise
            logger.warning(
                "rerank_degraded", extra={"model": self.reranker.model, "error": str(exc)}
            )
            keep = len(documents) if top_n is None else min(top_n, len(documents))
            return [RerankResult(index=i, score=0.0) for i in range(keep)]
        except BaseException:
            meter.emit("error", estimate)
            raise
        meter.emit("ok", estimate)
        return results

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        time_limit: float | None = None,
        **options: Any,
    ) -> ChatResult:
        """Non-streaming chat; `time_limit` (seconds) bounds the whole call including retries."""
        await self._refresh_chat()
        meter = _Meter(self, KIND_CHAT, self.chat.model, len(messages))
        prompt_estimate = estimate_messages([m.content for m in messages])
        status, completion = "error", ""
        try:
            with collect_usage(meter.reports):
                result = await asyncio.wait_for(self.chat.complete(messages, **options), time_limit)
            status, completion = "ok", result.content
            if not meter.reports and result.usage:
                meter.reports.append(UsageReport(result.model, dict(result.usage)))
            return result
        except TimeoutError as exc:
            raise LLMError(
                f"chat completion timed out after {time_limit}s", retryable=True
            ) from exc
        finally:
            meter.emit(status, prompt_estimate, estimate_tokens(completion))

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        await self._refresh_chat()
        meter = _Meter(self, KIND_CHAT, self.chat.model, len(messages))
        source = self.chat.stream(messages, **options)
        parts: list[str] = []
        first_token_ms: int | None = None
        status = "ok"
        try:
            while True:
                with collect_usage(meter.reports):
                    try:
                        token = await anext(source)
                    except StopAsyncIteration:
                        break
                if first_token_ms is None:
                    first_token_ms = _elapsed_ms(meter.started)
                parts.append(token)
                yield token
        except GeneratorExit:
            status = "cancelled"
            raise
        except BaseException:
            status = "error"
            raise
        finally:
            close = getattr(source, "aclose", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()
            meter.emit(
                status,
                estimate_messages([m.content for m in messages]),
                estimate_tokens("".join(parts)),
                first_token_ms,
            )

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()


def default_embedding_spec(settings: Settings) -> EmbeddingSpec:
    return EmbeddingSpec(
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        base_url=settings.embedding_base_url,
    )


def build_mock_gateway(settings: Settings) -> LLMGateway:
    return LLMGateway(
        default_embedding=default_embedding_spec(settings),
        embedding_factory=MockEmbeddingClient,
        reranker=MockRerankClient(settings.rerank_model),
        chat=MockChatClient(settings.chat_model),
    )


def build_llm_gateway(settings: Settings) -> LLMGateway:
    if settings.llm_provider == "mock":
        return build_mock_gateway(settings)

    http = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.llm_max_connections,
            max_keepalive_connections=settings.llm_max_keepalive_connections,
        )
    )

    def caller(base_url: str, timeout: float) -> HttpCaller:
        return HttpCaller(
            http,
            base_url,
            api_key=settings.llm_api_key,
            timeout=timeout,
            max_retries=settings.llm_max_retries,
            backoff_seconds=settings.llm_retry_backoff_seconds,
            pool_timeout=settings.llm_pool_timeout_seconds,
        )

    def embedding_factory(spec: EmbeddingSpec) -> EmbeddingClient:
        return InstrumentedEmbeddingClient(
            OpenAIEmbeddingClient(
                caller(spec.base_url, settings.embedding_timeout_seconds),
                spec,
                batch_size=settings.embedding_batch_size,
                concurrency=settings.embedding_concurrency,
                send_dimensions=settings.embedding_send_dimensions,
            )
        )

    chat: ChatClient = OpenAIChatClient(
        caller(settings.chat_base_url, settings.llm_timeout_seconds),
        settings.chat_model,
        extra_body=settings.chat_extra_body,
        stream_usage=settings.chat_stream_include_usage,
    )
    if settings.chat_fallback_model:
        fallback = OpenAIChatClient(
            caller(
                settings.chat_fallback_base_url or settings.chat_base_url,
                settings.llm_timeout_seconds,
            ),
            settings.chat_fallback_model,
            extra_body=settings.chat_extra_body,
            stream_usage=settings.chat_stream_include_usage,
        )
        chat = FallbackChatClient(chat, fallback)

    return LLMGateway(
        default_embedding=default_embedding_spec(settings),
        embedding_factory=embedding_factory,
        reranker=InstrumentedRerankClient(
            OpenAIRerankClient(
                caller(settings.rerank_base_url, settings.rerank_timeout_seconds),
                settings.rerank_model,
                path=settings.rerank_path,
                instruct=settings.rerank_instruct,
            )
        ),
        chat=InstrumentedChatClient(chat, capture_content=settings.llm_trace_content),
        http=http,
    )


def routed_chat_factory(settings: Settings, http: httpx.AsyncClient) -> ChatFactory:
    """Builds the chat client of a route chosen in the model admin page."""

    def client(target: ChatTarget) -> ChatClient:
        return OpenAIChatClient(
            HttpCaller(
                http,
                target.base_url,
                api_key=target.api_key,
                timeout=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
                backoff_seconds=settings.llm_retry_backoff_seconds,
                pool_timeout=settings.llm_pool_timeout_seconds,
            ),
            target.model,
            extra_body=settings.chat_extra_body,
            stream_usage=settings.chat_stream_include_usage,
        )

    def build(route: ChatRoute) -> ChatClient:
        primary = client(route.primary)
        if route.fallback is None:
            return primary
        return FallbackChatClient(primary, client(route.fallback))

    return build
