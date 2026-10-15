from typing import Any

from sqlalchemy import select

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.models import LOCAL_SOURCE, User, UserIdentity
from app.repositories.base import paginate
from app.repositories.group_repo import GroupRepository
from app.repositories.org_repo import DepartmentRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.schemas.common import Page
from app.schemas.identity import (
    GroupBrief,
    RoleBrief,
    UserCreate,
    UserDepartmentBrief,
    UserDetail,
    UserIdentityBrief,
    UserOut,
    UserUpdate,
)
from app.services.audit_service import audited
from app.services.context import BaseService

# Owned by the primary directory source when users.source != "local".
SYNCED_USER_FIELDS = {
    "display_name",
    "email",
    "mobile",
    "employee_no",
    "job_title",
    "department_id",
    "department_ids",
}


def to_user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.keycloak_bound = user.keycloak_sub is not None
    return out


async def _load(self: "UserService", user_id: str, *_: Any, **__: Any) -> User:
    return await self.get(user_id)


class UserService(BaseService):
    @property
    def repo(self) -> UserRepository:
        return UserRepository(self.session)

    async def get(self, user_id: str) -> User:
        user = await self.repo.get(self.org_id, user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def search(
        self,
        *,
        page: int,
        size: int,
        keyword: str | None = None,
        department_id: str | None = None,
        include_sub_departments: bool = True,
        group_id: str | None = None,
        is_active: bool | None = None,
    ) -> Page[UserOut]:
        dept_ids: list[str] | None = None
        if department_id:
            dept_repo = DepartmentRepository(self.session)
            dept = await dept_repo.get(self.org_id, department_id)
            if dept is None:
                raise NotFoundError("Department not found")
            dept_ids = (
                [d.id for d in await dept_repo.list_subtree(self.org_id, dept.path)]
                if include_sub_departments
                else [dept.id]
            )
        stmt = self.repo.search_stmt(self.org_id, keyword, dept_ids, group_id, is_active)
        users, total = await paginate(self.session, stmt, page, size)
        return Page(items=await self.outs(list(users)), total=total, page=page, size=size)

    async def outs(self, users: list[User]) -> list[UserOut]:
        """UserOut with every department membership and its full path."""
        links = await self.repo.list_department_links(self.org_id, [u.id for u in users])
        by_user: dict[str, dict[str, bool]] = {}
        for link in links:
            by_user.setdefault(link.user_id, {})[link.department_id] = link.is_primary
        for user in users:
            if user.department_id:
                by_user.setdefault(user.id, {})[user.department_id] = True
        dept_repo = DepartmentRepository(self.session)
        all_ids = sorted({d for memberships in by_user.values() for d in memberships})
        depts = {d.id: d for d in await dept_repo.list_by_ids(self.org_id, all_ids)}
        paths = await dept_repo.path_names(self.org_id, list(depts.values()))
        result = []
        for user in users:
            out = to_user_out(user)
            memberships = by_user.get(user.id, {})
            out.departments = sorted(
                (
                    UserDepartmentBrief(
                        id=did,
                        name=depts[did].name,
                        path_name=paths[did],
                        is_primary=did == user.department_id,
                    )
                    for did in memberships
                    if did in depts
                ),
                key=lambda d: (not d.is_primary, d.path_name),
            )
            result.append(out)
        return result

    async def out(self, user: User) -> UserOut:
        return (await self.outs([user]))[0]

    async def detail(self, user_id: str) -> UserDetail:
        user = await self.get(user_id)
        roles = await self.repo.list_roles(self.org_id, user_id)
        groups = await self.repo.list_groups(self.org_id, user_id)
        identities = await self.session.execute(
            select(UserIdentity)
            .where(UserIdentity.org_id == self.org_id, UserIdentity.user_id == user_id)
            .order_by(UserIdentity.provider)
        )
        return UserDetail(
            **(await self.out(user)).model_dump(),
            roles=[RoleBrief.model_validate(r) for r in roles],
            groups=[GroupBrief.model_validate(g) for g in groups],
            identities=[UserIdentityBrief.model_validate(i) for i in identities.scalars()],
        )

    async def _check_departments(self, dept_ids: list[str]) -> None:
        wanted = set(dept_ids)
        found = await DepartmentRepository(self.session).list_by_ids(self.org_id, sorted(wanted))
        if len(found) != len(wanted):
            raise NotFoundError("Department not found")

    @audited("user.create", "user")
    async def create(self, data: UserCreate) -> User:
        """Pre-provision a user; it is bound to the Keycloak identity on first login by username."""
        if await self.repo.get_by_username(self.org_id, data.username):
            raise ConflictError(f"Username '{data.username}' already exists")
        dept_ids = ([data.department_id] if data.department_id else []) + data.department_ids
        await self._check_departments(dept_ids)
        user = await self.repo.add(
            User(org_id=self.org_id, **data.model_dump(exclude={"department_id", "department_ids"}))
        )
        if dept_ids:
            await self.repo.set_departments(
                self.org_id, user, dept_ids, data.department_id, LOCAL_SOURCE
            )
        return user

    @audited("user.update", "user", load=_load)
    async def update(self, user_id: str, data: UserUpdate) -> User:
        user = await self.get(user_id)
        values = data.model_dump(exclude_unset=True)
        if values.get("is_active") is False and user_id == self.ctx.user.id:
            raise AppError("Cannot disable yourself", code="INVALID_OPERATION")
        if user.source != LOCAL_SOURCE:
            locked = sorted(set(values) & SYNCED_USER_FIELDS)
            if locked:
                raise AppError(
                    "Fields are managed by the directory source",
                    code="DIRECTORY_MANAGED",
                    detail={"fields": locked, "source": user.source},
                )
        if "department_id" in values or "department_ids" in values:
            primary = values.pop("department_id", user.department_id)
            extra = values.pop("department_ids", None)
            if extra is None:
                current = await self.repo.department_ids(self.org_id, user)
                extra = sorted(current - {user.department_id} if user.department_id else current)
            dept_ids = ([primary] if primary else []) + list(extra)
            await self._check_departments(dept_ids)
            await self.repo.set_departments(self.org_id, user, dept_ids, primary, LOCAL_SOURCE)
        for key, value in values.items():
            setattr(user, key, value)
        await self.session.flush()
        await self.authz_cache.invalidate_user(self.org_id, user_id)
        return user

    @audited("user.disable", "user", load=_load)
    async def disable(self, user_id: str) -> User:
        if user_id == self.ctx.user.id:
            raise AppError("Cannot disable yourself", code="INVALID_OPERATION")
        user = await self.get(user_id)
        user.is_active = False
        await self.session.flush()
        await self.authz_cache.invalidate_user(self.org_id, user_id)
        return user

    async def set_roles(self, user_id: str, role_ids: list[str]) -> UserDetail:
        await self.get(user_id)
        roles = await RoleRepository(self.session).list_by_ids(self.org_id, role_ids)
        if len(roles) != len(set(role_ids)):
            raise NotFoundError("Some roles do not exist")
        before = sorted(r.code for r in await self.repo.list_roles(self.org_id, user_id))
        await self.repo.replace_roles(self.org_id, user_id, {r.id for r in roles}, LOCAL_SOURCE)
        after = sorted(r.code for r in await self.repo.list_roles(self.org_id, user_id))
        await self.audit.record(
            self.audit_ctx,
            "user.assign_roles",
            "user",
            user_id,
            {"roles": before},
            {"roles": after},
        )
        await self.authz_cache.invalidate_user(self.org_id, user_id)
        return await self.detail(user_id)

    async def set_groups(self, user_id: str, group_ids: list[str]) -> UserDetail:
        await self.get(user_id)
        groups = await GroupRepository(self.session).list_by_ids(self.org_id, group_ids)
        if len(groups) != len(set(group_ids)):
            raise NotFoundError("Some groups do not exist")
        before = sorted(g.name for g in await self.repo.list_groups(self.org_id, user_id))
        await self.repo.replace_groups(self.org_id, user_id, {g.id for g in groups}, LOCAL_SOURCE)
        after = sorted(g.name for g in await self.repo.list_groups(self.org_id, user_id))
        await self.audit.record(
            self.audit_ctx,
            "user.assign_groups",
            "user",
            user_id,
            {"groups": before},
            {"groups": after},
        )
        await self.authz_cache.invalidate_user(self.org_id, user_id)
        return await self.detail(user_id)
