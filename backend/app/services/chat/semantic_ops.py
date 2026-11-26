"""Code-orchestrated ontology semantic branch for manufacturing closed-loop Q&A.

Model only phrases the answer; steps are fixed by this module (Wave 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ObjectRelation, StructuredRecord
from app.models.structured import ObjectEndpointKind, StructuredObjectType
from app.services.action.runtime import ActionRuntime
from app.services.authz import CurrentUser
from app.services.context import RequestContext
from app.services.structured.access import StructuredAccess
from app.services.structured.identity import EntityIdentityService


class SemanticKind(StrEnum):
    NONE = "none"
    PRODUCTION_RISK = "production_risk"
    MATERIAL_IDENTITY = "material_identity"
    MATERIAL_TRANSFER = "material_transfer"


_RISK_RE = re.compile(
    r"(延期|延期风险|缺料|生产订单|交期|at[_ -]?risk|delay|production.?order|shortage)",
    re.I,
)
_IDENTITY_RE = re.compile(
    r"(同一|是不是同|identity|canonical|RM-PET|YN-RM|料号|跨系统|映射)",
    re.I,
)
_TRANSFER_RE = re.compile(
    r"(调拨|转仓|transfer|挪料|移库)",
    re.I,
)
_CONFIRM_RE = re.compile(r"(确认调拨|执行调拨|approve.?transfer|confirm.?transfer)", re.I)


@dataclass
class SemanticPlan:
    kind: SemanticKind
    confirm_transfer: bool = False


@dataclass
class SemanticBundle:
    kind: SemanticKind
    steps: list[dict[str, Any]] = field(default_factory=list)
    context_blocks: list[str] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)
    action_result: dict[str, Any] | None = None
    hit: bool = False


def detect_semantic_plan(query: str) -> SemanticPlan:
    text = (query or "").strip()
    if not text:
        return SemanticPlan(SemanticKind.NONE)
    confirm = bool(_CONFIRM_RE.search(text))
    # Explicit execute/confirm → transfer path (may also analyze risk inside).
    if confirm:
        return SemanticPlan(SemanticKind.MATERIAL_TRANSFER, confirm_transfer=True)
    # Risk / delay questions may mention 调拨方案 as advice — keep production_risk.
    if _RISK_RE.search(text):
        return SemanticPlan(SemanticKind.PRODUCTION_RISK)
    if _IDENTITY_RE.search(text):
        return SemanticPlan(SemanticKind.MATERIAL_IDENTITY)
    if _TRANSFER_RE.search(text):
        return SemanticPlan(SemanticKind.MATERIAL_TRANSFER, confirm_transfer=False)
    return SemanticPlan(SemanticKind.NONE)


class SemanticOpsService:
    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self.session = session
        self.ctx = ctx
        self.identity = EntityIdentityService(session)
        self.access = StructuredAccess(session)

    @property
    def org_id(self) -> str:
        return self.ctx.user.org_id

    async def run(self, query: str, plan: SemanticPlan) -> SemanticBundle:
        if plan.kind == SemanticKind.NONE:
            return SemanticBundle(kind=plan.kind, hit=False)
        bundle = SemanticBundle(kind=plan.kind, hit=True)
        bundle.steps.append({"step": "describe_ontology", "status": "running"})
        summary = await self._describe_summary()
        bundle.steps[-1] = {
            "step": "describe_ontology",
            "status": "done",
            "detail": summary,
        }
        bundle.context_blocks.append(
            "【Ontology】"
            + f" classes={', '.join(summary.get('classes', [])[:12])}"
            + f"; relations={', '.join(summary.get('relations', [])[:8])}"
        )

        if plan.kind == SemanticKind.MATERIAL_IDENTITY:
            await self._run_identity(query, bundle)
        elif plan.kind == SemanticKind.PRODUCTION_RISK:
            await self._run_risk(bundle)
        elif plan.kind == SemanticKind.MATERIAL_TRANSFER:
            await self._run_risk(bundle)
            await self._run_transfer_plan(bundle, confirm=plan.confirm_transfer)
        return bundle

    async def _describe_summary(self) -> dict[str, Any]:
        from app.ontology.catalog import INDUSTRIAL_OBJECT_CLASSES, OntologyCatalog

        cat = OntologyCatalog.from_enums()
        return {
            "classes": sorted(INDUSTRIAL_OBJECT_CLASSES)[:20],
            "relations": sorted(cat.industrial_relation_properties)[:20],
            "version": "published",
        }

    async def _visible_records(
        self, object_type: str, *, status: str | None = None
    ) -> list[StructuredRecord]:
        rows = list(
            await self.session.scalars(
                select(StructuredRecord).where(
                    StructuredRecord.org_id == self.org_id,
                    StructuredRecord.object_type == object_type,
                )
            )
        )
        if status:
            filtered: list[StructuredRecord] = []
            for row in rows:
                attrs = dict(row.attrs or {})
                risk = str(attrs.get("risk_status") or row.status or "").lower()
                if risk == status or row.status == status:
                    filtered.append(row)
            rows = filtered
        visible_ids = set(
            await self.access.filter_readable(self.ctx.user, [r.id for r in rows])
        )
        return [r for r in rows if r.id in visible_ids]

    async def _run_identity(self, query: str, bundle: SemanticBundle) -> None:
        bundle.steps.append({"step": "resolve_identity", "status": "running"})
        codes = re.findall(r"[A-Z]{1,4}-?[A-Z0-9-]{3,}", query.upper())
        # Also catch Chinese-adjacent latin tokens already in query.
        if not codes:
            codes = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{3,}", query)
        resolved: list[dict[str, Any]] = []
        for code in codes[:6]:
            for system in ("nb-erp", "vn-wms", "vn-erp", "vn-mes"):
                entity = await self.identity.resolve_identifier(
                    self.org_id, system=system, external_id=code
                )
                if entity is None:
                    continue
                ids = await self.identity.list_identifiers(self.org_id, entity.id)
                resolved.append(
                    {
                        "queried": code,
                        "system": system,
                        "canonical_id": entity.id,
                        "display_name": entity.display_name,
                        "object_type": entity.object_type,
                        "identifiers": [
                            {"system": i.system, "external_id": i.external_id}
                            for i in ids
                        ],
                    }
                )
                break
        bundle.steps[-1] = {
            "step": "resolve_identity",
            "status": "done",
            "detail": {"matches": resolved},
        }
        bundle.objects.extend(resolved)
        if not resolved:
            bundle.context_blocks.append("【身份】未在跨系统身份表中解析到编码。")
            return
        # Same canonical?
        cids = {r["canonical_id"] for r in resolved}
        if len(cids) == 1 and len(resolved) >= 2:
            name = resolved[0]["display_name"]
            ids = resolved[0]["identifiers"]
            bundle.context_blocks.append(
                f"【身份】{resolved[0]['queried']} 与其他编码解析为同一 Canonical「{name}」"
                f"（id={resolved[0]['canonical_id']}）；系统编码="
                + ", ".join(f"{i['system']}:{i['external_id']}" for i in ids)
            )
        else:
            for r in resolved:
                bundle.context_blocks.append(
                    f"【身份】{r['queried']} → Canonical {r['display_name']} "
                    f"({r['canonical_id']}) identifiers="
                    + ", ".join(
                        f"{i['system']}:{i['external_id']}" for i in r["identifiers"]
                    )
                )

    async def _run_risk(self, bundle: SemanticBundle) -> None:
        bundle.steps.append({"step": "query_objects", "status": "running"})
        orders = await self._visible_records(
            StructuredObjectType.PRODUCTION_ORDER.value
        )
        at_risk = []
        for row in orders:
            attrs = dict(row.attrs or {})
            risk = str(attrs.get("risk_status") or row.status or "").lower()
            if risk not in {"at_risk", "delayed"}:
                continue
            item = {
                "object_id": row.id,
                "external_id": row.external_id,
                "title": row.title,
                "risk_status": risk,
                "due_date": attrs.get("due_date"),
                "customer_order_external_id": attrs.get("customer_order_external_id"),
                "material_external_id": attrs.get("material_external_id"),
                "equipment_external_id": attrs.get("equipment_external_id"),
                "shortage_qty": attrs.get("shortage_qty"),
                "planned_qty": attrs.get("planned_qty"),
                "completed_qty": attrs.get("completed_qty"),
                "required_qty": attrs.get("required_qty"),
                "factory_external_id": attrs.get("factory_external_id"),
                "line_external_id": attrs.get("line_external_id"),
                "anomaly": attrs.get("anomaly"),
            }
            at_risk.append(item)
            bundle.objects.append({"kind": "production_order", **item})
        bundle.steps[-1] = {
            "step": "query_objects",
            "status": "done",
            "detail": {"count": len(at_risk), "items": at_risk},
        }
        if not at_risk:
            bundle.context_blocks.append("【生产订单】当前未见 at_risk/delayed 订单。")
            return

        bundle.steps.append({"step": "traverse", "status": "running"})
        neighbors: list[dict[str, Any]] = []
        for item in at_risk:
            rels = list(
                await self.session.scalars(
                    select(ObjectRelation).where(
                        ObjectRelation.org_id == self.org_id,
                        ObjectRelation.from_kind == ObjectEndpointKind.STRUCTURED.value,
                        ObjectRelation.from_id == item["object_id"],
                    )
                )
            )
            for rel in rels:
                neighbors.append(
                    {
                        "from": item["external_id"],
                        "relation": rel.relation_type,
                        "to_object_type": rel.to_object_type,
                        "to_id": rel.to_id,
                        "attrs": dict(rel.attrs or {}),
                    }
                )
        # Surplus inventories for consumed materials
        inventories = await self._visible_records(StructuredObjectType.INVENTORY.value)
        surplus: list[dict[str, Any]] = []
        for inv in inventories:
            attrs = dict(inv.attrs or {})
            qty = float(attrs.get("qty") or 0)
            if qty < 100:
                continue
            surplus.append(
                {
                    "object_id": inv.id,
                    "external_id": inv.external_id,
                    "title": inv.title,
                    "qty": qty,
                    "material_external_id": attrs.get("material_external_id"),
                    "factory_external_id": attrs.get("factory_external_id"),
                }
            )
            bundle.objects.append({"kind": "inventory", **surplus[-1]})
        short_inv = [
            {
                "object_id": inv.id,
                "external_id": inv.external_id,
                "qty": float((inv.attrs or {}).get("qty") or 0),
                "material_external_id": (inv.attrs or {}).get("material_external_id"),
                "factory_external_id": (inv.attrs or {}).get("factory_external_id"),
            }
            for inv in inventories
            if float((inv.attrs or {}).get("qty") or 0) < 100
        ]
        bundle.steps[-1] = {
            "step": "traverse",
            "status": "done",
            "detail": {
                "relations": neighbors,
                "surplus_inventory": surplus,
                "short_inventory": short_inv,
            },
        }
        lines = [f"【风险订单】共 {len(at_risk)} 条："]
        for o in at_risk:
            lines.append(
                f"- {o['external_id']} {o['title']} risk={o['risk_status']} "
                f"customer_order={o.get('customer_order_external_id')} "
                f"planned={o.get('planned_qty')} completed={o.get('completed_qty')} "
                f"due={o['due_date']} shortage={o['shortage_qty']} "
                f"material={o['material_external_id']} equipment={o.get('equipment_external_id')} "
                f"line={o.get('line_external_id')} factory={o['factory_external_id']}"
                + (f" anomaly={o['anomaly']}" if o.get("anomaly") else "")
            )
        if surplus:
            lines.append("【可调拨库存】")
            for s in surplus:
                lines.append(
                    f"- {s['external_id']} qty={s['qty']} "
                    f"material={s['material_external_id']} factory={s['factory_external_id']}"
                )
        if short_inv:
            lines.append("【缺料库存】")
            for s in short_inv:
                lines.append(
                    f"- {s['external_id']} qty={s['qty']} "
                    f"material={s['material_external_id']} factory={s['factory_external_id']}"
                )
        bundle.context_blocks.append("\n".join(lines))
        # stash for transfer
        bundle.steps.append(
            {
                "step": "transfer_candidates",
                "status": "done",
                "detail": {
                    "orders": at_risk,
                    "surplus": surplus,
                    "short": short_inv,
                },
            }
        )

    async def _run_transfer_plan(self, bundle: SemanticBundle, *, confirm: bool) -> None:
        cand = next(
            (s for s in bundle.steps if s.get("step") == "transfer_candidates"),
            None,
        )
        detail = (cand or {}).get("detail") or {}
        orders = list(detail.get("orders") or [])
        surplus = list(detail.get("surplus") or [])
        short = list(detail.get("short") or [])
        if not orders or not surplus or not short:
            bundle.context_blocks.append("【调拨】缺少源/目标库存或风险订单，无法给出方案。")
            return
        order = orders[0]
        mat = order.get("material_external_id")
        src = next((s for s in surplus if s.get("material_external_id") == mat), surplus[0])
        tgt = next((s for s in short if s.get("material_external_id") == mat), short[0])
        qty = float(order.get("shortage_qty") or 100)
        plan_text = (
            f"【调拨方案】从 {src['external_id']}({src.get('factory_external_id')}) "
            f"调拨 {qty} → {tgt['external_id']}({tgt.get('factory_external_id')}) "
            f"以缓解订单 {order['external_id']}；跨厂调拨需审批。"
        )
        bundle.context_blocks.append(plan_text)
        if not confirm:
            bundle.context_blocks.append(
                "如需执行，请回复「确认调拨」并确保具备动作权限；系统将走 ActionRuntime 审批链路。"
            )
            return
        if not _user_can_action(self.ctx.user):
            bundle.context_blocks.append("【调拨】当前用户无动作权限，仅提供方案不执行。")
            return
        runtime = ActionRuntime(self.session, self.ctx)
        payload = {
            "source_inventory_id": src["object_id"],
            "target_inventory_id": tgt["object_id"],
            "qty": qty,
            "production_order_id": order["object_id"],
            "material_external_id": mat,
            "note": f"qa semantic transfer {datetime.now(UTC).isoformat()}",
        }
        key = f"qa-transfer-{order['object_id']}-{src['object_id']}-{tgt['object_id']}-{qty}"
        preview = await runtime.execute(
            "material.transfer", payload, idempotency_key=f"{key}-preview", dry_run=True
        )
        if preview.status == "awaiting_approval":
            approval = await runtime.create_approval(
                "material.transfer", payload, acknowledge_risk=True
            )
            result = await runtime.execute(
                "material.transfer",
                payload,
                idempotency_key=key,
                approval_id=approval.id,
            )
        else:
            result = await runtime.execute(
                "material.transfer", payload, idempotency_key=key
            )
        bundle.action_result = {
            "status": result.status,
            "execution_id": result.execution_id,
            "result": result.result,
            "error": result.error,
        }
        bundle.context_blocks.append(
            f"【调拨执行】status={result.status} error={result.error} "
            f"result={result.result}"
        )
        bundle.steps.append(
            {
                "step": "invoke_action",
                "status": "done",
                "detail": bundle.action_result,
            }
        )


def _user_can_action(user: CurrentUser) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    checker = getattr(user, "has_permission", None)
    if callable(checker):
        return bool(checker("admin:retrieval"))
    perms = getattr(user, "permissions", None) or set()
    return "admin:retrieval" in perms


def semantic_prompt_appendix(bundle: SemanticBundle) -> str:
    if not bundle.hit:
        return ""
    return (
        "以下为系统从结构化 Ontology / 身份 / 库存镜像编排得到的业务事实，"
        "请据此回答；不要编造未给出的订单或库存数字。\n\n"
        + "\n\n".join(bundle.context_blocks)
    )
