"""Prometheus /metrics, instrumented model clients and the Langfuse span filter."""

from typing import Any

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import Settings
from app.core.telemetry import LlmSpanFilter
from app.llm import ChatMessage, LLMError
from app.llm import instrumented as instrumented_module
from app.llm.instrumented import InstrumentedChatClient, InstrumentedRerankClient
from app.llm.mock import MockChatClient, MockRerankClient
from tests.conftest import auth


async def test_metrics_endpoint_reports_requests_and_backlog(
    api: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    await api.get("/api/v1/auth/me", headers=auth("alice-token"))
    await api.get("/api/v1/documents/doc-42", headers=auth("alice-token"))
    resp = await api.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert 'ekb_http_requests_total{method="GET",route="/api/v1/auth/me",status="200"}' in body
    assert 'route="/api/v1/documents/{document_id}",status="404"' in body
    assert "doc-42" not in body
    assert 'ekb_queue_backlog{queue="ingest"}' in body
    assert 'ekb_outbox_events{status="pending"}' in body

    monkeypatch.setattr(settings, "metrics_token", "s3cret")
    assert (await api.get("/metrics")).status_code == 401
    ok = await api.get("/metrics", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


class _Failing(MockChatClient):
    async def complete(self, messages: Any, **options: Any) -> Any:
        raise LLMError("boom")


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(instrumented_module, "tracer", provider.get_tracer("test"))
    return exporter


async def test_instrumented_clients_emit_llm_spans(spans: InMemorySpanExporter) -> None:
    chat = InstrumentedChatClient(MockChatClient("m-chat"), capture_content=True)
    msgs = [ChatMessage("system", "s"), ChatMessage("user", "你好")]
    await chat.complete(msgs, temperature=0.1)
    tokens = [t async for t in chat.stream(msgs)]
    assert tokens
    await InstrumentedRerankClient(MockRerankClient("m-rerank")).rerank("q", ["a", "b"])
    with pytest.raises(LLMError):
        await InstrumentedChatClient(_Failing("bad")).complete(msgs)

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert {"llm.chat", "llm.chat.stream", "llm.rerank"} <= set(finished)
    chat_span = finished["llm.chat"]
    assert chat_span.attributes is not None
    assert chat_span.attributes["gen_ai.request.model"] in {"m-chat", "bad"}
    stream_attrs = finished["llm.chat.stream"].attributes or {}
    assert "llm.first_token_ms" in stream_attrs
    assert "langfuse.observation.output" in stream_attrs
    errors = [s for s in spans.get_finished_spans() if not s.status.is_ok]
    assert len(errors) == 1


def test_langfuse_filter_forwards_only_llm_spans() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(LlmSpanFilter(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer("test")
    with (
        tracer.start_as_current_span("GET /api/v1/search"),
        tracer.start_as_current_span("llm.embedding"),
    ):
        pass
    assert [s.name for s in exporter.get_finished_spans()] == ["llm.embedding"]
