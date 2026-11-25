"""O1.2 typed attribute schemas: validate + JSON Schema + create_record gate."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ValidationAppError
from app.models.base import new_id
from app.ontology.attributes import (
    DEVICE_STATUS_ENUM_MAP,
    attrs_to_json_schema,
    list_schemas,
    resolve_enum_raw,
    schema_for,
    validate_attrs,
    validate_enum_raw,
)
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
    return StructuredService(session, _ctx("org-attrs"), AuthzCache(MemoryCache(), ttl_seconds=60))


def test_industrial_schemas_cover_required_types() -> None:
    types = {s.object_type for s in list_schemas()}
    assert {
        "site",
        "area",
        "line",
        "equipment",
        "component",
        "failure_mode",
        "event",
        "process_parameter",
    } <= types


def test_quantity_requires_unit() -> None:
    """Alias name from Wave A Task3 plan; quantity must carry unit."""
    issues = validate_attrs("equipment", {"rated_power": {"value": 15}})
    assert any(i.code == "unit_required" for i in issues)


def test_quantity_requires_unit_and_rejects_bare_number() -> None:
    issues = validate_attrs(
        "equipment",
        {"rated_power": 15},
    )
    assert any(i.code == "type" for i in issues)

    issues = validate_attrs(
        "equipment",
        {"rated_power": {"value": 15}},
    )
    assert any(i.code == "unit_required" for i in issues)

    assert (
        validate_attrs(
            "equipment",
            {"rated_power": {"value": 15, "unit": "kW"}},
        )
        == []
    )


def test_enum_map_rejects_unknown_raw_status() -> None:
    ok = validate_enum_raw("0", DEVICE_STATUS_ENUM_MAP, path="status")
    assert ok == []
    resolved = resolve_enum_raw("0", DEVICE_STATUS_ENUM_MAP)
    assert resolved is not None
    assert resolved.standard == "RUNNING"
    assert resolved.label == "运行"

    bad = validate_enum_raw("9", DEVICE_STATUS_ENUM_MAP, path="status")
    assert any(i.code == "enum_unknown" for i in bad)

    # Already-normalized standard values are accepted
    assert validate_enum_raw("STOPPED", DEVICE_STATUS_ENUM_MAP) == []


def test_range_and_unknown_attr_rejected() -> None:
    issues = validate_attrs(
        "failure_mode",
        {
            "equipment_external_id": "EQ-1",
            "code": "FM-YARN",
            "severity": 99,
            "extra": "nope",
        },
    )
    codes = {i.code for i in issues}
    assert "maximum" in codes
    assert "unknown_attr" in codes


def test_process_parameter_limit_unit_must_match_setpoint() -> None:
    issues = validate_attrs(
        "process_parameter",
        {
            "name": "temp",
            "setpoint": {"value": 180, "unit": "C"},
            "upper_limit": {"value": 200, "unit": "F"},
        },
    )
    assert any(i.code == "unit_mismatch" for i in issues)


def test_custom_object_type_has_no_schema() -> None:
    assert schema_for("recipe") is None
    assert validate_attrs("recipe", {"anything": 1}) == []


def test_json_schema_export_additional_properties_false() -> None:
    schema = schema_for("component")
    assert schema is not None
    js = attrs_to_json_schema(schema)
    assert js["additionalProperties"] is False
    assert "equipment_external_id" in js["required"]
    assert js["properties"]["equipment_external_id"]["type"] == "string"


async def test_create_record_rejects_invalid_industrial_attrs(
    session: AsyncSession, service: StructuredService
) -> None:
    domains = await service.list_domains()
    process = next(d for d in domains if d.code == "process")
    source = await service.create_source(StructuredSourceCreate(name="ATTR-demo", type="mes"))

    with pytest.raises(ValidationAppError) as exc:
        await service.create_record(
            StructuredRecordCreate(
                domain_id=process.id,
                source_id=source.id,
                object_type="failure_mode",
                external_id="FM-1",
                title="断纱",
                attrs={"code": "FM-YARN"},  # missing equipment_external_id
            )
        )
    assert exc.value.detail is not None
    assert any(i["code"] == "required" for i in exc.value.detail["issues"])

    ok = await service.create_record(
        StructuredRecordCreate(
            domain_id=process.id,
            source_id=source.id,
            object_type="failure_mode",
            external_id="FM-1",
            title="断纱",
            attrs={
                "equipment_external_id": "EQ-LOOM-01",
                "code": "FM-YARN",
                "severity": 7,
            },
        )
    )
    assert ok.attrs["code"] == "FM-YARN"


async def test_list_attribute_schemas_api_shape(service: StructuredService) -> None:
    rows = service.list_attribute_schemas()
    assert len(rows) >= 8
    failure = service.get_attribute_schema("failure_mode")
    assert failure["object_type"] == "failure_mode"
    assert failure["json_schema"]["type"] == "object"
