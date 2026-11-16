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
        """Merge allow (highest permission) and deny (one per principal); reject unknown ids."""
        levels = {"read": 1, "edit": 2, "manage": 3}
        allows: dict[tuple[str, str], AclEntryIn] = {}
        denies: dict[tuple[str, str], AclEntryIn] = {}
        for entry in entries:
            effect = entry.effect or "allow"
            key = (entry.principal_type, entry.principal_id)
            if effect == "deny":
                # DENY blocks all access; permission is stored as read for uniqueness.
                denies[key] = AclEntryIn(
                    principal_type=entry.principal_type,
                    principal_id=entry.principal_id,
                    permission="read",
                    effect="deny",
                )
                continue
            current = allows.get(key)
            if current is None or levels[entry.permission] > levels[current.permission]:
                allows[key] = AclEntryIn(
                    principal_type=entry.principal_type,
                    principal_id=entry.principal_id,
                    permission=entry.permission,
                    effect="allow",
                )
        merged = list(allows.values()) + list(denies.values())
        known = await self.names((e.principal_type, e.principal_id) for e in merged)
        missing = [
            f"{e.principal_type}:{e.principal_id}"
            for e in merged
            if (e.principal_type, e.principal_id) not in known
        ]
        if missing:
            raise ValidationAppError("Unknown ACL principals", detail={"principals": missing})
        return merged

    async def describe(
        self, entries: Iterable[tuple[str, str, str] | tuple[str, str, str, str]]
    ) -> list[AclEntryOut]:
        rows = list(entries)
        normalized: list[tuple[str, str, str, str]] = []
        for row in rows:
            if len(row) == 4:
                normalized.append(row)  # type: ignore[arg-type]
            else:
                t, i, p = row  # type: ignore[misc]
                normalized.append((t, i, p, "allow"))
        names = await self.names((t, i) for t, i, _, _ in normalized)
        users = await self._users(sorted({i for t, i, _, _ in normalized if t == "user"}))
        out: list[AclEntryOut] = []
        for t, i, p, effect in normalized:
            user = users.get(i) if t == "user" else None
            out.append(
                AclEntryOut(
                    principal_type=t,
                    principal_id=i,
                    permission=p,  # type: ignore[arg-type]
                    effect=effect,  # type: ignore[arg-type]
                    principal_name=names.get((t, i)),
                    principal_detail=user_detail(user) if user else None,
                    principal_active=user.is_active if user else True,
                )
            )
        return out

    async def _users(self, ids: list[str]) -> dict[str, User]:
        if not ids:
            return {}
        stmt = select(User).where(User.org_id == self.org_id, User.id.in_(ids))
        return {u.id: u for u in (await self.session.execute(stmt)).scalars()}


def user_detail(user: User) -> str:
    return " · ".join(p for p in (user.username, user.employee_no) if p)


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
                    type="user",
                    id=u.id,
                    name=u.display_name or u.username,
                    description=user_detail(u),
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
