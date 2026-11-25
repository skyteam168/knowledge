"""O2.1–O2.3 directed object_relations CRUD + constraints + admin routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ConflictError, ValidationAppError
from app.models.base import new_id
from app.schemas.structured import (
    ObjectRelationCreate,
    StructuredRecordCreate,
    StructuredSourceCreate,
)
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.structured.object_relations import ObjectRelationService
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
def structured(session: AsyncSession) -> StructuredService:
    return StructuredService(
        session, _ctx("org-rel"), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


@pytest.fixture
def relations(session: AsyncSession) -> ObjectRelationService:
    return ObjectRelationService(
        session, _ctx("org-rel"), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


async def test_create_list_delete_and_guards(
    session: AsyncSession,
    structured: StructuredService,
    relations: ObjectRelationService,
) -> None:
    domains = await structured.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    source = await structured.create_source(
        StructuredSourceCreate(name="REL-demo", type="mes")
    )
    equip = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="equipment",
            external_id="EQ-R-1",
            title="设备R1",
            attrs={"model": "M1"},
        )
    )
    fm = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="failure_mode",
            external_id="FM-R-1",
            title="断纱",
            attrs={
                "equipment_external_id": "EQ-R-1",
                "code": "FM-R-1",
                "severity": 5,
            },
        )
    )

    with pytest.raises(ValidationAppError):
        await relations.create(
            ObjectRelationCreate(
                relation_type="has_failure_mode",
                from_kind="structured",
                from_id=equip.id,
                from_object_type="equipment",
                to_kind="structured",
                to_id=equip.id,
                to_object_type="equipment",
            )
        )

    edge = await relations.create(
        ObjectRelationCreate(
            relation_type="has_failure_mode",
            from_kind="structured",
            from_id=equip.id,
            from_object_type="equipment",
            to_kind="structured",
            to_id=fm.id,
            to_object_type="failure_mode",
        )
    )
    assert edge.relation_local_name == "hasFailureMode"

    with pytest.raises(ConflictError):
        await relations.create(
            ObjectRelationCreate(
                relation_type="has_failure_mode",
                from_kind="structured",
                from_id=equip.id,
                from_object_type="equipment",
                to_kind="structured",
                to_id=fm.id,
                to_object_type="failure_mode",
            )
        )

    listed = await relations.list_relations(
        from_kind="structured", from_id=equip.id, relation_type="has_failure_mode"
    )
    assert len(listed) == 1
    assert listed[0].to_id == fm.id

    await relations.delete(edge.id)
    assert await relations.list_relations(from_id=equip.id) == []


async def test_hard_domain_range_and_soft_warnings(
    session: AsyncSession,
    structured: StructuredService,
    relations: ObjectRelationService,
) -> None:
    domains = await structured.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    source = await structured.create_source(
        StructuredSourceCreate(name="REL-constraint", type="mes")
    )
    equip = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="equipment",
            external_id="EQ-C-1",
            title="设备C1",
            attrs={"model": "M1"},
        )
    )
    fm = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="failure_mode",
            external_id="FM-C-1",
            title="断纱C",
            attrs={
                "equipment_external_id": "EQ-C-1",
                "code": "FM-C-1",
                "severity": 3,
            },
        )
    )
    site = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="site",
            external_id="SITE-C",
            title="C厂",
            attrs={"code": "C"},
        )
    )

    # hard: wrong range for has_failure_mode
    with pytest.raises(ValidationAppError) as exc:
        await relations.create(
            ObjectRelationCreate(
                relation_type="has_failure_mode",
                from_kind="structured",
                from_id=equip.id,
                from_object_type="equipment",
                to_kind="structured",
                to_id=site.id,
                to_object_type="site",
            )
        )
    assert "domain/range" in str(exc.value).lower() or "violations" in str(
        getattr(exc.value, "detail", {})
    )

    # hard: wrong domain (failure_mode → equipment)
    with pytest.raises(ValidationAppError):
        await relations.create(
            ObjectRelationCreate(
                relation_type="has_failure_mode",
                from_kind="structured",
                from_id=fm.id,
                from_object_type="failure_mode",
                to_kind="structured",
                to_id=equip.id,
                to_object_type="equipment",
            )
        )

    # legal core edge
    ok = await relations.create(
        ObjectRelationCreate(
            relation_type="has_failure_mode",
            from_kind="structured",
            from_id=equip.id,
            from_object_type="equipment",
            to_kind="structured",
            to_id=fm.id,
            to_object_type="failure_mode",
        )
    )
    assert ok.warnings == []

    # soft: located_in with atypical types → allowed + warnings
    soft = await relations.create(
        ObjectRelationCreate(
            relation_type="located_in",
            from_kind="structured",
            from_id=fm.id,
            from_object_type="failure_mode",
            to_kind="structured",
            to_id=equip.id,
            to_object_type="equipment",
        )
    )
    assert soft.warnings
    assert any("软约束" in w for w in soft.warnings)


async def test_cardinality_many_to_one_rejects_second_outgoing(
    session: AsyncSession,
    structured: StructuredService,
    relations: ObjectRelationService,
) -> None:
    domains = await structured.list_domains()
    equipment = next(d for d in domains if d.code == "equipment")
    source = await structured.create_source(
        StructuredSourceCreate(name="REL-card", type="mes")
    )
    equip = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="equipment",
            external_id="EQ-CARD-1",
            title="设备Card",
            attrs={"model": "M"},
        )
    )
    area_a = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="area",
            external_id="AREA-A",
            title="A区",
            attrs={"code": "A", "site_external_id": "SITE-CARD"},
        )
    )
    area_b = await structured.create_record(
        StructuredRecordCreate(
            domain_id=equipment.id,
            source_id=source.id,
            object_type="area",
            external_id="AREA-B",
            title="B区",
            attrs={"code": "B", "site_external_id": "SITE-CARD"},
        )
    )
    first = await relations.create(
        ObjectRelationCreate(
            relation_type="located_in",
            from_kind="structured",
            from_id=equip.id,
            from_object_type="equipment",
            to_kind="structured",
            to_id=area_a.id,
            to_object_type="area",
            attrs={"role": "primary"},
        )
    )
    assert first.cardinality == "many_to_one"
    assert first.attrs["role"] == "primary"

    with pytest.raises(ValidationAppError) as exc:
        await relations.create(
            ObjectRelationCreate(
                relation_type="located_in",
                from_kind="structured",
                from_id=equip.id,
                from_object_type="equipment",
                to_kind="structured",
                to_id=area_b.id,
                to_object_type="area",
            )
        )
    assert "cardinality" in str(exc.value.message).lower() or (
        isinstance(exc.value.detail, dict) and "cardinality" in exc.value.detail
    )


def test_admin_object_relation_routes_registered(app: FastAPI) -> None:
    openapi_paths = set(app.openapi().get("paths", {}))
    assert "/api/v1/admin/structured/object-relations" in openapi_paths
    assert "/api/v1/admin/structured/object-relations/{relation_id}" in openapi_paths
