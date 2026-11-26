"""Action Type registry + execute runtime (Wave C Task13–14)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationAppError
from app.core.metrics import ACTION_CALLS
from app.models.action import (
    ActionApproval,
    ActionExecution,
    ActionExecutionStatus,
    ActionRisk,
    ActionType,
    OntologyRule,
    RuleVerdict,
)
from app.ontology.rules import evaluate_rules
from app.ontology.state_machines import DeviceState, can_transition, normalize_device_status
from app.services.context import RequestContext
from app.models.entity_identity import CanonicalEntity
from app.models.entity_state_history import EntityStateHistory
from app.services.structured.identity import EntityIdentityService
from app.services.structured.state_history import EntityStateHistoryService

APPROVAL_TTL = timedelta(minutes=30)

# Built-in pilot actions (seeded per org on first list / ensure_builtins).
BUILTIN_ACTIONS: list[dict[str, Any]] = [
    {
        "name": "device.set_status",
        "description": "Set device standard status (MES-style write pilot)",
        "input_schema": {
            "type": "object",
            "required": ["canonical_id", "to_status"],
            "properties": {
                "canonical_id": {"type": "string"},
                "to_status": {
                    "type": "string",
                    "enum": [s.value for s in DeviceState if s != DeviceState.UNKNOWN],
                },
                "permit_maintenance": {"type": "boolean", "default": False},
            },
        },
        "preconditions": {"object_type": "device"},
        "risk": ActionRisk.HIGH.value,
        "systems": ["mes"],
    },
    {
        "name": "device.record_note",
        "description": "Attach an operator note to a device (low risk)",
        "input_schema": {
            "type": "object",
            "required": ["canonical_id", "note"],
            "properties": {
                "canonical_id": {"type": "string"},
                "note": {"type": "string", "maxLength": 500},
            },
        },
        "preconditions": {"object_type": "device"},
        "risk": ActionRisk.LOW.value,
        "systems": ["kb"],
    },
    {
        "name": "production.query_risk",
        "description": "Aggregate at-risk / delayed production orders and shortage hints",
        "input_schema": {
            "type": "object",
            "properties": {
                "factory_external_id": {"type": "string"},
                "risk_status": {
                    "type": "string",
                    "enum": ["at_risk", "delayed", "open"],
                },
            },
        },
        "preconditions": {"object_type": "production_order"},
        "risk": ActionRisk.LOW.value,
        "systems": ["erp", "mes"],
    },
    {
        "name": "material.transfer",
        "description": "Transfer inventory qty between mirrored warehouses (high risk)",
        "input_schema": {
            "type": "object",
            "required": ["source_inventory_id", "target_inventory_id", "qty"],
            "properties": {
                "source_inventory_id": {"type": "string"},
                "target_inventory_id": {"type": "string"},
                "qty": {"type": "number", "minimum": 0},
                "production_order_id": {"type": "string"},
                "material_external_id": {"type": "string"},
                "note": {"type": "string", "maxLength": 500},
            },
        },
        "preconditions": {"object_type": "inventory"},
        "risk": ActionRisk.HIGH.value,
        "systems": ["wms", "erp"],
    },
]

BUILTIN_RULES: list[dict[str, Any]] = [
    {
        "name": "mfg.transfer.require_identity",
        "priority": 10,
        "condition": {"action": "material.transfer", "has_identity_mapping": False},
        "verdict": RuleVerdict.DENY.value,
        "message": "material.transfer denied: material has no cross-system identity mapping",
    },
    {
        "name": "mfg.transfer.cross_plant_confirm",
        "priority": 20,
        "condition": {"action": "material.transfer", "cross_plant": True},
        "verdict": RuleVerdict.REQUIRE_CONFIRM.value,
        "message": "cross-plant material transfer requires confirmation",
    },
]


@dataclass
class ActionResult:
    status: str
    action_type: str
    execution_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    approval_id: str | None = None
    approval_expires_at: datetime | None = None
    rule_verdict: str | None = None


def _payload_hash(action_type: str, payload: dict[str, Any]) -> str:
    blob = json.dumps({"action": action_type, "input": payload}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ActionRuntime:
    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self.session = session
        self.ctx = ctx
        self.identity = EntityIdentityService(session)
        self.history = EntityStateHistoryService(session)

    @property
    def org_id(self) -> str:
        return self.ctx.user.org_id

    async def ensure_builtins(self) -> None:
        existing = {
            r.name
            for r in await self.session.scalars(
                select(ActionType).where(ActionType.org_id == self.org_id)
            )
        }
        for spec in BUILTIN_ACTIONS:
            if spec["name"] in existing:
                continue
            self.session.add(
                ActionType(
                    org_id=self.org_id,
                    name=spec["name"],
                    description=spec.get("description"),
                    input_schema=dict(spec.get("input_schema") or {}),
                    preconditions=dict(spec.get("preconditions") or {}),
                    risk=spec.get("risk") or ActionRisk.LOW.value,
                    systems=list(spec.get("systems") or []),
                    enabled=True,
                    created_by=self.ctx.user.id,
                )
            )
        existing_rules = {
            r.name
            for r in await self.session.scalars(
                select(OntologyRule).where(OntologyRule.org_id == self.org_id)
            )
        }
        for spec in BUILTIN_RULES:
            if spec["name"] in existing_rules:
                continue
            self.session.add(
                OntologyRule(
                    org_id=self.org_id,
                    name=spec["name"],
                    condition=dict(spec.get("condition") or {}),
                    verdict=spec["verdict"],
                    priority=int(spec.get("priority") or 100),
                    message=spec.get("message"),
                    enabled=True,
                    created_by=self.ctx.user.id,
                )
            )
        await self.session.flush()

    async def list_actions(self) -> list[ActionType]:
        await self.ensure_builtins()
        rows = await self.session.scalars(
            select(ActionType)
            .where(ActionType.org_id == self.org_id, ActionType.enabled.is_(True))
            .order_by(ActionType.name)
        )
        return list(rows)

    async def get_action(self, name: str) -> ActionType:
        await self.ensure_builtins()
        row = await self.session.scalar(
            select(ActionType).where(
                ActionType.org_id == self.org_id,
                ActionType.name == name.strip(),
                ActionType.enabled.is_(True),
            )
        )
        if row is None:
            raise NotFoundError("Action type not found")
        return row

    async def list_rules(self) -> list[OntologyRule]:
        await self.ensure_builtins()
        rows = await self.session.scalars(
            select(OntologyRule)
            .where(OntologyRule.org_id == self.org_id, OntologyRule.enabled.is_(True))
            .order_by(OntologyRule.priority, OntologyRule.name)
        )
        return list(rows)

    async def list_executions(self, *, limit: int = 50) -> list[ActionExecution]:
        rows = await self.session.scalars(
            select(ActionExecution)
            .where(ActionExecution.org_id == self.org_id)
            .order_by(ActionExecution.created_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def add_rule(
        self,
        *,
        name: str,
        condition: dict[str, Any],
        verdict: str,
        priority: int = 100,
        message: str | None = None,
    ) -> OntologyRule:
        if verdict not in {v.value for v in RuleVerdict}:
            raise ValidationAppError("Invalid rule verdict")
        row = OntologyRule(
            org_id=self.org_id,
            name=name.strip(),
            condition=dict(condition),
            verdict=verdict,
            priority=priority,
            message=message,
            enabled=True,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def create_approval(
        self,
        action_type: str,
        payload: dict[str, Any],
        *,
        acknowledge_risk: bool,
    ) -> ActionApproval:
        if not acknowledge_risk:
            raise ValidationAppError(
                "High-risk actions require acknowledge_risk=true",
                detail={"required": "acknowledge_risk"},
            )
        # Must match invoke_action: unknown / disabled action types cannot mint tokens.
        await self.get_action(action_type)
        row = ActionApproval(
            org_id=self.org_id,
            action_type=action_type.strip(),
            actor_id=self.ctx.user.id,
            payload_hash=_payload_hash(action_type.strip(), payload),
            expires_at=datetime.now(UTC) + APPROVAL_TTL,
            acknowledge_risk=True,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def execute(
        self,
        action_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        approval_id: str | None = None,
        on_behalf_of: str | None = None,
        dry_run: bool = False,
    ) -> ActionResult:
        started = time.perf_counter()
        action = await self.get_action(action_type)
        key = idempotency_key.strip()
        if not key:
            raise ValidationAppError("idempotency_key required")

        prior = await self.session.scalar(
            select(ActionExecution).where(
                ActionExecution.org_id == self.org_id,
                ActionExecution.idempotency_key == key,
            )
        )
        if prior is not None:
            return ActionResult(
                status=prior.status,
                action_type=action_type,
                execution_id=prior.id,
                result=dict(prior.result or {}),
                error=prior.error,
                approval_id=prior.approval_id,
            )

        # Schema-lite required keys
        required = list((action.input_schema or {}).get("required") or [])
        missing = [k for k in required if k not in payload or payload[k] in (None, "")]
        if missing:
            raise ValidationAppError("Action input missing required fields", detail={"missing": missing})

        context = await self._build_context(action_type, payload)
        rules = await self.list_rules()
        evaluation = evaluate_rules(rules, context)
        if evaluation.verdict == RuleVerdict.DENY.value:
            ACTION_CALLS.labels(action_type, "denied").inc()
            return await self._persist(
                action_type,
                payload,
                key,
                ActionExecutionStatus.DENIED.value,
                result={"rule": evaluation.rule_name},
                error=evaluation.message or "Denied by ontology rule",
                on_behalf_of=on_behalf_of,
                started=started,
                rule_verdict=evaluation.verdict,
            )

        if action.risk == ActionRisk.HIGH.value or evaluation.verdict == RuleVerdict.REQUIRE_CONFIRM.value:
            if not approval_id:
                if dry_run:
                    return ActionResult(
                        status=ActionExecutionStatus.AWAITING_APPROVAL.value,
                        action_type=action_type,
                        result={"needs_approval": True},
                        rule_verdict=evaluation.verdict,
                    )
                ACTION_CALLS.labels(action_type, "awaiting_approval").inc()
                return ActionResult(
                    status=ActionExecutionStatus.AWAITING_APPROVAL.value,
                    action_type=action_type,
                    result={"needs_approval": True, "hint": "create approval then retry"},
                    rule_verdict=evaluation.verdict,
                )
            approval = await self._consume_approval(approval_id, action_type, payload)
        else:
            approval = None

        if dry_run:
            return ActionResult(
                status="preview",
                action_type=action_type,
                result={"ok": True, "context": context},
                rule_verdict=evaluation.verdict,
            )

        try:
            result_body = await self._dispatch(action_type, payload, context)
        except Exception as exc:  # noqa: BLE001 — persist failure then re-raise path
            ACTION_CALLS.labels(action_type, "failed").inc()
            return await self._persist(
                action_type,
                payload,
                key,
                ActionExecutionStatus.FAILED.value,
                result={},
                error=str(exc),
                on_behalf_of=on_behalf_of,
                approval_id=approval.id if approval else None,
                started=started,
                rule_verdict=evaluation.verdict,
            )

        ACTION_CALLS.labels(action_type, "succeeded").inc()
        return await self._persist(
            action_type,
            payload,
            key,
            ActionExecutionStatus.SUCCEEDED.value,
            result=result_body,
            on_behalf_of=on_behalf_of,
            approval_id=approval.id if approval else None,
            started=started,
            rule_verdict=evaluation.verdict,
        )

    async def _consume_approval(
        self, approval_id: str, action_type: str, payload: dict[str, Any]
    ) -> ActionApproval:
        row = await self.session.scalar(
            select(ActionApproval).where(
                ActionApproval.org_id == self.org_id,
                ActionApproval.id == approval_id,
            )
        )
        if row is None:
            raise NotFoundError("Approval not found")
        if row.actor_id != self.ctx.user.id:
            raise PermissionDeniedError(detail={"reason": "approval_actor_mismatch"})
        if row.used_at is not None:
            raise ConflictError("Approval already used")
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            raise ValidationAppError("Approval expired")
        if row.action_type != action_type:
            raise ValidationAppError("Approval action_type mismatch")
        if row.payload_hash != _payload_hash(action_type, payload):
            raise ValidationAppError("Approval payload mismatch")
        if not row.acknowledge_risk:
            raise ValidationAppError("Approval missing acknowledge_risk")
        row.used_at = datetime.now(UTC)
        await self.session.flush()
        return row

    async def _build_context(
        self, action_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {"action": action_type, **payload}
        cid = payload.get("canonical_id")
        if cid:
            entity = await self.session.get(CanonicalEntity, cid)
            if entity is not None and entity.org_id == self.org_id:
                ctx["object"] = {
                    "canonical_id": entity.id,
                    "object_type": entity.object_type,
                    "display_name": entity.display_name,
                    "status": entity.status,
                }
                open_row = await self.session.scalar(
                    select(EntityStateHistory)
                    .where(
                        EntityStateHistory.org_id == self.org_id,
                        EntityStateHistory.canonical_id == entity.id,
                        EntityStateHistory.valid_to.is_(None),
                    )
                    .order_by(EntityStateHistory.valid_from.desc())
                )
                if open_row is not None:
                    ctx["object"]["standard_status"] = open_row.standard_status
        if "to_status" in payload:
            ctx["to_status"] = payload["to_status"]
            ctx["to"] = payload["to_status"]
        if action_type == "material.transfer":
            await self._enrich_transfer_context(ctx, payload)
        return ctx

    async def _enrich_transfer_context(
        self, ctx: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        from app.models import StructuredRecord

        src = await self.session.get(StructuredRecord, str(payload.get("source_inventory_id") or ""))
        tgt = await self.session.get(StructuredRecord, str(payload.get("target_inventory_id") or ""))
        if src is None or src.org_id != self.org_id or src.object_type != "inventory":
            raise ValidationAppError("source_inventory_id invalid")
        if tgt is None or tgt.org_id != self.org_id or tgt.object_type != "inventory":
            raise ValidationAppError("target_inventory_id invalid")
        src_attrs = dict(src.attrs or {})
        tgt_attrs = dict(tgt.attrs or {})
        src_fac = str(src_attrs.get("factory_external_id") or src.parent_external_id or "")
        tgt_fac = str(tgt_attrs.get("factory_external_id") or tgt.parent_external_id or "")
        ctx["cross_plant"] = bool(src_fac and tgt_fac and src_fac != tgt_fac)
        mat_ext = str(
            payload.get("material_external_id")
            or src_attrs.get("material_external_id")
            or tgt_attrs.get("material_external_id")
            or ""
        ).strip()
        ctx["material_external_id"] = mat_ext or None
        has_identity = False
        if mat_ext:
            mat_row = await self.session.scalar(
                select(StructuredRecord).where(
                    StructuredRecord.org_id == self.org_id,
                    StructuredRecord.object_type == "material",
                    StructuredRecord.external_id == mat_ext,
                )
            )
            if mat_row is not None:
                canon = await self.identity.get_by_structured(
                    self.org_id,
                    structured_object_type="material",
                    structured_object_id=mat_row.id,
                )
                if canon is not None:
                    ids = await self.identity.list_identifiers(self.org_id, canon.id)
                    has_identity = len(ids) >= 2
        ctx["has_identity_mapping"] = has_identity
        ctx["source_factory"] = src_fac or None
        ctx["target_factory"] = tgt_fac or None
        ctx["source_qty"] = float(src_attrs.get("qty") or 0)
        ctx["target_qty"] = float(tgt_attrs.get("qty") or 0)

    async def _dispatch(
        self, action_type: str, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        if action_type == "device.set_status":
            return await self._set_device_status(payload, context)
        if action_type == "device.record_note":
            return {
                "canonical_id": payload["canonical_id"],
                "note": str(payload["note"]).strip(),
                "recorded": True,
            }
        if action_type == "production.query_risk":
            return await self._query_production_risk(payload)
        if action_type == "material.transfer":
            return await self._transfer_material(payload, context)
        raise ValidationAppError(
            f"No handler for action {action_type}",
            detail={"hint": "custom ActionTypes need a built-in handler name"},
        )

    async def _query_production_risk(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.models import StructuredRecord

        risk_filter = (payload.get("risk_status") or "").strip().lower() or None
        factory = (payload.get("factory_external_id") or "").strip() or None
        rows = list(
            await self.session.scalars(
                select(StructuredRecord).where(
                    StructuredRecord.org_id == self.org_id,
                    StructuredRecord.object_type == "production_order",
                )
            )
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            attrs = dict(row.attrs or {})
            status = str(attrs.get("risk_status") or row.status or "").lower()
            if risk_filter:
                if status != risk_filter:
                    continue
            elif status not in {"at_risk", "delayed"}:
                continue
            if factory and str(attrs.get("factory_external_id") or "") != factory:
                continue
            items.append(
                {
                    "object_id": row.id,
                    "external_id": row.external_id,
                    "title": row.title,
                    "status": row.status,
                    "risk_status": status,
                    "due_date": attrs.get("due_date"),
                    "material_external_id": attrs.get("material_external_id"),
                    "required_qty": attrs.get("required_qty"),
                    "shortage_qty": attrs.get("shortage_qty"),
                    "factory_external_id": attrs.get("factory_external_id"),
                    "line_external_id": attrs.get("line_external_id"),
                }
            )
        return {"count": len(items), "items": items}

    async def _transfer_material(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        from app.models import StructuredRecord
        from app.services.audit_service import AuditService

        qty = float(payload["qty"])
        if qty <= 0:
            raise ValidationAppError("qty must be > 0")
        src = await self.session.get(StructuredRecord, str(payload["source_inventory_id"]))
        tgt = await self.session.get(StructuredRecord, str(payload["target_inventory_id"]))
        if src is None or src.org_id != self.org_id or src.object_type != "inventory":
            raise ValidationAppError("source_inventory_id invalid")
        if tgt is None or tgt.org_id != self.org_id or tgt.object_type != "inventory":
            raise ValidationAppError("target_inventory_id invalid")

        from app.services.structured.access import StructuredAccess

        acl = StructuredAccess(self.session)
        await acl.require_write(self.ctx.user, src.id)
        await acl.require_write(self.ctx.user, tgt.id)

        src_attrs = dict(src.attrs or {})
        tgt_attrs = dict(tgt.attrs or {})
        src_qty = float(src_attrs.get("qty") or 0)
        if src_qty < qty:
            raise ValidationAppError(
                "insufficient source inventory",
                detail={"source_qty": src_qty, "requested": qty},
            )
        src_attrs["qty"] = src_qty - qty
        tgt_attrs["qty"] = float(tgt_attrs.get("qty") or 0) + qty
        src.attrs = src_attrs
        tgt.attrs = tgt_attrs
        if src_attrs["qty"] <= 50:
            src.status = "low"
        elif src.status == "low":
            src.status = "ok"
        if tgt_attrs["qty"] > 50 and tgt.status == "low":
            tgt.status = "ok"

        po_update: dict[str, Any] | None = None
        po_id = (payload.get("production_order_id") or "").strip() or None
        if po_id:
            po = await self.session.get(StructuredRecord, po_id)
            if po is not None and po.org_id == self.org_id and po.object_type == "production_order":
                po_attrs = dict(po.attrs or {})
                shortage = float(po_attrs.get("shortage_qty") or 0)
                new_shortage = max(0.0, shortage - qty)
                po_attrs["shortage_qty"] = new_shortage
                if new_shortage <= 0:
                    po_attrs["risk_status"] = "open"
                    po.status = "open"
                else:
                    po_attrs["risk_status"] = po_attrs.get("risk_status") or "at_risk"
                po.attrs = po_attrs
                po_update = {
                    "object_id": po.id,
                    "external_id": po.external_id,
                    "shortage_qty": new_shortage,
                    "risk_status": po_attrs.get("risk_status"),
                    "status": po.status,
                }

        await self.session.flush()
        result = {
            "source_inventory_id": src.id,
            "target_inventory_id": tgt.id,
            "qty": qty,
            "source_qty_after": src_attrs["qty"],
            "target_qty_after": tgt_attrs["qty"],
            "cross_plant": bool(context.get("cross_plant")),
            "production_order": po_update,
            "note": (payload.get("note") or None),
        }
        await AuditService(self.session).record(
            self.ctx.audit,
            "ontology.action",
            resource_type="action",
            resource_id="material.transfer",
            after={
                "action_type": "material.transfer",
                "payload": {
                    "source_inventory_id": src.id,
                    "target_inventory_id": tgt.id,
                    "qty": qty,
                    "production_order_id": po_id,
                },
                "result": {
                    "source_qty_after": src_attrs["qty"],
                    "target_qty_after": tgt_attrs["qty"],
                    "cross_plant": bool(context.get("cross_plant")),
                },
            },
        )
        return result

    async def _set_device_status(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        cid = str(payload["canonical_id"])
        to_raw = str(payload["to_status"])
        permit = bool(payload.get("permit_maintenance"))
        obj = context.get("object") or {}
        from_status = obj.get("standard_status") or DeviceState.UNKNOWN.value
        to_norm = normalize_device_status(to_raw)
        if not can_transition(
            from_status, to_norm.standard_status, permit=permit, raise_on_illegal=True
        ):
            raise ValidationAppError("Illegal device transition")
        row = await self.history.record_status(
            self.org_id, cid, to_norm.standard_status.value, source="action"
        )
        return {
            "canonical_id": cid,
            "from_status": from_status,
            "to_status": to_norm.standard_status.value,
            "status_label": to_norm.status_label,
            "history_id": row.id,
        }

    async def _persist(
        self,
        action_type: str,
        payload: dict[str, Any],
        key: str,
        status: str,
        *,
        result: dict[str, Any],
        error: str | None = None,
        on_behalf_of: str | None = None,
        approval_id: str | None = None,
        started: float,
        rule_verdict: str | None = None,
    ) -> ActionResult:
        latency = (time.perf_counter() - started) * 1000
        row = ActionExecution(
            org_id=self.org_id,
            action_type=action_type,
            actor_id=self.ctx.user.id,
            on_behalf_of=on_behalf_of,
            input=dict(payload),
            status=status,
            result={**result, "rule_verdict": rule_verdict},
            error=error,
            idempotency_key=key,
            approval_id=approval_id,
            attempt=1,
            compensated=False,
            latency_ms=latency,
        )
        self.session.add(row)
        await self.session.flush()
        return ActionResult(
            status=status,
            action_type=action_type,
            execution_id=row.id,
            result=dict(row.result or {}),
            error=error,
            approval_id=approval_id,
            rule_verdict=rule_verdict,
        )
