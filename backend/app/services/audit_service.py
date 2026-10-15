import functools
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.models.base import Base
from app.repositories.audit_repo import AuditLogRepository, AuditQuery

SENSITIVE_FIELDS = frozenset({"claims_hash"})
AUDIT_RECORDED_FLAG = "audit_recorded"


@dataclass
class AuditContext:
    org_id: str
    actor_id: str | None
    actor_name: str | None
    ip: str | None = None
    user_agent: str | None = None
    trace_id: str | None = None
    method: str | None = None
    path: str | None = None
    # ASGI scope["state"]; used to tell AuditMiddleware the request was audited in detail.
    request_state: dict[str, Any] | None = field(default=None, repr=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(v) for v in value]
    return value


def snapshot(obj: Base | dict[str, Any] | None) -> dict[str, Any] | None:
    if obj is None:
        return None
    data = obj if isinstance(obj, dict) else obj.to_dict()
    return {k: _json_safe(v) for k, v in data.items() if k not in SENSITIVE_FIELDS}


IGNORED_DIFF_FIELDS = frozenset({"updated_at", "created_at"})


def compute_diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, dict[str, Any]]:
    before = before or {}
    after = after or {}
    diff: dict[str, dict[str, Any]] = {}
    for key in sorted(set(before) | set(after)):
        if key in IGNORED_DIFF_FIELDS:
            continue
        old, new = before.get(key), after.get(key)
        if old != new:
            diff[key] = {"before": old, "after": new}
    return diff


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditLogRepository(session)

    async def record(
        self,
        ctx: AuditContext,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> AuditLog:
        log = AuditLog(
            org_id=ctx.org_id,
            actor_id=ctx.actor_id,
            actor_name=ctx.actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            diff=compute_diff(before, after) or None,
            ip=ctx.ip,
            user_agent=(ctx.user_agent or "")[:512] or None,
            trace_id=ctx.trace_id,
            method=ctx.method,
            path=ctx.path,
            status_code=status_code,
        )
        await self.repo.add(log)
        if ctx.request_state is not None:
            ctx.request_state[AUDIT_RECORDED_FLAG] = True
        return log

    async def search(
        self, org_id: str, query: AuditQuery, page: int, size: int
    ) -> tuple[list[AuditLog], int]:
        return await self.repo.search(org_id, query, page, size)


class AuditedService(Protocol):
    audit: AuditService

    @property
    def audit_ctx(self) -> AuditContext: ...


S = TypeVar("S", bound=AuditedService)
P = ParamSpec("P")
R = TypeVar("R")


def audited(
    action: str,
    resource_type: str,
    *,
    load: Callable[..., Awaitable[Base | None]] | None = None,
) -> Callable[
    [Callable[Concatenate[S, P], Coroutine[Any, Any, R]]],
    Callable[Concatenate[S, P], Coroutine[Any, Any, R]],
]:
    """Record an audit log for a service write method.

    `load(self, *args, **kwargs)` returns the entity before the change (for update/delete);
    the decorated method's return value (an ORM entity) is used as the "after" snapshot.
    """

    def decorator(
        fn: Callable[Concatenate[S, P], Coroutine[Any, Any, R]],
    ) -> Callable[Concatenate[S, P], Coroutine[Any, Any, R]]:
        async def wrapper(self: S, /, *args: P.args, **kwargs: P.kwargs) -> R:
            before = snapshot(await load(self, *args, **kwargs)) if load else None
            result = await fn(self, *args, **kwargs)
            after = snapshot(result) if isinstance(result, Base) else None
            resource_id = (after or before or {}).get("id")
            await self.audit.record(
                self.audit_ctx, action, resource_type, resource_id, before, after
            )
            return result

        functools.update_wrapper(wrapper, fn)
        return wrapper

    return decorator
