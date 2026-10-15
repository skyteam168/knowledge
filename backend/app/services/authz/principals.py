import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.org_repo import DepartmentRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.user_repo import UserRepository
from app.services.authz.cache import AuthzCache


@dataclass(frozen=True)
class Principals:
    """Every subject a user acts as: {user, groups, roles, depts (incl. ancestors), org}."""

    org_id: str
    user_id: str
    group_ids: frozenset[str] = field(default_factory=frozenset)
    role_ids: frozenset[str] = field(default_factory=frozenset)
    dept_ids: frozenset[str] = field(default_factory=frozenset)

    def pairs(self) -> list[tuple[str, str]]:
        """(principal_type, principal_id) pairs, matching resource_acl rows."""
        result = [("user", self.user_id), ("org", self.org_id)]
        result += [("group", g) for g in sorted(self.group_ids)]
        result += [("role", r) for r in sorted(self.role_ids)]
        result += [("dept", d) for d in sorted(self.dept_ids)]
        return result

    def to_json(self) -> str:
        return json.dumps(
            {
                "org_id": self.org_id,
                "user_id": self.user_id,
                "group_ids": sorted(self.group_ids),
                "role_ids": sorted(self.role_ids),
                "dept_ids": sorted(self.dept_ids),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "Principals":
        data = json.loads(raw)
        return cls(
            org_id=data["org_id"],
            user_id=data["user_id"],
            group_ids=frozenset(data["group_ids"]),
            role_ids=frozenset(data["role_ids"]),
            dept_ids=frozenset(data["dept_ids"]),
        )


class PrincipalResolver:
    def __init__(self, session: AsyncSession, cache: AuthzCache) -> None:
        self.users = UserRepository(session)
        self.departments = DepartmentRepository(session)
        self.cache = cache

    async def resolve(self, org_id: str, user_id: str) -> Principals:
        cached = await self.cache.get("principals", org_id, user_id)
        if cached:
            return Principals.from_json(cached)
        principals = await self._compute(org_id, user_id)
        await self.cache.set("principals", org_id, user_id, principals.to_json())
        return principals

    async def _compute(self, org_id: str, user_id: str) -> Principals:
        user = await self.users.get(org_id, user_id)
        dept_ids: set[str] = set()
        if user:
            member_of = await self.users.department_ids(org_id, user)
            for dept in await self.departments.list_by_ids(org_id, sorted(member_of)):
                dept_ids.update(dept.ancestor_ids)
        groups = await self.users.list_group_links(org_id, user_id)
        roles = await self.users.list_role_links(org_id, user_id)
        return Principals(
            org_id=org_id,
            user_id=user_id,
            group_ids=frozenset(g.group_id for g in groups),
            role_ids=frozenset(r.role_id for r in roles),
            dept_ids=frozenset(dept_ids),
        )


class PermissionResolver:
    """Functional (RBAC) permission codes of a user, derived from their roles."""

    def __init__(self, session: AsyncSession, cache: AuthzCache) -> None:
        self.roles = RoleRepository(session)
        self.cache = cache

    async def resolve(self, principals: Principals) -> frozenset[str]:
        cached = await self.cache.get("perms", principals.org_id, principals.user_id)
        if cached is not None:
            return frozenset(json.loads(cached))
        codes = await self.roles.permission_codes(principals.org_id, principals.role_ids)
        await self.cache.set(
            "perms", principals.org_id, principals.user_id, json.dumps(sorted(codes))
        )
        return frozenset(codes)


def principal_tokens(principals: Iterable[tuple[str, str]]) -> list[str]:
    return [f"{ptype}:{pid}" for ptype, pid in principals]
