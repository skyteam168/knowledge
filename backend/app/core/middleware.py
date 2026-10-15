import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import trace_id_var

TRACE_HEADER = "X-Trace-ID"
_VALID_TRACE_ID = re.compile(r"^[A-Za-z0-9\-_.]{1,128}$")

logger = logging.getLogger("app.access")


class TraceIdMiddleware:
    """Assign a trace_id per request, expose it via contextvar/request.state and response header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for key, value in scope.get("headers", []):
            if key.decode("latin-1").lower() == TRACE_HEADER.lower():
                incoming = value.decode("latin-1")
                break
        trace_id = incoming if incoming and _VALID_TRACE_ID.match(incoming) else uuid.uuid4().hex

        scope.setdefault("state", {})["trace_id"] = trace_id
        token = trace_id_var.set(trace_id)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[TRACE_HEADER] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            trace_id_var.reset(token)
