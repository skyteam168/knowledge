from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import AuditContext, AuditService
from app.services.authz.cache import AuthzCache
from app.services.authz.context import CurrentUser


@dataclass(frozen=True)
class RequestContext:
    user: CurrentUser
    audit: AuditContext

    @property
    def org_id(self) -> str:
        return self.user.org_id


class BaseService:
    """Request-scoped service: owns the session, the caller context and audit recording."""

    def __init__(self, session: AsyncSession, ctx: RequestContext, authz_cache: AuthzCache) -> None:
        self.session = session
        self.ctx = ctx
        self.authz_cache = authz_cache
        self.audit = AuditService(session)

    @property
    def audit_ctx(self) -> AuditContext:
        return self.ctx.audit

    @property
    def org_id(self) -> str:
        return self.ctx.org_id
