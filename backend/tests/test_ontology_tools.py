"""O4 Open/MCP ontology + object tools."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import NotFoundError
from app.models import ObjectRelation, ObjectRelationType
from app.models.base import new_id
from app.schemas.open_api import OpenGetObjectIn, OpenQueryObjectsIn, OpenTraverseIn
from app.schemas.structured import StructuredRecordCreate, StructuredSourceCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools
from app.services.structured.seed_equipment import seed_equipment
from app.services.structured.service import StructuredService


ORG = "org-onto-tools"


def _ctx(org_id: str = ORG) -> RequestContext:
    user_id = new_id()
    user = CurrentUser(
        id=user_id,
        org_id=org_id,
        username="onto",
        display_name="Onto",
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
        name="onto-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=ctx.user,
    )
    return OpenOntologyTools(session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60), caller)


async def test_describe_ontology_contract_fields(session: AsyncSession) -> None:
    tools = _tools(session, _ctx())
    summary = await tools.describe_ontology(scope="summary", version="platform")
    assert summary.namespace
    assert "Equipment" in summary.classes or "FailureMode" in summary.classes
    assert "hasFailureMode" in summary.industrial_relation_properties
    assert summary.attribute_schemas == []
    assert "has_failure_mode" in summary.hard_object_relations
    assert "located_in" in summary.soft_object_relations

    full = await tools.describe_ontology(scope="all", version="platform")
    assert full.attribute_schemas
    assert full.scope == "all"


async def test_get_query_traverse_objects(session: AsyncSession) -> None:
    ctx = _ctx()
    structured = StructuredService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60)
    )
    await seed_equipment(session, ORG)
    await session.commit()
    domains = await structured.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    source = await structured.create_source(
        StructuredSourceCreate(name="onto-src", type="mes")
    )
    equip = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="equipment",
            external_id="EQ-ONTO-1",
            title="本体测设备",
            attrs={"model": "X"},
        )
    )
    fm = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="failure_mode",
            external_id="FM-ONTO-1",
            title="断纱",
            attrs={
                "equipment_external_id": "EQ-ONTO-1",
                "code": "FM-ONTO-1",
                "severity": 4,
            },
        )
    )
    session.add(
        ObjectRelation(
            id=new_id(),
            org_id=ORG,
            relation_type=ObjectRelationType.HAS_FAILURE_MODE.value,
            from_kind="structured",
            from_id=equip.id,
            from_object_type="equipment",
            to_kind="structured",
            to_id=fm.id,
            to_object_type="failure_mode",
        )
    )
    await session.commit()

    tools = _tools(session, ctx)
    got = await tools.get_object(
        OpenGetObjectIn(object_type="equipment", external_id="EQ-ONTO-1")
    )
    assert got.external_id == "EQ-ONTO-1"
    assert any(n.object_id == fm.id for n in got.neighbors)

    page = await tools.query_objects(
        OpenQueryObjectsIn(object_type="failure_mode", equipment_external_id="EQ-ONTO-1")
    )
    assert any(i.external_id == "FM-ONTO-1" for i in page.items)

    devices = await tools.query_objects(OpenQueryObjectsIn(object_type="device", q="飞织"))
    assert devices.total >= 1
    loom = await tools.get_object(
        OpenGetObjectIn(object_type="device", external_id="EQ-LOOM-01")
    )
    assert loom.links
    assert any(link.terminology_name for link in loom.links)

    trav = await tools.traverse(
        OpenTraverseIn(
            mode="object",
            kind="structured",
            object_id=equip.id,
            object_type="equipment",
            direction="out",
            relation_types=["has_failure_mode"],
            max_hops=1,
        )
    )
    assert {n.object_id for n in trav.neighbors} == {fm.id}

    with pytest.raises(NotFoundError):
        await tools.get_object(
            OpenGetObjectIn(object_type="equipment", external_id="EQ-MISSING")
        )


def test_mcp_ontology_tools_registered() -> None:
    from app.services.open_api.mcp import TOOLS, TOOL_SCOPES

    for name in (
        "describe_ontology",
        "get_object",
        "query_objects",
        "aggregate_objects",
        "traverse",
        "list_actions",
        "approve_action",
        "invoke_action",
    ):
        assert name in TOOLS
        assert name in TOOL_SCOPES
    assert TOOL_SCOPES["invoke_action"].value == "action"
