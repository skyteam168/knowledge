"""OS1 semantic model versions: draft → approve → publish; Agent sees published only."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.base import new_id
from app.ontology.attributes import DEVICE_STATUS_ENUM_MAP, validate_enum_raw
from app.schemas.semantic import (
    SchemaColumnIn,
    SchemaImportIn,
    SchemaTableIn,
    SemanticAttributeCreate,
    SemanticAttributeUpdate,
    SemanticBatchStatusIn,
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


ORG = "org-semantic"


def _ctx(org_id: str = ORG) -> RequestContext:
    uid = new_id()
    user = CurrentUser(
        id=uid,
        org_id=org_id,
        username="steward",
        display_name="Steward",
        principals=Principals(org_id, uid),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user, AuditContext(org_id=org_id, actor_id=uid, actor_name="Steward")
    )


@pytest.fixture
def studio(session: AsyncSession) -> OntologyStudioService:
    return OntologyStudioService(
        session, _ctx(), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


def _tools(session: AsyncSession, ctx: RequestContext) -> OpenOntologyTools:
    return OpenOntologyTools(
        session,
        ctx,
        AuthzCache(MemoryCache(), ttl_seconds=60),
        ApiCaller(
            client_id=new_id(),
            key_id=new_id(),
            org_id=ctx.user.org_id,
            name="agent",
            kb_ids=frozenset({new_id()}),
            scopes=frozenset({"entity"}),
            rate_limit_per_minute=60,
            daily_quota=0,
            user=ctx.user,
        ),
    )


async def test_publish_requires_approved_entity(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ver = await studio.create_version(SemanticVersionCreate(name="v1"))
    with pytest.raises(ValidationAppError):
        await studio.publish(ver.id)

    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(
            local_name="LoomLine",
            label="飞织产线",
            description="织造产线",
            object_type="line",
        ),
    )
    with pytest.raises(ValidationAppError):
        await studio.publish(ver.id)

    await studio.set_entity_status(ent.id, "approved")
    published = await studio.publish(ver.id)
    assert published.status == "published"
    assert published.is_active is True


async def test_draft_hidden_from_agent_describe(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ctx = _ctx()
    tools = _tools(session, ctx)
    ver = await studio.create_version(SemanticVersionCreate(name="draft-only"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(
            local_name="SecretDraft",
            label="草稿实体",
            object_type="equipment",
        ),
    )
    await studio.set_entity_status(ent.id, "approved")
    # not published yet
    summary = await tools.describe_ontology(scope="summary", version="published")
    assert summary.scope == "summary"
    assert summary.attribute_schemas == []
    assert all(e.get("local_name") != "SecretDraft" for e in summary.org_entities)

    published = await studio.publish(ver.id)
    all_view = await tools.describe_ontology(scope="all", version="published")
    assert all_view.version == "published"
    assert all_view.version_id == published.id
    assert any(e.get("local_name") == "SecretDraft" for e in all_view.org_entities)
    assert any(
        s.get("local_name") == "SecretDraft" or s.get("object_type") == "equipment"
        for s in all_view.attribute_schemas
        if s.get("source") == "org_published"
    )

    # draft version id must not be readable as published
    ver2 = await studio.create_version(SemanticVersionCreate(name="still-draft"))
    with pytest.raises(NotFoundError):
        await tools.describe_ontology(scope="summary", version=ver2.id)


async def test_scope_summary_omits_attributes(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ctx = _ctx()
    tools = _tools(session, ctx)
    summary = await tools.describe_ontology(scope="summary", version="platform")
    assert summary.classes
    assert summary.industrial_relation_properties
    assert summary.attribute_schemas == []

    attrs = await tools.describe_ontology(scope="attributes", version="platform")
    assert attrs.attribute_schemas
    assert attrs.classes == []


async def test_mapping_and_detail(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ver = await studio.create_version(SemanticVersionCreate(name="mapped"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(local_name="Device", label="设备", object_type="device"),
    )
    attr = await studio.add_attribute(
        ent.id,
        SemanticAttributeCreate(
            name="externalId", label="外部编号", description="MES 设备号"
        ),
    )
    mapping = await studio.add_mapping(
        attr.id,
        SemanticMappingCreate(table_name="equip_devices", column_name="external_id"),
    )
    await studio.set_entity_status(ent.id, "approved")
    await studio.set_attribute_status(attr.id, "approved")
    await studio.set_mapping_status(mapping.id, "approved")
    await studio.publish(ver.id)

    detail = await studio.get_version(ver.id)
    assert len(detail.entities) == 1
    assert len(detail.attributes) == 1
    assert detail.mappings[0].table_name == "equip_devices"

    tools = _tools(session, _ctx())
    described = await tools.describe_ontology(scope="all", version="published")
    org_schemas = [s for s in described.attribute_schemas if s.get("source") == "org_published"]
    assert org_schemas
    assert org_schemas[0]["attributes"][0]["represented_by"][0]["column"] == "external_id"


async def test_schema_import_idempotent(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    payload = SchemaImportIn(
        version_name="mes-import",
        source_id=None,
        tables=[
            SchemaTableIn(
                name="equip_devices",
                comment="设备主数据",
                columns=[
                    SchemaColumnIn(name="external_id", data_type="varchar", comment="外部编号"),
                    SchemaColumnIn(name="name", data_type="varchar"),
                    SchemaColumnIn(name="qty", data_type="numeric"),
                ],
            )
        ],
    )
    first = await studio.import_schema(payload)
    assert first.stats.entities_created == 1
    assert first.stats.attributes_created == 3
    assert first.stats.mappings_created == 3

    second = await studio.import_schema(
        SchemaImportIn(version_id=first.version.id, tables=payload.tables)
    )
    assert second.stats.entities_created == 0
    assert second.stats.entities_unchanged == 1
    assert second.stats.attributes_created == 0
    assert second.stats.attributes_unchanged == 3
    assert second.stats.mappings_created == 0
    assert second.stats.mappings_unchanged == 3

    detail = await studio.get_version(first.version.id)
    assert {a.name for a in detail.attributes} == {"externalId", "name", "qty"}
    qty = next(a for a in detail.attributes if a.name == "qty")
    assert qty.attr_kind == "number"


async def test_suggest_and_batch_approve(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    imported = await studio.import_schema(
        SchemaImportIn(
            version_name="suggest-demo",
            tables=[
                SchemaTableIn(
                    name="equip_devices",
                    columns=[
                        SchemaColumnIn(name="external_id", data_type="varchar"),
                        SchemaColumnIn(name="name", data_type="varchar"),
                    ],
                )
            ],
        )
    )
    suggested = await studio.suggest_labels(imported.version.id)
    assert suggested.entities_updated >= 1
    assert suggested.attributes_updated >= 1
    detail = await studio.get_version(imported.version.id)
    entity = detail.entities[0]
    assert entity.label == "设备"
    assert entity.object_type == "device"
    ext = next(a for a in detail.attributes if a.name == "externalId")
    assert ext.label == "外部编号"

    batch = await studio.batch_set_status(
        imported.version.id,
        SemanticBatchStatusIn(
            entity_ids=[entity.id],
            attribute_ids=[a.id for a in detail.attributes],
            mapping_ids=[m.id for m in detail.mappings],
            status="approved",
        ),
    )
    assert batch.entities_updated == 1
    assert batch.attributes_updated == 2
    published = await studio.publish(imported.version.id)
    assert published.is_active

    tools = _tools(session, _ctx())
    # Unapproved draft must not appear: create another draft with different entity
    draft = await studio.create_version(SemanticVersionCreate(name="hidden"))
    hidden = await studio.add_entity(
        draft.id,
        SemanticEntityCreate(local_name="HiddenThing", label="隐藏"),
    )
    await studio.set_entity_status(hidden.id, "approved")
    view = await tools.describe_ontology(scope="all", version="published")
    assert all(e.get("local_name") != "HiddenThing" for e in view.org_entities)
    assert any(e.get("local_name") == "EquipDevices" for e in view.org_entities)


async def test_attribute_unit_enum_map_and_labels(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ver = await studio.create_version(SemanticVersionCreate(name="enum-meta"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(local_name="Device", label="设备", object_type="device"),
    )
    enum_map = {
        raw: {"standard": entry.standard, "label": entry.label}
        for raw, entry in DEVICE_STATUS_ENUM_MAP.items()
    }
    attr = await studio.add_attribute(
        ent.id,
        SemanticAttributeCreate(
            name="status",
            label="状态",
            attr_kind="enum",
            unit=None,
            enum_map=enum_map,
            labels={"zh": "状态", "en": "Status", "vi": "Trạng thái"},
        ),
    )
    assert attr.attr_kind == "enum"
    assert attr.enum_map["0"]["standard"] == "RUNNING"
    assert attr.labels["en"] == "Status"

    updated = await studio.update_attribute(
        attr.id,
        SemanticAttributeUpdate(unit=None, labels={"zh": "设备状态", "en": "Device status"}),
    )
    assert updated.labels["zh"] == "设备状态"

    # Studio-stored enum_map rejects unknown raw the same way as platform map
    issues = validate_enum_raw("99", updated.enum_map or {}, path="status")
    assert any(i.code == "enum_unknown" for i in issues)

    await studio.set_entity_status(ent.id, "approved")
    await studio.set_attribute_status(attr.id, "approved")
    await studio.publish(ver.id)
    tools = _tools(session, _ctx())
    described = await tools.describe_ontology(scope="attributes", version="published")
    org = [s for s in described.attribute_schemas if s.get("source") == "org_published"]
    status_attr = next(
        a for s in org for a in s["attributes"] if a["name"] == "status"
    )
    assert status_attr["enum_map"]["0"]["standard"] == "RUNNING"
    assert status_attr["labels"]["en"] == "Device status"
