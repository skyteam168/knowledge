"""Deterministic manufacturing Ontology closed-loop acceptance (CI / ops CLI).

Does not create a new Agent portal: exercises seed → query/traverse → identity →
actions → audit → semantic intent gates. Manual UI checklist is printed for humans.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ConflictError
from app.models import StructuredRecord
from app.models.action import ActionExecutionStatus
from app.models.audit import AuditLog
from app.models.base import new_id
from app.schemas.open_api import OpenGetObjectIn, OpenQueryObjectsIn, OpenTraverseIn
from app.services.action.runtime import ActionRuntime
from app.services.authz import AuthzCache, CurrentUser
from app.services.chat.semantic_ops import SemanticKind, detect_semantic_plan
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

MANUAL_CHECKLIST: tuple[str, ...] = (
    "结构化页：域 mfg 可见 Factory/Line/ProductionOrder/Material/Inventory/Employee 与关系",
    "身份台：RM-PET-150D(nb-erp) 与 YN-RM-150(vn-wms) 同 Canonical；重复绑码 409",
    "Ontology Studio：制造实体/属性已发布（或沿用 mfg-multi-plant-v1）",
    "规则与动作：试运行 production.query_risk；material.transfer 无审批 awaiting，审批后执行成功",
    "问答专家：问「今天有哪些生产订单可能延期…」出现 semantic_ops 步骤与缺料/调拨建议",
    "问答专家：问「RM-PET-150D 和 YN-RM-150 是否同一物料」答同一 Canonical",
    "问答专家：问「织机怎么保养」不走制造语义支路（纯 RAG）",
    "MCP：describe_ontology → query_objects(risk_status=at_risk) → traverse → list_actions → approve → invoke",
)


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class AcceptanceReport:
    org_id: str
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    manual_checklist: list[str] = field(default_factory=list)
    seed: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "org_id": self.org_id,
            "seed": self.seed,
            "steps": [asdict(s) for s in self.steps],
            "manual_checklist": list(self.manual_checklist),
            "failed": [s.name for s in self.steps if not s.ok],
        }


def _ctx(user: CurrentUser) -> RequestContext:
    return RequestContext(
        user,
        AuditContext(org_id=user.org_id, actor_id=user.id, actor_name=user.username),
    )


def _tools(session: AsyncSession, user: CurrentUser) -> OpenOntologyTools:
    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=user.org_id,
        name="mfg-accept",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "action", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=user,
    )
    return OpenOntologyTools(
        session, _ctx(user), AuthzCache(MemoryCache(), ttl_seconds=60), caller
    )


async def run_mfg_acceptance(
    session: AsyncSession,
    *,
    org_id: str,
    user: CurrentUser,
    reseeds: bool = True,
) -> AcceptanceReport:
    """Run the full deterministic closed-loop gate. Mutates DB (seed + transfer)."""
    report = AcceptanceReport(
        org_id=org_id,
        ok=True,
        manual_checklist=list(MANUAL_CHECKLIST),
    )
    if user.org_id != org_id:
        report.ok = False
        report.steps.append(
            StepResult(
                name="actor_org",
                ok=False,
                error=f"user.org_id={user.org_id} != org_id={org_id}",
            )
        )
        return report

    if reseeds:
        report.seed = await seed_mfg(session, org_id)
        await session.flush()
        report.steps.append(
            StepResult(name="seed_mfg", ok=True, detail=dict(report.seed))
        )
    else:
        report.steps.append(StepResult(name="seed_mfg", ok=True, detail={"skipped": True}))

    identity = EntityIdentityService(session)
    tools = _tools(session, user)
    runtime = ActionRuntime(session, _ctx(user))

    # 1) Cross-system identity
    try:
        erp = await identity.resolve_identifier(
            org_id, system="nb-erp", external_id="RM-PET-150D"
        )
        wms = await identity.resolve_identifier(
            org_id, system="vn-wms", external_id="YN-RM-150"
        )
        same = erp is not None and wms is not None and erp.id == wms.id
        conflict_ok = False
        if same:
            other = await identity.create_canonical(
                org_id, object_type="material", display_name="accept-dup"
            )
            try:
                await identity.attach_identifier(
                    other.id,
                    org_id=org_id,
                    system="nb-erp",
                    external_id="RM-PET-150D",
                )
            except ConflictError:
                conflict_ok = True
        report.steps.append(
            StepResult(
                name="identity_resolve",
                ok=same and conflict_ok,
                detail={
                    "canonical_id": erp.id if erp else None,
                    "same_canonical": same,
                    "duplicate_bind_409": conflict_ok,
                },
                error=None if (same and conflict_ok) else "identity gate failed",
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.steps.append(
            StepResult(name="identity_resolve", ok=False, error=str(exc)[:500])
        )

    # 2) describe + query at_risk + get_object + traverse
    try:
        desc = await tools.describe_ontology(scope="summary", version="platform")
        has_po_class = "ProductionOrder" in (desc.classes or [])
        q = await tools.query_objects(
            OpenQueryObjectsIn(object_type="production_order", risk_status="at_risk")
        )
        hit = next((i for i in q.items if i.external_id == PO_AT_RISK), None)
        due = await tools.query_objects(
            OpenQueryObjectsIn(
                object_type="production_order",
                due_before=datetime.now(UTC) + timedelta(days=7),
            )
        )
        due_hit = any(i.external_id == PO_AT_RISK for i in due.items)
        neighbors = 0
        if hit is not None:
            got = await tools.get_object(
                OpenGetObjectIn(
                    object_type="production_order",
                    object_id=hit.object_id,
                    include_neighbors=True,
                    neighbor_hops=1,
                )
            )
            trav = await tools.traverse(
                OpenTraverseIn(
                    mode="object",
                    kind="structured",
                    object_id=hit.object_id,
                    object_type="production_order",
                    direction="out",
                    max_hops=1,
                )
            )
            neighbors = len(got.neighbors) + len(trav.neighbors or [])
        report.steps.append(
            StepResult(
                name="query_traverse",
                ok=bool(has_po_class and hit is not None and due_hit and neighbors > 0),
                detail={
                    "production_order_class": has_po_class,
                    "at_risk_count": len(q.items),
                    "po": hit.external_id if hit else None,
                    "due_before_hit": due_hit,
                    "neighbor_signals": neighbors,
                    "canonical_id": getattr(hit, "object_id", None) if hit else None,
                },
                error=None
                if (has_po_class and hit and due_hit and neighbors > 0)
                else "query/traverse incomplete",
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.steps.append(
            StepResult(name="query_traverse", ok=False, error=str(exc)[:500])
        )

    # 3) actions list + transfer approve path + audit
    try:
        actions = await runtime.list_actions()
        names = {a.name for a in actions}
        need = {"production.query_risk", "material.transfer"}
        listed = need.issubset(names)

        risk = await runtime.execute(
            "production.query_risk",
            {"risk_status": "at_risk"},
            idempotency_key=f"accept-risk-{new_id()[:8]}",
        )
        risk_ok = (
            risk.status == ActionExecutionStatus.SUCCEEDED.value
            and int(risk.result.get("count") or 0) >= 1
        )

        inv_src = await session.scalar(
            select(StructuredRecord).where(
                StructuredRecord.org_id == org_id,
                StructuredRecord.external_id == INV_NB_SURPLUS,
            )
        )
        inv_tgt = await session.scalar(
            select(StructuredRecord).where(
                StructuredRecord.org_id == org_id,
                StructuredRecord.external_id == INV_VN_SHORT,
            )
        )
        po = await session.scalar(
            select(StructuredRecord).where(
                StructuredRecord.org_id == org_id,
                StructuredRecord.external_id == PO_AT_RISK,
            )
        )
        if inv_src is None or inv_tgt is None or po is None:
            raise RuntimeError("fixture inventory/po missing after seed")

        src_before = float((inv_src.attrs or {}).get("qty") or 0)
        tgt_before = float((inv_tgt.attrs or {}).get("qty") or 0)
        qty = 50.0
        payload = {
            "source_inventory_id": inv_src.id,
            "target_inventory_id": inv_tgt.id,
            "qty": qty,
            "production_order_id": po.id,
            "material_external_id": MAT_PET,
            "note": "accept-mfg",
        }
        blocked = await runtime.execute(
            "material.transfer",
            payload,
            idempotency_key=f"accept-xfer-block-{new_id()[:8]}",
        )
        awaiting = blocked.status == ActionExecutionStatus.AWAITING_APPROVAL.value
        approval = await runtime.create_approval(
            "material.transfer", payload, acknowledge_risk=True
        )
        key = f"accept-xfer-{new_id()[:8]}"
        done = await runtime.execute(
            "material.transfer",
            payload,
            idempotency_key=key,
            approval_id=approval.id,
        )
        again = await runtime.execute(
            "material.transfer",
            payload,
            idempotency_key=key,
            approval_id=approval.id,
        )
        await session.refresh(inv_src)
        await session.refresh(inv_tgt)
        await session.refresh(po)
        src_after = float((inv_src.attrs or {}).get("qty") or 0)
        tgt_after = float((inv_tgt.attrs or {}).get("qty") or 0)
        transfer_ok = (
            awaiting
            and done.status == ActionExecutionStatus.SUCCEEDED.value
            and again.execution_id == done.execution_id
            and abs(src_after - (src_before - qty)) < 1e-6
            and abs(tgt_after - (tgt_before + qty)) < 1e-6
        )

        audit = await session.scalar(
            select(AuditLog)
            .where(
                AuditLog.org_id == org_id,
                AuditLog.action == "ontology.action",
                AuditLog.resource_id == "material.transfer",
            )
            .order_by(AuditLog.created_at.desc())
        )
        audit_ok = audit is not None

        report.steps.append(
            StepResult(
                name="actions_transfer_audit",
                ok=listed and risk_ok and transfer_ok and audit_ok,
                detail={
                    "actions_listed": sorted(need & names),
                    "query_risk_ok": risk_ok,
                    "awaiting_without_approval": awaiting,
                    "transfer_status": done.status,
                    "idempotent": again.execution_id == done.execution_id,
                    "src_qty": [src_before, src_after],
                    "tgt_qty": [tgt_before, tgt_after],
                    "po_shortage": (po.attrs or {}).get("shortage_qty"),
                    "audit": bool(audit_ok),
                },
                error=None
                if (listed and risk_ok and transfer_ok and audit_ok)
                else "action/audit gate failed",
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.steps.append(
            StepResult(name="actions_transfer_audit", ok=False, error=str(exc)[:500])
        )

    # 4) Semantic intent gates (no LLM)
    try:
        cases = [
            ("今天有哪些生产订单可能延期", SemanticKind.PRODUCTION_RISK),
            ("RM-PET-150D 和 YN-RM-150 是不是同一物料", SemanticKind.MATERIAL_IDENTITY),
            ("给出跨厂调拨方案", SemanticKind.MATERIAL_TRANSFER),
            ("织机怎么保养", SemanticKind.NONE),
        ]
        mismatches: list[dict[str, str]] = []
        for text, expect in cases:
            got = detect_semantic_plan(text).kind
            if got != expect:
                mismatches.append(
                    {"q": text, "expected": expect.value, "got": got.value}
                )
        report.steps.append(
            StepResult(
                name="semantic_intent_gates",
                ok=not mismatches,
                detail={"cases": len(cases), "mismatches": mismatches},
                error=None if not mismatches else "semantic intent mismatch",
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.steps.append(
            StepResult(name="semantic_intent_gates", ok=False, error=str(exc)[:500])
        )

    report.ok = all(s.ok for s in report.steps)
    return report
