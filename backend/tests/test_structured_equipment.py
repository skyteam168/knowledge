"""Equipment structured mirror: seed, resolve, link constraints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import StructuredObjectType
from app.models.base import new_id
from app.schemas.structured import StructuredLinkCreate, StructuredSourceCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.structured.seed_equipment import SEED_SOURCE_NAME, seed_equipment
from app.services.structured.service import StructuredService
from app.core.cache import MemoryCache


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
    return StructuredService(session, _ctx("org-struct"), AuthzCache(MemoryCache(), ttl_seconds=60))


async def test_seed_equipment_idempotent(session: AsyncSession) -> None:
    org_id = "org-struct"
    first = await seed_equipment(session, org_id)
    await session.commit()
    assert first["sources"] == 1
    assert first["devices"] >= 2
    assert first["work_orders"] >= 2
    assert first["spare_parts"] >= 2
    assert first["links"] >= 2

    second = await seed_equipment(session, org_id)
    await session.commit()
    assert second == {
        "sources": 0,
        "devices": 0,
        "work_orders": 0,
        "spare_parts": 0,
        "links": 0,
        "kos": 0,
        "ko_relations": 0,
        "ko_links": 0,
    }


async def test_resolve_external_id_returns_terminology_link(
    session: AsyncSession, service: StructuredService
) -> None:
    await seed_equipment(session, service.org_id)
    await session.commit()

    resolved = await service.resolve(StructuredObjectType.DEVICE.value, "EQ-LOOM-01")
    assert resolved.label == "1号飞织机"
    assert resolved.external_id == "EQ-LOOM-01"
    assert any(link.terminology_name == "织机" for link in resolved.links)

    wo = await service.resolve(StructuredObjectType.WORK_ORDER.value, "WO-2026-001")
    assert "断纱" in wo.label
    assert wo.links


async def test_create_source_and_link_validation(
    session: AsyncSession, service: StructuredService
) -> None:
    await seed_equipment(session, service.org_id)
    await session.commit()

    sources = await service.list_sources()
    assert any(s.name == SEED_SOURCE_NAME for s in sources)

    with pytest.raises(ConflictError):
        await service.create_source(
            StructuredSourceCreate(name=SEED_SOURCE_NAME, type="mes")
        )

    devices = await service.list_devices(page=1, size=10)
    device = devices.items[0]
    term_id = (await service.list_links("device", device.id))[0].terminology_entity_id
    assert term_id

    with pytest.raises(ConflictError):
        await service.create_link(
            StructuredLinkCreate(
                object_type="device",
                object_id=device.id,
                terminology_entity_id=term_id,
            )
        )

    with pytest.raises(NotFoundError):
        await service.resolve("device", "EQ-MISSING")

    with pytest.raises(NotFoundError):
        await service.resolve("recipe", "RC-MISSING")


def test_link_create_requires_target() -> None:
    with pytest.raises(ValidationError):
        StructuredLinkCreate(object_type="device", object_id="x" * 32)


async def test_generic_domain_record_and_resolve(
    session: AsyncSession, service: StructuredService
) -> None:
    from app.schemas.structured import StructuredDomainCreate, StructuredRecordCreate

    domains = await service.list_domains()
    codes = {d.code for d in domains}
    assert {"equipment", "process", "material", "quality"} <= codes

    process = next(d for d in domains if d.code == "process")
    source = await service.create_source(
        StructuredSourceCreate(name="PLM-demo", type="plm")
    )
    record = await service.create_record(
        StructuredRecordCreate(
            domain_id=process.id,
            source_id=source.id,
            object_type="recipe",
            external_id="RC-1001",
            title="飞织上机配方A",
        )
    )
    assert record.external_id == "RC-1001"

    resolved = await service.resolve("recipe", "RC-1001")
    assert resolved.label == "飞织上机配方A"
    assert resolved.object_id == record.id

    custom = await service.create_domain(
        StructuredDomainCreate(code="warehouse", name="仓储", description="库位")
    )
    assert custom.kind == "generic"

    with pytest.raises(ConflictError):
        await service.create_domain(StructuredDomainCreate(code="process", name="工艺2"))

    with pytest.raises(ValidationAppError):
        await service.create_domain(StructuredDomainCreate(code="equipment", name="设备2"))
