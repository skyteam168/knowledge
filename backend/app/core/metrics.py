"""Prometheus metrics. With PROMETHEUS_MULTIPROC_DIR set (several uvicorn/gunicorn workers),
samples are aggregated across processes at scrape time."""

import os
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import multiprocess as _multiprocess
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)

HTTP_REQUESTS = Counter("ekb_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "ekb_http_request_duration_seconds",
    "HTTP request latency (streams: until the last byte)",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)
LLM_CALLS = Counter("ekb_llm_calls_total", "Model calls", ["kind", "model", "outcome"])
LLM_LATENCY = Histogram(
    "ekb_llm_call_duration_seconds",
    "Model call latency (chat streams: until the last token)",
    ["kind", "model"],
    buckets=_LATENCY_BUCKETS,
)
LLM_FIRST_TOKEN = Histogram(
    "ekb_llm_first_token_seconds",
    "Chat stream time to first token",
    ["model"],
    buckets=_LATENCY_BUCKETS,
)
CACHE_LOOKUPS = Counter("ekb_cache_lookups_total", "Cache lookups", ["cache", "result"])
RATE_LIMITED = Counter(
    "ekb_rate_limited_total", "Requests rejected by the rate limiter", ["scope", "bucket"]
)
TASKS = Counter(
    "ekb_worker_messages_total", "Worker messages processed", ["queue", "actor", "outcome"]
)
TASK_LATENCY = Histogram(
    "ekb_worker_message_duration_seconds",
    "Worker message processing time",
    ["queue", "actor"],
    buckets=(*_LATENCY_BUCKETS, 300, 900, 3600),
)
QUEUE_BACKLOG = Gauge(
    "ekb_queue_backlog", "Messages waiting in a task queue", ["queue"], multiprocess_mode="max"
)
OUTBOX_BACKLOG = Gauge(
    "ekb_outbox_events", "Index outbox events by status", ["status"], multiprocess_mode="max"
)
OUTBOX_OLDEST = Gauge(
    "ekb_outbox_oldest_pending_seconds",
    "Age of the oldest pending outbox event",
    multiprocess_mode="max",
)


def collector_registry() -> CollectorRegistry:
    """All processes' metrics in multiprocess mode (PROMETHEUS_MULTIPROC_DIR), else this one's."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        _multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return REGISTRY


def render() -> tuple[bytes, str]:
    return generate_latest(collector_registry()), CONTENT_TYPE_LATEST


def cache_lookup(cache: str, hit: bool) -> None:
    CACHE_LOOKUPS.labels(cache, "hit" if hit else "miss").inc()


def route_template(scope: Scope) -> str:
    """Full route template, e.g. /api/v1/documents/{document_id}.

    Included routers keep their own (relative) path, so the mount prefix is recovered from the
    request path minus the rendered relative path.
    """
    route = scope.get("route")
    relative = str(getattr(route, "path_format", None) or getattr(route, "path", None) or "")
    if not relative:
        return "unmatched"
    rendered = relative
    for name, value in (scope.get("path_params") or {}).items():
        rendered = rendered.replace(f"{{{name}}}", str(value))
    path = str(scope.get("path", ""))
    if rendered and path.endswith(rendered):
        return path[: len(path) - len(rendered)] + relative
    return relative


class HttpMetricsMiddleware:
    """Counts requests by route template (never the raw path: ids would explode cardinality)."""

    def __init__(self, app: ASGIApp, exclude: tuple[str, ...] = ("/metrics",)) -> None:
        self.app = app
        self.exclude = exclude

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exclude:
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            template = route_template(scope)
            method = scope.get("method", "")
            HTTP_REQUESTS.labels(method, template, str(status)).inc()
            HTTP_LATENCY.labels(method, template).observe(time.perf_counter() - start)
