"""Semantic evidence: draft CRUD, published MCP visibility."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ConflictError, ValidationAppError
from app.models.base import new_id
from app.schemas.semantic import (
    SemanticEntityCreate,
    SemanticEvidenceCreate,
    SemanticVersionCreate,
)
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.service import OntologyStudioService
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools


ORG = "org-evidence"


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
def studio(session: AsyncSession) -> OntologyStudioService:
    return OntologyStudioService(
        session, _ctx(), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


def _tools(session: AsyncSession, ctx: RequestContext) -> OpenOntologyTools:
    return OpenOntologyTools(
        session,
        ctx,
        AuthzCache(MemoryCache(), ttl_seconds=60),
        ApiCaller(
            client_id=new_id(),
            key_id=new_id(),
            org_id=ctx.user.org_id,
            name="agent",
            kb_ids=frozenset({new_id()}),
            scopes=frozenset({"entity"}),
            rate_limit_per_minute=60,
            daily_quota=0,
            user=ctx.user,
        ),
    )


async def test_evidence_publish_visible_to_agent(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ver = await studio.create_version(SemanticVersionCreate(name="ev-v1"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(
            local_name="Device",
            label="设备",
            object_type="device",
        ),
    )
    ev = await studio.add_evidence(
        ver.id,
        SemanticEvidenceCreate(
            target_kind="entity",
            target_id=ent.id,
            evidence_kind="document",
            evidence_id="doc-orphan-ref",
            note="SOP 依据",
        ),
    )
    assert ev.evidence_id == "doc-orphan-ref"

    with pytest.raises(ConflictError):
        await studio.add_evidence(
            ver.id,
            SemanticEvidenceCreate(
                target_kind="entity",
                target_id=ent.id,
                evidence_kind="document",
                evidence_id="doc-orphan-ref",
            ),
        )

    # Draft must not leak via MCP
    tools = _tools(session, studio.ctx)
    draft_desc = await tools.describe_ontology(scope="all", version="published")
    assert draft_desc.version_id is None or draft_desc.evidences == []

    await studio.set_entity_status(ent.id, "approved")
    await studio.publish(ver.id)

    published = await tools.describe_ontology(scope="all", version="published")
    assert published.version_id == ver.id
    assert any(e.get("evidence_id") == "doc-orphan-ref" for e in published.evidences)
    assert any(e.get("note") == "SOP 依据" for e in published.evidences)


async def test_evidence_only_on_draft(
    session: AsyncSession, studio: OntologyStudioService
) -> None:
    ver = await studio.create_version(SemanticVersionCreate(name="ev-v2"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(local_name="Line", label="产线", object_type="line"),
    )
    await studio.set_entity_status(ent.id, "approved")
    await studio.publish(ver.id)
    with pytest.raises(ValidationAppError):
        await studio.add_evidence(
            ver.id,
            SemanticEvidenceCreate(
                target_kind="entity",
                target_id=ent.id,
                evidence_kind="ko",
                evidence_id="ko-1",
            ),
        )
