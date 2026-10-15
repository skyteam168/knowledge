import logging
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.audit_service import AUDIT_RECORDED_FLAG, AuditContext, AuditService

logger = logging.getLogger(__name__)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditMiddleware:
    """Safety net for write requests.

    Services record detailed audit logs (with before/after) inside the business
    transaction. This middleware records a request-level entry when no detailed log
    was written, or when the request failed (the detailed log was rolled back with it).
    """

    def __init__(self, app: ASGIApp, path_prefix: str) -> None:
        self.app = app
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in WRITE_METHODS
            or not str(scope.get("path", "")).startswith(self.path_prefix)
        ):
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            await self._record(scope, status_code)

    async def _record(self, scope: Scope, status_code: int) -> None:
        state: dict[str, Any] = scope.get("state") or {}
        user = state.get("current_user")
        if user is None or (state.get(AUDIT_RECORDED_FLAG) and status_code < 400):
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        forwarded = headers.get("x-forwarded-for")
        client = scope.get("client")
        ctx = AuditContext(
            org_id=user.org_id,
            actor_id=user.id,
            actor_name=user.username,
            ip=forwarded.split(",")[0].strip() if forwarded else (client[0] if client else None),
            user_agent=headers.get("user-agent"),
            trace_id=state.get("trace_id"),
            method=scope.get("method"),
            path=scope.get("path"),
        )
        try:
            resources = scope["app"].state.resources
            async with resources.session_factory() as session:
                await AuditService(session).record(
                    ctx, f"http.{str(scope.get('method')).lower()}", status_code=status_code
                )
                await session.commit()
        except Exception:
            logger.exception("audit_middleware_failed")
