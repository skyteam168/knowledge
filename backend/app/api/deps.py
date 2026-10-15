from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.core.rate_limit import RateLimiter
from app.core.resources import AppResources
from app.llm.usage import bind_usage_scope
from app.services.audit_service import AuditContext
from app.services.authz import AuthzCache, CurrentUser, PermissionResolver, PrincipalResolver
from app.services.context import BaseService, RequestContext
from app.services.health_service import HealthService, build_dependency_checks
from app.services.identity_sync_service import IdentitySyncService
from app.services.knowledge.document_service import DocumentService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_resources(request: Request) -> AppResources:
    resources: AppResources = request.app.state.resources
    return resources


ResourcesDep = Annotated[AppResources, Depends(get_resources)]


async def get_db_session(resources: ResourcesDep) -> AsyncIterator[AsyncSession]:
    # aclosing: an exception thrown in at `yield` must finalize session_scope right away
    # (rollback + release the connection), not whenever the generator is garbage-collected.
    async with aclosing(session_scope(resources.session_factory)) as scope:
        async for session in scope:
            yield session


# scope="function": commit/rollback runs before the response is sent, so clients never
# observe a 2xx for a transaction that later failed to commit.
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]


def get_authz_cache(settings: SettingsDep, resources: ResourcesDep) -> AuthzCache:
    return AuthzCache(resources.cache, settings.authz_cache_ttl_seconds)


AuthzCacheDep = Annotated[AuthzCache, Depends(get_authz_cache)]

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    settings: SettingsDep,
    resources: ResourcesDep,
    cache: AuthzCacheDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()
    claims = await resources.token_verifier.verify(credentials.credentials)
    # Identity sync runs in its own transaction: provisioning must persist even if the
    # business transaction of this request is rolled back.
    async with resources.session_factory() as session:
        user, org = await IdentitySyncService(session, settings, cache).sync(claims)
        await session.commit()
        principals = await PrincipalResolver(session, cache).resolve(org.id, user.id)
        permissions = await PermissionResolver(session, cache).resolve(principals)
    current = CurrentUser(
        id=user.id,
        org_id=org.id,
        username=user.username,
        display_name=user.display_name,
        principals=principals,
        permissions=permissions,
        is_platform_admin=settings.platform_admin_role in claims.roles,
    )
    request.state.current_user = current
    bind_usage_scope(org_id=current.org_id, user_id=current.id)
    await RateLimiter(resources.cache, settings).check(
        user_id=current.id, org_id=current.org_id, method=request.method, path=request.url.path
    )
    return current


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_request_context(request: Request, user: CurrentUserDep) -> RequestContext:
    state: dict[str, Any] = request.scope.setdefault("state", {})
    audit = AuditContext(
        org_id=user.org_id,
        actor_id=user.id,
        actor_name=user.username,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        trace_id=getattr(request.state, "trace_id", None),
        method=request.method,
        path=request.url.path,
        request_state=state,
    )
    return RequestContext(user=user, audit=audit)


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


def require_permission(*codes: str) -> Callable[..., Awaitable[CurrentUser]]:
    """Dependency factory: the caller needs at least one of `codes`."""

    async def checker(user: CurrentUserDep) -> CurrentUser:
        if not user.has_any_permission(*codes):
            raise PermissionDeniedError(detail={"required_any": list(codes)})
        return user

    return checker


async def require_platform_admin(user: CurrentUserDep) -> CurrentUser:
    if not user.is_platform_admin:
        raise PermissionDeniedError("Platform administrator required")
    return user


TService = TypeVar("TService", bound=BaseService)


def provide(cls: type[TService]) -> Callable[..., TService]:
    def factory(session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep) -> TService:
        return cls(session, ctx, cache)

    return factory


def get_document_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> DocumentService:
    return DocumentService(
        session,
        ctx,
        cache,
        storage=resources.storage,
        queue=resources.task_queue,
        cache=resources.cache,
        settings=settings,
    )


def get_health_service(settings: SettingsDep, resources: ResourcesDep) -> HealthService:
    return HealthService(
        build_dependency_checks(settings, resources), settings.ready_check_timeout_seconds
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
