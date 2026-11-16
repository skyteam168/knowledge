"""Open platform entity.read / graph.traverse service behaviour."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import NotFoundError
from app.models import (
    KnowledgeBase,
    KoEntry,
    KoRelation,
    KoRelationType,
    KoStatus,
    KoVersion,
    KoVersionStatus,
    KnowledgeObject,
)
from app.models.base import new_id
from app.schemas.open_api import OpenEntityReadIn, OpenGraphTraverseIn
from app.schemas.structured import StructuredSourceCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.entity_service import OpenEntityService
from app.services.structured.seed_equipment import seed_equipment
from app.services.structured.service import StructuredService


ORG = "org-open-entity"


def _ctx(org_id: str = ORG) -> RequestContext:
    user_id = new_id()
    user = CurrentUser(
        id=user_id,
        org_id=org_id,
        username="agent-tester",
        display_name="Agent",
        principals=Principals(org_id, user_id),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user,
        AuditContext(org_id=org_id, actor_id=user.id, actor_name=user.display_name),
    )


def _caller(user: CurrentUser, kb_ids: frozenset[str]) -> ApiCaller:
    return ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=user.org_id,
        name="test-agent",
        kb_ids=kb_ids,
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=user,
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


async def test_entity_read_by_structured_external_id(session: AsyncSession) -> None:
    ctx = _ctx()
    cache = AuthzCache(MemoryCache(), ttl_seconds=60)
    kb = KnowledgeBase(id=new_id(), org_id=ORG, name="entity-seed-kb", visibility="org")
    session.add(kb)
    await session.flush()
    await seed_equipment(session, ORG)
    await session.commit()
    svc = OpenEntityService(session, ctx, cache, _caller(ctx.user, frozenset({kb.id})))
    out = await svc.entity_read(
        OpenEntityReadIn(object_type="device", external_id="EQ-LOOM-01")
    )
    assert out.mirror is not None
    assert out.mirror.label == "1号飞织机"
    assert out.terminology is not None
    assert out.terminology.canonical_name == "织机"
    assert len(out.knowledge_objects) >= 1
    seed_ko = out.knowledge_objects[0].id
    graph = await svc.graph_traverse(OpenGraphTraverseIn(ko_id=seed_ko, max_hops=1))
    assert graph.seed.id == seed_ko
    assert len(graph.neighbors) >= 1


async def test_entity_read_by_name(session: AsyncSession) -> None:
    ctx = _ctx()
    cache = AuthzCache(MemoryCache(), ttl_seconds=60)
    await seed_equipment(session, ORG)
    await session.commit()
    svc = OpenEntityService(session, ctx, cache, _caller(ctx.user, frozenset()))
    out = await svc.entity_read(OpenEntityReadIn(name="飞织机"))
    assert out.terminology is not None
    assert out.terminology.canonical_name == "织机"


async def test_graph_traverse_filters_ungranted_kb(session: AsyncSession) -> None:
    ctx = _ctx()
    cache = AuthzCache(MemoryCache(), ttl_seconds=60)
    kb_ok = KnowledgeBase(id=new_id(), org_id=ORG, name="ok-kb", visibility="org")
    kb_deny = KnowledgeBase(id=new_id(), org_id=ORG, name="deny-kb", visibility="org")
    session.add_all([kb_ok, kb_deny])
    await session.flush()
    a = await _published_ko(session, org_id=ORG, kb_id=kb_ok.id, title="Seed-A")
    b = await _published_ko(session, org_id=ORG, kb_id=kb_ok.id, title="Neigh-B")
    c = await _published_ko(session, org_id=ORG, kb_id=kb_deny.id, title="Secret-C")
    session.add(
        KoRelation(
            id=new_id(),
            org_id=ORG,
            from_ko_id=a.id,
            to_ko_id=b.id,
            relation_type=KoRelationType.RELATED_TO.value,
        )
    )
    session.add(
        KoRelation(
            id=new_id(),
            org_id=ORG,
            from_ko_id=a.id,
            to_ko_id=c.id,
            relation_type=KoRelationType.RELATED_TO.value,
        )
    )
    await session.commit()

    svc = OpenEntityService(session, ctx, cache, _caller(ctx.user, frozenset({kb_ok.id})))
    out = await svc.graph_traverse(OpenGraphTraverseIn(ko_id=a.id, max_hops=1))
    assert out.seed.id == a.id
    assert {n.ko_id for n in out.neighbors} == {b.id}

    with pytest.raises(NotFoundError):
        await svc.graph_traverse(OpenGraphTraverseIn(ko_id=c.id, max_hops=1))


async def test_entity_read_generic_record(session: AsyncSession) -> None:
    ctx = _ctx()
    cache = AuthzCache(MemoryCache(), ttl_seconds=60)
    structured = StructuredService(session, ctx, cache)
    domains = await structured.list_domains()
    process = next(d for d in domains if d.code == "process")
    source = await structured.create_source(StructuredSourceCreate(name="PLM-x", type="plm"))
    from app.schemas.structured import StructuredRecordCreate

    await structured.create_record(
        StructuredRecordCreate(
            domain_id=process.id,
            source_id=source.id,
            object_type="recipe",
            external_id="RC-OPEN-1",
            title="开放平台配方",
        )
    )
    await session.commit()
    svc = OpenEntityService(session, ctx, cache, _caller(ctx.user, frozenset()))
    out = await svc.entity_read(
        OpenEntityReadIn(object_type="recipe", external_id="RC-OPEN-1")
    )
    assert out.mirror is not None
    assert out.mirror.label == "开放平台配方"
