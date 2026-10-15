from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.models.base import utcnow
from app.repositories.base import paginate
from app.repositories.curation_repo import NotificationRepository
from app.schemas.common import Page
from app.schemas.curation import NotificationOut
from app.services.context import BaseService


class NotificationKind:
    KO_PUBLISHED = "ko_published"
    KO_REJECTED = "ko_rejected"
    KO_DEPRECATED = "ko_deprecated"
    KO_EXPIRING = "ko_expiring"
    DOCUMENT_EXPIRING = "document_expiring"
    GAP_ASSIGNED = "gap_assigned"
    GAP_RESOLVED = "gap_resolved"
    REVIEW_REQUESTED = "review_requested"


async def notify(
    session: AsyncSession,
    org_id: str,
    user_ids: Iterable[str | None],
    *,
    kind: str,
    title: str,
    body: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> int:
    """Queue notifications in the caller's transaction; a known dedupe key is skipped."""
    repo = NotificationRepository(session)
    created = 0
    for user_id in dict.fromkeys(u for u in user_ids if u):
        if dedupe_key and await repo.exists(user_id, dedupe_key):
            continue
        session.add(
            Notification(
                org_id=org_id,
                user_id=user_id,
                kind=kind,
                title=title[:255],
                body=body,
                resource_type=resource_type,
                resource_id=resource_id,
                link=link,
                dedupe_key=dedupe_key,
            )
        )
        created += 1
    if created:
        await session.flush()
    return created


class NotificationService(BaseService):
    @property
    def repo(self) -> NotificationRepository:
        return NotificationRepository(self.session)

    async def list_page(self, *, unread_only: bool, page: int, size: int) -> Page[NotificationOut]:
        stmt = self.repo.list_stmt(self.org_id, self.ctx.user.id, unread_only)
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(
            items=[NotificationOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            size=size,
        )

    async def unread_count(self) -> int:
        return await self.repo.unread_count(self.org_id, self.ctx.user.id)

    async def mark_read(self, ids: list[str] | None) -> int:
        return await self.repo.mark_read(self.org_id, self.ctx.user.id, ids, utcnow())
