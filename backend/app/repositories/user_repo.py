from sqlalchemy import Select, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SERVICE_USER_PREFIX,
    Group,
    Role,
    User,
    UserDepartment,
    UserGroup,
    UserRole,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, user_id: str) -> User | None:
        stmt = select(User).where(User.org_id == org_id, User.id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_sub(self, sub: str) -> User | None:
        stmt = select(User).where(User.keycloak_sub == sub)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_username(self, org_id: str, username: str) -> User | None:
        stmt = select(User).where(User.org_id == org_id, User.username == username)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def search_stmt(
        self,
        org_id: str,
        keyword: str | None = None,
        department_ids: list[str] | None = None,
        group_id: str | None = None,
        is_active: bool | None = None,
    ) -> Select[User]:
        # Service users of open API clients are managed on the open platform pages.
        stmt = select(User).where(
            User.org_id == org_id, ~User.username.startswith(SERVICE_USER_PREFIX)
        )
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    User.username.ilike(like), User.display_name.ilike(like), User.email.ilike(like)
                )
            )
        if department_ids is not None:
            stmt = stmt.where(
                or_(
                    User.department_id.in_(department_ids),
                    User.id.in_(
                        select(UserDepartment.user_id).where(
                            UserDepartment.org_id == org_id,
                            UserDepartment.department_id.in_(department_ids),
                        )
                    ),
                )
            )
        if group_id:
            stmt = stmt.where(
                User.id.in_(select(UserGroup.user_id).where(UserGroup.group_id == group_id))
            )
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
        return stmt.order_by(User.created_at.desc(), User.id)

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user

    async def count_in_departments(self, org_id: str, dept_ids: list[str]) -> int:
        stmt = select(User.id).where(User.org_id == org_id, User.department_id.in_(dept_ids))
        members = select(UserDepartment.user_id).where(
            UserDepartment.org_id == org_id, UserDepartment.department_id.in_(dept_ids)
        )
        return len({row[0] for row in (await self.session.execute(stmt.union(members))).all()})

    # ---- departments -------------------------------------------------------

    async def list_department_links(self, org_id: str, user_ids: list[str]) -> list[UserDepartment]:
        if not user_ids:
            return []
        stmt = select(UserDepartment).where(
            UserDepartment.org_id == org_id, UserDepartment.user_id.in_(user_ids)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def department_ids(self, org_id: str, user: User) -> set[str]:
        """Every department the user belongs to, the primary one included."""
        links = await self.list_department_links(org_id, [user.id])
        ids = {link.department_id for link in links}
        if user.department_id:
            ids.add(user.department_id)
        return ids

    async def set_departments(
        self, org_id: str, user: User, dept_ids: list[str], primary_id: str | None, source: str
    ) -> None:
        """Replace all memberships; the primary one is mirrored to users.department_id."""
        wanted = list(dict.fromkeys(dept_ids))
        if primary_id and primary_id not in wanted:
            wanted.insert(0, primary_id)
        if primary_id is None and wanted:
            primary_id = wanted[0]
        await self.session.execute(
            delete(UserDepartment).where(
                UserDepartment.org_id == org_id, UserDepartment.user_id == user.id
            )
        )
        for dept_id in wanted:
            self.session.add(
                UserDepartment(
                    org_id=org_id,
                    user_id=user.id,
                    department_id=dept_id,
                    is_primary=dept_id == primary_id,
                    source=source,
                )
            )
        user.department_id = primary_id
        await self.session.flush()

    # ---- memberships -------------------------------------------------------

    async def list_group_links(self, org_id: str, user_id: str) -> list[UserGroup]:
        stmt = select(UserGroup).where(UserGroup.org_id == org_id, UserGroup.user_id == user_id)
        return list((await self.session.execute(stmt)).scalars())

    async def list_groups(self, org_id: str, user_id: str) -> list[Group]:
        stmt = (
            select(Group)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(UserGroup.org_id == org_id, UserGroup.user_id == user_id)
            .order_by(Group.name)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_role_links(self, org_id: str, user_id: str) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.org_id == org_id, UserRole.user_id == user_id)
        return list((await self.session.execute(stmt)).scalars())

    async def list_roles(self, org_id: str, user_id: str) -> list[Role]:
        stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.org_id == org_id, UserRole.user_id == user_id)
            .order_by(Role.code)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def replace_groups(
        self, org_id: str, user_id: str, group_ids: set[str], source: str
    ) -> None:
        await self.session.execute(
            delete(UserGroup).where(
                UserGroup.org_id == org_id,
                UserGroup.user_id == user_id,
                UserGroup.source == source,
            )
        )
        existing = {link.group_id for link in await self.list_group_links(org_id, user_id)}
        for gid in group_ids - existing:
            self.session.add(UserGroup(org_id=org_id, user_id=user_id, group_id=gid, source=source))
        await self.session.flush()

    async def add_roles(
        self, org_id: str, user_id: str, role_ids: list[str], source: str = "local"
    ) -> None:
        existing = {link.role_id for link in await self.list_role_links(org_id, user_id)}
        for rid in dict.fromkeys(role_ids):
            if rid not in existing:
                self.session.add(
                    UserRole(org_id=org_id, user_id=user_id, role_id=rid, source=source)
                )
        await self.session.flush()

    async def replace_roles(
        self, org_id: str, user_id: str, role_ids: set[str], source: str
    ) -> None:
        await self.session.execute(
            delete(UserRole).where(
                UserRole.org_id == org_id,
                UserRole.user_id == user_id,
                UserRole.source == source,
            )
        )
        existing = {link.role_id for link in await self.list_role_links(org_id, user_id)}
        for rid in role_ids - existing:
            self.session.add(UserRole(org_id=org_id, user_id=user_id, role_id=rid, source=source))
        await self.session.flush()
