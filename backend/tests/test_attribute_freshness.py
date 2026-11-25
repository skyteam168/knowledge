"""Wave B Task7: source_of_truth + freshness SLA on get_object."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models import EquipDevice, StructuredSource, StructuredSourceType
from app.models.base import new_id
from app.ontology.freshness import compute_freshness
from app.schemas.open_api import OpenGetObjectIn
from app.schemas.semantic import (
    SemanticAttributeCreate,
    SemanticEntityCreate,
    SemanticMappingCreate,
    SemanticVersionCreate,
)
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.service import OntologyStudioService
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools


ORG = "org-fresh"


def _ctx() -> RequestContext:
    uid = new_id()
    user = CurrentUser(
        id=uid,
        org_id=ORG,
        username="fresh",
        display_name="Fresh",
        principals=Principals(ORG, uid),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user, AuditContext(org_id=ORG, actor_id=uid, actor_name="Fresh")
    )


def test_compute_freshness_stale_when_age_exceeds_sla() -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    fresh = compute_freshness(
        updated_at=now - timedelta(seconds=30),
        now=now,
        sla_seconds=60,
        source_of_truth=[{"table": "equip_devices", "column": "status"}],
    )
    assert fresh.stale is False
    stale = compute_freshness(
        updated_at=now - timedelta(seconds=120),
        now=now,
        sla_seconds=60,
    )
    assert stale.stale is True
    assert stale.age_seconds == 120


async def test_attribute_freshness_stale_flag(session: AsyncSession) -> None:
    ctx = _ctx()
    studio = OntologyStudioService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60)
    )
    ver = await studio.create_version(SemanticVersionCreate(name="fresh-v1"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(local_name="Device", label="设备", object_type="device"),
    )
    attr = await studio.add_attribute(
        ent.id, SemanticAttributeCreate(name="status", label="状态", attr_kind="enum")
    )
    mapping = await studio.add_mapping(
        attr.id,
        SemanticMappingCreate(
            table_name="equip_devices",
            column_name="status",
            source_of_truth=True,
            freshness_sla_seconds=60,
        ),
    )
    assert mapping.source_of_truth is True
    assert mapping.freshness_sla_seconds == 60
    await studio.set_entity_status(ent.id, "approved")
    await studio.set_attribute_status(attr.id, "approved")
    await studio.set_mapping_status(mapping.id, "approved")
    await studio.publish(ver.id)

    source = StructuredSource(
        org_id=ORG,
        name="fresh-src",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={},
    )
    session.add(source)
    await session.flush()
    device = EquipDevice(
        org_id=ORG,
        source_id=source.id,
        external_id="EQ-FRESH-1",
        name="陈旧设备",
        status="1",
        location="A",
        meta={},
    )
    session.add(device)
    await session.flush()
    # Force an old updated_at
    device.updated_at = datetime.now(UTC) - timedelta(hours=2)
    await session.flush()

    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=ORG,
        name="fresh-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=ctx.user,
    )
    tools = OpenOntologyTools(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60), caller
    )
    got = await tools.get_object(
        OpenGetObjectIn(object_type="device", object_id=device.id)
    )
    freshness = got.attrs.get("_meta", {}).get("freshness")
    assert freshness is not None
    assert freshness["stale"] is True
    assert freshness["sla_seconds"] == 60
    assert freshness["source_of_truth"]
    assert freshness["source_of_truth"][0]["column"] == "status"
