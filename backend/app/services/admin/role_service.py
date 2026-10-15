from typing import Any

from sqlalchemy import delete, or_, select

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.permissions import is_privileged
from app.models import (
    LOCAL_SOURCE,
    SERVICE_USER_PREFIX,
    Department,
    Group,
    Role,
    User,
    UserDepartment,
    UserGroup,
    UserRole,
)
from app.repositories.org_repo import DepartmentRepository
from app.repositories.role_repo import PermissionRepository, RoleRepository
from app.schemas.identity import (
    PermissionOut,
    RoleBulkAssign,
    RoleBulkResult,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from app.services.audit_service import audited
from app.services.context import BaseService


async def _load(self: "RoleService", role_id: str, *_: Any, **__: Any) -> Role:
    return await self.get(role_id)


class PrivilegedRoleError(ValidationAppError):
    code = "ROLE_PRIVILEGED"
    message = "Roles with superuser or administration permissions must be assigned per user"


class RoleService(BaseService):
    @property
    def repo(self) -> RoleRepository:
        return RoleRepository(self.session)

    async def get(self, role_id: str) -> Role:
        role = await self.repo.get(self.org_id, role_id)
        if role is None:
            raise NotFoundError("Role not found")
        return role

    async def permission_codes(self, role: Role) -> list[str]:
        return (await self.repo.permission_codes_by_role(self.org_id, [role.id]))[role.id]

    async def to_out(self, role: Role) -> RoleOut:
        perms = await self.permission_codes(role)
        return RoleOut.model_validate(role).model_copy(update={"permissions": perms})

    async def list_roles(self) -> list[RoleOut]:
        roles = await self.repo.list_all(self.org_id)
        perms = await self.repo.permission_codes_by_role(self.org_id, [r.id for r in roles])
        return [
            RoleOut.model_validate(r).model_copy(update={"permissions": perms[r.id]}) for r in roles
        ]

    async def list_permissions(self) -> list[PermissionOut]:
        return [
            PermissionOut.model_validate(p)
            for p in await PermissionRepository(self.session).list_all()
        ]

    @audited("role.create", "role")
    async def create(self, data: RoleCreate) -> Role:
        if await self.repo.get_by_code(self.org_id, data.code):
            raise ConflictError(f"Role '{data.code}' already exists")
        return await self.repo.add(Role(org_id=self.org_id, is_system=False, **data.model_dump()))

    @audited("role.update", "role", load=_load)
    async def update(self, role_id: str, data: RoleUpdate) -> Role:
        role = await self.get(role_id)
        if data.is_default and is_privileged(await self.permission_codes(role)):
            raise PrivilegedRoleError()
        for key, value in data.model_dump(exclude_unset=True).items():
            if key == "is_default" and value is None:
                continue
            setattr(role, key, value)
        await self.session.flush()
        return role

    @audited("role.delete", "role", load=_load)
    async def delete(self, role_id: str) -> None:
        role = await self.get(role_id)
        if role.is_system:
            raise ConflictError("System roles cannot be deleted")
        await self.repo.delete(role)
        await self.authz_cache.invalidate_org(self.org_id)

    async def set_permissions(self, role_id: str, codes: list[str]) -> RoleOut:
        role = await self.get(role_id)
        wanted = sorted(set(codes))
        if role.is_default and is_privileged(wanted):
            raise PrivilegedRoleError(
                "A default role cannot hold superuser or administration permissions"
            )
        perms = await PermissionRepository(self.session).list_by_codes(wanted)
        unknown = set(wanted) - {p.code for p in perms}
        if unknown:
            raise NotFoundError("Unknown permissions", detail=sorted(unknown))
        before = await self.permission_codes(role)
        await self.repo.set_permissions(role, perms)
        await self.audit.record(
            self.audit_ctx,
            "role.set_permissions",
            "role",
            role.id,
            {"permissions": before},
            {"permissions": wanted},
        )
        await self.authz_cache.invalidate_org(self.org_id)
        return await self.to_out(role)

    # ---- bulk assignment ---------------------------------------------------------------

    async def _department_subtrees(self, dept_ids: list[str]) -> set[str]:
        wanted = list(dict.fromkeys(dept_ids))
        if not wanted:
            return set()
        rows = await self.session.execute(
            select(Department).where(Department.org_id == self.org_id, Department.id.in_(wanted))
        )
        depts = list(rows.scalars())
        missing = set(wanted) - {d.id for d in depts}
        if missing:
            raise NotFoundError("Department not found", detail=sorted(missing))
        repo = DepartmentRepository(self.session)
        result: set[str] = set()
        for dept in depts:
            result.update(d.id for d in await repo.list_subtree(self.org_id, dept.path))
        return result

    async def _check_groups(self, group_ids: list[str]) -> list[str]:
        wanted = list(dict.fromkeys(group_ids))
        if not wanted:
            return []
        rows = await self.session.execute(
            select(Group.id).where(Group.org_id == self.org_id, Group.id.in_(wanted))
        )
        missing = set(wanted) - set(rows.scalars())
        if missing:
            raise NotFoundError("Group not found", detail=sorted(missing))
        return wanted

    async def _target_user_ids(self, data: RoleBulkAssign) -> set[str]:
        dept_ids = await self._department_subtrees(data.department_ids)
        group_ids = await self._check_groups(data.group_ids)
        conditions = []
        if dept_ids:
            conditions.append(User.department_id.in_(dept_ids))
            conditions.append(
                User.id.in_(
                    select(UserDepartment.user_id).where(
                        UserDepartment.org_id == self.org_id,
                        UserDepartment.department_id.in_(dept_ids),
                    )
                )
            )
        if group_ids:
            conditions.append(
                User.id.in_(
                    select(UserGroup.user_id).where(
                        UserGroup.org_id == self.org_id, UserGroup.group_id.in_(group_ids)
                    )
                )
            )
        stmt = select(User.id).where(
            User.org_id == self.org_id,
            ~User.username.startswith(SERVICE_USER_PREFIX),
            or_(*conditions),
        )
        if not data.include_inactive:
            stmt = stmt.where(User.is_active.is_(True))
        return set((await self.session.execute(stmt)).scalars())

    async def bulk_assign(self, role_id: str, data: RoleBulkAssign) -> RoleBulkResult:
        role = await self.get(role_id)
        if data.action == "grant" and is_privileged(await self.permission_codes(role)):
            raise PrivilegedRoleError()
        targets = await self._target_user_ids(data)
        links: dict[str, str] = {}
        ids = sorted(targets)
        for i in range(0, len(ids), 1000):
            rows = await self.session.execute(
                select(UserRole.user_id, UserRole.source).where(
                    UserRole.org_id == self.org_id,
                    UserRole.role_id == role.id,
                    UserRole.user_id.in_(ids[i : i + 1000]),
                )
            )
            links.update({uid: src for uid, src in rows.all()})

        skipped = 0
        if data.action == "grant":
            to_change = sorted(targets - links.keys())
            unchanged = len(links)
        else:
            to_change = sorted(
                uid for uid, src in links.items() if src == LOCAL_SOURCE and uid != self.ctx.user.id
            )
            skipped = len(links) - len(to_change)
            unchanged = len(targets) - len(links)

        if not data.dry_run and to_change:
            if data.action == "grant":
                self.session.add_all(
                    UserRole(org_id=self.org_id, user_id=uid, role_id=role.id, source=LOCAL_SOURCE)
                    for uid in to_change
                )
            else:
                for i in range(0, len(to_change), 1000):
                    await self.session.execute(
                        delete(UserRole).where(
                            UserRole.org_id == self.org_id,
                            UserRole.role_id == role.id,
                            UserRole.user_id.in_(to_change[i : i + 1000]),
                        )
                    )
            await self.session.flush()
            await self.audit.record(
                self.audit_ctx,
                f"role.bulk_{data.action}",
                "role",
                role.id,
                None,
                {
                    "department_ids": data.department_ids,
                    "group_ids": data.group_ids,
                    "include_inactive": data.include_inactive,
                    "matched": len(targets),
                    "changed": len(to_change),
                },
            )
            await self.authz_cache.invalidate_org(self.org_id)
        return RoleBulkResult(
            matched=len(targets),
            changed=len(to_change),
            unchanged=unchanged,
            skipped=skipped,
            dry_run=data.dry_run,
        )
