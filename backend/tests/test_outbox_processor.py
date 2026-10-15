from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import OutboxEvent, OutboxStatus
from app.models.base import utcnow
from app.services.indexing.outbox import EventEnvelope, OutboxProcessor, PermanentEventError
from app.workers.outbox_dispatcher import dispatch_once


async def add_events(engine: AsyncEngine, *specs: tuple[str, str]) -> list[str]:
    """(aggregate_id, event_type) in creation order."""
    base = utcnow() - timedelta(minutes=1)
    async with create_session_factory(engine)() as session:
        events = [
            OutboxEvent(
                org_id="o1",
                aggregate_type="document",
                aggregate_id=agg,
                event_type=etype,
                payload={},
                created_at=base + timedelta(seconds=i),
            )
            for i, (agg, etype) in enumerate(specs)
        ]
        session.add_all(events)
        await session.commit()
        return [e.id for e in events]


async def load(engine: AsyncEngine, event_id: str) -> OutboxEvent:
    async with create_session_factory(engine)() as session:
        event = await session.get(OutboxEvent, event_id)
        assert event is not None
        return event


def make_processor(
    settings: Settings, engine: AsyncEngine, handled: list[str], fail: set[str] | None = None
) -> OutboxProcessor:
    async def handler(event: EventEnvelope) -> None:
        if event.event_type in (fail or set()):
            raise RuntimeError("boom")
        if event.event_type == "bad":
            raise PermanentEventError("malformed")
        handled.append(event.id)

    handlers = {name: handler for name in ("a", "b", "boom", "bad")}
    return OutboxProcessor(create_session_factory(engine), handlers, settings)


async def test_claim_keeps_one_event_in_flight_per_aggregate(
    settings: Settings, engine: AsyncEngine
) -> None:
    d1_a, d2_a, d1_b = await add_events(engine, ("d1", "a"), ("d2", "a"), ("d1", "b"))
    handled: list[str] = []
    processor = make_processor(settings, engine, handled)

    assert await processor.claim() == [d1_a, d2_a], "d1's second event waits for its first"
    assert await processor.claim() == [], "claimed events are leased"
    assert await processor.process(d1_a) == "done"
    assert await processor.claim() == [d1_b]
    assert (await load(engine, d1_b)).status == OutboxStatus.PROCESSING.value
    # A message delivered twice is ignored once the event left `processing`.
    assert await processor.process(d1_b) == "done"
    assert await processor.process(d1_b) == "skipped"
    assert handled == [d1_a, d1_b]


async def test_expired_lease_is_reclaimed(settings: Settings, engine: AsyncEngine) -> None:
    (event_id,) = await add_events(engine, ("d1", "a"))
    processor = make_processor(settings, engine, [])
    assert await processor.claim() == [event_id]
    async with create_session_factory(engine)() as session:
        event = await session.get(OutboxEvent, event_id)
        assert event is not None
        event.locked_until = utcnow() - timedelta(seconds=1)
        await session.commit()
    assert await processor.claim() == [event_id]


async def test_failure_backs_off_and_dead_letters(settings: Settings, engine: AsyncEngine) -> None:
    (event_id,) = await add_events(engine, ("d1", "boom"))
    processor = make_processor(settings, engine, [], fail={"boom"})
    processor.max_attempts = 2

    await processor.claim()
    assert await processor.process(event_id) == OutboxStatus.PENDING.value
    event = await load(engine, event_id)
    assert event.retry_count == 1 and event.last_error == "RuntimeError: boom"
    assert event.next_attempt_at is not None and event.locked_until is None
    assert await processor.claim() == []

    async with create_session_factory(engine)() as session:
        ev = await session.get(OutboxEvent, event_id)
        assert ev is not None
        ev.next_attempt_at = utcnow() - timedelta(seconds=1)
        await session.commit()
    assert await processor.claim() == [event_id]
    assert await processor.process(event_id) == OutboxStatus.DEAD.value
    assert await processor.claim() == []


async def test_dead_events_do_not_block_their_aggregate(
    settings: Settings, engine: AsyncEngine
) -> None:
    bad, later = await add_events(engine, ("d1", "bad"), ("d1", "a"))
    processor = make_processor(settings, engine, [])
    await processor.claim()
    assert await processor.process(bad) == OutboxStatus.DEAD.value, "permanent error: no retry"
    assert await processor.claim() == [later]


@pytest.mark.parametrize(("attempt", "low", "high"), [(1, 4, 6), (2, 8, 12), (4, 32, 48)])
def test_backoff_is_exponential_with_jitter(
    settings: Settings, engine: AsyncEngine, attempt: int, low: float, high: float
) -> None:
    processor = make_processor(settings, engine, [])
    assert all(low <= processor.backoff_seconds(attempt) <= high for _ in range(50))
    assert processor.backoff_seconds(50) <= settings.outbox_backoff_max_seconds * 1.2


async def test_dispatch_once_sends_claimed_ids(settings: Settings, engine: AsyncEngine) -> None:
    ids = await add_events(engine, ("d1", "a"), ("d2", "a"))
    sent: list[str] = []
    assert await dispatch_once(make_processor(settings, engine, []), sent.append) == 2
    assert sent == ids
