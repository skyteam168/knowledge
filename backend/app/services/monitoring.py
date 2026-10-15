"""Backlog gauges (task queues, index outbox) refreshed lazily when /metrics is scraped."""

import asyncio
import logging
import time
from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import KeyValueCache
from app.core.metrics import OUTBOX_BACKLOG, OUTBOX_OLDEST, QUEUE_BACKLOG
from app.models import OutboxEvent, OutboxStatus
from app.models.base import utcnow

logger = logging.getLogger(__name__)

QUEUES = (
    "default",
    "ingest",
    "index",
    "curation",
    "analytics",
    "evaluation",
    "directory",
    "maintenance",
)
OUTBOX_STATUSES = (OutboxStatus.PENDING, OutboxStatus.PROCESSING, OutboxStatus.DEAD)


class BacklogCollector:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cache: KeyValueCache,
        max_age_seconds: float,
        namespace: str = "dramatiq",
    ) -> None:
        self.session_factory = session_factory
        self.cache = cache
        self.max_age_seconds = max_age_seconds
        self.namespace = namespace
        self._refreshed = 0.0
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        """At most once per `max_age_seconds`; failures keep the previous values."""
        if time.monotonic() - self._refreshed < self.max_age_seconds:
            return
        async with self._lock:
            if time.monotonic() - self._refreshed < self.max_age_seconds:
                return
            try:
                await self._queues()
                await self._outbox()
            except Exception:
                logger.warning("backlog_metrics_failed", exc_info=True)
            self._refreshed = time.monotonic()

    async def _queues(self) -> None:
        for queue in QUEUES:
            ready = await self.cache.llen(f"{self.namespace}:{queue}")
            delayed = await self.cache.llen(f"{self.namespace}:{queue}.DQ")
            QUEUE_BACKLOG.labels(queue).set(ready + delayed)

    async def _outbox(self) -> None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(OutboxEvent.status, func.count(), func.min(OutboxEvent.created_at))
                    .where(OutboxEvent.status.in_([s.value for s in OUTBOX_STATUSES]))
                    .group_by(OutboxEvent.status)
                )
            ).all()
        counts = {s: int(c) for s, c, _ in rows}
        for status in OUTBOX_STATUSES:
            OUTBOX_BACKLOG.labels(status.value).set(counts.get(status.value, 0))
        oldest = next((m for s, _, m in rows if s == OutboxStatus.PENDING.value), None)
        if oldest is not None and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        OUTBOX_OLDEST.set((utcnow() - oldest).total_seconds() if oldest else 0)
