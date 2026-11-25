"""S4: Open API on-behalf-of + same client / two end users see different objects."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import ApiClient, ApiScope, EquipDevice, StructuredSource, StructuredSourceType
from app.models.base import new_id
from app.schemas.open_api import OpenGetObjectIn, OpenQueryObjectsIn
from app.services.authz import (
    AclEffect,
    AclPermission,
    AclService,
    AuthzCache,
    PrincipalType,
    ResourceRef,
)
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.open_api.auth import (
    ScopeDeniedError,
    build_caller,
    client_principal_overlap,
    resolve_on_behalf_user,
)
from app.services.open_api.ontology_tools import OpenOntologyTools
from app.services.structured.access import RESOURCE_STRUCTURED
from tests.factories import make_group, make_org, make_user
from tests.test_acl_service import as_current

READ = AclPermission.READ


def _settings_ttl() -> int:
    return 60


async def _device(session: AsyncSession, org_id: str, external_id: str) -> EquipDevice:
    source = StructuredSource(
        org_id=org_id,
        name=f"src-{external_id}",
        type=StructuredSourceType.MANUAL.value,
        enabled=True,
        meta={},
    )
    session.add(source)
    await session.flush()
    device = EquipDevice(
        org_id=org_id,
        source_id=source.id,
        external_id=external_id,
        name=external_id,
        status="active",
        location="车间A",
        meta={},
    )
    session.add(device)
    await session.flush()
    return device


def _tools(session: AsyncSession, user, *, kb_ids: frozenset[str] | None = None) -> OpenOntologyTools:
    ctx = RequestContext(
        user,
        AuditContext(org_id=user.org_id, actor_id=user.id, actor_name=user.username),
    )
    caller = build_caller(
        new_id(),
        ApiClient(
            id=new_id(),
            org_id=user.org_id,
            name="agent",
            service_user_id=user.id,
            kb_ids=list(kb_ids or []),
            principals=[],
            scopes=[ApiScope.ENTITY.value, ApiScope.ON_BEHALF.value],
        ),
        user,
        type("S", (), {"open_api_default_rate_per_minute": 60})(),
        on_behalf_of=user.id,
    )
    return OpenOntologyTools(session, ctx, AuthzCache(MemoryCache(), 60), caller)


@pytest.mark.acl
async def test_on_behalf_requires_scope(session: AsyncSession) -> None:
    org = await make_org(session)
    alice = await make_user(session, org, username="alice-ob")
    group = await make_group(session, org, alice)
    client = ApiClient(
        id=new_id(),
        org_id=org.id,
        name="no-ob",
        service_user_id=alice.id,
        kb_ids=["kb1"],
        principals=[{"type": "group", "id": group.id}],
        scopes=[ApiScope.ENTITY.value],
    )
    with pytest.raises(ScopeDeniedError):
        await resolve_on_behalf_user(
            session, client, ref=alice.username, cache=MemoryCache(), authz_ttl_seconds=60
        )


@pytest.mark.acl
async def test_on_behalf_out_of_scope(session: AsyncSession) -> None:
    org = await make_org(session)
    alice = await make_user(session, org, username="alice-scope")
    bob = await make_user(session, org, username="bob-scope")
    sales = await make_group(session, org, alice)
    await make_group(session, org, bob)  # bob not in sales
    client = ApiClient(
        id=new_id(),
        org_id=org.id,
        name="sales-agent",
        service_user_id=alice.id,
        kb_ids=["kb1"],
        principals=[{"type": "group", "id": sales.id}],
        scopes=[ApiScope.ENTITY.value, ApiScope.ON_BEHALF.value],
    )
    with pytest.raises(PermissionDeniedError) as exc:
        await resolve_on_behalf_user(
            session, client, ref=bob.username, cache=MemoryCache(), authz_ttl_seconds=60
        )
    assert exc.value.code == "ON_BEHALF_OUT_OF_SCOPE"


@pytest.mark.acl
async def test_same_client_two_users_see_different_objects(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    """S4+S5 acceptance: same app, Alice sees EQ-A, Bob does not."""
    org = await make_org(session)
    alice = await make_user(session, org, username="alice-vis")
    bob = await make_user(session, org, username="bob-vis")
    sales = await make_group(session, org, alice, bob)
    eq_a = await _device(session, org.id, "EQ-A")
    eq_b = await _device(session, org.id, "EQ-B")

    acl = AclService(session)
    # Restrict both devices to sales; DENY bob on EQ-A only.
    for device in (eq_a, eq_b):
        await acl.grant(
            org.id,
            ResourceRef(RESOURCE_STRUCTURED, device.id),
            PrincipalType.GROUP,
            sales.id,
            READ,
        )
    await acl.grant(
        org.id,
        ResourceRef(RESOURCE_STRUCTURED, eq_a.id),
        PrincipalType.USER,
        bob.id,
        READ,
        effect=AclEffect.DENY,
    )

    alice_u = await as_current(session, authz_cache, alice)
    bob_u = await as_current(session, authz_cache, bob)
    assert client_principal_overlap(alice_u.principals, [{"type": "group", "id": sales.id}])
    assert client_principal_overlap(bob_u.principals, [{"type": "group", "id": sales.id}])

    alice_tools = _tools(session, alice_u)
    bob_tools = _tools(session, bob_u)

    alice_a = await alice_tools.get_object(
        OpenGetObjectIn(object_type="device", object_id=eq_a.id)
    )
    assert alice_a.external_id == "EQ-A"
    with pytest.raises(NotFoundError):
        await bob_tools.get_object(OpenGetObjectIn(object_type="device", object_id=eq_a.id))

    bob_b = await bob_tools.get_object(
        OpenGetObjectIn(object_type="device", object_id=eq_b.id)
    )
    assert bob_b.external_id == "EQ-B"

    alice_q = await alice_tools.query_objects(
        OpenQueryObjectsIn(object_type="device", page=1, size=20)
    )
    bob_q = await bob_tools.query_objects(
        OpenQueryObjectsIn(object_type="device", page=1, size=20)
    )
    alice_ids = {i.external_id for i in alice_q.items}
    bob_ids = {i.external_id for i in bob_q.items}
    assert "EQ-A" in alice_ids and "EQ-B" in alice_ids
    assert "EQ-A" not in bob_ids and "EQ-B" in bob_ids


@pytest.mark.acl
async def test_resolve_on_behalf_by_username(session: AsyncSession) -> None:
    org = await make_org(session)
    alice = await make_user(session, org, username="alice-ob2")
    group = await make_group(session, org, alice)
    client = ApiClient(
        id=new_id(),
        org_id=org.id,
        name="ob-agent",
        service_user_id=alice.id,
        kb_ids=["kb1"],
        principals=[{"type": "group", "id": group.id}],
        scopes=[ApiScope.ENTITY.value, ApiScope.ON_BEHALF.value],
    )
    user = await resolve_on_behalf_user(
        session, client, ref="alice-ob2", cache=MemoryCache(), authz_ttl_seconds=60
    )
    assert user.id == alice.id
    assert user.username == "alice-ob2"
    assert isinstance(user.principals, Principals)
