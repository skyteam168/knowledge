from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EquipDevice,
    EquipSparePart,
    EquipWorkOrder,
    KnowledgeObject,
    StructuredDomain,
    StructuredEntityLink,
    StructuredRecord,
    StructuredSource,
    TerminologyEntity,
)


class StructuredRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- sources ------------------------------------------------------------------

    async def get_source(self, org_id: str, source_id: str) -> StructuredSource | None:
        return await self.session.scalar(
            select(StructuredSource).where(
                StructuredSource.org_id == org_id, StructuredSource.id == source_id
            )
        )

    async def get_source_by_name(self, org_id: str, name: str) -> StructuredSource | None:
        return await self.session.scalar(
            select(StructuredSource).where(
                StructuredSource.org_id == org_id, StructuredSource.name == name
            )
        )

    async def list_sources(self, org_id: str) -> list[StructuredSource]:
        rows = await self.session.scalars(
            select(StructuredSource)
            .where(StructuredSource.org_id == org_id)
            .order_by(StructuredSource.name, StructuredSource.id)
        )
        return list(rows)

    def add_source(self, row: StructuredSource) -> None:
        self.session.add(row)

    async def delete_source(self, row: StructuredSource) -> None:
        await self.session.delete(row)

    # ---- domains ------------------------------------------------------------------

    async def get_domain(self, org_id: str, domain_id: str) -> StructuredDomain | None:
        return await self.session.scalar(
            select(StructuredDomain).where(
                StructuredDomain.org_id == org_id, StructuredDomain.id == domain_id
            )
        )

    async def get_domain_by_code(self, org_id: str, code: str) -> StructuredDomain | None:
        return await self.session.scalar(
            select(StructuredDomain).where(
                StructuredDomain.org_id == org_id, StructuredDomain.code == code
            )
        )

    async def list_domains(self, org_id: str) -> list[StructuredDomain]:
        rows = await self.session.scalars(
            select(StructuredDomain)
            .where(StructuredDomain.org_id == org_id)
            .order_by(StructuredDomain.code, StructuredDomain.id)
        )
        return list(rows)

    def add_domain(self, row: StructuredDomain) -> None:
        self.session.add(row)

    # ---- generic records ----------------------------------------------------------

    async def get_record(self, org_id: str, record_id: str) -> StructuredRecord | None:
        return await self.session.scalar(
            select(StructuredRecord).where(
                StructuredRecord.org_id == org_id, StructuredRecord.id == record_id
            )
        )

    async def get_record_by_external(
        self,
        org_id: str,
        object_type: str,
        external_id: str,
        *,
        source_id: str | None = None,
        domain_id: str | None = None,
    ) -> StructuredRecord | None:
        filters = [
            StructuredRecord.org_id == org_id,
            StructuredRecord.object_type == object_type,
            StructuredRecord.external_id == external_id,
        ]
        if source_id:
            filters.append(StructuredRecord.source_id == source_id)
        if domain_id:
            filters.append(StructuredRecord.domain_id == domain_id)
        return await self.session.scalar(select(StructuredRecord).where(*filters))

    async def list_records(
        self,
        org_id: str,
        *,
        domain_id: str,
        page: int,
        size: int,
        q: str | None = None,
        source_id: str | None = None,
        object_type: str | None = None,
    ) -> tuple[list[StructuredRecord], int]:
        filters = [
            StructuredRecord.org_id == org_id,
            StructuredRecord.domain_id == domain_id,
        ]
        if source_id:
            filters.append(StructuredRecord.source_id == source_id)
        if object_type:
            filters.append(StructuredRecord.object_type == object_type)
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    StructuredRecord.title.ilike(like),
                    StructuredRecord.external_id.ilike(like),
                    StructuredRecord.object_type.ilike(like),
                )
            )
        stmt = (
            select(StructuredRecord)
            .where(*filters)
            .order_by(StructuredRecord.object_type, StructuredRecord.external_id)
        )
        page_stmt, count_stmt = self._page(stmt, page=page, size=size)
        total = await self.session.scalar(count_stmt)
        return list(await self.session.scalars(page_stmt)), int(total or 0)

    def add_record(self, row: StructuredRecord) -> None:
        self.session.add(row)

    async def list_records_by_parent(
        self,
        org_id: str,
        *,
        parent_object_type: str,
        parent_external_id: str,
        object_type: str | None = None,
        source_id: str | None = None,
        limit: int = 200,
    ) -> list[StructuredRecord]:
        filters = [
            StructuredRecord.org_id == org_id,
            StructuredRecord.parent_object_type == parent_object_type,
            StructuredRecord.parent_external_id == parent_external_id,
        ]
        if object_type:
            filters.append(StructuredRecord.object_type == object_type)
        if source_id:
            filters.append(StructuredRecord.source_id == source_id)
        rows = await self.session.scalars(
            select(StructuredRecord)
            .where(*filters)
            .order_by(StructuredRecord.object_type, StructuredRecord.external_id)
            .limit(max(1, min(limit, 500)))
        )
        return list(rows)

    # ---- generic list helpers -----------------------------------------------------

    def _page(self, stmt: Select[Any], *, page: int, size: int) -> tuple[Select[Any], Select[Any]]:
        count = select(func.count()).select_from(stmt.order_by(None).subquery())
        return stmt.offset((page - 1) * size).limit(size), count

    async def list_devices(
        self,
        org_id: str,
        *,
        page: int,
        size: int,
        q: str | None = None,
        source_id: str | None = None,
    ) -> tuple[list[EquipDevice], int]:
        filters = [EquipDevice.org_id == org_id]
        if source_id:
            filters.append(EquipDevice.source_id == source_id)
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                or_(EquipDevice.name.ilike(like), EquipDevice.external_id.ilike(like))
            )
        stmt = (
            select(EquipDevice)
            .where(*filters)
            .order_by(EquipDevice.external_id, EquipDevice.id)
        )
        page_stmt, count_stmt = self._page(stmt, page=page, size=size)
        total = await self.session.scalar(count_stmt)
        return list(await self.session.scalars(page_stmt)), int(total or 0)

    async def list_work_orders(
        self,
        org_id: str,
        *,
        page: int,
        size: int,
        q: str | None = None,
        source_id: str | None = None,
    ) -> tuple[list[EquipWorkOrder], int]:
        filters = [EquipWorkOrder.org_id == org_id]
        if source_id:
            filters.append(EquipWorkOrder.source_id == source_id)
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    EquipWorkOrder.title.ilike(like),
                    EquipWorkOrder.external_id.ilike(like),
                    EquipWorkOrder.device_external_id.ilike(like),
                )
            )
        stmt = (
            select(EquipWorkOrder)
            .where(*filters)
            .order_by(EquipWorkOrder.external_id, EquipWorkOrder.id)
        )
        page_stmt, count_stmt = self._page(stmt, page=page, size=size)
        total = await self.session.scalar(count_stmt)
        return list(await self.session.scalars(page_stmt)), int(total or 0)

    async def list_spare_parts(
        self,
        org_id: str,
        *,
        page: int,
        size: int,
        q: str | None = None,
        source_id: str | None = None,
    ) -> tuple[list[EquipSparePart], int]:
        filters = [EquipSparePart.org_id == org_id]
        if source_id:
            filters.append(EquipSparePart.source_id == source_id)
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    EquipSparePart.name.ilike(like),
                    EquipSparePart.external_id.ilike(like),
                    EquipSparePart.sku.ilike(like),
                )
            )
        stmt = (
            select(EquipSparePart)
            .where(*filters)
            .order_by(EquipSparePart.external_id, EquipSparePart.id)
        )
        page_stmt, count_stmt = self._page(stmt, page=page, size=size)
        total = await self.session.scalar(count_stmt)
        return list(await self.session.scalars(page_stmt)), int(total or 0)

    async def get_device(self, org_id: str, device_id: str) -> EquipDevice | None:
        return await self.session.scalar(
            select(EquipDevice).where(EquipDevice.org_id == org_id, EquipDevice.id == device_id)
        )

    async def get_device_by_external(
        self, org_id: str, external_id: str, *, source_id: str | None = None
    ) -> EquipDevice | None:
        filters = [EquipDevice.org_id == org_id, EquipDevice.external_id == external_id]
        if source_id:
            filters.append(EquipDevice.source_id == source_id)
        return await self.session.scalar(select(EquipDevice).where(*filters))

    async def get_work_order(self, org_id: str, wo_id: str) -> EquipWorkOrder | None:
        return await self.session.scalar(
            select(EquipWorkOrder).where(
                EquipWorkOrder.org_id == org_id, EquipWorkOrder.id == wo_id
            )
        )

    async def get_work_order_by_external(
        self, org_id: str, external_id: str, *, source_id: str | None = None
    ) -> EquipWorkOrder | None:
        filters = [EquipWorkOrder.org_id == org_id, EquipWorkOrder.external_id == external_id]
        if source_id:
            filters.append(EquipWorkOrder.source_id == source_id)
        return await self.session.scalar(select(EquipWorkOrder).where(*filters))

    async def get_spare_part(self, org_id: str, part_id: str) -> EquipSparePart | None:
        return await self.session.scalar(
            select(EquipSparePart).where(
                EquipSparePart.org_id == org_id, EquipSparePart.id == part_id
            )
        )

    async def get_spare_part_by_external(
        self, org_id: str, external_id: str, *, source_id: str | None = None
    ) -> EquipSparePart | None:
        filters = [EquipSparePart.org_id == org_id, EquipSparePart.external_id == external_id]
        if source_id:
            filters.append(EquipSparePart.source_id == source_id)
        return await self.session.scalar(select(EquipSparePart).where(*filters))

    def add_device(self, row: EquipDevice) -> None:
        self.session.add(row)

    def add_work_order(self, row: EquipWorkOrder) -> None:
        self.session.add(row)

    def add_spare_part(self, row: EquipSparePart) -> None:
        self.session.add(row)

    # ---- links --------------------------------------------------------------------

    async def get_link(self, org_id: str, link_id: str) -> StructuredEntityLink | None:
        return await self.session.scalar(
            select(StructuredEntityLink).where(
                StructuredEntityLink.org_id == org_id, StructuredEntityLink.id == link_id
            )
        )

    async def list_links_for(
        self, org_id: str, object_type: str, object_id: str
    ) -> list[StructuredEntityLink]:
        rows = await self.session.scalars(
            select(StructuredEntityLink)
            .where(
                StructuredEntityLink.org_id == org_id,
                StructuredEntityLink.object_type == object_type,
                StructuredEntityLink.object_id == object_id,
            )
            .order_by(StructuredEntityLink.created_at.desc(), StructuredEntityLink.id)
        )
        return list(rows)

    async def list_links_for_term(
        self, org_id: str, terminology_entity_id: str
    ) -> list[StructuredEntityLink]:
        rows = await self.session.scalars(
            select(StructuredEntityLink)
            .where(
                StructuredEntityLink.org_id == org_id,
                StructuredEntityLink.terminology_entity_id == terminology_entity_id,
            )
            .order_by(StructuredEntityLink.created_at.desc(), StructuredEntityLink.id)
        )
        return list(rows)

    async def find_link(
        self,
        org_id: str,
        *,
        object_type: str,
        object_id: str,
        terminology_entity_id: str | None,
        ko_id: str | None,
    ) -> StructuredEntityLink | None:
        return await self.session.scalar(
            select(StructuredEntityLink).where(
                StructuredEntityLink.org_id == org_id,
                StructuredEntityLink.object_type == object_type,
                StructuredEntityLink.object_id == object_id,
                StructuredEntityLink.terminology_entity_id == terminology_entity_id,
                StructuredEntityLink.ko_id == ko_id,
            )
        )

    def add_link(self, row: StructuredEntityLink) -> None:
        self.session.add(row)

    async def delete_link(self, row: StructuredEntityLink) -> None:
        await self.session.delete(row)

    async def terminology_names(
        self, org_id: str, entity_ids: Sequence[str]
    ) -> dict[str, str]:
        if not entity_ids:
            return {}
        rows = await self.session.scalars(
            select(TerminologyEntity).where(
                TerminologyEntity.org_id == org_id,
                TerminologyEntity.id.in_(list(entity_ids)),
            )
        )
        return {e.id: e.canonical_name for e in rows}

    async def ko_titles(self, org_id: str, ko_ids: Sequence[str]) -> dict[str, str]:
        if not ko_ids:
            return {}
        rows = await self.session.scalars(
            select(KnowledgeObject).where(
                KnowledgeObject.org_id == org_id, KnowledgeObject.id.in_(list(ko_ids))
            )
        )
        return {k.id: k.title for k in rows}

    async def get_terminology(self, org_id: str, entity_id: str) -> TerminologyEntity | None:
        return await self.session.scalar(
            select(TerminologyEntity).where(
                TerminologyEntity.org_id == org_id, TerminologyEntity.id == entity_id
            )
        )

    async def get_ko(self, org_id: str, ko_id: str) -> KnowledgeObject | None:
        return await self.session.scalar(
            select(KnowledgeObject).where(
                KnowledgeObject.org_id == org_id, KnowledgeObject.id == ko_id
            )
        )
