"""Data retention purge (enqueued daily by app.workers.scheduler)."""

import logging

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.services.maintenance import RetentionService
from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)
settings = get_settings()

MAINTENANCE_QUEUE = "maintenance"

_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Created lazily inside the worker's event loop (the async engine binds to it)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(create_engine(settings))
    return _session_factory


@dramatiq.actor(queue_name=MAINTENANCE_QUEUE, max_retries=0, time_limit=2 * 60 * 60 * 1000)
async def purge_expired_data() -> None:
    await RetentionService(get_session_factory(), settings).run_once()
