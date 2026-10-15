from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, Organization

PATH_SEPARATOR = " / "


def build_path_name(dept: Department, names: dict[str, str]) -> str:
    return PATH_SEPARATOR.join(names.get(a, "?") for a in dept.ancestor_ids)


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str) -> Organization | None:
        return await self.session.get(Organization, org_id)

    async def get_by_code(self, code: str) -> Organization | None:
        stmt = select(Organization).where(Organization.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(self) -> list[Organization]:
        stmt = select(Organization).order_by(Organization.created_at)
        return list((await self.session.execute(stmt)).scalars())

    async def add(self, org: Organization) -> Organization:
        self.session.add(org)
        await self.session.flush()
        return org


class DepartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, dept_id: str) -> Department | None:
        stmt = select(Department).where(Department.org_id == org_id, Department.id == dept_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(self, org_id: str) -> list[Department]:
        stmt = (
            select(Department)
            .where(Department.org_id == org_id)
            .order_by(Department.sort_order, Department.name)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_by_ids(self, org_id: str, ids: list[str]) -> list[Department]:
        if not ids:
            return []
        stmt = select(Department).where(Department.org_id == org_id, Department.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars())

    async def path_names(self, org_id: str, depts: list[Department]) -> dict[str, str]:
        """Full name path per department, e.g. "集团 / 越南Flyknit / 织造车间"."""
        names = {d.id: d.name for d in depts}
        missing = {a for d in depts for a in d.ancestor_ids} - names.keys()
        if missing:
            rows = await self.session.execute(
                select(Department.id, Department.name).where(
                    Department.org_id == org_id, Department.id.in_(missing)
                )
            )
            names.update({r[0]: r[1] for r in rows.all()})
        return {d.id: build_path_name(d, names) for d in depts}

    async def list_subtree(self, org_id: str, path: str) -> list[Department]:
        stmt = select(Department).where(
            Department.org_id == org_id, Department.path.startswith(path, autoescape=True)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def has_children(self, org_id: str, dept_id: str) -> bool:
        stmt = (
            select(Department.id)
            .where(Department.org_id == org_id, Department.parent_id == dept_id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def add(self, dept: Department) -> Department:
        self.session.add(dept)
        await self.session.flush()
        return dept

    async def delete(self, dept: Department) -> None:
        await self.session.delete(dept)
        await self.session.flush()
