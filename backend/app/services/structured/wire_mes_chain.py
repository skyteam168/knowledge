"""Wire MES device_info → terminology links → published Ontology Studio for Agent debug."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models import (
    EquipDevice,
    StructuredEntityLink,
    StructuredSource,
    TerminologyAlias,
    TerminologyEntity,
    TerminologyEntityType,
    TerminologyLang,
    TerminologyStatus,
)
from app.models.semantic import SemanticItemStatus
from app.repositories.structured_repo import StructuredRepository
from app.schemas.semantic import SchemaColumnIn, SchemaImportIn, SchemaTableIn
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.service import OntologyStudioService
from app.services.terminology.expander import normalize_alias

MES_SOURCE_NAME = "MES device_info"
TERM_CANONICAL = "电脑编织横机"
TERM_ALIASES = ("横机", "STOLL横机", "CMS编织机", "电脑横机")
LINK_SAMPLE_LIMIT = 30


def _admin_ctx(org_id: str) -> RequestContext:
    user_id = "cli-mes-wire"
    user = CurrentUser(
        id=user_id,
        org_id=org_id,
        username="cli",
        display_name="CLI MES wire",
        principals=Principals(org_id, user_id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user,
        AuditContext(org_id=org_id, actor_id=user.id, actor_name=user.display_name),
    )


async def _ensure_term(session: AsyncSession, org_id: str) -> TerminologyEntity:
    existing = await session.scalar(
        select(TerminologyEntity).where(
            TerminologyEntity.org_id == org_id,
            TerminologyEntity.canonical_name == TERM_CANONICAL,
        )
    )
    if existing is not None:
        entity = existing
    else:
        entity = TerminologyEntity(
            org_id=org_id,
            canonical_name=TERM_CANONICAL,
            entity_type=TerminologyEntityType.DEVICE.value,
            description="MES device_info 主设备类型（电脑编织横机）",
            status=TerminologyStatus.ACTIVE.value,
        )
        session.add(entity)
        await session.flush()

    existing_aliases = {
        a.alias_normalized
        for a in await session.scalars(
            select(TerminologyAlias).where(
                TerminologyAlias.org_id == org_id,
                TerminologyAlias.entity_id == entity.id,
            )
        )
    }
    for alias in TERM_ALIASES:
        norm = normalize_alias(alias)
        if norm in existing_aliases:
            continue
        session.add(
            TerminologyAlias(
                org_id=org_id,
                entity_id=entity.id,
                alias=alias,
                alias_normalized=norm,
                lang=TerminologyLang.ANY.value,
            )
        )
        existing_aliases.add(norm)
    await session.flush()
    return entity


async def _link_devices(
    session: AsyncSession,
    org_id: str,
    *,
    source_id: str,
    term_id: str,
) -> dict[str, Any]:
    repo = StructuredRepository(session)
    rows = list(
        await session.scalars(
            select(EquipDevice)
            .where(
                EquipDevice.org_id == org_id,
                EquipDevice.source_id == source_id,
                EquipDevice.name == TERM_CANONICAL,
            )
            .order_by(EquipDevice.external_id)
            .limit(LINK_SAMPLE_LIMIT)
        )
    )
    # Always include external_id=1 if present.
    first = await session.scalar(
        select(EquipDevice).where(
            EquipDevice.org_id == org_id,
            EquipDevice.source_id == source_id,
            EquipDevice.external_id == "1",
        )
    )
    by_id = {r.id: r for r in rows}
    if first is not None:
        by_id[first.id] = first
    linked = 0
    skipped = 0
    sample_ids: list[dict[str, str]] = []
    for device in by_id.values():
        existing = await repo.find_link(
            org_id,
            object_type="device",
            object_id=device.id,
            terminology_entity_id=term_id,
            ko_id=None,
        )
        if existing is not None:
            skipped += 1
        else:
            repo.add_link(
                StructuredEntityLink(
                    org_id=org_id,
                    object_type="device",
                    object_id=device.id,
                    terminology_entity_id=term_id,
                    ko_id=None,
                    created_by="cli-mes-wire",
                )
            )
            linked += 1
        if len(sample_ids) < 5:
            sample_ids.append(
                {
                    "object_id": device.id,
                    "external_id": device.external_id,
                    "device_number": str(
                        (device.meta or {}).get("col_device_number") or ""
                    ),
                }
            )
    await session.flush()
    return {
        "candidates": len(by_id),
        "linked": linked,
        "already_linked": skipped,
        "samples": sample_ids,
    }


async def _publish_semantic(
    session: AsyncSession, org_id: str, *, source_id: str
) -> dict[str, Any]:
    ctx = _admin_ctx(org_id)
    studio = OntologyStudioService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60)
    )
    imported = await studio.import_schema(
        SchemaImportIn(
            version_name=f"mes-device-info-{source_id[:8]}",
            source_id=source_id,
            auto_approve=True,
            tables=[
                SchemaTableIn(
                    name="equip_devices",
                    comment="设备",
                    columns=[
                        SchemaColumnIn(name="external_id", data_type="string", comment="外部编号"),
                        SchemaColumnIn(name="name", data_type="string", comment="名称"),
                        SchemaColumnIn(name="status", data_type="string", comment="状态"),
                        SchemaColumnIn(name="location", data_type="string", comment="位置"),
                        SchemaColumnIn(
                            name="meta.col_device_number",
                            data_type="string",
                            comment="资产编号",
                        ),
                        SchemaColumnIn(
                            name="meta.col_brand",
                            data_type="string",
                            comment="品牌",
                        ),
                        SchemaColumnIn(
                            name="meta.col_device_model",
                            data_type="string",
                            comment="型号",
                        ),
                        SchemaColumnIn(
                            name="meta.col_department",
                            data_type="string",
                            comment="部门",
                        ),
                    ],
                )
            ],
        )
    )
    version_id = imported.version.id
    # Bind entity to runtime object_type=device for Agent matching.
    from app.models.semantic import SemanticEntity

    entity = await session.scalar(
        select(SemanticEntity).where(
            SemanticEntity.org_id == org_id,
            SemanticEntity.version_id == version_id,
        )
    )
    if entity is not None:
        entity.object_type = "device"
        entity.label = "设备"
        entity.status = SemanticItemStatus.APPROVED.value
        await session.flush()

    published = await studio.publish(version_id)
    detail = await studio.get_version(published.id)
    return {
        "version_id": published.id,
        "version_name": published.name,
        "is_active": published.is_active,
        "entities": [
            {"local_name": e.local_name, "label": e.label, "object_type": e.object_type, "status": e.status}
            for e in detail.entities
        ],
        "attributes": [
            {"name": a.name, "label": a.label, "status": a.status}
            for a in detail.attributes
        ],
        "mappings": len(detail.mappings),
    }


async def wire_mes_debug_chain(
    session: AsyncSession,
    org_id: str,
    *,
    source_name: str = MES_SOURCE_NAME,
) -> dict[str, Any]:
    """Idempotent: terminology + sample links + published EquipDevice semantic model."""
    source = await session.scalar(
        select(StructuredSource).where(
            StructuredSource.org_id == org_id,
            StructuredSource.name == source_name,
        )
    )
    if source is None:
        raise ValueError(f"structured source not found: {source_name}")

    term = await _ensure_term(session, org_id)
    link_stats = await _link_devices(
        session, org_id, source_id=source.id, term_id=term.id
    )
    semantic = await _publish_semantic(session, org_id, source_id=source.id)
    from sqlalchemy import func

    device_count = int(
        await session.scalar(
            select(func.count())
            .select_from(EquipDevice)
            .where(EquipDevice.org_id == org_id, EquipDevice.source_id == source.id)
        )
        or 0
    )
    return {
        "org_id": org_id,
        "source_id": source.id,
        "source_name": source.name,
        "device_count": device_count,
        "terminology": {
            "id": term.id,
            "canonical_name": term.canonical_name,
            "aliases": list(TERM_ALIASES),
        },
        "links": link_stats,
        "semantic": semantic,
        "agent_fixtures": {
            "object_type": "device",
            "external_id": "1",
            "source_id": source.id,
            "sample_object_ids": [s["object_id"] for s in link_stats["samples"]],
        },
    }
