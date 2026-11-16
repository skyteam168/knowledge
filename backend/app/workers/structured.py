"""Structured mirror sync: manual enqueue + periodic due-source dispatcher."""

from __future__ import annotations

import logging

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.services.structured.sync import StructuredSyncExecutor, due_structured_sources
from app.workers import broker as _broker  # noqa: F401

logger = logging.getLogger(__name__)
settings = get_settings()

STRUCTURED_QUEUE = "structured"
SCHEDULER_ACTOR = "structured-sync"

_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(create_engine(settings))
    return _session_factory


@dramatiq.actor(queue_name=STRUCTURED_QUEUE, max_retries=0, time_limit=30 * 60 * 1000)
async def sync_structured_source(org_id: str, source_id: str, triggered_by: str | None = None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await StructuredSyncExecutor(session, settings).sync_source(
                org_id,
                source_id,
                triggered_by=triggered_by or SCHEDULER_ACTOR,
            )
            await session.commit()
            logger.info(
                "structured_sync_finished",
                extra={
                    "org_id": org_id,
                    "source_id": source_id,
                    "status": result.get("status"),
                    "stats": result.get("stats"),
                },
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "structured_sync_failed",
                extra={"org_id": org_id, "source_id": source_id},
            )
            raise


@dramatiq.actor(queue_name=STRUCTURED_QUEUE, max_retries=0, time_limit=5 * 60 * 1000)
async def dispatch_structured_syncs() -> None:
    factory = get_session_factory()
    due: list[tuple[str, str]] = []
    async with factory() as session:
        for source in await due_structured_sources(session):
            due.append((source.org_id, source.id))
    for org_id, source_id in due:
        sync_structured_source.send(org_id, source_id, SCHEDULER_ACTOR)
        logger.info(
            "structured_sync_dispatched",
            extra={"org_id": org_id, "source_id": source_id},
        )
