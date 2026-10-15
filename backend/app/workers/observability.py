"""Dramatiq middleware: trace context propagation (producer -> worker) and task metrics."""

import contextlib
import logging
import threading
import time
from typing import Any

from dramatiq import Broker, Message
from dramatiq.broker import MessageProxy
from dramatiq.middleware import Middleware
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.core.config import Settings
from app.core.metrics import TASK_LATENCY, TASKS
from app.core.telemetry import setup_tracing, tracing_enabled

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("app.workers")

TRACE_OPTION = "otel"


class TracingMiddleware(Middleware):
    """Producers (API and workers) inject the trace context; consumers continue it."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._spans: dict[str, Any] = {}
        self._lock = threading.Lock()

    def after_process_boot(self, broker: Broker) -> None:
        # Worker processes only: the API installs its own provider in create_app.
        setup_tracing(self.settings, service_name=f"{self.settings.otel_service_name}-worker")

    def before_enqueue(self, broker: Broker, message: Message[Any], delay: int) -> None:
        carrier: dict[str, str] = {}
        inject(carrier)
        if carrier:
            message.options[TRACE_OPTION] = carrier

    def before_process_message(self, broker: Broker, message: MessageProxy) -> None:
        parent = extract(message.options.get(TRACE_OPTION) or {})
        span = tracer.start_span(
            f"dramatiq {message.actor_name}",
            context=parent,
            kind=SpanKind.CONSUMER,
            attributes={
                "messaging.system": "dramatiq",
                "messaging.destination.name": message.queue_name,
                "messaging.message.id": message.message_id,
                "dramatiq.retries": message.options.get("retries", 0),
            },
        )
        token = otel_context.attach(trace.set_span_in_context(span))
        with self._lock:
            self._spans[message.message_id] = (span, token)

    def _finish(self, message: MessageProxy, exception: BaseException | None) -> None:
        with self._lock:
            item = self._spans.pop(message.message_id, None)
        if item is None:
            return
        span, token = item
        if exception is not None:
            span.record_exception(exception)
            span.set_status(Status(StatusCode.ERROR, str(exception)))
        span.end()
        with contextlib.suppress(Exception):
            otel_context.detach(token)

    def after_process_message(
        self,
        broker: Broker,
        message: MessageProxy,
        *,
        result: Any | None = None,
        exception: BaseException | None = None,
    ) -> None:
        self._finish(message, exception)

    def after_skip_message(self, broker: Broker, message: MessageProxy) -> None:
        self._finish(message, None)


class TaskMetricsMiddleware(Middleware):
    def __init__(self, port: int | None) -> None:
        self.port = port
        self._started: dict[str, float] = {}
        self._lock = threading.Lock()

    def after_worker_boot(self, broker: Broker, worker: Any) -> None:
        if self.port is None:
            return
        from prometheus_client import start_http_server

        from app.core.metrics import collector_registry

        try:
            # With several worker processes the first one to bind serves everyone's samples.
            start_http_server(self.port, registry=collector_registry())
        except OSError:
            logger.warning("worker_metrics_port_in_use", extra={"port": self.port})

    def before_process_message(self, broker: Broker, message: MessageProxy) -> None:
        with self._lock:
            self._started[message.message_id] = time.perf_counter()

    def after_process_message(
        self,
        broker: Broker,
        message: MessageProxy,
        *,
        result: Any | None = None,
        exception: BaseException | None = None,
    ) -> None:
        with self._lock:
            started = self._started.pop(message.message_id, None)
        outcome = "error" if exception is not None else "ok"
        TASKS.labels(message.queue_name, message.actor_name, outcome).inc()
        if started is not None:
            TASK_LATENCY.labels(message.queue_name, message.actor_name).observe(
                time.perf_counter() - started
            )

    def after_skip_message(self, broker: Broker, message: MessageProxy) -> None:
        with self._lock:
            self._started.pop(message.message_id, None)
        TASKS.labels(message.queue_name, message.actor_name, "skipped").inc()


def observability_middleware(settings: Settings) -> list[Middleware]:
    middleware: list[Middleware] = [TaskMetricsMiddleware(settings.worker_metrics_port)]
    if tracing_enabled(settings):
        middleware.append(TracingMiddleware(settings))
    return middleware
