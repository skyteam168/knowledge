from collections.abc import Iterable

from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models import KnowledgeBase, User
from app.schemas.curation import UserRef
from app.services.audit_service import AuditContext
from app.services.authz import CurrentUser
from app.services.knowledge.access import KnowledgeAccess

RESOURCE_GAP = "knowledge_gap"
RESOURCE_KO_AUDIT = "knowledge_object"
SYSTEM_ACTOR = "system"


def system_audit_ctx(org_id: str) -> AuditContext:
    return AuditContext(org_id=org_id, actor_id=None, actor_name=SYSTEM_ACTOR)


async def user_refs(
    session: AsyncSession, org_id: str, ids: Iterable[str | None]
) -> dict[str, UserRef]:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    stmt = select(User).where(User.org_id == org_id, User.id.in_(wanted))
    return {
        u.id: UserRef(id=u.id, name=u.display_name or u.username)
        for u in (await session.execute(stmt)).scalars()
    }


async def kb_names(session: AsyncSession, org_id: str, ids: Iterable[str | None]) -> dict[str, str]:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    stmt = select(KnowledgeBase.id, KnowledgeBase.name).where(
        KnowledgeBase.org_id == org_id, KnowledgeBase.id.in_(wanted)
    )
    return {i: n for i, n in (await session.execute(stmt)).all()}


def readable_kb_scope(
    access: KnowledgeAccess,
    user: CurrentUser,
    column: InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    *,
    include_unscoped: bool = False,
) -> ColumnElement[bool]:
    """Rows whose knowledge base (`column`) the user can read (optionally: or no KB yet)."""
    if user.is_superuser:
        return true()
    kb_ids = select(KnowledgeBase.id).where(
        KnowledgeBase.org_id == user.org_id,
        KnowledgeBase.deleted_at.is_(None),
        access.readable_kb_clause(user),
    )
    clause = column.in_(kb_ids)
    return or_(column.is_(None), clause) if include_unscoped else clause
