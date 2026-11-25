"""S2: event timeline denorm + time-range query / downtime count."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models import StructuredRecord
from app.models.base import new_id
from app.schemas.open_api import OpenAggregateObjectsIn, OpenQueryObjectsIn
from app.schemas.structured import StructuredRecordCreate, StructuredSourceCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools
from app.services.structured.seed_equipment import SEED_EQ_EXTERNAL, seed_equipment
from app.services.structured.service import StructuredService

ORG = "org-events-s2"


def _ctx(org_id: str = ORG) -> RequestContext:
    user_id = new_id()
    user = CurrentUser(
        id=user_id,
        org_id=org_id,
        username="events",
        display_name="Events",
        principals=Principals(org_id, user_id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user,
        AuditContext(org_id=org_id, actor_id=user.id, actor_name=user.display_name),
    )


def _tools(session: AsyncSession, ctx: RequestContext) -> OpenOntologyTools:
    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=ctx.user.org_id,
        name="events-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=ctx.user,
    )
    return OpenOntologyTools(session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60), caller)


@pytest.fixture
def service(session: AsyncSession) -> StructuredService:
    return StructuredService(
        session, _ctx(), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


async def test_create_event_denorms_timeline_columns(
    session: AsyncSession, service: StructuredService
) -> None:
    domains = await service.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    source = await service.create_source(
        StructuredSourceCreate(name="EVT-src", type="mes")
    )
    out = await service.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="event",
            external_id="EVT-DT-TEST",
            title="测试停机",
            attrs={
                "equipment_external_id": "EQ-X",
                "event_type": "downtime",
                "occurred_at": "2026-11-18T08:00:00+00:00",
                "ended_at": "2026-11-18T10:30:00+00:00",
                "severity": "high",
                "message": "断纱停机",
            },
        )
    )
    assert out.parent_object_type == "equipment"
    assert out.parent_external_id == "EQ-X"
    assert out.occurred_at == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    assert out.ended_at == datetime(2026, 11, 18, 10, 30, tzinfo=UTC)
    assert out.event_type == "downtime"

    row = await session.scalar(
        select(StructuredRecord).where(StructuredRecord.id == out.id)
    )
    assert row is not None
    # SQLite may drop tzinfo on round-trip; compare wall time.
    got = row.occurred_at
    assert got is not None
    assert got.replace(tzinfo=UTC) == datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    assert row.event_type == "downtime"


async def test_query_and_aggregate_downtime_window(session: AsyncSession) -> None:
    ctx = _ctx()
    await seed_equipment(session, ORG)
    await session.commit()
    tools = _tools(session, ctx)

    page = await tools.query_objects(
        OpenQueryObjectsIn(
            object_type="event",
            event_type="downtime",
            equipment_external_id=SEED_EQ_EXTERNAL,
            occurred_from=datetime(2026, 11, 17, tzinfo=UTC),
            occurred_to=datetime(2026, 11, 24, tzinfo=UTC),
        )
    )
    assert page.total >= 2
    assert {i.external_id for i in page.items} >= {"EVT-DT-01", "EVT-DT-02"}
    assert all(i.attrs.get("event_type") == "downtime" for i in page.items)

    alarm = await tools.query_objects(
        OpenQueryObjectsIn(
            object_type="event",
            event_type="alarm",
            equipment_external_id=SEED_EQ_EXTERNAL,
        )
    )
    assert alarm.total >= 1
    assert any(i.external_id == "EVT-AL-01" for i in alarm.items)

    agg = await tools.aggregate_objects(
        OpenAggregateObjectsIn(
            object_type="event",
            event_type="downtime",
            equipment_external_id=SEED_EQ_EXTERNAL,
            occurred_from=datetime(2026, 11, 17, tzinfo=UTC),
            occurred_to=datetime(2026, 11, 24, tzinfo=UTC),
        )
    )
    assert agg.metric == "count"
    assert agg.value >= 2
