"""Knowledge-loop actors: gap clustering and expiry checks (enqueued by app.workers.scheduler)."""

import logging
from dataclasses import dataclass

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.llm import LLMGateway, build_llm_gateway
from app.services.curation.clustering import GapClusterer
from app.services.curation.expiry import ExpiryMonitor
from app.services.usage import attach_usage_recorder
from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)
settings = get_settings()

CURATION_QUEUE = "curation"


@dataclass
class _Runtime:
    session_factory: async_sessionmaker[AsyncSession]
    gateway: LLMGateway


_runtime: _Runtime | None = None


def get_runtime() -> _Runtime:
    """Created lazily inside the worker's event loop (the async engine binds to it)."""
    global _runtime
    if _runtime is None:
        session_factory = create_session_factory(create_engine(settings))
        gateway = build_llm_gateway(settings)
        attach_usage_recorder(gateway, session_factory, settings)
        _runtime = _Runtime(session_factory=session_factory, gateway=gateway)
    return _runtime


@dramatiq.actor(queue_name=CURATION_QUEUE, max_retries=0, time_limit=30 * 60 * 1000)
async def cluster_gaps() -> None:
    rt = get_runtime()
    result = await GapClusterer(rt.session_factory, rt.gateway, settings).run_once()
    logger.info("gap_clustering_finished", extra=result.model_dump())


@dramatiq.actor(queue_name=CURATION_QUEUE, max_retries=0, time_limit=30 * 60 * 1000)
async def check_expirations() -> None:
    result = await ExpiryMonitor(get_runtime().session_factory, settings).run_once()
    logger.info("expiry_check_finished", extra=result.__dict__)
