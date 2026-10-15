from typing import Any

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Group
from app.repositories.base import paginate
from app.repositories.group_repo import GroupRepository
from app.repositories.user_repo import UserRepository
from app.schemas.common import Page
from app.schemas.identity import GroupCreate, GroupOut, GroupUpdate, UserOut
from app.services.admin.user_service import to_user_out
from app.services.audit_service import audited
from app.services.context import BaseService


async def _load(self: "GroupService", group_id: str, *_: Any, **__: Any) -> Group:
    return await self.get(group_id)


class GroupService(BaseService):
    @property
    def repo(self) -> GroupRepository:
        return GroupRepository(self.session)

    async def get(self, group_id: str) -> Group:
        group = await self.repo.get(self.org_id, group_id)
        if group is None:
            raise NotFoundError("Group not found")
        return group

    async def search(self, *, page: int, size: int, keyword: str | None = None) -> Page[GroupOut]:
        groups, total = await paginate(
            self.session, self.repo.search_stmt(self.org_id, keyword), page, size
        )
        counts = await self.repo.member_counts(self.org_id, [g.id for g in groups])
        items = [
            GroupOut.model_validate(g).model_copy(update={"member_count": counts.get(g.id, 0)})
            for g in groups
        ]
        return Page(items=items, total=total, page=page, size=size)

    @audited("group.create", "group")
    async def create(self, data: GroupCreate) -> Group:
        if await self.repo.get_by_name(self.org_id, data.name):
            raise ConflictError(f"Group '{data.name}' already exists")
        return await self.repo.add(Group(org_id=self.org_id, source="local", **data.model_dump()))

    @audited("group.update", "group", load=_load)
    async def update(self, group_id: str, data: GroupUpdate) -> Group:
        group = await self.get(group_id)
        if data.name is not None and data.name != group.name:
            if group.source == "keycloak":
                raise ConflictError("Groups synced from Keycloak cannot be renamed")
            if await self.repo.get_by_name(self.org_id, data.name):
                raise ConflictError(f"Group '{data.name}' already exists")
            group.name = data.name
        if "description" in data.model_fields_set:
            group.description = data.description
        await self.session.flush()
        return group

    @audited("group.delete", "group", load=_load)
    async def delete(self, group_id: str) -> None:
        group = await self.get(group_id)
        if group.source == "keycloak":
            raise ConflictError("Groups synced from Keycloak must be removed in Keycloak")
        await self.repo.delete(group)
        await self.authz_cache.invalidate_org(self.org_id)

    async def members(self, group_id: str) -> list[UserOut]:
        await self.get(group_id)
        return [to_user_out(u) for u in await self.repo.list_members(self.org_id, group_id)]

    async def set_members(self, group_id: str, user_ids: list[str]) -> list[UserOut]:
        group = await self.get(group_id)
        users_repo = UserRepository(self.session)
        for uid in set(user_ids):
            if await users_repo.get(self.org_id, uid) is None:
                raise NotFoundError(f"User {uid} not found")
        before = set(await self.repo.list_member_ids(self.org_id, group_id))
        await self.repo.set_local_members(self.org_id, group_id, set(user_ids))
        after = set(await self.repo.list_member_ids(self.org_id, group_id))
        await self.audit.record(
            self.audit_ctx,
            "group.set_members",
            "group",
            group.id,
            {"members": sorted(before)},
            {"members": sorted(after)},
        )
        changed = before ^ after
        if changed:
            await self.authz_cache.invalidate_user(self.org_id, *changed)
        return await self.members(group_id)
