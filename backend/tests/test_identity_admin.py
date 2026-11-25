"""Identity admin: canonical + identifiers + conflicts."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.core.exceptions import ConflictError
from app.models.base import new_id
from app.schemas.identity_admin import CanonicalCreate, IdentifierCreate, ResolveMatchIn
from app.services.authz import AuthzCache, CurrentUser
from app.services.authz.principals import Principals
from app.services.context import AuditContext, RequestContext
from app.services.structured.identity_admin import IdentityAdminService


ORG = "org-identity-admin"


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
def admin(session: AsyncSession) -> IdentityAdminService:
    return IdentityAdminService(
        session, _ctx(), AuthzCache(MemoryCache(), ttl_seconds=60)
    )


async def test_canonical_crud_and_conflict(admin: IdentityAdminService) -> None:
    a = await admin.create_canonical(
        CanonicalCreate(object_type="device", display_name="Loom-A")
    )
    b = await admin.create_canonical(
        CanonicalCreate(object_type="device", display_name="Loom-B")
    )
    await admin.add_identifier(
        a.id, IdentifierCreate(system="mes", external_id="M-1")
    )
    await admin.add_identifier(
        b.id, IdentifierCreate(system="erp", external_id="E-1")
    )

    page = await admin.list_canonical(object_type="device")
    assert page.total >= 2

    detail = await admin.get_canonical(a.id)
    assert len(detail.identifiers) == 1

    with pytest.raises(ConflictError):
        await admin.add_identifier(
            b.id, IdentifierCreate(system="mes", external_id="M-1")
        )

    match = await admin.resolve_match(
        ResolveMatchIn(
            identifiers=[
                {"system": "mes", "external_id": "M-1"},
                {"system": "erp", "external_id": "E-1"},
            ]
        )
    )
    assert match.status == "conflict"
    conflicts = await admin.list_conflicts()
    assert conflicts.total >= 2
