"""Metrics + tracing around model clients. Spans are named `llm.*` (Langfuse picks those up)
and follow the OpenTelemetry gen_ai semantic conventions."""

import json
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from app.core.metrics import LLM_CALLS, LLM_FIRST_TOKEN, LLM_LATENCY
from app.llm.base import (
    ChatClient,
    ChatMessage,
    ChatResult,
    EmbeddingClient,
    EmbeddingSpec,
    RerankClient,
    RerankResult,
)

tracer = trace.get_tracer("app.llm")


def _observe(kind: str, model: str, started: float, error: BaseException | None) -> None:
    LLM_CALLS.labels(kind, model, "error" if error else "ok").inc()
    LLM_LATENCY.labels(kind, model).observe(time.perf_counter() - started)


def _fail(span: Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))


def _messages_json(messages: Sequence[ChatMessage]) -> str:
    return json.dumps(
        [{"role": m.role, "content": m.content} for m in messages], ensure_ascii=False
    )


class InstrumentedEmbeddingClient:
    def __init__(self, inner: EmbeddingClient) -> None:
        self.inner = inner

    @property
    def spec(self) -> EmbeddingSpec:
        return self.inner.spec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self.inner.spec.model
        started = time.perf_counter()
        with tracer.start_as_current_span(
            "llm.embedding",
            attributes={
                "gen_ai.operation.name": "embeddings",
                "gen_ai.request.model": model,
                "llm.input_count": len(texts),
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                vectors = await self.inner.embed(texts)
            except BaseException as exc:
                _fail(span, exc)
                _observe("embedding", model, started, exc)
                raise
            _observe("embedding", model, started, None)
            return vectors


class InstrumentedRerankClient:
    def __init__(self, inner: RerankClient) -> None:
        self.inner = inner

    @property
    def model(self) -> str:
        return self.inner.model

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int | None = None
    ) -> list[RerankResult]:
        model = self.inner.model
        started = time.perf_counter()
        with tracer.start_as_current_span(
            "llm.rerank",
            attributes={
                "gen_ai.operation.name": "rerank",
                "gen_ai.request.model": model,
                "llm.input_count": len(documents),
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                results = await self.inner.rerank(query, documents, top_n)
            except BaseException as exc:
                _fail(span, exc)
                _observe("rerank", model, started, exc)
                raise
            _observe("rerank", model, started, None)
            return results


class InstrumentedChatClient:
    def __init__(self, inner: ChatClient, *, capture_content: bool = False) -> None:
        self.inner = inner
        self.capture_content = capture_content

    @property
    def model(self) -> str:
        return self.inner.model

    def _attributes(
        self, messages: Sequence[ChatMessage], options: dict[str, Any]
    ) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": self.inner.model,
        }
        for key in ("temperature", "max_tokens"):
            if options.get(key) is not None:
                attrs[f"gen_ai.request.{key}"] = options[key]
        if self.capture_content:
            attrs["langfuse.observation.input"] = _messages_json(messages)
        return attrs

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        model = self.inner.model
        started = time.perf_counter()
        with tracer.start_as_current_span(
            "llm.chat",
            attributes=self._attributes(messages, options),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                result = await self.inner.complete(messages, **options)
            except BaseException as exc:
                _fail(span, exc)
                _observe("chat", model, started, exc)
                raise
            _observe("chat", model, started, None)
            span.set_attribute("gen_ai.response.model", result.model)
            if result.finish_reason:
                span.set_attribute("gen_ai.response.finish_reasons", [result.finish_reason])
            for key, value in result.usage.items():
                span.set_attribute(f"gen_ai.usage.{key}", value)
            if self.capture_content:
                span.set_attribute("langfuse.observation.output", result.content)
            return result

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        model = self.inner.model
        started = time.perf_counter()
        # Not the current span: the generator is resumed from other contexts.
        span = tracer.start_span("llm.chat.stream", attributes=self._attributes(messages, options))
        first = True
        parts: list[str] = []
        error: BaseException | None = None
        try:
            async for token in self.inner.stream(messages, **options):
                if first:
                    first = False
                    ttft = time.perf_counter() - started
                    LLM_FIRST_TOKEN.labels(model).observe(ttft)
                    span.set_attribute("llm.first_token_ms", round(ttft * 1000, 1))
                if self.capture_content:
                    parts.append(token)
                yield token
        except GeneratorExit:
            span.set_attribute("llm.cancelled", True)
            raise
        except BaseException as exc:
            error = exc
            _fail(span, exc)
            raise
        finally:
            _observe("chat_stream", model, started, error)
            if self.capture_content:
                span.set_attribute("langfuse.observation.output", "".join(parts))
            span.end()
