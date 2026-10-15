"""Deletes log-like rows past their retention period (enqueued daily by the scheduler)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import (
    ApiCallLog,
    AuditLog,
    LlmUsage,
    OutboxEvent,
    OutboxStatus,
    QaTrace,
    RetrievalTrace,
)
from app.models.base import utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionRule:
    name: str
    model: Any
    days: int
    extra: tuple[ColumnElement[bool], ...] = ()


@dataclass
class RetentionResult:
    deleted: dict[str, int] = field(default_factory=dict)


class RetentionService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def rules(self) -> list[RetentionRule]:
        s = self.settings
        return [
            RetentionRule("qa_traces", QaTrace, s.retention_trace_days),
            RetentionRule("retrieval_traces", RetrievalTrace, s.retention_trace_days),
            # Pending / failed / dead events are never purged: they still need attention.
            RetentionRule(
                "outbox_events",
                OutboxEvent,
                s.retention_outbox_days,
                (OutboxEvent.status == OutboxStatus.DONE.value,),
            ),
            RetentionRule("api_call_logs", ApiCallLog, s.retention_api_call_log_days),
            RetentionRule("llm_usage", LlmUsage, s.retention_llm_usage_days),
            RetentionRule("audit_logs", AuditLog, s.retention_audit_days),
        ]

    async def run_once(self, now: datetime | None = None) -> RetentionResult:
        now = now or utcnow()
        result = RetentionResult()
        for rule in self.rules():
            if rule.days <= 0:
                continue
            cutoff = now - timedelta(days=rule.days)
            result.deleted[rule.name] = await self._purge(rule, cutoff)
        logger.info("retention_purged", extra={"deleted": result.deleted})
        return result

    async def _purge(self, rule: RetentionRule, cutoff: datetime) -> int:
        model = rule.model
        total = 0
        batch = max(1, self.settings.retention_batch_size)
        # Small batches keep each transaction (and its locks) short on large tables.
        while True:
            ids = (
                select(model.id)
                .where(model.created_at < cutoff, *rule.extra)
                .limit(batch)
                .scalar_subquery()
            )
            async with self.session_factory() as session:
                res = await session.execute(delete(model).where(model.id.in_(ids)))
                await session.commit()
            count = int(getattr(res, "rowcount", 0) or 0)
            total += count
            if count < batch:
                return total
