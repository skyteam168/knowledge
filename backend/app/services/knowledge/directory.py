from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import Department, DepartmentStatus, Group, Role, User
from app.repositories.group_repo import GroupRepository
from app.repositories.org_repo import DepartmentRepository, build_path_name
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.schemas.knowledge import (
    AclEntryIn,
    AclEntryOut,
    DirectoryDepartment,
    GrantablePrincipal,
    PrincipalOption,
)
from app.services.context import BaseService


class PrincipalDirectory:
    """Validates and names ACL principals (user / group / role / dept) within one org."""

    def __init__(self, session: AsyncSession, org_id: str) -> None:
        self.session = session
        self.org_id = org_id

    async def _names(self, ptype: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        if ptype == "user":
            users = await self.session.execute(
                select(User.id, User.username, User.display_name).where(
                    User.org_id == self.org_id, User.id.in_(ids)
                )
            )
            return {uid: (display or username) for uid, username, display in users.all()}
        if ptype == "group":
            groups = await GroupRepository(self.session).list_by_ids(self.org_id, ids)
            return {g.id: g.name for g in groups}
        if ptype == "role":
            roles = await RoleRepository(self.session).list_by_ids(self.org_id, ids)
            return {r.id: r.name for r in roles}
        if ptype == "dept":
            # Full path: same-named departments in different factories stay distinguishable.
            repo = DepartmentRepository(self.session)
            return await repo.path_names(self.org_id, await repo.list_by_ids(self.org_id, ids))
        return {}

    async def names(self, entries: Iterable[tuple[str, str]]) -> dict[tuple[str, str], str]:
        by_type: dict[str, list[str]] = {}
        for ptype, pid in entries:
            by_type.setdefault(ptype, []).append(pid)
        result: dict[tuple[str, str], str] = {}
        for ptype, ids in by_type.items():
            for pid, name in (await self._names(ptype, sorted(set(ids)))).items():
                result[(ptype, pid)] = name
        return result

    async def validate(self, entries: list[AclEntryIn]) -> list[AclEntryIn]:
        """Drop duplicates (keeping the highest permission) and reject unknown principals."""
        levels = {"read": 1, "edit": 2, "manage": 3}
        merged: dict[tuple[str, str], AclEntryIn] = {}
        for entry in entries:
            key = (entry.principal_type, entry.principal_id)
            current = merged.get(key)
            if current is None or levels[entry.permission] > levels[current.permission]:
                merged[key] = entry
        known = await self.names(merged.keys())
        missing = [f"{t}:{i}" for t, i in merged if (t, i) not in known]
        if missing:
            raise ValidationAppError("Unknown ACL principals", detail={"principals": missing})
        return list(merged.values())

    async def describe(self, entries: Iterable[tuple[str, str, str]]) -> list[AclEntryOut]:
        rows = list(entries)
        names = await self.names((t, i) for t, i, _ in rows)
        return [
            AclEntryOut(
                principal_type=t,
                principal_id=i,
                permission=p,
                principal_name=names.get((t, i)),
            )
            for t, i, p in rows
        ]


class DirectoryService(BaseService):
    """Lightweight principal lookup for permission pickers (no admin permission needed)."""

    async def _active_departments(self) -> tuple[list[Department], dict[str, str]]:
        """Archived departments are hidden from pickers (existing grants keep working)."""
        all_depts = await DepartmentRepository(self.session).list_all(self.org_id)
        names = {d.id: d.name for d in all_depts}
        archived = {d.id for d in all_depts if d.status == DepartmentStatus.ARCHIVED}
        active = [d for d in all_depts if not (set(d.ancestor_ids) & archived)]
        return active, {d.id: build_path_name(d, names) for d in active}

    async def departments(self) -> list[DirectoryDepartment]:
        depts, paths = await self._active_departments()
        nodes = {
            d.id: DirectoryDepartment(id=d.id, name=d.name, path_name=paths[d.id]) for d in depts
        }
        roots: list[DirectoryDepartment] = []
        for dept in depts:
            parent = nodes.get(dept.parent_id) if dept.parent_id else None
            (parent.children if parent else roots).append(nodes[dept.id])
        return roots

    async def principals(
        self, ptype: GrantablePrincipal, keyword: str | None, limit: int = 20
    ) -> list[PrincipalOption]:
        kw = keyword.strip() if keyword else None
        if ptype == "user":
            stmt = UserRepository(self.session).search_stmt(self.org_id, kw, is_active=True)
            users: list[User] = list((await self.session.execute(stmt.limit(limit))).scalars())
            return [
                PrincipalOption(
                    type="user", id=u.id, name=u.display_name or u.username, description=u.username
                )
                for u in users
            ]
        if ptype == "group":
            gstmt = GroupRepository(self.session).search_stmt(self.org_id, kw)
            groups: list[Group] = list((await self.session.execute(gstmt.limit(limit))).scalars())
            return [
                PrincipalOption(type="group", id=g.id, name=g.name, description=g.description)
                for g in groups
            ]
        if ptype == "role":
            roles: list[Role] = await RoleRepository(self.session).list_all(self.org_id)
            if kw:
                roles = [r for r in roles if kw.lower() in f"{r.name} {r.code}".lower()]
            return [
                PrincipalOption(type="role", id=r.id, name=r.name, description=r.code)
                for r in roles[:limit]
            ]
        depts, paths = await self._active_departments()
        if kw:
            depts = [d for d in depts if kw.lower() in paths[d.id].lower()]
        return [
            PrincipalOption(type="dept", id=d.id, name=d.name, description=paths[d.id])
            for d in depts[:limit]
        ]
