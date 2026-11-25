"""O1.3 industrial structured_records: parent denorm + equipment-domain allowlist."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ValidationAppError
from app.models.base import new_id
from app.ontology.catalog import derive_parent_ref
from app.schemas.structured import StructuredRecordCreate, StructuredSourceCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.structured.service import StructuredService


def _ctx(org_id: str) -> RequestContext:
    user_id = new_id()
    user = CurrentUser(
        id=user_id,
        org_id=org_id,
        username="tester",
        display_name="Tester",
        principals=Principals(org_id, user_id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user,
        AuditContext(org_id=org_id, actor_id=user.id, actor_name=user.display_name),
    )


@pytest.fixture
def service(session: AsyncSession) -> StructuredService:
    return StructuredService(
        session, _ctx("org-industrial"), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


def test_derive_parent_ref_prefers_line_for_equipment() -> None:
    assert derive_parent_ref(
        "equipment",
        {
            "site_external_id": "SITE-1",
            "line_external_id": "LINE-1",
            "model": "X",
        },
    ) == ("line", "LINE-1")


async def test_industrial_hierarchy_under_equipment_domain(
    session: AsyncSession, service: StructuredService
) -> None:
    domains = await service.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    process = next(d for d in domains if d.code == "process")
    source = await service.create_source(
        StructuredSourceCreate(name="IND-demo", type="mes")
    )

    with pytest.raises(ValidationAppError):
        await service.create_record(
            StructuredRecordCreate(
                domain_id=equipment.id,
                source_id=source.id,
                object_type="recipe",
                external_id="RC-1",
                title="不允许的自定义类型",
            )
        )

    site = await service.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="site",
            external_id="SITE-A",
            title="A厂",
            attrs={"code": "A"},
        )
    )
    assert site.parent_external_id is None

    line = await service.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="line",
            external_id="LINE-1",
            title="织造一线",
            attrs={"code": "L1", "area_external_id": "AREA-1", "site_external_id": "SITE-A"},
        )
    )
    # area preferred over site when both present? candidates say area first
    assert line.parent_object_type == "area"
    assert line.parent_external_id == "AREA-1"

    equip = await service.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="equipment",
            external_id="EQ-H-01",
            title="层级设备1",
            attrs={
                "line_external_id": "LINE-1",
                "model": "Loom-X",
                "rated_power": {"value": 7.5, "unit": "kW"},
            },
        )
    )
    assert equip.parent_object_type == "line"
    assert equip.parent_external_id == "LINE-1"

    fm = await service.create_record(
        StructuredRecordCreate(
            domain_id=process.id,
            source_id=source.id,
            object_type="failure_mode",
            external_id="FM-YARN",
            title="断纱",
            attrs={"equipment_external_id": "EQ-H-01", "code": "FM-YARN", "severity": 8},
        )
    )
    assert fm.parent_object_type == "equipment"
    assert fm.parent_external_id == "EQ-H-01"

    children = await service.list_children(
        parent_object_type="equipment",
        parent_external_id="EQ-H-01",
    )
    assert {c.external_id for c in children} == {"FM-YARN"}
