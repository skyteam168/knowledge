import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import PermissionDeniedError, UnauthorizedError
from app.models import AuditLog, Group, User
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.services.authz import AuthzCache
from app.services.identity_sync_service import IdentitySyncService
from tests.conftest import make_claims
from tests.factories import make_group


async def test_first_login_provisions_org_user_groups_and_roles(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    claims = make_claims("sub-1", "alice", ("kb_admin", "platform_admin"), ("engineering",))
    user, org = await IdentitySyncService(session, settings, authz_cache).sync(claims)

    assert org.code == "org-demo"
    assert user.keycloak_sub == "sub-1" and user.org_id == org.id
    repo = UserRepository(session)
    assert [g.name for g in await repo.list_groups(org.id, user.id)] == ["engineering"]
    assert [r.code for r in await repo.list_roles(org.id, user.id)] == ["kb_admin"]
    assert {r.code for r in await RoleRepository(session).list_all(org.id)} == {
        "kb_admin",
        "kb_editor",
        "kb_viewer",
    }
    logs = (await session.execute(select(AuditLog))).scalars().all()
    assert [log.action for log in logs] == ["user.provision"]


async def test_unchanged_claims_do_not_write(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    svc = IdentitySyncService(session, settings, authz_cache)
    claims = make_claims("sub-1", "alice", ("kb_viewer",))
    user, _ = await svc.sync(claims)
    first_login = user.last_login_at
    user2, _ = await svc.sync(claims)
    assert user2.id == user.id
    assert user2.last_login_at == first_login


async def test_changed_claims_resync_but_keep_local_memberships(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    svc = IdentitySyncService(session, settings, authz_cache)
    user, org = await svc.sync(
        make_claims("sub-1", "alice", ("kb_editor",), ("engineering", "ops"))
    )
    local_group = await make_group(session, org, user)

    await svc.sync(make_claims("sub-1", "alice", ("kb_viewer",), ("engineering",)))

    repo = UserRepository(session)
    assert {g.name for g in await repo.list_groups(org.id, user.id)} == {
        "engineering",
        local_group.name,
    }
    assert [r.code for r in await repo.list_roles(org.id, user.id)] == ["kb_viewer"]


async def test_pre_provisioned_user_is_bound_by_username(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    svc = IdentitySyncService(session, settings, authz_cache)
    _, org = await svc.sync(make_claims("sub-admin", "admin"))
    session.add(User(org_id=org.id, username="newbie", display_name="预置用户"))
    await session.flush()

    user, _ = await svc.sync(make_claims("sub-newbie", "newbie"))

    assert user.keycloak_sub == "sub-newbie"
    assert user.display_name == "Newbie"
    count = len((await session.execute(select(User).where(User.username == "newbie"))).all())
    assert count == 1


async def test_disabled_user_is_rejected(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    svc = IdentitySyncService(session, settings, authz_cache)
    claims = make_claims("sub-1", "alice")
    user, _ = await svc.sync(claims)
    user.is_active = False
    await session.flush()
    with pytest.raises(PermissionDeniedError):
        await svc.sync(claims)


async def test_unknown_org_rejected_when_auto_create_disabled(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    strict = settings.model_copy(update={"auth_auto_create_org": False})
    with pytest.raises(UnauthorizedError):
        await IdentitySyncService(session, strict, authz_cache).sync(make_claims("s", "x"))


async def test_keycloak_groups_are_created_with_source(
    session: AsyncSession, settings: Settings, authz_cache: AuthzCache
) -> None:
    _, org = await IdentitySyncService(session, settings, authz_cache).sync(
        make_claims("sub-1", "alice", (), ("research",))
    )
    group = (await session.execute(select(Group).where(Group.org_id == org.id))).scalar_one()
    assert (group.name, group.source) == ("research", "keycloak")
