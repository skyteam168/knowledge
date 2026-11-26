"""Deterministic manufacturing Ontology acceptance gate (CI)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.authz import CurrentUser
from app.services.authz.principals import Principals
from app.services.chat.semantic_ops import (
    SemanticKind,
    SemanticOpsService,
    detect_semantic_plan,
)
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.accept_mfg import MANUAL_CHECKLIST, run_mfg_acceptance
from app.services.structured.seed_mfg import PO_AT_RISK, seed_mfg
from tests.factories import make_org, make_user


@pytest.fixture
async def accept_actor(session: AsyncSession):
    org = await make_org(session, code="mfg-accept")
    db_user = await make_user(session, org, username="accept-alice")
    await session.commit()
    user = CurrentUser(
        id=db_user.id,
        org_id=org.id,
        username=db_user.username,
        display_name=db_user.username,
        principals=Principals(org.id, db_user.id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return org, user


async def test_run_mfg_acceptance_green(session: AsyncSession, accept_actor):
    org, user = accept_actor
    report = await run_mfg_acceptance(session, org_id=org.id, user=user, reseeds=True)
    await session.commit()
    assert report.ok, report.to_dict()
    names = {s.name for s in report.steps}
    assert {
        "seed_mfg",
        "identity_resolve",
        "query_traverse",
        "actions_transfer_audit",
        "semantic_intent_gates",
    }.issubset(names)
    assert all(s.ok for s in report.steps)
    assert len(report.manual_checklist) == len(MANUAL_CHECKLIST)


async def test_semantic_nl_regression_cases(session: AsyncSession, accept_actor):
    """Lightweight NL gates: intent + fixture-backed semantic bundle (no LLM)."""
    org, user = accept_actor
    await seed_mfg(session, org.id)
    await session.commit()
    ctx = RequestContext(
        user,
        AuditContext(org_id=user.org_id, actor_id=user.id, actor_name=user.username),
    )

    cases = [
        (
            "帮我检查今天有哪些生产订单可能延期；若有风险，分析原因并给出调拨方案",
            SemanticKind.PRODUCTION_RISK,
            True,
        ),
        (
            "RM-PET-150D vs YN-RM-150 是不是同一个料",
            SemanticKind.MATERIAL_IDENTITY,
            True,
        ),
        ("确认调拨越南缺料", SemanticKind.MATERIAL_TRANSFER, True),
        ("织机断纱怎么检修", SemanticKind.NONE, False),
    ]
    for text, kind, expect_hit in cases:
        plan = detect_semantic_plan(text)
        assert plan.kind == kind, text
        if kind == SemanticKind.NONE:
            continue
        bundle = await SemanticOpsService(session, ctx).run(text, plan)
        assert bundle.hit is expect_hit
        if kind == SemanticKind.PRODUCTION_RISK:
            assert any(
                o.get("external_id") == PO_AT_RISK for o in bundle.objects if isinstance(o, dict)
            )
            assert any("风险" in b or "调拨" in b for b in bundle.context_blocks)
        if kind == SemanticKind.MATERIAL_IDENTITY:
            assert any("Canonical" in b or "身份" in b for b in bundle.context_blocks)
