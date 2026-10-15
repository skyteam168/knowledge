"""Offline evaluation runs (enqueued by EvalService.create_run)."""

import logging
from dataclasses import dataclass

import dramatiq

from app.core.cache import RedisCache
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.llm import build_llm_gateway
from app.retrieval.factory import build_search_backends
from app.retrieval.pipeline import RetrievalPipeline
from app.services.authz import AuthzCache
from app.services.evaluation.runner import EvalRunner
from app.services.models import attach_chat_routing
from app.services.usage import attach_usage_recorder
from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)
settings = get_settings()

EVALUATION_QUEUE = "evaluation"


@dataclass
class _Runtime:
    runner: EvalRunner


_runtime: _Runtime | None = None


def get_runtime() -> _Runtime:
    """Created lazily inside the worker's event loop (the async engine binds to it)."""
    global _runtime
    if _runtime is None:
        cache = RedisCache.from_url(settings.redis_url)
        gateway = build_llm_gateway(settings)
        session_factory = create_session_factory(create_engine(settings))
        attach_usage_recorder(gateway, session_factory, settings)
        attach_chat_routing(gateway, session_factory, settings)
        _runtime = _Runtime(
            runner=EvalRunner(
                session_factory=session_factory,
                authz_cache=AuthzCache(cache, settings.authz_cache_ttl_seconds),
                pipeline=RetrievalPipeline.build(build_search_backends(settings), gateway, cache),
                gateway=gateway,
                settings=settings,
            )
        )
    return _runtime


@dramatiq.actor(queue_name=EVALUATION_QUEUE, max_retries=0, time_limit=6 * 60 * 60 * 1000)
async def run_evaluation(run_id: str) -> None:
    await get_runtime().runner.run(run_id)
    logger.info("eval_run_processed", extra={"run_id": run_id})
