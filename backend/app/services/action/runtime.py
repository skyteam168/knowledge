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

# Built-in pilot actions (seeded per org on first list if empty).
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
        rows = await self.session.scalars(
            select(OntologyRule)
            .where(OntologyRule.org_id == self.org_id, OntologyRule.enabled.is_(True))
            .order_by(OntologyRule.priority, OntologyRule.name)
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
        row = ActionApproval(
            org_id=self.org_id,
            action_type=action_type,
            actor_id=self.ctx.user.id,
            payload_hash=_payload_hash(action_type, payload),
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
        return ctx

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
        raise ValidationAppError(f"No handler for action {action_type}")

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
