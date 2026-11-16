from collections.abc import Iterable

from sqlalchemy import ColumnElement, Select, and_, delete, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResourceAcl

EFFECT_ALLOW = "allow"
EFFECT_DENY = "deny"


def principal_clause(principals: Iterable[tuple[str, str]]) -> ColumnElement[bool]:
    pairs = list(principals)
    if not pairs:
        return false()
    return or_(
        *(
            and_(ResourceAcl.principal_type == ptype, ResourceAcl.principal_id == pid)
            for ptype, pid in pairs
        )
    )


class ResourceAclRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def granted_ids_stmt(
        org_id: str, resource_type: str, principals: Iterable[tuple[str, str]]
    ) -> Select[str]:
        """Ids of resources of `resource_type` on which any of `principals` holds an allow grant."""
        return select(ResourceAcl.resource_id).where(
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.effect == EFFECT_ALLOW,
            principal_clause(principals),
        )

    @staticmethod
    def denied_ids_stmt(
        org_id: str, resource_type: str, principals: Iterable[tuple[str, str]]
    ) -> Select[str]:
        """Ids of resources explicitly denied for any of `principals`."""
        return select(ResourceAcl.resource_id).where(
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.effect == EFFECT_DENY,
            principal_clause(principals),
        )

    async def list_matching_many(
        self,
        org_id: str,
        resource_type: str,
        resource_ids: Iterable[str],
        principals: Iterable[tuple[str, str]],
        *,
        effect: str | None = None,
    ) -> list[ResourceAcl]:
        ids = list(resource_ids)
        if not ids:
            return []
        filters = [
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.resource_id.in_(ids),
            principal_clause(principals),
        ]
        if effect is not None:
            filters.append(ResourceAcl.effect == effect)
        stmt = select(ResourceAcl).where(*filters)
        return list((await self.session.execute(stmt)).scalars())

    async def delete_for_resource(self, org_id: str, resource_type: str, resource_id: str) -> int:
        result = await self.session.execute(
            delete(ResourceAcl).where(
                ResourceAcl.org_id == org_id,
                ResourceAcl.resource_type == resource_type,
                ResourceAcl.resource_id == resource_id,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def list_for_resource(
        self, org_id: str, resource_type: str, resource_id: str
    ) -> list[ResourceAcl]:
        stmt = select(ResourceAcl).where(
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.resource_id == resource_id,
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_matching(
        self,
        org_id: str,
        resource_type: str,
        resource_id: str,
        principals: Iterable[tuple[str, str]],
        *,
        effect: str | None = None,
    ) -> list[ResourceAcl]:
        pairs = list(principals)
        if not pairs:
            return []
        filters = [
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.resource_id == resource_id,
            or_(
                *(
                    and_(ResourceAcl.principal_type == ptype, ResourceAcl.principal_id == pid)
                    for ptype, pid in pairs
                )
            ),
        ]
        if effect is not None:
            filters.append(ResourceAcl.effect == effect)
        stmt = select(ResourceAcl).where(*filters)
        return list((await self.session.execute(stmt)).scalars())

    async def find(
        self,
        org_id: str,
        resource_type: str,
        resource_id: str,
        principal_type: str,
        principal_id: str,
        permission: str,
        *,
        effect: str = EFFECT_ALLOW,
    ) -> ResourceAcl | None:
        stmt = select(ResourceAcl).where(
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.resource_id == resource_id,
            ResourceAcl.principal_type == principal_type,
            ResourceAcl.principal_id == principal_id,
            ResourceAcl.permission == permission,
            ResourceAcl.effect == effect,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, entry: ResourceAcl) -> ResourceAcl:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def delete_entry(
        self,
        org_id: str,
        resource_type: str,
        resource_id: str,
        principal_type: str,
        principal_id: str,
        permission: str | None = None,
        *,
        effect: str | None = None,
    ) -> int:
        stmt = delete(ResourceAcl).where(
            ResourceAcl.org_id == org_id,
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.resource_id == resource_id,
            ResourceAcl.principal_type == principal_type,
            ResourceAcl.principal_id == principal_id,
        )
        if permission is not None:
            stmt = stmt.where(ResourceAcl.permission == permission)
        if effect is not None:
            stmt = stmt.where(ResourceAcl.effect == effect)
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
