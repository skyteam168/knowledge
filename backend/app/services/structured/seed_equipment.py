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
    ObjectRelation,
    ObjectRelationType,
    StructuredDomain,
    StructuredDomainKind,
    StructuredEntityLink,
    StructuredObjectType,
    StructuredRecord,
    StructuredSource,
    StructuredSourceType,
)
from app.models.base import new_id
from app.models.terminology import (
    TerminologyAlias,
    TerminologyEntity,
    TerminologyEntityType,
    TerminologyLang,
    TerminologyStatus,
)
from app.repositories.structured_repo import StructuredRepository
from app.services.terminology.expander import normalize_alias

SEED_SOURCE_NAME = "设备维保样例"
SEED_KO_LOOM = "【种子】织机维保要点"
SEED_KO_YARN = "【种子】断纱检修指引"
SEED_EQ_EXTERNAL = "EQ-LOOM-01"
SEED_FM_EXTERNAL = "FM-YARN-BREAK"
SEED_COMPONENT_EXTERNAL = "CMP-FEED-ROLLER"


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

        # Mitigates: disposition KO → symptom KO (inbound diagnosis walk).
        if await _ensure_ko_relation(
            session,
            org_id,
            yarn_ko.id,
            loom_ko.id,
            relation_type=KoRelationType.MITIGATES.value,
        ):
            created["ko_relations"] += 1

    diag = await _seed_diagnosis_chain(
        session, org_id, source=source, device_rows=device_rows, repo=repo
    )
    for key, value in diag.items():
        created[key] = created.get(key, 0) + value

    return created


async def _ensure_record(
    session: AsyncSession,
    org_id: str,
    *,
    domain_id: str,
    source_id: str,
    object_type: str,
    external_id: str,
    title: str,
    attrs: dict,
) -> tuple[StructuredRecord, bool]:
    existing = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org_id,
            StructuredRecord.source_id == source_id,
            StructuredRecord.object_type == object_type,
            StructuredRecord.external_id == external_id,
        )
    )
    if existing is not None:
        return existing, False
    from app.ontology.attributes import event_timeline_fields
    from app.ontology.catalog import derive_parent_ref

    parent_type, parent_ext = derive_parent_ref(object_type, attrs)
    occurred_at = ended_at = event_type = None
    if object_type == "event":
        occurred_at, ended_at, event_type = event_timeline_fields(attrs)
    row = StructuredRecord(
        org_id=org_id,
        domain_id=domain_id,
        source_id=source_id,
        object_type=object_type,
        external_id=external_id,
        title=title,
        status="active",
        parent_object_type=parent_type,
        parent_external_id=parent_ext,
        occurred_at=occurred_at,
        ended_at=ended_at,
        event_type=event_type,
        attrs=attrs,
    )
    session.add(row)
    await session.flush()
    return row, True


async def _ensure_object_relation(
    session: AsyncSession,
    org_id: str,
    *,
    relation_type: str,
    from_kind: str,
    from_id: str,
    from_object_type: str,
    to_kind: str,
    to_id: str,
    to_object_type: str,
) -> bool:
    existing = await session.scalar(
        select(ObjectRelation).where(
            ObjectRelation.org_id == org_id,
            ObjectRelation.relation_type == relation_type,
            ObjectRelation.from_kind == from_kind,
            ObjectRelation.from_id == from_id,
            ObjectRelation.from_object_type == from_object_type,
            ObjectRelation.to_kind == to_kind,
            ObjectRelation.to_id == to_id,
            ObjectRelation.to_object_type == to_object_type,
        )
    )
    if existing is not None:
        return False
    session.add(
        ObjectRelation(
            id=new_id(),
            org_id=org_id,
            relation_type=relation_type,
            from_kind=from_kind,
            from_id=from_id,
            from_object_type=from_object_type,
            to_kind=to_kind,
            to_id=to_id,
            to_object_type=to_object_type,
        )
    )
    await session.flush()
    return True


async def _seed_diagnosis_chain(
    session: AsyncSession,
    org_id: str,
    *,
    source: StructuredSource,
    device_rows: dict[str, EquipDevice],
    repo: StructuredRepository,
) -> dict[str, int]:
    """ISA-95 + FMEA demo chain for EQ-LOOM-01 (O5.1)."""
    created = {
        "industrial_records": 0,
        "object_relations": 0,
    }
    domain = await session.scalar(
        select(StructuredDomain).where(
            StructuredDomain.org_id == org_id,
            StructuredDomain.code == "equipment",
        )
    )
    if domain is None:
        domain = StructuredDomain(
            org_id=org_id,
            code="equipment",
            name="设备维保",
            kind=StructuredDomainKind.EQUIPMENT.value,
            description="设备 / 工单 / 备件专用表",
            enabled=True,
        )
        session.add(domain)
        await session.flush()

    site, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type="site",
        external_id="SITE-DEMO",
        title="演示工厂",
        attrs={"code": "DEMO"},
    )
    created["industrial_records"] += int(new)
    area, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type="area",
        external_id="AREA-WEAVE-A",
        title="织造车间A",
        attrs={"code": "WA", "site_external_id": "SITE-DEMO"},
    )
    created["industrial_records"] += int(new)
    line, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type="line",
        external_id="LINE-LOOM-1",
        title="飞织一线",
        attrs={
            "code": "L1",
            "area_external_id": "AREA-WEAVE-A",
            "site_external_id": "SITE-DEMO",
        },
    )
    created["industrial_records"] += int(new)
    equip, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type="equipment",
        external_id=SEED_EQ_EXTERNAL,
        title="1号飞织机（层级）",
        attrs={
            "model": "FK-Loom",
            "line_external_id": "LINE-LOOM-1",
            "rated_power": {"value": 7.5, "unit": "kW"},
        },
    )
    created["industrial_records"] += int(new)
    component, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type="component",
        external_id=SEED_COMPONENT_EXTERNAL,
        title="送纱轮",
        attrs={
            "equipment_external_id": SEED_EQ_EXTERNAL,
            "part_number": "FR-01",
            "position": "纱架侧",
        },
    )
    created["industrial_records"] += int(new)
    fm, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type="failure_mode",
        external_id=SEED_FM_EXTERNAL,
        title="断纱",
        attrs={
            "equipment_external_id": SEED_EQ_EXTERNAL,
            "component_external_id": SEED_COMPONENT_EXTERNAL,
            "code": SEED_FM_EXTERNAL,
            "severity": 8,
        },
    )
    created["industrial_records"] += int(new)

    # S2: fixed-window downtime / alarm events for EQ-LOOM-01 (2026-11-17..24 UTC).
    for ext, title, attrs in (
        (
            "EVT-DT-01",
            "断纱停机",
            {
                "equipment_external_id": SEED_EQ_EXTERNAL,
                "event_type": "downtime",
                "occurred_at": "2026-11-18T08:15:00+00:00",
                "ended_at": "2026-11-18T09:40:00+00:00",
                "severity": "high",
                "message": "送纱轮卡滞导致断纱停机",
            },
        ),
        (
            "EVT-DT-02",
            "换纱停机",
            {
                "equipment_external_id": SEED_EQ_EXTERNAL,
                "event_type": "downtime",
                "occurred_at": "2026-11-20T14:00:00+00:00",
                "ended_at": "2026-11-20T14:25:00+00:00",
                "severity": "medium",
                "message": "计划换纱",
            },
        ),
        (
            "EVT-AL-01",
            "张力报警",
            {
                "equipment_external_id": SEED_EQ_EXTERNAL,
                "event_type": "alarm",
                "occurred_at": "2026-11-19T11:05:00+00:00",
                "severity": "low",
                "message": "纱线张力偏低",
            },
        ),
    ):
        _, new = await _ensure_record(
            session,
            org_id,
            domain_id=domain.id,
            source_id=source.id,
            object_type="event",
            external_id=ext,
            title=title,
            attrs=attrs,
        )
        created["industrial_records"] += int(new)

    edges = [
        (
            ObjectRelationType.HAS_PART.value,
            "structured",
            equip.id,
            "equipment",
            "structured",
            component.id,
            "component",
        ),
        (
            ObjectRelationType.HAS_FAILURE_MODE.value,
            "structured",
            equip.id,
            "equipment",
            "structured",
            fm.id,
            "failure_mode",
        ),
        (
            ObjectRelationType.CAUSED_BY.value,
            "structured",
            fm.id,
            "failure_mode",
            "structured",
            component.id,
            "component",
        ),
        (
            ObjectRelationType.LOCATED_IN.value,
            "structured",
            equip.id,
            "equipment",
            "structured",
            line.id,
            "line",
        ),
    ]
    device = device_rows.get(SEED_EQ_EXTERNAL)
    wo = await repo.get_work_order_by_external(org_id, "WO-2026-001", source_id=source.id)
    spare = await repo.get_spare_part_by_external(
        org_id, "SP-NEEDLE-08", source_id=source.id
    )
    if device is not None and wo is not None:
        edges.append(
            (
                ObjectRelationType.WORK_ORDER_FOR.value,
                "structured",
                wo.id,
                "work_order",
                "structured",
                device.id,
                "device",
            )
        )
    if device is not None and spare is not None:
        edges.append(
            (
                ObjectRelationType.SPARE_FOR.value,
                "structured",
                spare.id,
                "spare_part",
                "structured",
                device.id,
                "device",
            )
        )

    for rel, fk, fid, fot, tk, tid, tot in edges:
        if await _ensure_object_relation(
            session,
            org_id,
            relation_type=rel,
            from_kind=fk,
            from_id=fid,
            from_object_type=fot,
            to_kind=tk,
            to_id=tid,
            to_object_type=tot,
        ):
            created["object_relations"] += 1

    # silence unused site/area for lint — they establish hierarchy parents
    _ = (site, area)
    return created
