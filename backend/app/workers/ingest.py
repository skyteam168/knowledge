"""Ingestion actors. Async actors run on the AsyncIO middleware's event loop thread."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import dramatiq

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.storage import MinioStorage
from app.services.ingest.chunker import Chunker, ChunkingConfig
from app.services.ingest.parsers import ParseError, ParserRegistry
from app.services.ingest.pipeline import IngestPipeline
from app.services.ingest.queue import DramatiqTaskQueue
from app.services.security.pii import PiiMasker
from app.workers import broker as _broker  # noqa: F401  (configures the global broker first)

logger = logging.getLogger(__name__)
settings = get_settings()

_pipeline: IngestPipeline | None = None

INGEST_QUEUE = "ingest"
MIN_BACKOFF_MS = 5_000
MAX_BACKOFF_MS = 300_000
TIME_LIMIT_MS = 30 * 60 * 1000
ON_RETRY_EXHAUSTED = "ingest_retries_exhausted"


async def get_pipeline() -> IngestPipeline:
    """Created lazily inside the worker's event loop (the async engine binds to it)."""
    global _pipeline
    if _pipeline is None:
        storage = MinioStorage(settings)
        await storage.ensure_bucket()
        _pipeline = IngestPipeline(
            session_factory=create_session_factory(create_engine(settings)),
            storage=storage,
            parsers=ParserRegistry(settings),
            chunker=Chunker(ChunkingConfig.from_settings(settings)),
            queue=DramatiqTaskQueue(),
            masker=PiiMasker(settings.pii_types) if settings.pii_mask_on_ingest else None,
        )
    return _pipeline


async def _run(
    step: Callable[[IngestPipeline], Callable[[str, int], Awaitable[bool]]],
    document_id: str,
    version: int,
) -> None:
    pipeline = await get_pipeline()
    try:
        await step(pipeline)(document_id, version)
    except ParseError as exc:
        # Permanent: retrying the same bytes cannot succeed.
        await pipeline.mark_failed(document_id, version, f"解析失败：{exc}")


@dramatiq.actor(
    queue_name=INGEST_QUEUE,
    max_retries=settings.ingest_max_retries,
    min_backoff=MIN_BACKOFF_MS,
    max_backoff=MAX_BACKOFF_MS,
    time_limit=TIME_LIMIT_MS,
    on_retry_exhausted=ON_RETRY_EXHAUSTED,
)
async def parse_document(document_id: str, version: int) -> None:
    await _run(lambda p: p.parse, document_id, version)


@dramatiq.actor(
    queue_name=INGEST_QUEUE,
    max_retries=settings.ingest_max_retries,
    min_backoff=MIN_BACKOFF_MS,
    max_backoff=MAX_BACKOFF_MS,
    time_limit=TIME_LIMIT_MS,
    on_retry_exhausted=ON_RETRY_EXHAUSTED,
)
async def chunk_document(document_id: str, version: int) -> None:
    await _run(lambda p: p.chunk, document_id, version)


@dramatiq.actor(queue_name=INGEST_QUEUE, max_retries=3)
async def ingest_retries_exhausted(message: dict[str, Any], retry_info: dict[str, Any]) -> None:
    args = message.get("args") or []
    if len(args) < 2:
        return
    traceback = str(message.get("options", {}).get("traceback") or "").strip()
    last_line = traceback.splitlines()[-1] if traceback else "unknown error"
    step = "解析" if message.get("actor_name") == "parse_document" else "切分"
    pipeline = await get_pipeline()
    await pipeline.mark_failed(
        str(args[0]),
        int(args[1]),
        f"{step}失败（已重试 {retry_info.get('retries', 0)} 次）：{last_line}",
    )
