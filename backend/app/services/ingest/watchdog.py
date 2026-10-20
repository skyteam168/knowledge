"""Reclaim documents stuck in parsing / indexing after a worker crash.

Without this, a process kill leaves ``status=parsing|indexing`` forever and the UI
only shows "processing". We mark them failed so operators can reprocess.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import Document, DocumentStatus
from app.models.base import utcnow

STUCK_STATUSES = (DocumentStatus.PARSING.value, DocumentStatus.INDEXING.value)


@dataclass
class WatchdogResult:
    scanned: int = 0
    failed: int = 0


class IngestWatchdog:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    async def run_once(self) -> WatchdogResult:
        timeout = max(60, int(self.settings.ingest_stuck_timeout_seconds))
        cutoff = utcnow() - timedelta(seconds=timeout)
        result = WatchdogResult()
        async with self.session_factory() as session:
            stmt = select(Document.id, Document.status).where(
                Document.deleted_at.is_(None),
                Document.status.in_(STUCK_STATUSES),
                Document.updated_at < cutoff,
            )
            rows = list((await session.execute(stmt)).all())
            result.scanned = len(rows)
            if not rows:
                return result
            message = (
                f"处理超时（超过 {timeout} 秒仍停留在解析/索引中，可能因 Worker 中断）；"
                "请在文档页点击重新处理"
            )
            await session.execute(
                update(Document)
                .where(Document.id.in_([r.id for r in rows]))
                .values(
                    status=DocumentStatus.FAILED.value,
                    error_message=message,
                    updated_at=utcnow(),
                )
            )
            await session.commit()
            result.failed = len(rows)
        return result
