"""Wave B Task11: entity owners + Open API call logs org isolation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models import ApiCallLog
from app.models.base import new_id
from app.schemas.semantic import SemanticEntityCreate, SemanticVersionCreate
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.service import OntologyStudioService


async def test_semantic_entity_owners_roundtrip(session: AsyncSession) -> None:
    org_id = "org-owners"
    uid = new_id()
    ctx = RequestContext(
        CurrentUser(
            id=uid,
            org_id=org_id,
            username="owner",
            display_name="Owner",
            principals=Principals(org_id, uid),
            permissions=frozenset({"*", "admin:retrieval"}),
        ),
        AuditContext(org_id=org_id, actor_id=uid, actor_name="Owner"),
    )
    studio = OntologyStudioService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60)
    )
    ver = await studio.create_version(SemanticVersionCreate(name="own-v1"))
    ent = await studio.add_entity(
        ver.id,
        SemanticEntityCreate(
            local_name="Device",
            label="设备",
            object_type="device",
            owners=["steward:alice", "dept:maintenance"],
        ),
    )
    assert ent.owners == ["steward:alice", "dept:maintenance"]
    detail = await studio.get_version(ver.id)
    assert detail.entities[0].owners == ["steward:alice", "dept:maintenance"]


async def test_api_call_logs_are_org_scoped(session: AsyncSession) -> None:
    session.add(
        ApiCallLog(
            org_id="org-a",
            client_id=new_id(),
            key_id=new_id(),
            endpoint="objects.get",
            status_code=200,
            latency_ms=12,
            result_count=1,
        )
    )
    session.add(
        ApiCallLog(
            org_id="org-b",
            client_id=new_id(),
            key_id=new_id(),
            endpoint="objects.get",
            status_code=200,
            latency_ms=9,
            result_count=0,
        )
    )
    await session.flush()
    a_logs = list(
        await session.scalars(select(ApiCallLog).where(ApiCallLog.org_id == "org-a"))
    )
    b_logs = list(
        await session.scalars(select(ApiCallLog).where(ApiCallLog.org_id == "org-b"))
    )
    assert len(a_logs) == 1
    assert len(b_logs) == 1
    assert a_logs[0].org_id != b_logs[0].org_id
