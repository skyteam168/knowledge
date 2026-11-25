"""Wave B Task8: valid-time device state history aligned with downtime windows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ontology.state_machines import DeviceState
from app.services.structured.identity import EntityIdentityService
from app.services.structured.state_history import EntityStateHistoryService


@pytest.fixture
def identity(session: AsyncSession) -> EntityIdentityService:
    return EntityIdentityService(session)


@pytest.fixture
def history(session: AsyncSession) -> EntityStateHistoryService:
    return EntityStateHistoryService(session)


async def test_downtime_window_query_aligns_with_stopped_interval(
    identity: EntityIdentityService,
    history: EntityStateHistoryService,
) -> None:
    org_id = "org-state-hist"
    entity = await identity.create_canonical(
        org_id, object_type="device", display_name="历史测机"
    )
    t0 = datetime(2026, 11, 25, 8, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=2)
    t2 = t0 + timedelta(hours=5)

    await history.record_status(org_id, entity.id, "0", at=t0, source="mes")
    await history.record_status(org_id, entity.id, "1", at=t1, source="mes")  # STOPPED
    await history.record_status(org_id, entity.id, "0", at=t2, source="mes")

    downs = await history.downtime_windows(
        org_id,
        entity.id,
        window_from=t0,
        window_to=t2 + timedelta(minutes=1),
    )
    assert len(downs) == 1
    assert downs[0].standard_status == DeviceState.STOPPED.value

    def _aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    assert _aware(downs[0].valid_from) == t1
    assert _aware(downs[0].valid_to) == t2

    # S2-style overlap: query a sub-window inside the stop interval
    mid = await history.downtime_windows(
        org_id,
        entity.id,
        window_from=t1 + timedelta(minutes=30),
        window_to=t1 + timedelta(hours=1),
    )
    assert len(mid) == 1
    assert mid[0].id == downs[0].id
