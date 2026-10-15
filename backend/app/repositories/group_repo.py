from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Group, User, UserGroup


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, group_id: str) -> Group | None:
        stmt = select(Group).where(Group.org_id == org_id, Group.id == group_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, org_id: str, name: str) -> Group | None:
        stmt = select(Group).where(Group.org_id == org_id, Group.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_names(self, org_id: str, names: list[str]) -> list[Group]:
        if not names:
            return []
        stmt = select(Group).where(Group.org_id == org_id, Group.name.in_(names))
        return list((await self.session.execute(stmt)).scalars())

    async def list_by_ids(self, org_id: str, ids: list[str]) -> list[Group]:
        if not ids:
            return []
        stmt = select(Group).where(Group.org_id == org_id, Group.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars())

    def search_stmt(self, org_id: str, keyword: str | None = None) -> Select[Group]:
        stmt = select(Group).where(Group.org_id == org_id)
        if keyword:
            stmt = stmt.where(Group.name.ilike(f"%{keyword}%"))
        return stmt.order_by(Group.name)

    async def member_counts(self, org_id: str, group_ids: list[str]) -> dict[str, int]:
        if not group_ids:
            return {}
        stmt = (
            select(UserGroup.group_id, func.count())
            .where(UserGroup.org_id == org_id, UserGroup.group_id.in_(group_ids))
            .group_by(UserGroup.group_id)
        )
        return {gid: int(cnt) for gid, cnt in (await self.session.execute(stmt)).all()}

    async def list_members(self, org_id: str, group_id: str) -> list[User]:
        stmt = (
            select(User)
            .join(UserGroup, UserGroup.user_id == User.id)
            .where(UserGroup.org_id == org_id, UserGroup.group_id == group_id)
            .order_by(User.username)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_member_ids(self, org_id: str, group_id: str) -> list[str]:
        stmt = select(UserGroup.user_id).where(
            UserGroup.org_id == org_id, UserGroup.group_id == group_id
        )
        return list((await self.session.execute(stmt)).scalars())

    async def set_local_members(self, org_id: str, group_id: str, user_ids: set[str]) -> None:
        await self.session.execute(
            delete(UserGroup).where(
                UserGroup.org_id == org_id,
                UserGroup.group_id == group_id,
                UserGroup.source == "local",
            )
        )
        existing = set(await self.list_member_ids(org_id, group_id))
        for uid in user_ids - existing:
            self.session.add(
                UserGroup(org_id=org_id, user_id=uid, group_id=group_id, source="local")
            )
        await self.session.flush()

    async def add(self, group: Group) -> Group:
        self.session.add(group)
        await self.session.flush()
        return group

    async def delete(self, group: Group) -> None:
        await self.session.execute(
            delete(UserGroup).where(
                UserGroup.org_id == group.org_id, UserGroup.group_id == group.id
            )
        )
        await self.session.delete(group)
        await self.session.flush()
