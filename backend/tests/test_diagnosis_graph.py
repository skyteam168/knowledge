"""O3.2 diagnosis directed expansion + ACL gate on KO neighbors."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KnowledgeBase,
    KnowledgeObject,
    KoEntry,
    KoRelation,
    KoRelationType,
    KoStatus,
    KoVersion,
    KoVersionStatus,
)
from app.models.base import new_id
from app.retrieval.diagnosis import expand_diagnosis_graph
from app.retrieval.object_graph import ObjectGraphSeed
from app.services.authz import CurrentUser
from app.services.authz.principals import Principals
from app.services.knowledge.ko_access import KoCheck


def _user(org_id: str) -> CurrentUser:
    uid = new_id()
    return CurrentUser(
        id=uid,
        org_id=org_id,
        username="diag",
        display_name="Diag",
        principals=Principals(org_id, uid),
        permissions=frozenset({"*"}),
    )


async def _published_ko(
    session: AsyncSession, *, org_id: str, kb_id: str, title: str
) -> KnowledgeObject:
    ko = KnowledgeObject(
        id=new_id(),
        org_id=org_id,
        kb_id=kb_id,
        ko_type="faq",
        title=title,
        question=f"Q:{title}",
        variants=[],
        answer=f"A:{title}",
        sources=[],
        status=KoStatus.PUBLISHED.value,
        version=1,
        published_version=1,
        acl_inherit=True,
        gap_ids=[],
        ai_draft={},
        conflicts=[],
        origin="manual",
    )
    session.add(ko)
    await session.flush()
    session.add(
        KoVersion(
            id=new_id(),
            org_id=org_id,
            ko_id=ko.id,
            version=1,
            ko_type=ko.ko_type,
            title=ko.title,
            question=ko.question,
            variants=[],
            answer=ko.answer,
            sources=[],
            status=KoVersionStatus.PUBLISHED.value,
        )
    )
    session.add(
        KoEntry(
            id=new_id(),
            org_id=org_id,
            ko_id=ko.id,
            ko_version=1,
            seq=0,
            question=ko.question,
        )
    )
    await session.flush()
    return ko


async def test_diagnosis_keeps_readable_and_drops_denied(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id = "org-diag"
    kb = KnowledgeBase(id=new_id(), org_id=org_id, name="diag-kb", visibility="org")
    session.add(kb)
    await session.flush()
    seed = await _published_ko(session, org_id=org_id, kb_id=kb.id, title="症状")
    neighbor = await _published_ko(session, org_id=org_id, kb_id=kb.id, title="处置")
    # mitigates is stored policy → defect; diagnosis walks inbound from symptom.
    session.add(
        KoRelation(
            id=new_id(),
            org_id=org_id,
            from_ko_id=neighbor.id,
            to_ko_id=seed.id,
            relation_type=KoRelationType.MITIGATES.value,
        )
    )
    await session.commit()

    user = _user(org_id)
    allowed = await expand_diagnosis_graph(
        session, user, ko_seeds=[seed.id], max_hops=1, limit=10
    )
    assert {n.ko_id for n in allowed.ko_neighbors} == {neighbor.id}
    assert allowed.dropped_acl_ko_ids == []

    async def _deny(_user: CurrentUser, ko_ids: list[str]) -> KoCheck:
        check = KoCheck()
        # pretend neighbor is not readable
        return check

    monkeypatch.setattr(
        "app.retrieval.diagnosis.KoAccess.live_objects",
        AsyncMock(side_effect=_deny),
    )
    denied = await expand_diagnosis_graph(
        session, user, ko_seeds=[seed.id], max_hops=1, limit=10
    )
    assert denied.ko_neighbors == []
    assert neighbor.id in denied.dropped_acl_ko_ids


async def test_diagnosis_object_outbound_chain(session: AsyncSession) -> None:
    from app.models import ObjectRelation, ObjectRelationType

    org_id = "org-diag-obj"
    equip_id, fm_id = new_id(), new_id()
    session.add(
        ObjectRelation(
            id=new_id(),
            org_id=org_id,
            relation_type=ObjectRelationType.HAS_FAILURE_MODE.value,
            from_kind="structured",
            from_id=equip_id,
            from_object_type="equipment",
            to_kind="structured",
            to_id=fm_id,
            to_object_type="failure_mode",
        )
    )
    await session.commit()
    user = _user(org_id)
    out = await expand_diagnosis_graph(
        session,
        user,
        object_seeds=[ObjectGraphSeed("structured", equip_id, "equipment")],
        max_hops=1,
    )
    assert {n.object_id for n in out.object_neighbors} == {fm_id}
