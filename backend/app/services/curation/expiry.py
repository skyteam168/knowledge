"""Periodic expiry handling: deprecate expired KOs, remind owners before KOs / documents expire
and when documents are due (or overdue) for their periodic review."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import ACTIVE_GAP_STATUSES, KnowledgeGap
from app.models.base import utcnow
from app.repositories.curation_repo import KnowledgeObjectRepository
from app.services.curation.common import RESOURCE_GAP, system_audit_ctx
from app.services.curation.lifecycle import KoLifecycle, ko_link
from app.services.curation.notifications import NotificationKind, notify
from app.services.knowledge.access import RESOURCE_DOCUMENT, RESOURCE_KO
from app.services.knowledge.review import REMINDER_OVERDUE, REMINDER_SOON, review_recipient

logger = logging.getLogger(__name__)

BATCH = 200
EXPIRED_REASON = "已超过失效时间，系统自动下线"


def _day(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass
class ExpiryResult:
    deprecated: int = 0
    ko_reminders: int = 0
    document_reminders: int = 0
    review_reminders: int = 0
    gap_overdue: int = 0


class ExpiryMonitor:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    async def run_once(self, now: datetime | None = None) -> ExpiryResult:
        now = now or utcnow()
        until = now + timedelta(days=self.settings.expiry_notice_days)
        result = ExpiryResult()
        async with self.session_factory() as session:
            repo = KnowledgeObjectRepository(session)
            for ko in await repo.expired(now, BATCH):
                await KoLifecycle(session, system_audit_ctx(ko.org_id)).deprecate(
                    ko, None, EXPIRED_REASON
                )
                result.deprecated += 1

            for ko in await repo.expiring(now, until, BATCH):
                assert ko.effective_to is not None
                result.ko_reminders += await notify(
                    session,
                    ko.org_id,
                    [ko.owner_id or ko.created_by],
                    kind=NotificationKind.KO_EXPIRING,
                    title=f"知识条目即将失效：{ko.title[:80]}",
                    body=f"失效时间 {_day(ko.effective_to)}，请确认是否需要更新或延期。",
                    resource_type=RESOURCE_KO,
                    resource_id=ko.id,
                    link=ko_link(ko.id),
                    dedupe_key=f"ko-expiry:{ko.id}:{ko.published_version}",
                )
                ko.expiry_notified_at = now

            for doc in await repo.expiring_documents(now, until, BATCH):
                assert doc.effective_to is not None
                result.document_reminders += await notify(
                    session,
                    doc.org_id,
                    [review_recipient(doc)],
                    kind=NotificationKind.DOCUMENT_EXPIRING,
                    title=f"文档即将失效：{doc.title[:80]}",
                    body=f"失效时间 {_day(doc.effective_to)}，请确认是否需要更新。",
                    resource_type=RESOURCE_DOCUMENT,
                    resource_id=doc.id,
                    link=f"/knowledge/{doc.kb_id}/documents/{doc.id}",
                    dedupe_key=f"doc-expiry:{doc.id}:{doc.version}",
                )

            for doc in await repo.review_reminders(now, until, BATCH):
                assert doc.review_due_at is not None
                due = _aware(doc.review_due_at)
                overdue = due <= now
                stage = REMINDER_OVERDUE if overdue else REMINDER_SOON
                result.review_reminders += await notify(
                    session,
                    doc.org_id,
                    [review_recipient(doc)],
                    kind=NotificationKind.DOCUMENT_REVIEW,
                    title=(
                        f"文档复核已逾期：{doc.title[:80]}"
                        if overdue
                        else f"文档即将到复核期：{doc.title[:80]}"
                    ),
                    body=(
                        f"复核截止 {_day(due)}。请确认内容仍然准确，"
                        "在文档详情点「确认复核」，或上传新版本。"
                    ),
                    resource_type=RESOURCE_DOCUMENT,
                    resource_id=doc.id,
                    link=f"/knowledge/{doc.kb_id}/documents/{doc.id}",
                    dedupe_key=f"doc-review:{doc.id}:{due:%Y%m%d}:{stage}",
                )
                doc.review_reminder = stage

            overdue_gaps = (
                await session.execute(
                    select(KnowledgeGap)
                    .where(
                        KnowledgeGap.status.in_(list(ACTIVE_GAP_STATUSES)),
                        KnowledgeGap.due_at.is_not(None),
                        KnowledgeGap.due_at <= now,
                        KnowledgeGap.assignee_id.is_not(None),
                    )
                    .order_by(KnowledgeGap.due_at)
                    .limit(BATCH)
                )
            ).scalars()
            for gap in overdue_gaps:
                assert gap.due_at is not None
                result.gap_overdue += await notify(
                    session,
                    gap.org_id,
                    [gap.assignee_id],
                    kind=NotificationKind.GAP_OVERDUE,
                    title=f"知识缺口已逾期：{gap.query[:80]}",
                    body=f"处理时限 {_day(_aware(gap.due_at))}，请尽快补齐或关闭。",
                    resource_type=RESOURCE_GAP,
                    resource_id=gap.id,
                    link=f"/curation/gaps/{gap.id}",
                    dedupe_key=f"gap-due:{gap.id}:{gap.due_at:%Y%m%d}",
                )
            await session.commit()
        if any(result.__dict__.values()):
            logger.info("expiry_checked", extra=result.__dict__)
        return result
