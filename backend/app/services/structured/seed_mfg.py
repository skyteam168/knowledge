"""Idempotent manufacturing Ontology ABox — 申洲越南厂延期闭环演示。

Story (natural-language Agent verification):
  CustomerOrder PO-1001 (品牌客户交期紧张)
    └── ProductionOrder MO-2001 (计划 10000 / 完成 6000 / 缺关键料 1000)
          ├── Line LINE-01 @ Factory FAC-VN-SZ (越南)
          ├── Equipment EQ-4001 (MES, 运行中但等料)
          ├── Material MAT-3001 (ERP) ↔ WMS YN-MAT-3001
          ├── Inventory VN short 200 / NB surplus 2200
          └── Employee EMP-001 生产经理（有调拨申请权限语义）
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KnowledgeBase,
    KnowledgeObject,
    KoEntry,
    KoOrigin,
    KoStatus,
    KoType,
    KoVersion,
    KoVersionStatus,
    ObjectRelation,
    StructuredDomain,
    StructuredDomainKind,
    StructuredObjectType,
    StructuredRecord,
    StructuredSource,
    StructuredSourceType,
)
from app.models.base import new_id
from app.models.structured import ObjectEndpointKind, ObjectRelationType
from app.models.terminology import (
    TerminologyAlias,
    TerminologyEntity,
    TerminologyEntityType,
    TerminologyLang,
    TerminologyStatus,
)
from app.repositories.structured_repo import StructuredRepository
from app.services.structured.identity import EntityIdentityService
from app.services.terminology.expander import normalize_alias

SEED_SOURCE_NAME = "制造试点 Fixture"
SEED_DOMAIN_CODE = "mfg"

# —— 对外稳定编号（给 Agent / 自然语言验收用）——
FACTORY_VN = "FAC-VN-SZ"
FACTORY_NB = "FAC-NB-SZ"
LINE_VN = "LINE-01"
LINE_NB = "LINE-NB-B"
CO_PO = "PO-1001"
MO_PO = "MO-2001"
MAT = "MAT-3001"
EQ = "EQ-4001"
INV_VN = "INV-VN-MAT-3001"
INV_NB = "INV-NB-MAT-3001"
EMP = "EMP-001"

# 兼容上一轮验收脚本的旧编号（仍可 query 到）
LEGACY_PO = "PO-VN-2026-1101"
LEGACY_MAT = "MAT-PET-150D"
LEGACY_INV_VN = "INV-VN-PET-150D"
LEGACY_INV_NB = "INV-NB-PET-150D"

# 兼容别名
PO_AT_RISK = MO_PO
MAT_PET = MAT
INV_VN_SHORT = INV_VN
INV_NB_SURPLUS = INV_NB
EMP_PLANNER = EMP


async def _ensure_term(
    session: AsyncSession, org_id: str, name: str, *, aliases: tuple[str, ...]
) -> TerminologyEntity:
    existing = await session.scalar(
        select(TerminologyEntity).where(
            TerminologyEntity.org_id == org_id,
            TerminologyEntity.canonical_name == name,
        )
    )
    if existing is not None:
        return existing
    for alias in aliases:
        hit = await session.scalar(
            select(TerminologyAlias).where(
                TerminologyAlias.org_id == org_id,
                TerminologyAlias.alias_normalized == normalize_alias(alias),
            )
        )
        if hit is not None:
            ent = await session.get(TerminologyEntity, hit.entity_id)
            if ent is not None:
                return ent
    entity = TerminologyEntity(
        org_id=org_id,
        canonical_name=name,
        entity_type=TerminologyEntityType.OTHER.value,
        description=f"制造试点种子：{name}",
        status=TerminologyStatus.ACTIVE.value,
    )
    session.add(entity)
    await session.flush()
    for alias in aliases:
        exists_alias = await session.scalar(
            select(TerminologyAlias).where(
                TerminologyAlias.org_id == org_id,
                TerminologyAlias.alias_normalized == normalize_alias(alias),
            )
        )
        if exists_alias is not None:
            continue
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


async def _ensure_record(
    session: AsyncSession,
    org_id: str,
    *,
    domain_id: str,
    source_id: str,
    object_type: str,
    external_id: str,
    title: str,
    status: str = "active",
    attrs: dict | None = None,
    parent_object_type: str | None = None,
    parent_external_id: str | None = None,
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
        existing.title = title
        existing.status = status
        existing.attrs = dict(attrs or {})
        existing.parent_object_type = parent_object_type
        existing.parent_external_id = parent_external_id
        await session.flush()
        return existing, False
    row = StructuredRecord(
        id=new_id(),
        org_id=org_id,
        domain_id=domain_id,
        source_id=source_id,
        object_type=object_type,
        external_id=external_id,
        title=title,
        status=status,
        parent_object_type=parent_object_type,
        parent_external_id=parent_external_id,
        attrs=dict(attrs or {}),
    )
    session.add(row)
    await session.flush()
    return row, True


async def _ensure_object_relation(
    session: AsyncSession,
    org_id: str,
    *,
    relation_type: str,
    from_id: str,
    from_object_type: str,
    to_id: str,
    to_object_type: str,
    attrs: dict | None = None,
) -> bool:
    kind = ObjectEndpointKind.STRUCTURED.value
    existing = await session.scalar(
        select(ObjectRelation).where(
            ObjectRelation.org_id == org_id,
            ObjectRelation.relation_type == relation_type,
            ObjectRelation.from_kind == kind,
            ObjectRelation.from_id == from_id,
            ObjectRelation.from_object_type == from_object_type,
            ObjectRelation.to_kind == kind,
            ObjectRelation.to_id == to_id,
            ObjectRelation.to_object_type == to_object_type,
        )
    )
    if existing is not None:
        if attrs:
            existing.attrs = dict(attrs)
            await session.flush()
        return False
    session.add(
        ObjectRelation(
            id=new_id(),
            org_id=org_id,
            relation_type=relation_type,
            from_kind=kind,
            from_id=from_id,
            from_object_type=from_object_type,
            to_kind=kind,
            to_id=to_id,
            to_object_type=to_object_type,
            attrs=dict(attrs or {}),
        )
    )
    await session.flush()
    return True


async def _ensure_identity(
    identity: EntityIdentityService,
    org_id: str,
    *,
    object_type: str,
    display_name: str,
    structured_id: str,
    identifiers: tuple[tuple[str, str], ...],
) -> tuple[str, int]:
    from app.core.exceptions import ConflictError

    existing = await identity.get_by_structured(
        org_id,
        structured_object_type=object_type,
        structured_object_id=structured_id,
    )
    created_ids = 0
    if existing is None:
        existing = await identity.create_canonical(
            org_id,
            object_type,
            display_name,
            structured_object_type=object_type,
            structured_object_id=structured_id,
        )
    for system, external_id in identifiers:
        try:
            await identity.attach_identifier(
                existing.id,
                org_id=org_id,
                system=system,
                external_id=external_id,
                id_kind="external_id",
                is_primary=system.endswith("erp") or system == "erp",
            )
            created_ids += 1
        except ConflictError:
            resolved = await identity.resolve_identifier(
                org_id, system=system, external_id=external_id
            )
            if resolved is None or resolved.id != existing.id:
                # Already bound elsewhere — leave for ops; don't fail whole seed.
                continue
    return existing.id, created_ids


async def _ensure_sop_ko(session: AsyncSession, org_id: str) -> str | None:
    kb_id = await session.scalar(
        select(KnowledgeBase.id)
        .where(KnowledgeBase.org_id == org_id)
        .order_by(KnowledgeBase.created_at.asc())
    )
    if kb_id is None:
        return None
    title = "【种子】跨厂物料调拨 SOP（越南厂缺料）"
    existing = await session.scalar(
        select(KnowledgeObject).where(
            KnowledgeObject.org_id == org_id,
            KnowledgeObject.title == title,
        )
    )
    if existing is not None:
        return existing.id
    answer = (
        "## 适用场景\n"
        "越南工厂生产订单因关键物料短缺导致延期风险时，优先评估宁波/国内仓富余库存并发起调拨。\n\n"
        "## 步骤\n"
        "1. 确认 ProductionOrder 的 shortage_qty 与交期。\n"
        "2. 核对 Material 跨系统身份（ERP 料号 ↔ WMS 料号）。\n"
        "3. 查找其他工厂/仓库同料富余库存，评估对其他订单影响。\n"
        "4. 生成调拨方案（来源仓、目标仓、数量、关联工单）。\n"
        "5. 高风险跨厂调拨须审批人 acknowledge_risk 后执行 TransferMaterial。\n"
        "6. 执行后复核库存与订单 risk_status，持续跟踪直至恢复 open。\n"
    )
    question = "越南厂缺料导致生产订单延期时如何调拨物料？"
    variants = ["跨厂调拨 SOP", "物料短缺怎么办", "生产订单延期缺料", "MO-2001 缺料"]
    ko = KnowledgeObject(
        id=new_id(),
        org_id=org_id,
        kb_id=kb_id,
        ko_type=KoType.POLICY.value,
        title=title,
        question=question,
        variants=variants,
        answer=answer,
        sources=[],
        status=KoStatus.PUBLISHED.value,
        version=1,
        published_version=1,
        acl_inherit=True,
        origin=KoOrigin.MANUAL.value,
        published_at=datetime.now(UTC),
    )
    session.add(ko)
    await session.flush()
    session.add(
        KoVersion(
            id=new_id(),
            org_id=org_id,
            ko_id=ko.id,
            version=1,
            ko_type=KoType.POLICY.value,
            title=title,
            status=KoVersionStatus.PUBLISHED.value,
            question=question,
            answer=answer,
            variants=variants,
            sources=[],
            published_at=datetime.now(UTC),
        )
    )
    for seq, q in enumerate([question, *variants]):
        session.add(
            KoEntry(
                id=new_id(),
                org_id=org_id,
                ko_id=ko.id,
                ko_version=1,
                seq=seq,
                question=q,
            )
        )
    await session.flush()
    return ko.id


async def seed_mfg(session: AsyncSession, org_id: str) -> dict[str, int]:
    """Upsert 申洲越南厂延期 ABox + 身份 + SOP。Idempotent."""
    repo = StructuredRepository(session)
    identity = EntityIdentityService(session)
    created = {
        "sources": 0,
        "domains": 0,
        "records": 0,
        "object_relations": 0,
        "identifiers": 0,
        "terms": 0,
        "kos": 0,
    }

    source = await repo.get_source_by_name(org_id, SEED_SOURCE_NAME)
    if source is None:
        source = StructuredSource(
            org_id=org_id,
            name=SEED_SOURCE_NAME,
            type=StructuredSourceType.WMS.value,
            enabled=True,
            meta={
                "seed": True,
                "domain": "mfg",
                "fixture": "shenzhou-vn-delay",
                "company": "申洲国际",
            },
        )
        repo.add_source(source)
        await session.flush()
        created["sources"] = 1

    domain = await repo.get_domain_by_code(org_id, SEED_DOMAIN_CODE)
    if domain is None:
        domain = StructuredDomain(
            org_id=org_id,
            code=SEED_DOMAIN_CODE,
            name="制造试点",
            kind=StructuredDomainKind.GENERIC.value,
            description="申洲国际越南厂延期闭环：客户订单/工单/物料/设备/产线/人员",
            enabled=True,
        )
        repo.add_domain(domain)
        await session.flush()
        created["domains"] = 1

    term = await _ensure_term(
        session,
        org_id,
        "针织关键面料-3001",
        aliases=(MAT, "YN-MAT-3001", "关键面料3001", LEGACY_MAT, "RM-PET-150D", "YN-RM-150"),
    )
    created["terms"] += 1 if term else 0

    today = date.today()
    due = (today + timedelta(days=2)).isoformat()

    fac_vn, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.FACTORY.value,
        external_id=FACTORY_VN,
        title="申洲国际越南工厂",
        attrs={
            "code": FACTORY_VN,
            "country": "VN",
            "timezone": "Asia/Ho_Chi_Minh",
            "company": "申洲国际",
        },
    )
    created["records"] += int(new)

    fac_nb, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.FACTORY.value,
        external_id=FACTORY_NB,
        title="申洲国际宁波基地",
        attrs={
            "code": FACTORY_NB,
            "country": "CN",
            "timezone": "Asia/Shanghai",
            "company": "申洲国际",
        },
    )
    created["records"] += int(new)

    line_vn, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.LINE.value,
        external_id=LINE_VN,
        title="越南一厂成衣一线",
        status="running",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_VN,
        attrs={
            "code": LINE_VN,
            "area_external_id": FACTORY_VN,
            "factory_external_id": FACTORY_VN,
            "shift": "A",
            "capacity_pcs_per_day": 5000,
            "team": "成衣一组",
        },
    )
    created["records"] += int(new)

    line_nb, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.LINE.value,
        external_id=LINE_NB,
        title="宁波基地仓储配套线",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_NB,
        attrs={
            "code": LINE_NB,
            "area_external_id": FACTORY_NB,
            "factory_external_id": FACTORY_NB,
            "capacity_pcs_per_day": 3000,
        },
    )
    created["records"] += int(new)

    eq, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.EQUIPMENT.value,
        external_id=EQ,
        title="越南一线圆机 EQ-4001",
        status="RUNNING",
        parent_object_type=StructuredObjectType.LINE.value,
        parent_external_id=LINE_VN,
        attrs={
            "model": "CIRCULAR-KNIT-X",
            "line_external_id": LINE_VN,
            "factory_external_id": FACTORY_VN,
            "capacity_pcs_per_day": 4500,
            "fault_open": False,
            "waiting_material": True,
            "anomaly": "等关键面料 MAT-3001，产能闲置",
        },
    )
    created["records"] += int(new)

    material, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.MATERIAL.value,
        external_id=MAT,
        title="关键针织面料 MAT-3001",
        attrs={"sku": MAT, "spec": "关键面料", "uom": "kg"},
    )
    created["records"] += int(new)

    co, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.CUSTOMER_ORDER.value,
        external_id=CO_PO,
        title="品牌客户订单 PO-1001",
        status="at_risk",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_VN,
        attrs={
            "customer_name": "全球运动品牌 A",
            "due_date": due,
            "order_qty": 10000,
            "order_status": "at_risk",
            "factory_external_id": FACTORY_VN,
            "product_sku": "SZ-TEE-42",
        },
    )
    created["records"] += int(new)

    mo, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.PRODUCTION_ORDER.value,
        external_id=MO_PO,
        title="越南生产工单 MO-2001（延期风险）",
        status="at_risk",
        parent_object_type=StructuredObjectType.LINE.value,
        parent_external_id=LINE_VN,
        attrs={
            "due_date": due,
            "risk_status": "at_risk",
            "customer_order_external_id": CO_PO,
            "material_external_id": MAT,
            "planned_qty": 10000,
            "completed_qty": 6000,
            "required_qty": 10000,
            "shortage_qty": 1000,
            "factory_external_id": FACTORY_VN,
            "line_external_id": LINE_VN,
            "equipment_external_id": EQ,
            "product_sku": "SZ-TEE-42",
            "anomaly": "关键面料短缺，剩余 4000 件无法继续投产；交期仅剩 2 天",
        },
    )
    created["records"] += int(new)

    # Legacy aliases for older MCP scripts
    await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.PRODUCTION_ORDER.value,
        external_id=LEGACY_PO,
        title="（兼容）越南PO-延期风险订单",
        status="at_risk",
        parent_object_type=StructuredObjectType.LINE.value,
        parent_external_id=LINE_VN,
        attrs=dict(mo.attrs or {}),
    )

    inv_vn, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.INVENTORY.value,
        external_id=INV_VN,
        title="越南仓 MAT-3001",
        status="low",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_VN,
        attrs={
            "material_external_id": MAT,
            "qty": 200,
            "uom": "kg",
            "factory_external_id": FACTORY_VN,
            "line_external_id": LINE_VN,
            "warehouse_code": "VN-WH-01",
        },
    )
    created["records"] += int(new)

    inv_nb, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.INVENTORY.value,
        external_id=INV_NB,
        title="宁波仓 MAT-3001",
        status="ok",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_NB,
        attrs={
            "material_external_id": MAT,
            "qty": 2200,
            "uom": "kg",
            "factory_external_id": FACTORY_NB,
            "line_external_id": LINE_NB,
            "warehouse_code": "NB-WH-02",
            "transferable_surplus": 2000,
        },
    )
    created["records"] += int(new)

    await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.INVENTORY.value,
        external_id=LEGACY_INV_VN,
        title="（兼容）越南仓",
        status="low",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_VN,
        attrs=dict(inv_vn.attrs or {}),
    )
    await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.INVENTORY.value,
        external_id=LEGACY_INV_NB,
        title="（兼容）宁波仓",
        status="ok",
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_NB,
        attrs=dict(inv_nb.attrs or {}),
    )

    emp, new = await _ensure_record(
        session,
        org_id,
        domain_id=domain.id,
        source_id=source.id,
        object_type=StructuredObjectType.EMPLOYEE.value,
        external_id=EMP,
        title="生产经理 陈工",
        attrs={
            "employee_no": "SZ-VN-PM-001",
            "role": "production_manager",
            "department": "越南一厂生产部",
            "factory_external_id": FACTORY_VN,
            "can_request_transfer": True,
            "approver_role": "warehouse_supervisor",
        },
        parent_object_type=StructuredObjectType.FACTORY.value,
        parent_external_id=FACTORY_VN,
    )
    created["records"] += int(new)

    rels: list[tuple] = [
        (
            ObjectRelationType.BELONGS_TO.value,
            line_vn.id,
            StructuredObjectType.LINE.value,
            fac_vn.id,
            StructuredObjectType.FACTORY.value,
            None,
        ),
        (
            ObjectRelationType.BELONGS_TO.value,
            line_nb.id,
            StructuredObjectType.LINE.value,
            fac_nb.id,
            StructuredObjectType.FACTORY.value,
            None,
        ),
        (
            ObjectRelationType.LOCATED_IN.value,
            eq.id,
            StructuredObjectType.EQUIPMENT.value,
            line_vn.id,
            StructuredObjectType.LINE.value,
            None,
        ),
        (
            ObjectRelationType.LOCATED_IN.value,
            inv_vn.id,
            StructuredObjectType.INVENTORY.value,
            fac_vn.id,
            StructuredObjectType.FACTORY.value,
            None,
        ),
        (
            ObjectRelationType.LOCATED_IN.value,
            inv_nb.id,
            StructuredObjectType.INVENTORY.value,
            fac_nb.id,
            StructuredObjectType.FACTORY.value,
            None,
        ),
        (
            ObjectRelationType.BELONGS_TO.value,
            mo.id,
            StructuredObjectType.PRODUCTION_ORDER.value,
            co.id,
            StructuredObjectType.CUSTOMER_ORDER.value,
            {"erp_po": CO_PO, "mes_mo": MO_PO},
        ),
        (
            ObjectRelationType.WORK_ORDER_FOR.value,
            mo.id,
            StructuredObjectType.PRODUCTION_ORDER.value,
            line_vn.id,
            StructuredObjectType.LINE.value,
            None,
        ),
        (
            ObjectRelationType.WORK_ORDER_FOR.value,
            mo.id,
            StructuredObjectType.PRODUCTION_ORDER.value,
            eq.id,
            StructuredObjectType.EQUIPMENT.value,
            None,
        ),
        (
            ObjectRelationType.CONSUMES.value,
            mo.id,
            StructuredObjectType.PRODUCTION_ORDER.value,
            material.id,
            StructuredObjectType.MATERIAL.value,
            {"required_qty": 1000, "uom": "kg", "remaining_pcs": 4000},
        ),
        (
            ObjectRelationType.CONSUMES.value,
            mo.id,
            StructuredObjectType.PRODUCTION_ORDER.value,
            inv_vn.id,
            StructuredObjectType.INVENTORY.value,
            {"shortage_qty": 1000},
        ),
        (
            ObjectRelationType.RESPONSIBLE_FOR.value,
            emp.id,
            StructuredObjectType.EMPLOYEE.value,
            mo.id,
            StructuredObjectType.PRODUCTION_ORDER.value,
            None,
        ),
        (
            ObjectRelationType.RESPONSIBLE_FOR.value,
            emp.id,
            StructuredObjectType.EMPLOYEE.value,
            co.id,
            StructuredObjectType.CUSTOMER_ORDER.value,
            None,
        ),
    ]
    for rel_type, fid, fot, tid, tot, attrs in rels:
        if await _ensure_object_relation(
            session,
            org_id,
            relation_type=rel_type,
            from_id=fid,
            from_object_type=fot,
            to_id=tid,
            to_object_type=tot,
            attrs=attrs,
        ):
            created["object_relations"] += 1

    _, n = await _ensure_identity(
        identity,
        org_id,
        object_type=StructuredObjectType.CUSTOMER_ORDER.value,
        display_name=co.title,
        structured_id=co.id,
        identifiers=(("erp", CO_PO), ("nb-erp", CO_PO)),
    )
    created["identifiers"] += n

    _, n = await _ensure_identity(
        identity,
        org_id,
        object_type=StructuredObjectType.PRODUCTION_ORDER.value,
        display_name=mo.title,
        structured_id=mo.id,
        identifiers=(("mes", MO_PO), ("vn-mes", MO_PO), ("erp", f"ERP-{MO_PO}")),
    )
    created["identifiers"] += n

    _, n = await _ensure_identity(
        identity,
        org_id,
        object_type=StructuredObjectType.MATERIAL.value,
        display_name=material.title,
        structured_id=material.id,
        identifiers=(
            ("erp", MAT),
            ("nb-erp", MAT),
            ("nb-erp", LEGACY_MAT),
            ("vn-wms", "YN-MAT-3001"),
            ("vn-wms", "YN-RM-150"),
        ),
    )
    created["identifiers"] += n

    _, n = await _ensure_identity(
        identity,
        org_id,
        object_type=StructuredObjectType.EQUIPMENT.value,
        display_name=eq.title,
        structured_id=eq.id,
        identifiers=(("mes", EQ), ("vn-mes", EQ)),
    )
    created["identifiers"] += n

    ko_id = await _ensure_sop_ko(session, org_id)
    if ko_id:
        created["kos"] = 1

    mo.updated_at = datetime.now(UTC)
    await session.flush()
    return created
