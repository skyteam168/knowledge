"""Indexing actors: outbox events dispatched by app.workers.outbox_dispatcher, KB repairs."""

import logging

import dramatiq

from app.core.config import get_settings
from app.services.indexing.runtime import IndexingRuntime
from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)
settings = get_settings()

INDEX_QUEUE = "index"
_runtime: IndexingRuntime | None = None


def get_runtime() -> IndexingRuntime:
    """Created lazily inside the worker's event loop (the async engine binds to it)."""
    global _runtime
    if _runtime is None:
        _runtime = IndexingRuntime.create(settings)
    return _runtime


# Retries are owned by the outbox (backoff + dead letter), not by Dramatiq.
@dramatiq.actor(
    queue_name=INDEX_QUEUE, max_retries=0, time_limit=settings.outbox_lease_seconds * 1000
)
async def process_outbox_event(event_id: str) -> None:
    await get_runtime().processor.process(event_id)


@dramatiq.actor(queue_name=INDEX_QUEUE, max_retries=0, time_limit=6 * 60 * 60 * 1000)
async def repair_kb_index(org_id: str, kb_id: str) -> None:
    result = await get_runtime().consistency.repair(org_id, kb_id)
    logger.info(
        "kb_index_repair_finished",
        extra={
            "kb_id": kb_id,
            "reindexed": len(result.reindexed_documents),
            "consistent": result.report.consistent,
        },
    )
