"""S5: structured row-level ACL (org-default + restricted + DENY wins)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import EquipDevice, StructuredSource, StructuredSourceType
from app.services.authz import (
    AclEffect,
    AclPermission,
    AclService,
    AuthzCache,
    PrincipalType,
    ResourceRef,
)
from app.services.structured.access import RESOURCE_STRUCTURED, StructuredAccess
from tests.factories import make_group, make_org, make_user
from tests.test_acl_service import as_current

READ = AclPermission.READ


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


@pytest.mark.acl
async def test_org_default_readable_without_acl(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    user = await make_user(session, org)
    device = await _device(session, org.id, "EQ-OPEN")
    access = StructuredAccess(session)
    current = await as_current(session, authz_cache, user)
    assert await access.can_read(current, device.id)
    assert await access.filter_readable(current, [device.id]) == [device.id]


@pytest.mark.acl
async def test_restricted_requires_allow(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    alice = await make_user(session, org)
    bob = await make_user(session, org)
    group = await make_group(session, org, alice)
    device = await _device(session, org.id, "EQ-RESTRICT")
    acl = AclService(session)
    await acl.grant(
        org.id,
        ResourceRef(RESOURCE_STRUCTURED, device.id),
        PrincipalType.GROUP,
        group.id,
        READ,
    )
    access = StructuredAccess(session)
    alice_u = await as_current(session, authz_cache, alice)
    bob_u = await as_current(session, authz_cache, bob)
    assert await access.can_read(alice_u, device.id)
    assert not await access.can_read(bob_u, device.id)
    assert await access.filter_readable(bob_u, [device.id]) == []


@pytest.mark.acl
async def test_deny_wins_over_group_allow(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    member = await make_user(session, org)
    group = await make_group(session, org, member)
    device = await _device(session, org.id, "EQ-DENY")
    acl = AclService(session)
    ref = ResourceRef(RESOURCE_STRUCTURED, device.id)
    await acl.grant(org.id, ref, PrincipalType.GROUP, group.id, READ)
    await acl.grant(
        org.id,
        ref,
        PrincipalType.USER,
        member.id,
        READ,
        effect=AclEffect.DENY,
    )
    access = StructuredAccess(session)
    user = await as_current(session, authz_cache, member)
    assert not await access.can_read(user, device.id)
    with pytest.raises(NotFoundError):
        await access.require_read(user, device.id)


@pytest.mark.acl
async def test_deny_under_org_default(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    """Like document DENY under org-visible KB: single DENY blocks one user."""
    org = await make_org(session)
    alice = await make_user(session, org)
    bob = await make_user(session, org)
    device = await _device(session, org.id, "EQ-ORG-DENY")
    acl = AclService(session)
    await acl.grant(
        org.id,
        ResourceRef(RESOURCE_STRUCTURED, device.id),
        PrincipalType.USER,
        bob.id,
        READ,
        effect=AclEffect.DENY,
    )
    access = StructuredAccess(session)
    assert await access.can_read(await as_current(session, authz_cache, alice), device.id)
    assert not await access.can_read(await as_current(session, authz_cache, bob), device.id)
