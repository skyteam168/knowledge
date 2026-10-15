"""Directory sync actors: one run (enqueued by the API) and the periodic dispatcher."""

import asyncio
import logging
from dataclasses import dataclass

import dramatiq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.cache import KeyValueCache, RedisCache
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.models import DirectorySource, DirectorySyncRun, SyncMode, SyncStatus
from app.services.audit_service import AuditContext
from app.services.authz.cache import AuthzCache
from app.services.directory.service import DirectorySyncExecutor, due_sources, expire_stale_runs
from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)
settings = get_settings()

DIRECTORY_QUEUE = "directory"
SCHEDULER_ACTOR = "directory-sync"


@dataclass
class _Runtime:
    session_factory: async_sessionmaker[AsyncSession]
    cache: KeyValueCache


_runtime: _Runtime | None = None


def get_runtime() -> _Runtime:
    """Created lazily inside the worker's event loop (the async engine binds to it)."""
    global _runtime
    if _runtime is None:
        _runtime = _Runtime(
            session_factory=create_session_factory(create_engine(settings)),
            cache=RedisCache.from_url(settings.redis_url),
        )
    return _runtime


async def run_sync(
    session_factory: async_sessionmaker[AsyncSession], cache: KeyValueCache, run_id: str
) -> str | None:
    async with session_factory() as session:
        run: DirectorySyncRun | None = None
        # The API commits before enqueueing; this only covers replica lag / slow commits.
        for _ in range(20):
            run = await session.get(DirectorySyncRun, run_id)
            if run is not None:
                break
            await asyncio.sleep(0.5)
        if run is None or run.status != SyncStatus.RUNNING:
            return None
        source = await session.get(DirectorySource, run.source_id)
        if source is None:
            return None
        audit_ctx = AuditContext(
            org_id=source.org_id, actor_id=None, actor_name=run.triggered_by or SCHEDULER_ACTOR
        )
        authz = AuthzCache(cache, settings.authz_cache_ttl_seconds)
        await DirectorySyncExecutor(session, settings, authz, cache).execute(run, source, audit_ctx)
        return run.status


@dramatiq.actor(queue_name=DIRECTORY_QUEUE, max_retries=0, time_limit=60 * 60 * 1000)
async def sync_directory(run_id: str) -> None:
    rt = get_runtime()
    status = await run_sync(rt.session_factory, rt.cache, run_id)
    logger.info("directory_sync_finished", extra={"run_id": run_id, "status": status})


async def dispatch_due(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    run_ids: list[str] = []
    async with session_factory() as session:
        for source in await due_sources(session):
            await expire_stale_runs(session, source.id)
            busy = await session.scalar(
                select(DirectorySyncRun.id)
                .where(
                    DirectorySyncRun.source_id == source.id,
                    DirectorySyncRun.status == SyncStatus.RUNNING.value,
                )
                .limit(1)
            )
            if busy:
                continue
            run = DirectorySyncRun(
                org_id=source.org_id,
                source_id=source.id,
                mode=SyncMode.APPLY.value,
                status=SyncStatus.RUNNING.value,
                stats={},
                changes={},
                triggered_by=SCHEDULER_ACTOR,
            )
            session.add(run)
            await session.flush()
            run_ids.append(run.id)
        await session.commit()
    return run_ids


@dramatiq.actor(queue_name=DIRECTORY_QUEUE, max_retries=0, time_limit=5 * 60 * 1000)
async def dispatch_directory_syncs() -> None:
    for run_id in await dispatch_due(get_runtime().session_factory):
        sync_directory.send(run_id)
        logger.info("directory_sync_dispatched", extra={"run_id": run_id})
