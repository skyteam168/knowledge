"""Idempotent equipment-maintenance sample mirror for local / demo orgs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EquipDevice,
    EquipSparePart,
    EquipWorkOrder,
    KnowledgeBase,
    KnowledgeObject,
    KoEntry,
    KoOrigin,
    KoRelation,
    KoRelationType,
    KoStatus,
    KoType,
    KoVersion,
    KoVersionStatus,
    StructuredEntityLink,
    StructuredObjectType,
    StructuredSource,
    StructuredSourceType,
    TerminologyAlias,
    TerminologyEntity,
    TerminologyEntityType,
    TerminologyLang,
    TerminologyStatus,
)
from app.models.base import new_id
from app.repositories.structured_repo import StructuredRepository
from app.services.terminology.expander import normalize_alias

SEED_SOURCE_NAME = "设备维保样例"
SEED_KO_LOOM = "【种子】织机维保要点"
SEED_KO_YARN = "【种子】断纱检修指引"


async def _ensure_term(
    session: AsyncSession, org_id: str, name: str, *, aliases: tuple[str, ...]
) -> TerminologyEntity:
    from sqlalchemy import select

    existing = await session.scalar(
        select(TerminologyEntity).where(
            TerminologyEntity.org_id == org_id,
            TerminologyEntity.canonical_name == name,
        )
    )
    if existing is not None:
        return existing
    entity = TerminologyEntity(
        org_id=org_id,
        canonical_name=name,
        entity_type=TerminologyEntityType.DEVICE.value,
        description=f"设备维保种子：{name}",
        status=TerminologyStatus.ACTIVE.value,
    )
    session.add(entity)
    await session.flush()
    for alias in aliases:
        session.add(
            TerminologyAlias(
                org_id=org_id,
                entity_id=entity.id,
                alias=alias,
                alias_normalized=normalize_alias(alias),
                lang=TerminologyLang.ANY.value,
            )
        )
    await session.flush()
    return entity


async def _ensure_published_ko(
    session: AsyncSession,
    org_id: str,
    kb_id: str,
    *,
    title: str,
    question: str,
    answer: str,
    ko_type: str = KoType.DEVICE.value,
) -> tuple[KnowledgeObject, bool]:
    existing = await session.scalar(
        select(KnowledgeObject).where(
            KnowledgeObject.org_id == org_id,
            KnowledgeObject.title == title,
        )
    )
    if existing is not None:
        return existing, False
    ko = KnowledgeObject(
        id=new_id(),
        org_id=org_id,
        kb_id=kb_id,
        ko_type=ko_type,
        title=title,
        question=question,
        variants=[],
        answer=answer,
        sources=[],
        status=KoStatus.PUBLISHED.value,
        version=1,
        published_version=1,
        acl_inherit=True,
        gap_ids=[],
        ai_draft={},
        conflicts=[],
        origin=KoOrigin.MANUAL.value,
    )
    session.add(ko)
    await session.flush()
    session.add(
        KoVersion(
            id=new_id(),
            org_id=org_id,
            ko_id=ko.id,
            version=1,
            ko_type=ko.ko_type,
            title=ko.title,
            question=ko.question,
            variants=[],
            answer=ko.answer,
            sources=[],
            status=KoVersionStatus.PUBLISHED.value,
        )
    )
    session.add(
        KoEntry(
            id=new_id(),
            org_id=org_id,
            ko_id=ko.id,
            ko_version=1,
            seq=0,
            question=ko.question,
        )
    )
    await session.flush()
    return ko, True


async def _ensure_ko_relation(
    session: AsyncSession,
    org_id: str,
    from_ko_id: str,
    to_ko_id: str,
    relation_type: str = KoRelationType.RELATED_TO.value,
) -> bool:
    existing = await session.scalar(
        select(KoRelation).where(
            KoRelation.org_id == org_id,
            KoRelation.from_ko_id == from_ko_id,
            KoRelation.to_ko_id == to_ko_id,
            KoRelation.relation_type == relation_type,
        )
    )
    if existing is not None:
        return False
    session.add(
        KoRelation(
            id=new_id(),
            org_id=org_id,
            from_ko_id=from_ko_id,
            to_ko_id=to_ko_id,
            relation_type=relation_type,
        )
    )
    await session.flush()
    return True


async def _attach_ko(
    repo: StructuredRepository,
    org_id: str,
    *,
    object_type: str,
    object_id: str,
    terminology_entity_id: str | None,
    ko_id: str,
) -> bool:
    """Ensure a link row carries ko_id (update empty link or insert)."""
    links = await repo.list_links_for(org_id, object_type, object_id)
    for link in links:
        if link.ko_id == ko_id:
            return False
        if link.ko_id is None and link.terminology_entity_id == terminology_entity_id:
            link.ko_id = ko_id
            return True
    if await repo.find_link(
        org_id,
        object_type=object_type,
        object_id=object_id,
        terminology_entity_id=terminology_entity_id,
        ko_id=ko_id,
    ):
        return False
    repo.add_link(
        StructuredEntityLink(
            org_id=org_id,
            object_type=object_type,
            object_id=object_id,
            terminology_entity_id=terminology_entity_id,
            ko_id=ko_id,
        )
    )
    return True


async def seed_equipment(session: AsyncSession, org_id: str) -> dict[str, int]:
    """Upsert sample MES mirror rows + terminology / KO links. Returns counts."""
    repo = StructuredRepository(session)
    created = {
        "sources": 0,
        "devices": 0,
        "work_orders": 0,
        "spare_parts": 0,
        "links": 0,
        "kos": 0,
        "ko_relations": 0,
        "ko_links": 0,
    }

    source = await repo.get_source_by_name(org_id, SEED_SOURCE_NAME)
    if source is None:
        source = StructuredSource(
            org_id=org_id,
            name=SEED_SOURCE_NAME,
            type=StructuredSourceType.MES.value,
            enabled=True,
            meta={"seed": True, "domain": "equipment"},
        )
        repo.add_source(source)
        await session.flush()
        created["sources"] = 1

    loom = await _ensure_term(session, org_id, "织机", aliases=("loom", "飞织机", "knitting machine"))
    dryer = await _ensure_term(
        session, org_id, "定型机", aliases=("heat setter", "定型设备", "stenter")
    )

    devices_spec = (
        ("EQ-LOOM-01", "1号飞织机", "active", "织造车间A", loom),
        ("EQ-HEAT-02", "2号定型机", "active", "整理车间", dryer),
    )
    device_rows: dict[str, EquipDevice] = {}
    for external_id, name, status, location, term in devices_spec:
        row = await repo.get_device_by_external(org_id, external_id, source_id=source.id)
        if row is None:
            row = EquipDevice(
                org_id=org_id,
                source_id=source.id,
                external_id=external_id,
                name=name,
                status=status,
                location=location,
                meta={"seed": True},
            )
            repo.add_device(row)
            await session.flush()
            created["devices"] += 1
        device_rows[external_id] = row
        if not await repo.list_links_for(
            org_id, StructuredObjectType.DEVICE.value, row.id
        ):
            repo.add_link(
                StructuredEntityLink(
                    org_id=org_id,
                    object_type=StructuredObjectType.DEVICE.value,
                    object_id=row.id,
                    terminology_entity_id=term.id,
                    ko_id=None,
                )
            )
            await session.flush()
            created["links"] += 1

    wo_spec = (
        ("WO-2026-001", "EQ-LOOM-01", "织机断纱检修", "open"),
        ("WO-2026-002", "EQ-HEAT-02", "定型机温控校准", "closed"),
    )
    for external_id, device_ext, title, status in wo_spec:
        row = await repo.get_work_order_by_external(org_id, external_id, source_id=source.id)
        if row is None:
            row = EquipWorkOrder(
                org_id=org_id,
                source_id=source.id,
                external_id=external_id,
                device_external_id=device_ext,
                title=title,
                status=status,
                opened_at=datetime(2026, 11, 1, tzinfo=UTC),
                meta={"seed": True},
            )
            repo.add_work_order(row)
            await session.flush()
            created["work_orders"] += 1
        device = device_rows.get(device_ext)
        if device is not None and not await repo.list_links_for(
            org_id, StructuredObjectType.WORK_ORDER.value, row.id
        ):
            # Link WO to the same terminology as its device.
            device_links = await repo.list_links_for(
                org_id, StructuredObjectType.DEVICE.value, device.id
            )
            term_id = device_links[0].terminology_entity_id if device_links else None
            if term_id:
                repo.add_link(
                    StructuredEntityLink(
                        org_id=org_id,
                        object_type=StructuredObjectType.WORK_ORDER.value,
                        object_id=row.id,
                        terminology_entity_id=term_id,
                        ko_id=None,
                    )
                )
                await session.flush()
                created["links"] += 1

    parts_spec = (
        ("SP-NEEDLE-08", "飞织机织针组", "NDL-08", 120.0, loom),
        ("SP-BELT-12", "定型机传动带", "BLT-12", 8.0, dryer),
    )
    for external_id, name, sku, qty, term in parts_spec:
        row = await repo.get_spare_part_by_external(org_id, external_id, source_id=source.id)
        if row is None:
            row = EquipSparePart(
                org_id=org_id,
                source_id=source.id,
                external_id=external_id,
                name=name,
                sku=sku,
                qty_on_hand=qty,
                meta={"seed": True},
            )
            repo.add_spare_part(row)
            await session.flush()
            created["spare_parts"] += 1
        if not await repo.list_links_for(
            org_id, StructuredObjectType.SPARE_PART.value, row.id
        ):
            repo.add_link(
                StructuredEntityLink(
                    org_id=org_id,
                    object_type=StructuredObjectType.SPARE_PART.value,
                    object_id=row.id,
                    terminology_entity_id=term.id,
                    ko_id=None,
                )
            )
            await session.flush()
            created["links"] += 1

    # ---- concept density: published seed KOs + relations + device ko_id --------
    # Prefer org-wide KBs so Open API / ACL demos can read without special ACL rows.
    kb_id = await session.scalar(
        select(KnowledgeBase.id)
        .where(KnowledgeBase.org_id == org_id, KnowledgeBase.visibility == "org")
        .order_by(KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc())
        .limit(1)
    )
    if kb_id is None:
        kb_id = await session.scalar(
            select(KnowledgeBase.id)
            .where(KnowledgeBase.org_id == org_id)
            .order_by(KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc())
            .limit(1)
        )
    if kb_id:
        loom_ko, loom_new = await _ensure_published_ko(
            session,
            org_id,
            kb_id,
            title=SEED_KO_LOOM,
            question="织机（飞织机 / loom）日常维保要注意什么？",
            answer=(
                "织机需按日/周/月点检：清洁针床与传动件、检查断纱与张力、记录《设备日常维护保养点检记录表》。"
                "样例设备编号 EQ-LOOM-01（1号飞织机）。"
            ),
            ko_type=KoType.DEVICE.value,
        )
        yarn_ko, yarn_new = await _ensure_published_ko(
            session,
            org_id,
            kb_id,
            title=SEED_KO_YARN,
            question="织机断纱检修如何处置？",
            answer=(
                "断纱时先停机断电，检查纱路与织针，更换损坏织针组（备件 SP-NEEDLE-08），"
                "完工后在工单 WO-2026-001 闭环并复检空载运行。"
            ),
            ko_type=KoType.DEVICE.value,
        )
        if loom_new:
            created["kos"] += 1
        if yarn_new:
            created["kos"] += 1
        if await _ensure_ko_relation(session, org_id, loom_ko.id, yarn_ko.id):
            created["ko_relations"] += 1
        if await _ensure_ko_relation(
            session,
            org_id,
            yarn_ko.id,
            loom_ko.id,
            relation_type=KoRelationType.DEPENDS_ON.value,
        ):
            created["ko_relations"] += 1

        loom_device = device_rows.get("EQ-LOOM-01")
        if loom_device is not None:
            if await _attach_ko(
                repo,
                org_id,
                object_type=StructuredObjectType.DEVICE.value,
                object_id=loom_device.id,
                terminology_entity_id=loom.id,
                ko_id=loom_ko.id,
            ):
                created["ko_links"] += 1
            if await _attach_ko(
                repo,
                org_id,
                object_type=StructuredObjectType.DEVICE.value,
                object_id=loom_device.id,
                terminology_entity_id=loom.id,
                ko_id=yarn_ko.id,
            ):
                created["ko_links"] += 1

    return created
