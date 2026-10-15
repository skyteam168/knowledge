"""OpenTelemetry tracing: FastAPI, SQLAlchemy, httpx and worker spans exported over OTLP/HTTP.

When Langfuse keys are configured, `llm.*` spans are additionally exported to Langfuse's OTLP
endpoint (only those: request/database spans stay in the regular backend).
"""

import base64
import logging
import threading
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings

logger = logging.getLogger(__name__)

LLM_SPAN_PREFIX = "llm."

_lock = threading.Lock()
_provider: TracerProvider | None = None


class LlmSpanFilter(SpanProcessor):
    """Forwards only model-call spans to `inner`."""

    def __init__(self, inner: SpanProcessor) -> None:
        self.inner = inner

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        if span.name.startswith(LLM_SPAN_PREFIX):
            self.inner.on_end(span)

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def langfuse_enabled(settings: Settings) -> bool:
    return bool(
        settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key
    )


def tracing_enabled(settings: Settings) -> bool:
    return settings.otel_enabled or langfuse_enabled(settings)


def _exporter(endpoint: str, headers: dict[str, str] | None = None) -> Any:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint, headers=headers)


def setup_tracing(settings: Settings, service_name: str | None = None) -> TracerProvider | None:
    """Idempotent: the first call per process installs the global tracer provider."""
    global _provider
    if not tracing_enabled(settings):
        return None
    with _lock:
        if _provider is not None:
            return _provider
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name or settings.otel_service_name,
                    "deployment.environment": settings.app_env,
                }
            ),
            sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_ratio)),
        )
        if settings.otel_enabled:
            endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(_exporter(endpoint)))
        if langfuse_enabled(settings):
            token = base64.b64encode(
                f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
            ).decode()
            endpoint = str(settings.langfuse_host).rstrip("/") + "/api/public/otel/v1/traces"
            provider.add_span_processor(
                LlmSpanFilter(
                    BatchSpanProcessor(_exporter(endpoint, {"Authorization": f"Basic {token}"}))
                )
            )
        trace.set_tracer_provider(provider)
        if settings.otel_enabled:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _provider = provider
        logger.info(
            "tracing_enabled",
            extra={"otlp": settings.otel_enabled, "langfuse": langfuse_enabled(settings)},
        )
        return provider


def instrument_app(app: FastAPI, settings: Settings) -> None:
    provider = setup_tracing(settings)
    if provider is None or not settings.otel_enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="/health,/ready,/metrics",
        exclude_spans=["receive", "send"],
    )


def instrument_engine(engine: AsyncEngine, settings: Settings) -> None:
    provider = setup_tracing(settings)
    if provider is None or not settings.otel_enabled:
        return
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=provider)


def shutdown_tracing() -> None:
    global _provider
    with _lock:
        if _provider is not None:
            _provider.shutdown()
            _provider = None
