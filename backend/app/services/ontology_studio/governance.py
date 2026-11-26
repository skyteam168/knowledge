"""Admin CRUD for ontology_rules and action_types."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.action import ActionType, OntologyRule, RuleVerdict
from app.schemas.ontology_governance import (
    ActionTypeCreate,
    ActionTypeOut,
    ActionTypeUpdate,
    OntologyRuleCreate,
    OntologyRuleOut,
    OntologyRuleUpdate,
)
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext

RESOURCE_RULE = "ontology_rule"
RESOURCE_ACTION = "action_type"


def _reject_empty_restrictive_condition(condition: dict, verdict: str) -> None:
    """Empty {} matches every action; forbid that for deny / require_confirm."""
    v = (verdict or "").strip().lower()
    if v in {RuleVerdict.DENY.value, RuleVerdict.REQUIRE_CONFIRM.value} and not condition:
        raise ValidationAppError(
            "deny/require_confirm rules must set a non-empty condition "
            '(e.g. {"action": "material.transfer"}); empty {} matches all actions',
            detail={"verdict": v, "condition": condition},
        )


class OntologyGovernanceService(BaseService):
    def __init__(
        self, session: AsyncSession, ctx: RequestContext, authz_cache: AuthzCache
    ) -> None:
        super().__init__(session, ctx, authz_cache)

    async def list_rules(self) -> list[OntologyRuleOut]:
        from app.services.action.runtime import ActionRuntime

        await ActionRuntime(self.session, self.ctx).ensure_builtins()
        rows = await self.session.scalars(
            select(OntologyRule)
            .where(OntologyRule.org_id == self.org_id)
            .order_by(OntologyRule.priority.asc(), OntologyRule.name.asc())
        )
        return [self._rule_out(r) for r in rows]

    async def create_rule(self, data: OntologyRuleCreate) -> OntologyRuleOut:
        condition = dict(data.condition or {})
        verdict = data.verdict.strip().lower()
        _reject_empty_restrictive_condition(condition, verdict)
        row = OntologyRule(
            org_id=self.org_id,
            name=data.name.strip(),
            description=(data.description or "").strip() or None,
            priority=data.priority,
            enabled=data.enabled,
            condition=condition,
            verdict=verdict,
            message=(data.message or "").strip() or None,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        out = self._rule_out(row)
        await self.audit.record(
            self.audit_ctx,
            "ontology_rule.create",
            RESOURCE_RULE,
            row.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def patch_rule(self, rule_id: str, data: OntologyRuleUpdate) -> OntologyRuleOut:
        row = await self._get_rule(rule_id)
        before = self._rule_out(row).model_dump(mode="json")
        if data.name is not None:
            row.name = data.name.strip()
        if data.description is not None:
            row.description = data.description.strip() or None
        if data.priority is not None:
            row.priority = data.priority
        if data.enabled is not None:
            row.enabled = data.enabled
        if data.condition is not None:
            row.condition = dict(data.condition)
        if data.verdict is not None:
            row.verdict = data.verdict.strip().lower()
        if data.message is not None:
            row.message = data.message.strip() or None
        _reject_empty_restrictive_condition(
            dict(row.condition or {}), str(row.verdict or "")
        )
        await self.session.flush()
        out = self._rule_out(row)
        await self.audit.record(
            self.audit_ctx,
            "ontology_rule.update",
            RESOURCE_RULE,
            row.id,
            before,
            out.model_dump(mode="json"),
        )
        return out

    async def list_action_types(self, *, enabled_only: bool = False) -> list[ActionTypeOut]:
        from app.services.action.runtime import ActionRuntime

        await ActionRuntime(self.session, self.ctx).ensure_builtins()
        stmt = select(ActionType).where(ActionType.org_id == self.org_id)
        if enabled_only:
            stmt = stmt.where(ActionType.enabled.is_(True))
        rows = await self.session.scalars(stmt.order_by(ActionType.name.asc()))
        return [self._action_out(r) for r in rows]

    async def create_action_type(self, data: ActionTypeCreate) -> ActionTypeOut:
        existing = await self.session.scalar(
            select(ActionType).where(
                ActionType.org_id == self.org_id,
                ActionType.name == data.name.strip(),
            )
        )
        if existing is not None:
            raise ConflictError("Action type name already exists")
        row = ActionType(
            org_id=self.org_id,
            name=data.name.strip(),
            description=(data.description or "").strip() or None,
            input_schema=dict(data.input_schema or {}),
            preconditions=dict(data.preconditions or {}),
            risk=data.risk.strip().lower(),
            systems=list(data.systems or []),
            enabled=data.enabled,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        out = self._action_out(row)
        await self.audit.record(
            self.audit_ctx,
            "action_type.create",
            RESOURCE_ACTION,
            row.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def patch_action_type(
        self, action_id: str, data: ActionTypeUpdate
    ) -> ActionTypeOut:
        row = await self._get_action(action_id)
        before = self._action_out(row).model_dump(mode="json")
        if data.description is not None:
            row.description = data.description.strip() or None
        if data.input_schema is not None:
            row.input_schema = dict(data.input_schema)
        if data.preconditions is not None:
            row.preconditions = dict(data.preconditions)
        if data.risk is not None:
            row.risk = data.risk.strip().lower()
        if data.systems is not None:
            row.systems = list(data.systems)
        if data.enabled is not None:
            row.enabled = data.enabled
        await self.session.flush()
        out = self._action_out(row)
        await self.audit.record(
            self.audit_ctx,
            "action_type.update",
            RESOURCE_ACTION,
            row.id,
            before,
            out.model_dump(mode="json"),
        )
        return out

    async def _get_rule(self, rule_id: str) -> OntologyRule:
        row = await self.session.scalar(
            select(OntologyRule).where(
                OntologyRule.org_id == self.org_id,
                OntologyRule.id == rule_id,
            )
        )
        if row is None:
            raise NotFoundError("Ontology rule not found")
        return row

    async def _get_action(self, action_id: str) -> ActionType:
        row = await self.session.scalar(
            select(ActionType).where(
                ActionType.org_id == self.org_id,
                ActionType.id == action_id,
            )
        )
        if row is None:
            raise NotFoundError("Action type not found")
        return row

    @staticmethod
    def _rule_out(row: OntologyRule) -> OntologyRuleOut:
        return OntologyRuleOut(
            id=row.id,
            name=row.name,
            description=row.description,
            priority=row.priority,
            enabled=row.enabled,
            condition=dict(row.condition or {}),
            verdict=row.verdict,
            message=row.message,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _action_out(row: ActionType) -> ActionTypeOut:
        return ActionTypeOut(
            id=row.id,
            name=row.name,
            description=row.description,
            input_schema=dict(row.input_schema or {}),
            preconditions=dict(row.preconditions or {}),
            risk=row.risk,
            systems=[str(s) for s in (row.systems or [])],
            enabled=row.enabled,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
