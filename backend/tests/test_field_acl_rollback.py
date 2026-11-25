"""Wave B Task10: field-level ACL strip + semantic publish rollback."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models import EquipDevice, StructuredSource, StructuredSourceType
from app.models.base import new_id
from app.schemas.open_api import OpenGetObjectIn
from app.schemas.semantic import (
    SemanticAttributeCreate,
    SemanticEntityCreate,
    SemanticVersionCreate,
)
from app.services.authz import (
    AclEffect,
    AclPermission,
    AclService,
    AuthzCache,
    CurrentUser,
    PrincipalType,
)
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.ontology_studio.service import OntologyStudioService
from app.services.open_api.auth import ApiCaller
from app.services.open_api.ontology_tools import OpenOntologyTools
from app.services.structured.access import StructuredAccess, structured_field_ref
from tests.factories import make_org, make_user
from tests.test_acl_service import as_current

READ = AclPermission.READ


@pytest.mark.acl
async def test_get_object_strips_denied_fields(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    alice = await make_user(session, org)
    source = StructuredSource(
        org_id=org.id,
        name="field-acl",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={},
    )
    session.add(source)
    await session.flush()
    device = EquipDevice(
        org_id=org.id,
        source_id=source.id,
        external_id="EQ-FIELD-1",
        name="字段ACL设备",
        status="0",
        location="A",
        meta={"model": "X1", "secret_code": "TOP"},
    )
    session.add(device)
    await session.flush()

    acl = AclService(session)
    await acl.grant(
        org.id,
        structured_field_ref(device.id, "secret_code"),
        PrincipalType.USER,
        alice.id,
        READ,
        effect=AclEffect.DENY,
    )

    user = await as_current(session, authz_cache, alice)
    access = StructuredAccess(session)
    filtered = await access.filter_attrs(
        user, device.id, dict(device.meta or {})
    )
    assert "model" in filtered
    assert "secret_code" not in filtered

    ctx = RequestContext(
        user,
        AuditContext(org_id=org.id, actor_id=user.id, actor_name=user.display_name),
    )
    caller = ApiCaller(
        client_id=new_id(),
        key_id=new_id(),
        org_id=org.id,
        name="field-agent",
        kb_ids=frozenset({new_id()}),
        scopes=frozenset({"entity", "mcp"}),
        rate_limit_per_minute=60,
        daily_quota=0,
        user=user,
    )
    tools = OpenOntologyTools(session, ctx, authz_cache, caller)
    got = await tools.get_object(
        OpenGetObjectIn(object_type="device", object_id=device.id)
    )
    assert "model" in got.attrs
    assert "secret_code" not in got.attrs


async def test_publish_rollback_reactivates_previous(
    session: AsyncSession,
) -> None:
    uid = new_id()
    org_id = "org-rollback"
    user = CurrentUser(
        id=uid,
        org_id=org_id,
        username="rb",
        display_name="RB",
        principals=Principals(org_id, uid),
        permissions=frozenset({"*", "admin:retrieval"}),
    )
    ctx = RequestContext(
        user, AuditContext(org_id=org_id, actor_id=uid, actor_name="RB")
    )
    studio = OntologyStudioService(
        session, ctx, AuthzCache(MemoryCache(), ttl_seconds=60)
    )

    async def _publish_named(name: str) -> str:
        ver = await studio.create_version(SemanticVersionCreate(name=name))
        ent = await studio.add_entity(
            ver.id,
            SemanticEntityCreate(local_name=name, label=name, object_type="device"),
        )
        await studio.add_attribute(
            ent.id, SemanticAttributeCreate(name="status", label="状态")
        )
        await studio.set_entity_status(ent.id, "approved")
        out = await studio.publish(ver.id)
        return out.id

    first_id = await _publish_named("v1")
    second_id = await _publish_named("v2")
    active = await studio.get_active_published()
    assert active is not None and active.id == second_id

    rolled = await studio.rollback_publish(first_id)
    assert rolled.id == first_id
    assert rolled.is_active is True
    assert rolled.status == "published"
    active2 = await studio.get_active_published()
    assert active2 is not None and active2.id == first_id

    tools = OpenOntologyTools(
        session,
        ctx,
        AuthzCache(MemoryCache(), ttl_seconds=60),
        ApiCaller(
            client_id=new_id(),
            key_id=new_id(),
            org_id=org_id,
            name="rb-agent",
            kb_ids=frozenset({new_id()}),
            scopes=frozenset({"entity", "mcp"}),
            rate_limit_per_minute=60,
            daily_quota=0,
            user=user,
        ),
    )
    described = await tools.describe_ontology(scope="all", version="published")
    assert described.version_id == first_id
    assert any(e.get("local_name") == "v1" for e in described.org_entities)
    assert all(e.get("local_name") != "v2" for e in described.org_entities)
