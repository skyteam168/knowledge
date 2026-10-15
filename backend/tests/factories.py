from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, Group, Organization, Role, User, UserGroup, UserRole
from app.models.base import new_id


async def make_org(session: AsyncSession, code: str = "acme") -> Organization:
    org = Organization(code=code, name=code)
    session.add(org)
    await session.flush()
    return org


async def make_dept(
    session: AsyncSession, org: Organization, parent: Department | None = None
) -> Department:
    dept_id = new_id()
    dept = Department(
        id=dept_id,
        org_id=org.id,
        parent_id=parent.id if parent else None,
        name=f"dept-{dept_id[:6]}",
        path=f"{parent.path if parent else '/'}{dept_id}/",
    )
    session.add(dept)
    await session.flush()
    return dept


async def make_user(
    session: AsyncSession,
    org: Organization,
    dept: Department | None = None,
    username: str | None = None,
) -> User:
    user = User(
        org_id=org.id,
        username=username or f"u-{new_id()[:8]}",
        department_id=dept.id if dept else None,
    )
    session.add(user)
    await session.flush()
    return user


async def make_group(session: AsyncSession, org: Organization, *members: User) -> Group:
    group = Group(org_id=org.id, name=f"g-{new_id()[:8]}")
    session.add(group)
    await session.flush()
    for m in members:
        session.add(UserGroup(org_id=org.id, user_id=m.id, group_id=group.id))
    await session.flush()
    return group


async def make_role(session: AsyncSession, org: Organization, *members: User) -> Role:
    role = Role(org_id=org.id, code=f"r-{new_id()[:8]}", name="role")
    session.add(role)
    await session.flush()
    for m in members:
        session.add(UserRole(org_id=org.id, user_id=m.id, role_id=role.id))
    await session.flush()
    return role
