"""API key authentication for external agents.

authenticate(): secret -> (key, client), or 401 without revealing which check failed beyond
revoked / expired. enforce(): client state, source IP, per-minute limit and daily quota.
caller_user(): the CurrentUser the client acts as (its service user + bound principals,
search/chat permissions only, never a superuser).
"""

import ipaddress
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import KeyValueCache
from app.core.config import Settings
from app.core.exceptions import AppError, PermissionDeniedError, UnauthorizedError
from app.core.rate_limit import RateLimitedError
from app.models import (
    ApiClient,
    ApiClientStatus,
    ApiKey,
    ApiKeyStatus,
    ApiScope,
    Department,
    Group,
    Role,
    User,
)
from app.models.base import utcnow
from app.services.authz import CurrentUser, Principals
from app.services.open_api.keys import hash_secret, looks_like_key

logger = logging.getLogger(__name__)

TOUCH_INTERVAL = timedelta(seconds=60)


class OpenApiDisabledError(AppError):
    status_code = 404
    code = "OPEN_API_DISABLED"
    message = "Open API is disabled"


class ScopeDeniedError(PermissionDeniedError):
    code = "SCOPE_DENIED"
    message = "This API client is not allowed to use this capability"


class KbNotGrantedError(PermissionDeniedError):
    code = "KB_NOT_GRANTED"
    message = "Knowledge base not granted to this API client"


class QuotaExceededError(AppError):
    status_code = 429
    code = "QUOTA_EXCEEDED"
    message = "Daily quota exhausted"


@dataclass(frozen=True)
class ApiCaller:
    client_id: str
    key_id: str
    org_id: str
    name: str
    kb_ids: frozenset[str]
    scopes: frozenset[str]
    rate_limit_per_minute: int
    daily_quota: int
    user: CurrentUser

    def require_scope(self, scope: ApiScope) -> None:
        if scope.value not in self.scopes:
            raise ScopeDeniedError(detail={"required": scope.value})

    def resolve_kbs(self, requested: list[str]) -> list[str]:
        """Requested knowledge bases must all be granted; none requested = every grant."""
        if not requested:
            return sorted(self.kb_ids)
        denied = [kb for kb in requested if kb not in self.kb_ids]
        if denied:
            raise KbNotGrantedError(detail={"kb_ids": denied})
        return requested


def effective_rate(client: ApiClient, settings: Settings) -> int:
    return client.rate_limit_per_minute or settings.open_api_default_rate_per_minute


async def authenticate(
    session: AsyncSession, settings: Settings, secret: str | None
) -> tuple[ApiKey, ApiClient]:
    if not settings.open_api_enabled:
        raise OpenApiDisabledError()
    if not secret or not looks_like_key(secret):
        raise UnauthorizedError("Missing or malformed API key", code="INVALID_API_KEY")
    digest = hash_secret(secret, settings.open_api_key_pepper)
    key = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == digest))
    ).scalar_one_or_none()
    if key is None:
        raise UnauthorizedError("Invalid API key", code="INVALID_API_KEY")
    if key.status != ApiKeyStatus.ACTIVE.value:
        raise UnauthorizedError("API key revoked", code="API_KEY_REVOKED")
    now = utcnow()
    if key.expires_at is not None and _aware(key.expires_at) <= now:
        raise UnauthorizedError("API key expired", code="API_KEY_EXPIRED")
    client = await session.get(ApiClient, key.client_id)
    if client is None or client.org_id != key.org_id:
        raise UnauthorizedError("Invalid API key", code="INVALID_API_KEY")
    return key, client


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def ip_allowed(ip: str | None, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


async def enforce(
    client: ApiClient,
    ip: str | None,
    cache: KeyValueCache,
    settings: Settings,
) -> None:
    if client.status != ApiClientStatus.ACTIVE.value:
        raise PermissionDeniedError("API client disabled", code="API_CLIENT_DISABLED")
    if client.expires_at is not None and _aware(client.expires_at) <= utcnow():
        raise PermissionDeniedError("API client expired", code="API_CLIENT_EXPIRED")
    if not ip_allowed(ip, list(client.ip_allowlist or [])):
        raise PermissionDeniedError(
            "Source IP not allowed", code="IP_NOT_ALLOWED", detail={"ip": ip}
        )
    await apply_limits(client, cache, settings)


async def apply_limits(client: ApiClient, cache: KeyValueCache, settings: Settings) -> None:
    """Sliding-window counter: the previous minute's count, weighted by how much of it still
    overlaps the last 60 s, is added so a burst straddling a minute boundary can't double up."""
    now = time.time()
    window = int(now // 60)
    elapsed = (now % 60) / 60
    retry_after = max(1, int(60 - now % 60))
    limit = effective_rate(client, settings)
    try:
        current = await cache.incr(f"rl:open:{client.id}:{window}", ttl_seconds=121)
        previous = int(await cache.get(f"rl:open:{client.id}:{window - 1}") or 0)
        count = current + previous * (1 - elapsed)
        day = datetime.now(UTC).strftime("%Y%m%d")
        used = (
            await cache.incr(f"quota:open:{client.id}:{day}", ttl_seconds=2 * 86400)
            if client.daily_quota > 0
            else 0
        )
    except Exception:
        logger.warning("open_api_limit_unavailable", exc_info=True)
        return
    if limit > 0 and count > limit:
        raise RateLimitedError(
            detail={"scope": "api_client", "limit": limit, "window_seconds": 60},
            headers={"Retry-After": str(retry_after)},
        )
    if client.daily_quota > 0 and used > client.daily_quota:
        raise QuotaExceededError(detail={"daily_quota": client.daily_quota})


async def caller_user(session: AsyncSession, client: ApiClient) -> CurrentUser:
    user = await session.get(User, client.service_user_id)
    if user is None or not user.is_active:
        raise PermissionDeniedError("API client disabled", code="API_CLIENT_DISABLED")
    refs = list(client.principals or [])
    ids = {
        kind: [str(p["id"]) for p in refs if p.get("type") == kind]
        for kind in ("dept", "group", "role")
    }
    dept_ids: set[str] = set()
    if ids["dept"]:
        depts = await session.execute(
            select(Department).where(
                Department.org_id == client.org_id, Department.id.in_(ids["dept"])
            )
        )
        for dept in depts.scalars():
            dept_ids.update(dept.ancestor_ids)
    group_ids: set[str] = set()
    if ids["group"]:
        rows = await session.execute(
            select(Group.id).where(Group.org_id == client.org_id, Group.id.in_(ids["group"]))
        )
        group_ids = set(rows.scalars())
    role_ids: set[str] = set()
    if ids["role"]:
        rows = await session.execute(
            select(Role.id).where(Role.org_id == client.org_id, Role.id.in_(ids["role"]))
        )
        role_ids = set(rows.scalars())
    scopes = set(client.scopes or [])
    permissions = {"search:use"}
    if ApiScope.CHAT.value in scopes:
        permissions.add("chat:use")
    return CurrentUser(
        id=user.id,
        org_id=client.org_id,
        username=user.username,
        display_name=user.display_name,
        principals=Principals(
            org_id=client.org_id,
            user_id=user.id,
            group_ids=frozenset(group_ids),
            role_ids=frozenset(role_ids),
            dept_ids=frozenset(dept_ids),
        ),
        permissions=frozenset(permissions),
        is_platform_admin=False,
    )


def build_caller(
    key_id: str, client: ApiClient, user: CurrentUser, settings: Settings
) -> ApiCaller:
    return ApiCaller(
        client_id=client.id,
        key_id=key_id,
        org_id=client.org_id,
        name=client.name,
        kb_ids=frozenset(client.kb_ids or []),
        scopes=frozenset(client.scopes or []),
        rate_limit_per_minute=effective_rate(client, settings),
        daily_quota=client.daily_quota,
        user=user,
    )


def touch(key: ApiKey, client: ApiClient, ip: str | None) -> bool:
    """Updates usage timestamps at most once per interval; returns whether anything changed."""
    now = utcnow()
    if key.last_used_at is not None and now - _aware(key.last_used_at) < TOUCH_INTERVAL:
        return False
    key.last_used_at = now
    key.last_used_ip = ip
    client.last_used_at = now
    return True
