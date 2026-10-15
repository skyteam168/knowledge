"""Periodic expiry handling: deprecate expired KOs, remind owners before KOs / documents expire."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.base import utcnow
from app.repositories.curation_repo import KnowledgeObjectRepository
from app.services.curation.common import system_audit_ctx
from app.services.curation.lifecycle import KoLifecycle, ko_link
from app.services.curation.notifications import NotificationKind, notify
from app.services.knowledge.access import RESOURCE_DOCUMENT, RESOURCE_KO

logger = logging.getLogger(__name__)

BATCH = 200
EXPIRED_REASON = "已超过失效时间，系统自动下线"


def _day(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


@dataclass
class ExpiryResult:
    deprecated: int = 0
    ko_reminders: int = 0
    document_reminders: int = 0


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
                    [doc.created_by],
                    kind=NotificationKind.DOCUMENT_EXPIRING,
                    title=f"文档即将失效：{doc.title[:80]}",
                    body=f"失效时间 {_day(doc.effective_to)}，请确认是否需要更新。",
                    resource_type=RESOURCE_DOCUMENT,
                    resource_id=doc.id,
                    link=f"/knowledge/{doc.kb_id}/documents/{doc.id}",
                    dedupe_key=f"doc-expiry:{doc.id}:{doc.version}",
                )
            await session.commit()
        if result.deprecated or result.ko_reminders or result.document_reminders:
            logger.info("expiry_checked", extra=result.__dict__)
        return result
