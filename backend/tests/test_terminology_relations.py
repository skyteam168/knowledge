"""Wave A Task6: terminology contains / inherits / related hierarchy."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models.base import new_id
from app.schemas.open_api import OpenEntityReadIn
from app.schemas.terminology import (
    TerminologyEntityCreate,
    TerminologyRelationCreate,
)
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import ApiCaller
from app.services.open_api.entity_service import OpenEntityService
from app.services.terminology.service import TerminologyService


ORG = "org-term-rel"


def _ctx(org_id: str = ORG) -> RequestContext:
    uid = new_id()
    user = CurrentUser(
        id=uid,
        org_id=org_id,
        username="term",
        display_name="Term",
        principals=Principals(org_id, uid),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    return RequestContext(
        user, AuditContext(org_id=org_id, actor_id=uid, actor_name="Term")
    )


@pytest.fixture
def ctx() -> RequestContext:
    return _ctx()


@pytest.fixture
def terms(
    session: AsyncSession, ctx: RequestContext, settings: Settings
) -> TerminologyService:
    return TerminologyService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60), settings
    )


async def test_contains_and_inherits_related_terms(
    session: AsyncSession, terms: TerminologyService, ctx: RequestContext
) -> None:
    parent = await terms.create_entity(
        TerminologyEntityCreate(
            canonical_name="编织机",
            entity_type="device",
            aliases=["横机"],
        )
    )
    child = await terms.create_entity(
        TerminologyEntityCreate(
            canonical_name="电脑编织横机",
            entity_type="device",
            aliases=["飞织机"],
        )
    )
    related = await terms.create_entity(
        TerminologyEntityCreate(
            canonical_name="断纱",
            entity_type="defect",
        )
    )

    contains = await terms.add_relation(
        TerminologyRelationCreate(from_id=parent.id, to_id=child.id, kind="contains")
    )
    assert contains.kind == "contains"

    inherits = await terms.add_relation(
        TerminologyRelationCreate(from_id=child.id, to_id=parent.id, kind="inherits")
    )
    assert inherits.kind == "inherits"

    await terms.add_relation(
        TerminologyRelationCreate(from_id=child.id, to_id=related.id, kind="related")
    )

    with pytest.raises(ValidationAppError):
        await terms.add_relation(
            TerminologyRelationCreate(from_id=child.id, to_id=child.id, kind="related")
        )

    listed = await terms.list_relations(parent.id)
    assert any(r.kind == "contains" and r.to_id == child.id for r in listed)

    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=ORG,
        name="term-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=ctx.user,
    )
    entity_svc = OpenEntityService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60), caller
    )
    got = await entity_svc.entity_read(OpenEntityReadIn(entity_id=child.id))
    assert got.terminology is not None
    kinds = {t.kind for t in got.related_terms}
    assert "inherits" in kinds
    assert "related" in kinds
    names = {t.canonical_name for t in got.related_terms}
    assert "编织机" in names
    assert "断纱" in names
