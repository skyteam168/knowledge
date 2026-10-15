from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import AuditLog, OutboxEvent, OutboxStatus, QaTrace
from app.models.base import utcnow
from app.services.maintenance import RetentionService

ORG = "org-1"


def _trace(age_days: int) -> QaTrace:
    return QaTrace(
        org_id=ORG, query="q", status="ok", created_at=utcnow() - timedelta(days=age_days)
    )


def _event(age_days: int, status: OutboxStatus) -> OutboxEvent:
    return OutboxEvent(
        org_id=ORG,
        aggregate_type="document",
        aggregate_id="d1",
        event_type="document.indexed",
        status=status.value,
        created_at=utcnow() - timedelta(days=age_days),
    )


def _audit(age_days: int) -> AuditLog:
    return AuditLog(org_id=ORG, action="kb.update", created_at=utcnow() - timedelta(days=age_days))


async def _count(engine: AsyncEngine, model: type) -> int:
    async with create_session_factory(engine)() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_purges_only_rows_past_retention(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add_all([_trace(400), _trace(200), _trace(10)])
        session.add_all(
            [
                _event(60, OutboxStatus.DONE),
                _event(60, OutboxStatus.DEAD),
                _event(60, OutboxStatus.PENDING),
                _event(5, OutboxStatus.DONE),
            ]
        )
        session.add_all([_audit(4000), _audit(1)])
        await session.commit()

    settings = Settings(retention_trace_days=180, retention_outbox_days=30, retention_audit_days=0)
    result = await RetentionService(factory, settings).run_once()

    assert result.deleted["qa_traces"] == 2
    assert result.deleted["outbox_events"] == 1
    assert "audit_logs" not in result.deleted
    assert await _count(engine, QaTrace) == 1
    async with factory() as session:
        left = (await session.execute(select(OutboxEvent.status))).scalars().all()
    assert sorted(left) == sorted(
        [OutboxStatus.DEAD.value, OutboxStatus.PENDING.value, OutboxStatus.DONE.value]
    )
    assert await _count(engine, AuditLog) == 2


async def test_purges_in_batches_until_done(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add_all([_trace(365) for _ in range(7)] + [_trace(1)])
        await session.commit()

    settings = Settings(retention_trace_days=30, retention_batch_size=3)
    result = await RetentionService(factory, settings).run_once()

    assert result.deleted["qa_traces"] == 7
    assert await _count(engine, QaTrace) == 1


async def test_zero_days_keeps_everything(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add_all([_trace(3650), _audit(3650)])
        await session.commit()

    settings = Settings(
        retention_trace_days=0,
        retention_outbox_days=0,
        retention_api_call_log_days=0,
        retention_llm_usage_days=0,
        retention_audit_days=0,
    )
    result = await RetentionService(factory, settings).run_once()

    assert result.deleted == {}
    assert await _count(engine, QaTrace) == 1
    assert await _count(engine, AuditLog) == 1
