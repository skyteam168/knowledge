"""Rules + ActionType admin CRUD."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models.base import new_id
from app.schemas.ontology_governance import (
    ActionTypeCreate,
    ActionTypeUpdate,
    OntologyRuleCreate,
    OntologyRuleUpdate,
)
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.governance import OntologyGovernanceService


ORG = "org-gov"


def _ctx(org_id: str = ORG) -> RequestContext:
    uid = new_id()
    user = CurrentUser(
        id=uid,
        org_id=org_id,
        username="steward",
        display_name="Steward",
        principals=Principals(org_id, uid),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user, AuditContext(org_id=org_id, actor_id=uid, actor_name="Steward")
    )


@pytest.fixture
def gov(session: AsyncSession) -> OntologyGovernanceService:
    return OntologyGovernanceService(
        session, _ctx(), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


async def test_rules_priority_and_action_disable(
    gov: OntologyGovernanceService,
) -> None:
    r1 = await gov.create_rule(
        OntologyRuleCreate(
            name="deny-running-to-offline",
            priority=10,
            condition={"action": "device.set_status"},
            verdict="deny",
        )
    )
    r2 = await gov.create_rule(
        OntologyRuleCreate(
            name="allow-default",
            priority=100,
            condition={},
            verdict="allow",
        )
    )
    rules = await gov.list_rules()
    assert [r.id for r in rules[:2]] == [r1.id, r2.id]

    await gov.patch_rule(r1.id, OntologyRuleUpdate(enabled=False))
    assert (await gov.list_rules())[0].enabled is False

    at = await gov.create_action_type(
        ActionTypeCreate(
            name="device.set_status",
            risk="medium",
            systems=["mes"],
            input_schema={"type": "object"},
        )
    )
    assert at.enabled is True
    await gov.patch_action_type(at.id, ActionTypeUpdate(enabled=False))
    enabled = await gov.list_action_types(enabled_only=True)
    assert all(a.name != "device.set_status" for a in enabled)
    all_types = await gov.list_action_types()
    assert any(a.name == "device.set_status" and not a.enabled for a in all_types)
