from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Permission, Role, RolePermission, UserRole


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[Permission]:
        stmt = select(Permission).order_by(Permission.code)
        return list((await self.session.execute(stmt)).scalars())

    async def list_by_codes(self, codes: Iterable[str]) -> list[Permission]:
        codes = list(codes)
        if not codes:
            return []
        stmt = select(Permission).where(Permission.code.in_(codes))
        return list((await self.session.execute(stmt)).scalars())

    async def ensure_catalog(self, catalog: dict[str, str]) -> None:
        existing = {p.code: p for p in await self.list_all()}
        for code, name in catalog.items():
            if code in existing:
                existing[code].name = name
            else:
                self.session.add(Permission(code=code, name=name))
        await self.session.flush()


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, role_id: str) -> Role | None:
        stmt = select(Role).where(Role.org_id == org_id, Role.id == role_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, org_id: str, code: str) -> Role | None:
        stmt = select(Role).where(Role.org_id == org_id, Role.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(self, org_id: str) -> list[Role]:
        stmt = select(Role).where(Role.org_id == org_id).order_by(Role.is_system.desc(), Role.code)
        return list((await self.session.execute(stmt)).scalars())

    async def list_by_codes(self, org_id: str, codes: Iterable[str]) -> list[Role]:
        codes = list(codes)
        if not codes:
            return []
        stmt = select(Role).where(Role.org_id == org_id, Role.code.in_(codes))
        return list((await self.session.execute(stmt)).scalars())

    async def list_by_ids(self, org_id: str, ids: Iterable[str]) -> list[Role]:
        ids = list(ids)
        if not ids:
            return []
        stmt = select(Role).where(Role.org_id == org_id, Role.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars())

    async def permission_codes(self, org_id: str, role_ids: Iterable[str]) -> set[str]:
        role_ids = list(role_ids)
        if not role_ids:
            return set()
        stmt = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.org_id == org_id, RolePermission.role_id.in_(role_ids))
        )
        return set((await self.session.execute(stmt)).scalars())

    async def permission_codes_by_role(
        self, org_id: str, role_ids: list[str]
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {rid: [] for rid in role_ids}
        if not role_ids:
            return result
        stmt = (
            select(RolePermission.role_id, Permission.code)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.org_id == org_id, RolePermission.role_id.in_(role_ids))
            .order_by(Permission.code)
        )
        for rid, code in (await self.session.execute(stmt)).all():
            result[rid].append(code)
        return result

    async def set_permissions(self, role: Role, permissions: list[Permission]) -> None:
        await self.session.execute(
            delete(RolePermission).where(
                RolePermission.org_id == role.org_id, RolePermission.role_id == role.id
            )
        )
        for perm in permissions:
            self.session.add(
                RolePermission(org_id=role.org_id, role_id=role.id, permission_id=perm.id)
            )
        await self.session.flush()

    async def default_role_ids(self, org_id: str) -> list[str]:
        stmt = select(Role.id).where(Role.org_id == org_id, Role.is_default.is_(True))
        return list((await self.session.execute(stmt)).scalars())

    async def user_ids_with_role(self, org_id: str, role_id: str) -> list[str]:
        stmt = select(UserRole.user_id).where(
            UserRole.org_id == org_id, UserRole.role_id == role_id
        )
        return list((await self.session.execute(stmt)).scalars())

    async def add(self, role: Role) -> Role:
        self.session.add(role)
        await self.session.flush()
        return role

    async def delete(self, role: Role) -> None:
        await self.session.execute(
            delete(RolePermission).where(
                RolePermission.org_id == role.org_id, RolePermission.role_id == role.id
            )
        )
        await self.session.execute(
            delete(UserRole).where(UserRole.org_id == role.org_id, UserRole.role_id == role.id)
        )
        await self.session.delete(role)
        await self.session.flush()
