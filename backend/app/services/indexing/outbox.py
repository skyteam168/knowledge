"""Outbox consumption: claim due events, run handlers, back off on failure, dead-letter."""

import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import OutboxEvent, OutboxStatus
from app.models.base import utcnow
from app.repositories.indexing_repo import OutboxRepository

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 4000


class PermanentEventError(Exception):
    """Retrying cannot help (unknown event type, malformed payload): dead-letter at once."""


@dataclass(frozen=True)
class EventEnvelope:
    id: str
    org_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    retry_count: int

    @classmethod
    def of(cls, event: OutboxEvent) -> "EventEnvelope":
        return cls(
            id=event.id,
            org_id=event.org_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            payload=dict(event.payload or {}),
            retry_count=event.retry_count,
        )

    def require(self, key: str) -> Any:
        if key not in self.payload:
            raise PermanentEventError(f"payload of {self.event_type} lacks '{key}'")
        return self.payload[key]


EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class OutboxProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: Mapping[str, EventHandler],
        settings: Settings,
        on_dead: EventHandler | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.handlers = handlers
        self.batch_size = settings.outbox_batch_size
        self.max_attempts = settings.outbox_max_attempts
        self.backoff_base = settings.outbox_backoff_base_seconds
        self.backoff_max = settings.outbox_backoff_max_seconds
        self.lease_seconds = settings.outbox_lease_seconds
        self.on_dead = on_dead

    def backoff_seconds(self, attempt: int) -> float:
        """Delay after the `attempt`-th failure: base * 2^(attempt-1), capped, ±20% jitter."""
        delay = min(self.backoff_base * (2 ** max(attempt - 1, 0)), self.backoff_max)
        return float(delay * random.uniform(0.8, 1.2))

    async def claim(self, limit: int | None = None) -> list[str]:
        now = utcnow()
        async with self.session_factory() as session:
            events = await OutboxRepository(session).claim(
                now, limit or self.batch_size, now + timedelta(seconds=self.lease_seconds)
            )
            ids = [e.id for e in events]
            await session.commit()
        return ids

    async def process(self, event_id: str) -> str:
        """Run the handler of a claimed event; returns the resulting status."""
        async with self.session_factory() as session:
            event = await session.get(OutboxEvent, event_id)
            if event is None or event.status != OutboxStatus.PROCESSING.value:
                return "skipped"
            envelope = EventEnvelope.of(event)

        handler = self.handlers.get(envelope.event_type)
        try:
            if handler is None:
                raise PermanentEventError(f"no handler for event type '{envelope.event_type}'")
            await handler(envelope)
        except Exception as exc:
            return await self._fail(envelope, exc)
        return await self._finish(envelope)

    async def _finish(self, envelope: EventEnvelope) -> str:
        async with self.session_factory() as session:
            event = await session.get(OutboxEvent, envelope.id)
            if event is None:
                return "skipped"
            event.status = OutboxStatus.DONE.value
            event.processed_at = utcnow()
            event.locked_until = None
            event.next_attempt_at = None
            await session.commit()
        logger.info(
            "outbox_event_done", extra={"event_id": envelope.id, "event_type": envelope.event_type}
        )
        return OutboxStatus.DONE.value

    async def _fail(self, envelope: EventEnvelope, exc: Exception) -> str:
        permanent = isinstance(exc, PermanentEventError)
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        async with self.session_factory() as session:
            event = await session.get(OutboxEvent, envelope.id)
            if event is None or event.status != OutboxStatus.PROCESSING.value:
                return "skipped"
            event.retry_count += 1
            event.last_error = error
            event.locked_until = None
            now = utcnow()
            if permanent or event.retry_count >= self.max_attempts:
                event.status = OutboxStatus.DEAD.value
                event.processed_at = now
                event.next_attempt_at = None
            else:
                event.status = OutboxStatus.PENDING.value
                event.next_attempt_at = now + timedelta(
                    seconds=self.backoff_seconds(event.retry_count)
                )
            status, attempts = event.status, event.retry_count
            await session.commit()

        log = logger.error if status == OutboxStatus.DEAD.value else logger.warning
        log(
            "outbox_event_failed",
            extra={
                "event_id": envelope.id,
                "event_type": envelope.event_type,
                "attempts": attempts,
                "status": status,
                "error": error[:300],
            },
        )
        if status == OutboxStatus.DEAD.value and self.on_dead is not None:
            try:
                await self.on_dead(envelope)
            except Exception:
                logger.exception("outbox_on_dead_failed", extra={"event_id": envelope.id})
        return status
