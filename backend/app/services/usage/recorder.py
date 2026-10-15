"""Buffered writer of model usage events: model calls never wait for the database."""

import asyncio
import contextlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.llm import LLMGateway
from app.llm.usage import FEATURE_OTHER, UsageEvent
from app.models import LlmUsage

logger = logging.getLogger(__name__)

# Events kept in memory while the database is unreachable; older ones are dropped beyond it.
MAX_BUFFER = 50_000


def to_row(event: UsageEvent) -> LlmUsage:
    scope = event.scope
    assert scope.org_id is not None
    return LlmUsage(
        org_id=scope.org_id,
        user_id=scope.user_id,
        feature=scope.feature or FEATURE_OTHER,
        stage=scope.stage,
        kind=event.kind,
        model=event.model[:128],
        prompt_tokens=event.prompt_tokens,
        completion_tokens=event.completion_tokens,
        total_tokens=event.total_tokens,
        estimated=event.estimated,
        input_count=event.input_count,
        latency_ms=event.latency_ms,
        first_token_ms=event.first_token_ms,
        status=event.status,
        fallback=event.fallback,
        conversation_id=scope.conversation_id,
        message_id=scope.message_id,
    )


class DbUsageRecorder:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        flush_seconds: float = 2.0,
        batch_size: int = 500,
    ) -> None:
        self.session_factory = session_factory
        self.flush_seconds = max(0.0, flush_seconds)
        self.batch_size = max(1, batch_size)
        self._buffer: list[UsageEvent] = []
        self._task: asyncio.Task[None] | None = None
        self._flushing = False

    def record(self, event: UsageEvent) -> None:
        if not event.scope.org_id:
            logger.debug("llm_usage_unattributed", extra={"kind": event.kind})
            return
        if len(self._buffer) >= MAX_BUFFER:
            del self._buffer[: self.batch_size]
            logger.warning("llm_usage_buffer_full", extra={"dropped": self.batch_size})
        self._buffer.append(event)
        if self._task is None or self._task.done():
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            self._task = loop.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(self.flush_seconds)
        await self.flush()

    async def flush(self) -> int:
        written = 0
        self._flushing = True
        try:
            while self._buffer:
                batch = self._buffer[: self.batch_size]
                del self._buffer[: self.batch_size]
                try:
                    async with self.session_factory() as session:
                        session.add_all([to_row(e) for e in batch])
                        await session.commit()
                    written += len(batch)
                except Exception:
                    logger.exception("llm_usage_flush_failed", extra={"dropped": len(batch)})
        finally:
            self._flushing = False
        return written

    async def aclose(self) -> None:
        task = self._task
        if task is not None and not task.done():
            if self._flushing:
                with contextlib.suppress(Exception):
                    await task
            else:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await self.flush()


def attach_usage_recorder(
    gateway: LLMGateway, session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> DbUsageRecorder | None:
    if not settings.llm_usage_enabled:
        return None
    recorder = DbUsageRecorder(
        session_factory,
        flush_seconds=settings.llm_usage_flush_seconds,
        batch_size=settings.llm_usage_batch_size,
    )
    gateway.recorder = recorder
    return recorder
