from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TerminologyAlias, TerminologyEntity, TerminologyStatus


class TerminologyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_entity(self, org_id: str, entity_id: str) -> TerminologyEntity | None:
        result = await self.session.execute(
            select(TerminologyEntity).where(
                TerminologyEntity.org_id == org_id, TerminologyEntity.id == entity_id
            )
        )
        return result.scalar_one_or_none()

    async def get_entity_by_canonical(
        self, org_id: str, canonical_name: str
    ) -> TerminologyEntity | None:
        result = await self.session.execute(
            select(TerminologyEntity).where(
                TerminologyEntity.org_id == org_id,
                TerminologyEntity.canonical_name == canonical_name,
            )
        )
        return result.scalar_one_or_none()

    async def list_entities(
        self,
        org_id: str,
        *,
        page: int,
        size: int,
        q: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[TerminologyEntity], int]:
        filters = [TerminologyEntity.org_id == org_id]
        if entity_type:
            filters.append(TerminologyEntity.entity_type == entity_type)
        if status:
            filters.append(TerminologyEntity.status == status)
        if q:
            like = f"%{q.strip()}%"
            alias_ids = select(TerminologyAlias.entity_id).where(
                TerminologyAlias.org_id == org_id,
                or_(
                    TerminologyAlias.alias.ilike(like),
                    TerminologyAlias.alias_normalized.ilike(like),
                ),
            )
            filters.append(
                or_(
                    TerminologyEntity.canonical_name.ilike(like),
                    TerminologyEntity.id.in_(alias_ids),
                )
            )
        total = await self.session.scalar(
            select(func.count()).select_from(TerminologyEntity).where(*filters)
        )
        rows = await self.session.scalars(
            select(TerminologyEntity)
            .where(*filters)
            .order_by(TerminologyEntity.canonical_name, TerminologyEntity.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows), int(total or 0)

    async def list_aliases_for(
        self, org_id: str, entity_ids: Sequence[str]
    ) -> list[TerminologyAlias]:
        if not entity_ids:
            return []
        rows = await self.session.scalars(
            select(TerminologyAlias)
            .where(
                TerminologyAlias.org_id == org_id,
                TerminologyAlias.entity_id.in_(list(entity_ids)),
            )
            .order_by(TerminologyAlias.alias, TerminologyAlias.id)
        )
        return list(rows)

    async def get_alias(self, org_id: str, alias_id: str) -> TerminologyAlias | None:
        result = await self.session.execute(
            select(TerminologyAlias).where(
                TerminologyAlias.org_id == org_id, TerminologyAlias.id == alias_id
            )
        )
        return result.scalar_one_or_none()

    async def find_alias_normalized(
        self, org_id: str, alias_normalized: str
    ) -> TerminologyAlias | None:
        result = await self.session.execute(
            select(TerminologyAlias).where(
                TerminologyAlias.org_id == org_id,
                TerminologyAlias.alias_normalized == alias_normalized,
            )
        )
        return result.scalar_one_or_none()

    async def load_active_alias_map(
        self, org_id: str
    ) -> list[tuple[TerminologyEntity, list[TerminologyAlias]]]:
        """Return active entities with their aliases for expansion."""
        entities = list(
            await self.session.scalars(
                select(TerminologyEntity).where(
                    TerminologyEntity.org_id == org_id,
                    TerminologyEntity.status == TerminologyStatus.ACTIVE.value,
                )
            )
        )
        if not entities:
            return []
        aliases = await self.list_aliases_for(org_id, [e.id for e in entities])
        by_entity: dict[str, list[TerminologyAlias]] = {e.id: [] for e in entities}
        for alias in aliases:
            by_entity.setdefault(alias.entity_id, []).append(alias)
        return [(e, by_entity.get(e.id, [])) for e in entities]

    def add(self, obj: TerminologyEntity | TerminologyAlias) -> None:
        self.session.add(obj)

    async def delete_entity(self, entity: TerminologyEntity) -> None:
        await self.session.delete(entity)

    async def delete_alias(self, alias: TerminologyAlias) -> None:
        await self.session.delete(alias)
