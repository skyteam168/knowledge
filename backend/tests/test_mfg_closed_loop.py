"""Manufacturing ontology closed-loop: fixture ABox, query filters, transfer, semantic ops."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ConflictError
from app.models import StructuredRecord
from app.models.action import ActionExecutionStatus, ActionRisk, ActionType, RuleVerdict
from app.models.base import new_id
from app.schemas.open_api import OpenQueryObjectsIn
from app.services.action.runtime import ActionRuntime
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.chat.semantic_ops import (
    SemanticKind,
    SemanticOpsService,
    detect_semantic_plan,
)
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools
from app.services.structured.identity import EntityIdentityService
from app.services.structured.seed_mfg import (
    INV_NB_SURPLUS,
    INV_VN_SHORT,
    MAT_PET,
    PO_AT_RISK,
    seed_mfg,
)
from tests.factories import make_org, make_user


@pytest.fixture
async def mfg_world(session: AsyncSession):
    org = await make_org(session, code="mfg-loop")
    db_user = await make_user(session, org, username="alice-mfg")
    counts = await seed_mfg(session, org.id)
    await session.commit()
    user = CurrentUser(
        id=db_user.id,
        org_id=org.id,
        username=db_user.username,
        display_name=db_user.username,
        principals=Principals(org.id, db_user.id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return org, user, counts


def _ctx(user: CurrentUser) -> RequestContext:
    return RequestContext(
        user,
        AuditContext(org_id=user.org_id, actor_id=user.id, actor_name=user.username),
    )


def _runtime(session: AsyncSession, user: CurrentUser) -> ActionRuntime:
    return ActionRuntime(session, _ctx(user))


def _tools(session: AsyncSession, user: CurrentUser) -> OpenOntologyTools:
    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=user.org_id,
        name="mfg-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "action", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=user,
    )
    return OpenOntologyTools(
        session, _ctx(user), AuthzCache(MemoryCache(), ttl_seconds=60), caller
    )


async def test_seed_mfg_has_at_risk_order_and_identity(session: AsyncSession, mfg_world):
    org, _user, counts = mfg_world
    assert counts["records"] >= 1
    identity = EntityIdentityService(session)
    erp = await identity.resolve_identifier(
        org.id, system="nb-erp", external_id="RM-PET-150D"
    )
    wms = await identity.resolve_identifier(
        org.id, system="vn-wms", external_id="YN-RM-150"
    )
    assert erp is not None and wms is not None
    assert erp.id == wms.id

    other = await identity.create_canonical(
        org.id, object_type="material", display_name="dup"
    )
    with pytest.raises(ConflictError):
        await identity.attach_identifier(
            other.id,
            org_id=org.id,
            system="nb-erp",
            external_id="RM-PET-150D",
        )


async def test_query_objects_risk_and_due_filters(session: AsyncSession, mfg_world):
    _org, user, _counts = mfg_world
    tools = _tools(session, user)
    out = await tools.query_objects(
        OpenQueryObjectsIn(object_type="production_order", risk_status="at_risk")
    )
    assert len(out.items) >= 1
    assert any(i.external_id == PO_AT_RISK for i in out.items)

    due = datetime.now(UTC) + timedelta(days=7)
    due_out = await tools.query_objects(
        OpenQueryObjectsIn(object_type="production_order", due_before=due)
    )
    assert any(i.external_id == PO_AT_RISK for i in due_out.items)


async def test_production_query_risk_and_material_transfer(
    session: AsyncSession, mfg_world
):
    org, user, _counts = mfg_world
    rt = _runtime(session, user)
    risk = await rt.execute(
        "production.query_risk",
        {"risk_status": "at_risk"},
        idempotency_key="risk-1",
    )
    assert risk.status == ActionExecutionStatus.SUCCEEDED.value
    assert risk.result.get("count", 0) >= 1

    inv_src = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org.id,
            StructuredRecord.external_id == INV_NB_SURPLUS,
        )
    )
    inv_tgt = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org.id,
            StructuredRecord.external_id == INV_VN_SHORT,
        )
    )
    po = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org.id,
            StructuredRecord.external_id == PO_AT_RISK,
        )
    )
    assert inv_src and inv_tgt and po
    payload = {
        "source_inventory_id": inv_src.id,
        "target_inventory_id": inv_tgt.id,
        "qty": 180,
        "production_order_id": po.id,
        "material_external_id": MAT_PET,
    }
    blocked = await rt.execute(
        "material.transfer", payload, idempotency_key="xfer-await"
    )
    assert blocked.status == ActionExecutionStatus.AWAITING_APPROVAL.value

    approval = await rt.create_approval(
        "material.transfer", payload, acknowledge_risk=True
    )
    done = await rt.execute(
        "material.transfer",
        payload,
        idempotency_key="xfer-1",
        approval_id=approval.id,
    )
    assert done.status == ActionExecutionStatus.SUCCEEDED.value
    await session.refresh(inv_src)
    await session.refresh(inv_tgt)
    await session.refresh(po)
    assert float((inv_src.attrs or {}).get("qty") or 0) == 640
    assert float((inv_tgt.attrs or {}).get("qty") or 0) == 220
    assert float((po.attrs or {}).get("shortage_qty") or 0) == 0
    assert (po.attrs or {}).get("risk_status") == "open"

    again = await rt.execute(
        "material.transfer",
        payload,
        idempotency_key="xfer-1",
        approval_id=approval.id,
    )
    assert again.execution_id == done.execution_id


async def test_transfer_denied_without_identity(session: AsyncSession, mfg_world):
    org, user, _counts = mfg_world
    domain_src = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org.id,
            StructuredRecord.external_id == INV_NB_SURPLUS,
        )
    )
    assert domain_src
    session.add(
        StructuredRecord(
            id=new_id(),
            org_id=org.id,
            domain_id=domain_src.domain_id,
            source_id=domain_src.source_id,
            object_type="material",
            external_id="MAT-ORPHAN",
            title="orphan",
            status="active",
            attrs={"sku": "ORPHAN"},
        )
    )
    src = StructuredRecord(
        id=new_id(),
        org_id=org.id,
        domain_id=domain_src.domain_id,
        source_id=domain_src.source_id,
        object_type="inventory",
        external_id="INV-ORPHAN-SRC",
        title="orphan src",
        status="ok",
        attrs={
            "material_external_id": "MAT-ORPHAN",
            "qty": 50,
            "factory_external_id": "FAC-NB-01",
        },
    )
    tgt = StructuredRecord(
        id=new_id(),
        org_id=org.id,
        domain_id=domain_src.domain_id,
        source_id=domain_src.source_id,
        object_type="inventory",
        external_id="INV-ORPHAN-TGT",
        title="orphan tgt",
        status="low",
        attrs={
            "material_external_id": "MAT-ORPHAN",
            "qty": 1,
            "factory_external_id": "FAC-VN-01",
        },
    )
    session.add_all([src, tgt])
    await session.flush()

    rt = _runtime(session, user)
    out = await rt.execute(
        "material.transfer",
        {
            "source_inventory_id": src.id,
            "target_inventory_id": tgt.id,
            "qty": 10,
            "material_external_id": "MAT-ORPHAN",
        },
        idempotency_key="xfer-deny",
    )
    assert out.status == ActionExecutionStatus.DENIED.value
    assert out.error and "identity" in out.error.lower()


def test_detect_semantic_plan_keywords():
    assert (
        detect_semantic_plan("今天有哪些生产订单可能延期").kind
        == SemanticKind.PRODUCTION_RISK
    )
    assert detect_semantic_plan("RM-PET-150D 和 YN-RM-150 是不是同一物料").kind == (
        SemanticKind.MATERIAL_IDENTITY
    )
    assert detect_semantic_plan("给出跨厂调拨方案").kind == SemanticKind.MATERIAL_TRANSFER
    assert detect_semantic_plan("织机怎么保养").kind == SemanticKind.NONE


async def test_semantic_ops_risk_bundle(session: AsyncSession, mfg_world):
    _org, user, _counts = mfg_world
    plan = detect_semantic_plan("帮我检查今天有哪些生产订单可能延期并分析缺料")
    bundle = await SemanticOpsService(session, _ctx(user)).run(
        "帮我检查今天有哪些生产订单可能延期并分析缺料", plan
    )
    assert bundle.hit
    assert any(
        o.get("external_id") == PO_AT_RISK
        for o in bundle.objects
        if isinstance(o, dict)
    )
    assert any("风险订单" in b or "可调拨" in b for b in bundle.context_blocks)


async def test_transfer_respects_structured_acl(session: AsyncSession, mfg_world):
    org, user, _counts = mfg_world
    from app.models import ResourceAcl
    from app.repositories.acl_repo import EFFECT_ALLOW
    from app.services.structured.access import RESOURCE_STRUCTURED

    inv_src = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org.id,
            StructuredRecord.external_id == INV_NB_SURPLUS,
        )
    )
    inv_tgt = await session.scalar(
        select(StructuredRecord).where(
            StructuredRecord.org_id == org.id,
            StructuredRecord.external_id == INV_VN_SHORT,
        )
    )
    assert inv_src and inv_tgt
    # Restrict source inventory to a non-matching principal → deny write.
    session.add(
        ResourceAcl(
            org_id=org.id,
            resource_type=RESOURCE_STRUCTURED,
            resource_id=inv_src.id,
            principal_type="user",
            principal_id="someone-else",
            permission="edit",
            effect=EFFECT_ALLOW,
            created_by=user.id,
        )
    )
    await session.flush()

    limited = CurrentUser(
        id=user.id,
        org_id=org.id,
        username=user.username,
        display_name=user.display_name,
        principals=Principals(org.id, user.id),
        permissions=frozenset({"admin:retrieval"}),
    )
    rt = _runtime(session, limited)
    payload = {
        "source_inventory_id": inv_src.id,
        "target_inventory_id": inv_tgt.id,
        "qty": 10,
        "material_external_id": MAT_PET,
    }
    approval = await rt.create_approval(
        "material.transfer", payload, acknowledge_risk=True
    )
    out = await rt.execute(
        "material.transfer",
        payload,
        idempotency_key="xfer-acl",
        approval_id=approval.id,
    )
    assert out.status == ActionExecutionStatus.FAILED.value
    assert out.error and (
        "permission" in out.error.lower() or "acl" in out.error.lower() or "denied" in out.error.lower()
    )


async def test_unknown_action_handler_errors(session: AsyncSession, mfg_world):
    _org, user, _counts = mfg_world
    rt = _runtime(session, user)
    await rt.ensure_builtins()
    session.add(
        ActionType(
            org_id=user.org_id,
            name="custom.no_handler",
            description="no handler",
            input_schema={},
            preconditions={},
            risk=ActionRisk.LOW.value,
            systems=[],
            enabled=True,
            created_by=user.id,
        )
    )
    await session.flush()
    out = await rt.execute(
        "custom.no_handler",
        {},
        idempotency_key="no-handler-1",
    )
    assert out.status == ActionExecutionStatus.FAILED.value
    assert out.error and "No handler" in out.error
