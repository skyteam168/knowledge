from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import MemoryCache
from app.models import UserGroup
from app.repositories.role_repo import RoleRepository
from app.schemas.identity import DepartmentUpdate
from app.services.admin.department_service import DepartmentService
from app.services.audit_service import AuditContext
from app.services.authz import AuthzCache, CurrentUser, PermissionResolver, PrincipalResolver
from app.services.authz.principals import Principals
from app.services.context import RequestContext
from app.services.org_bootstrap import seed_default_roles
from tests.factories import make_dept, make_group, make_org, make_role, make_user


async def test_resolves_user_groups_roles_and_department_ancestors(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    root = await make_dept(session, org)
    mid = await make_dept(session, org, root)
    leaf = await make_dept(session, org, mid)
    sibling = await make_dept(session, org, root)
    user = await make_user(session, org, leaf)
    g1 = await make_group(session, org, user)
    g2 = await make_group(session, org, user)
    await make_group(session, org)  # not a member
    role = await make_role(session, org, user)

    p = await PrincipalResolver(session, authz_cache).resolve(org.id, user.id)

    assert p.org_id == org.id and p.user_id == user.id
    assert p.group_ids == {g1.id, g2.id}
    assert p.role_ids == {role.id}
    assert p.dept_ids == {root.id, mid.id, leaf.id}
    assert sibling.id not in p.dept_ids
    assert ("dept", root.id) in p.pairs() and ("org", org.id) in p.pairs()


async def test_user_without_department_or_memberships(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    user = await make_user(session, org)
    p = await PrincipalResolver(session, authz_cache).resolve(org.id, user.id)
    assert p == Principals(org_id=org.id, user_id=user.id)


async def test_result_is_cached_until_user_invalidated(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    user = await make_user(session, org)
    resolver = PrincipalResolver(session, authz_cache)
    assert (await resolver.resolve(org.id, user.id)).group_ids == frozenset()

    group = await make_group(session, org)
    session.add(UserGroup(org_id=org.id, user_id=user.id, group_id=group.id))
    await session.flush()

    assert (await resolver.resolve(org.id, user.id)).group_ids == frozenset(), "served from cache"
    await authz_cache.invalidate_user(org.id, user.id)
    assert (await resolver.resolve(org.id, user.id)).group_ids == {group.id}


async def test_org_invalidation_affects_all_users(
    session: AsyncSession, memory_cache: MemoryCache, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    users = [await make_user(session, org) for _ in range(2)]
    resolver = PrincipalResolver(session, authz_cache)
    for u in users:
        await resolver.resolve(org.id, u.id)
    group = await make_group(session, org, *users)

    await authz_cache.invalidate_org(org.id)

    for u in users:
        assert (await resolver.resolve(org.id, u.id)).group_ids == {group.id}


async def test_cache_is_isolated_per_org(session: AsyncSession, authz_cache: AuthzCache) -> None:
    org_a, org_b = await make_org(session, "a"), await make_org(session, "b")
    ua, ub = await make_user(session, org_a), await make_user(session, org_b)
    resolver = PrincipalResolver(session, authz_cache)
    await resolver.resolve(org_a.id, ua.id)
    await resolver.resolve(org_b.id, ub.id)
    group = await make_group(session, org_a, ua)
    await make_group(session, org_b, ub)

    await authz_cache.invalidate_org(org_a.id)

    assert (await resolver.resolve(org_a.id, ua.id)).group_ids == {group.id}
    assert (await resolver.resolve(org_b.id, ub.id)).group_ids == frozenset()


async def test_department_move_updates_inherited_ancestors(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    old_root = await make_dept(session, org)
    new_root = await make_dept(session, org)
    team = await make_dept(session, org, old_root)
    sub_team = await make_dept(session, org, team)
    user = await make_user(session, org, sub_team)
    resolver = PrincipalResolver(session, authz_cache)
    assert old_root.id in (await resolver.resolve(org.id, user.id)).dept_ids

    actor = CurrentUser(
        id=user.id,
        org_id=org.id,
        username="admin",
        display_name=None,
        principals=Principals(org.id, user.id),
        permissions=frozenset({"*"}),
    )
    ctx = RequestContext(actor, AuditContext(org.id, user.id, "admin"))
    await DepartmentService(session, ctx, authz_cache).update(
        team.id, DepartmentUpdate(parent_id=new_root.id)
    )

    dept_ids = (await resolver.resolve(org.id, user.id)).dept_ids
    assert dept_ids == {new_root.id, team.id, sub_team.id}
    assert sub_team.path == f"/{new_root.id}/{team.id}/{sub_team.id}/"


async def test_permission_resolver_uses_roles(
    session: AsyncSession, authz_cache: AuthzCache
) -> None:
    org = await make_org(session)
    await seed_default_roles(session, org.id)
    user = await make_user(session, org)
    viewer = await RoleRepository(session).get_by_code(org.id, "kb_viewer")
    assert viewer is not None
    from app.models import UserRole

    session.add(UserRole(org_id=org.id, user_id=user.id, role_id=viewer.id))
    await session.flush()

    principals = await PrincipalResolver(session, authz_cache).resolve(org.id, user.id)
    perms = await PermissionResolver(session, authz_cache).resolve(principals)
    assert perms == {"kb:read", "chat:use", "search:use"}
