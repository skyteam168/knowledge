"""Admin facade over EntityIdentityService."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.entity_identity import CanonicalEntity, CanonicalEntityStatus, EntityIdentifier
from app.schemas.common import Page
from app.schemas.identity_admin import (
    CanonicalCreate,
    CanonicalOut,
    IdentifierCreate,
    IdentifierOut,
    ResolveMatchIn,
    ResolveMatchOut,
)
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.structured.identity import EntityIdentityService

RESOURCE = "canonical_entity"


class IdentityAdminService(BaseService):
    def __init__(
        self, session: AsyncSession, ctx: RequestContext, authz_cache: AuthzCache
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.identity = EntityIdentityService(session)

    async def list_canonical(
        self,
        *,
        page: int = 1,
        size: int = 20,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> Page[CanonicalOut]:
        filters = [CanonicalEntity.org_id == self.org_id]
        if object_type:
            filters.append(CanonicalEntity.object_type == object_type.strip().lower())
        if status:
            filters.append(CanonicalEntity.status == status.strip().lower())
        if q:
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    CanonicalEntity.display_name.ilike(like),
                    CanonicalEntity.id.ilike(like),
                )
            )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(CanonicalEntity).where(*filters)
            )
            or 0
        )
        rows = list(
            await self.session.scalars(
                select(CanonicalEntity)
                .where(*filters)
                .order_by(CanonicalEntity.updated_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        items = [await self._canonical_out(r, include_ids=False) for r in rows]
        return Page(items=items, total=total, page=page, size=size)

    async def create_canonical(self, data: CanonicalCreate) -> CanonicalOut:
        row = await self.identity.create_canonical(
            self.org_id,
            data.object_type,
            data.display_name,
            structured_object_type=data.structured_object_type,
            structured_object_id=data.structured_object_id,
            status=data.status,
        )
        out = await self._canonical_out(row)
        await self.audit.record(
            self.audit_ctx,
            "canonical_entity.create",
            RESOURCE,
            row.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def get_canonical(self, canonical_id: str) -> CanonicalOut:
        row = await self._get(canonical_id)
        return await self._canonical_out(row, include_ids=True)

    async def add_identifier(
        self, canonical_id: str, data: IdentifierCreate
    ) -> IdentifierOut:
        await self._get(canonical_id)
        row = await self.identity.attach_identifier(
            canonical_id,
            org_id=self.org_id,
            system=data.system,
            external_id=data.external_id,
            id_kind=data.id_kind,
            is_primary=data.is_primary,
        )
        out = self._id_out(row)
        await self.audit.record(
            self.audit_ctx,
            "entity_identifier.create",
            RESOURCE,
            row.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def delete_identifier(self, identifier_id: str) -> None:
        row = await self.session.scalar(
            select(EntityIdentifier).where(
                EntityIdentifier.org_id == self.org_id,
                EntityIdentifier.id == identifier_id,
            )
        )
        if row is None:
            raise NotFoundError("Identifier not found")
        before = self._id_out(row).model_dump(mode="json")
        await self.session.delete(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "entity_identifier.delete",
            RESOURCE,
            identifier_id,
            before,
            None,
        )

    async def list_conflicts(
        self, *, page: int = 1, size: int = 20
    ) -> Page[CanonicalOut]:
        return await self.list_canonical(
            page=page,
            size=size,
            status=CanonicalEntityStatus.CONFLICT.value,
        )

    async def resolve_match(self, data: ResolveMatchIn) -> ResolveMatchOut:
        result = await self.identity.resolve_match(self.org_id, data.identifiers)
        canonical = None
        if result.canonical is not None:
            canonical = await self._canonical_out(result.canonical, include_ids=True)
        return ResolveMatchOut(
            status=result.status,
            canonical_ids=result.canonical_ids,
            canonical=canonical,
        )

    async def _get(self, canonical_id: str) -> CanonicalEntity:
        row = await self.session.scalar(
            select(CanonicalEntity).where(
                CanonicalEntity.org_id == self.org_id,
                CanonicalEntity.id == canonical_id,
            )
        )
        if row is None:
            raise NotFoundError("Canonical entity not found")
        return row

    async def _canonical_out(
        self, row: CanonicalEntity, *, include_ids: bool = True
    ) -> CanonicalOut:
        ids: list[IdentifierOut] = []
        if include_ids:
            id_rows = await self.identity.list_identifiers(self.org_id, row.id)
            ids = [self._id_out(i) for i in id_rows]
        return CanonicalOut(
            id=row.id,
            object_type=row.object_type,
            display_name=row.display_name,
            status=row.status,
            structured_object_type=row.structured_object_type,
            structured_object_id=row.structured_object_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            identifiers=ids,
        )

    @staticmethod
    def _id_out(row: EntityIdentifier) -> IdentifierOut:
        return IdentifierOut(
            id=row.id,
            canonical_id=row.canonical_id,
            system=row.system,
            id_kind=row.id_kind,
            external_id=row.external_id,
            is_primary=row.is_primary,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
