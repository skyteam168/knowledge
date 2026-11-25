"""Wave C: ontology rules + Action runtime + approval + idempotency."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models.action import ActionExecutionStatus, ActionRisk, RuleVerdict
from app.ontology.rules import evaluate_rules
from app.ontology.state_machines import DeviceState
from app.services.action.runtime import ActionRuntime
from app.services.context import AuditContext, RequestContext
from app.services.structured.identity import EntityIdentityService
from app.services.structured.state_history import EntityStateHistoryService
from tests.factories import make_org, make_user


@pytest.fixture
async def org_user(session: AsyncSession):
    org = await make_org(session, code="action-org")
    user = await make_user(session, org, username="action-actor")
    return org, user


def _runtime(session: AsyncSession, user) -> ActionRuntime:
    ctx = RequestContext(
        user,
        AuditContext(org_id=user.org_id, actor_id=user.id, actor_name=user.username),
    )
    return ActionRuntime(session, ctx)


def test_evaluate_rules_deny_before_allow() -> None:
    rules = [
        SimpleNamespace(
            name="deny-maint",
            priority=10,
            enabled=True,
            condition={"action": "device.set_status", "to": "MAINTENANCE"},
            verdict=RuleVerdict.DENY.value,
            message="no maintenance",
        ),
        SimpleNamespace(
            name="allow-all",
            priority=100,
            enabled=True,
            condition={},
            verdict=RuleVerdict.ALLOW.value,
            message=None,
        ),
    ]
    out = evaluate_rules(
        rules,
        {"action": "device.set_status", "to_status": "MAINTENANCE"},
    )
    assert out.verdict == RuleVerdict.DENY.value
    assert out.rule_name == "deny-maint"


def test_evaluate_rules_require_confirm_on_when() -> None:
    rules = [
        SimpleNamespace(
            name="confirm-running",
            priority=5,
            enabled=True,
            condition={
                "action": "device.set_status",
                "when": {"standard_status": "RUNNING"},
                "to": "STOPPED",
            },
            verdict=RuleVerdict.REQUIRE_CONFIRM.value,
            message="confirm stop",
        ),
    ]
    out = evaluate_rules(
        rules,
        {
            "action": "device.set_status",
            "to_status": "STOPPED",
            "object": {"standard_status": "RUNNING"},
        },
    )
    assert out.verdict == RuleVerdict.REQUIRE_CONFIRM.value


async def test_list_actions_seeds_builtins(
    session: AsyncSession, org_user
) -> None:
    _org, user = org_user
    rt = _runtime(session, user)
    rows = await rt.list_actions()
    names = {r.name for r in rows}
    assert "device.set_status" in names
    assert "device.record_note" in names
    high = next(r for r in rows if r.name == "device.set_status")
    assert high.risk == ActionRisk.HIGH.value


async def test_low_risk_action_succeeds_and_is_idempotent(
    session: AsyncSession, org_user
) -> None:
    org, user = org_user
    identity = EntityIdentityService(session)
    entity = await identity.create_canonical(
        org.id, object_type="device", display_name="note-device"
    )
    rt = _runtime(session, user)
    payload = {"canonical_id": entity.id, "note": "operator check"}
    first = await rt.execute(
        "device.record_note",
        payload,
        idempotency_key="note-1",
    )
    assert first.status == ActionExecutionStatus.SUCCEEDED.value
    assert first.execution_id
    second = await rt.execute(
        "device.record_note",
        payload,
        idempotency_key="note-1",
    )
    assert second.execution_id == first.execution_id
    assert second.status == first.status


async def test_high_risk_requires_approval_then_updates_state(
    session: AsyncSession, org_user
) -> None:
    org, user = org_user
    identity = EntityIdentityService(session)
    history = EntityStateHistoryService(session)
    entity = await identity.create_canonical(
        org.id, object_type="device", display_name="status-device"
    )
    await history.record_status(org.id, entity.id, "0", source="mes")  # RUNNING

    rt = _runtime(session, user)
    payload = {"canonical_id": entity.id, "to_status": "STOPPED"}

    blocked = await rt.execute(
        "device.set_status",
        payload,
        idempotency_key="set-1",
    )
    assert blocked.status == ActionExecutionStatus.AWAITING_APPROVAL.value
    assert blocked.execution_id is None

    with pytest.raises(ValidationAppError):
        await rt.create_approval("device.set_status", payload, acknowledge_risk=False)

    approval = await rt.create_approval(
        "device.set_status", payload, acknowledge_risk=True
    )
    done = await rt.execute(
        "device.set_status",
        payload,
        idempotency_key="set-1b",
        approval_id=approval.id,
    )
    assert done.status == ActionExecutionStatus.SUCCEEDED.value
    assert done.result.get("to_status") == DeviceState.STOPPED.value

    rows = await history.list_in_window(
        org.id,
        entity.id,
        window_from=datetime(2000, 1, 1, tzinfo=UTC),
        window_to=datetime(2100, 1, 1, tzinfo=UTC),
    )
    open_row = rows[-1]
    assert open_row.standard_status == DeviceState.STOPPED.value
    assert open_row.valid_to is None


async def test_rule_deny_persists_denied_execution(
    session: AsyncSession, org_user
) -> None:
    org, user = org_user
    identity = EntityIdentityService(session)
    history = EntityStateHistoryService(session)
    entity = await identity.create_canonical(
        org.id, object_type="device", display_name="deny-device"
    )
    await history.record_status(org.id, entity.id, "0", source="mes")

    rt = _runtime(session, user)
    await rt.add_rule(
        name="block-idle",
        condition={"action": "device.set_status", "to": "IDLE"},
        verdict=RuleVerdict.DENY.value,
        priority=1,
        message="idle blocked",
    )
    out = await rt.execute(
        "device.set_status",
        {"canonical_id": entity.id, "to_status": "IDLE"},
        idempotency_key="deny-1",
    )
    assert out.status == ActionExecutionStatus.DENIED.value
    assert out.error and "idle blocked" in out.error
