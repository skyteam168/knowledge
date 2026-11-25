"""Canonical entity identity resolution and multi-system identifier mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.entity_identity import (
    CanonicalEntity,
    CanonicalEntityStatus,
    EntityIdentifier,
)


@dataclass(frozen=True)
class MatchResult:
    status: str
    canonical_ids: list[str] = field(default_factory=list)
    canonical: CanonicalEntity | None = None


class EntityIdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_canonical(
        self,
        org_id: str,
        object_type: str,
        display_name: str,
        *,
        structured_object_type: str | None = None,
        structured_object_id: str | None = None,
        status: str = CanonicalEntityStatus.ACTIVE.value,
    ) -> CanonicalEntity:
        entity = CanonicalEntity(
            org_id=org_id,
            object_type=object_type.strip().lower(),
            display_name=display_name.strip(),
            status=status,
            structured_object_type=structured_object_type,
            structured_object_id=structured_object_id,
        )
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def attach_identifier(
        self,
        canonical_id: str,
        *,
        org_id: str,
        system: str,
        external_id: str,
        id_kind: str = "external_id",
        is_primary: bool = False,
    ) -> EntityIdentifier:
        system_n = system.strip().lower()
        kind_n = id_kind.strip().lower() or "external_id"
        ext_n = external_id.strip()
        if not ext_n:
            raise ConflictError(message="external_id required")

        existing = await self.session.scalar(
            select(EntityIdentifier).where(
                EntityIdentifier.org_id == org_id,
                EntityIdentifier.system == system_n,
                EntityIdentifier.id_kind == kind_n,
                EntityIdentifier.external_id == ext_n,
            )
        )
        if existing is not None:
            if existing.canonical_id != canonical_id:
                raise ConflictError(
                    message=(
                        f"identifier {system_n}/{kind_n}/{ext_n} already bound to "
                        f"another canonical entity (conflict)"
                    )
                )
            if is_primary and not existing.is_primary:
                existing.is_primary = True
                await self.session.flush()
            return existing

        row = EntityIdentifier(
            org_id=org_id,
            canonical_id=canonical_id,
            system=system_n,
            id_kind=kind_n,
            external_id=ext_n,
            is_primary=is_primary,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def resolve_identifier(
        self,
        org_id: str,
        *,
        system: str,
        external_id: str,
        id_kind: str | None = None,
        object_type: str | None = None,
    ) -> CanonicalEntity | None:
        system_n = system.strip().lower()
        ext_n = external_id.strip()
        stmt = (
            select(CanonicalEntity)
            .join(EntityIdentifier, EntityIdentifier.canonical_id == CanonicalEntity.id)
            .where(
                CanonicalEntity.org_id == org_id,
                EntityIdentifier.org_id == org_id,
                EntityIdentifier.system == system_n,
                EntityIdentifier.external_id == ext_n,
            )
        )
        if id_kind:
            stmt = stmt.where(EntityIdentifier.id_kind == id_kind.strip().lower())
        if object_type:
            stmt = stmt.where(CanonicalEntity.object_type == object_type.strip().lower())
        return await self.session.scalar(stmt)

    async def resolve_match(
        self,
        org_id: str,
        identifiers: list[dict[str, Any]],
    ) -> MatchResult:
        """Resolve a set of system identifiers.

        - 0 hits → status unknown
        - 1 unique canonical → matched
        - ≥2 distinct canonicals → conflict (no silent merge)
        """
        found: dict[str, CanonicalEntity] = {}
        for item in identifiers:
            system = str(item.get("system") or "").strip()
            external_id = str(item.get("external_id") or "").strip()
            if not system or not external_id:
                continue
            id_kind = item.get("id_kind")
            entity = await self.resolve_identifier(
                org_id,
                system=system,
                external_id=external_id,
                id_kind=str(id_kind) if id_kind else None,
            )
            if entity is not None:
                found[entity.id] = entity

        ids = list(found.keys())
        if not ids:
            return MatchResult(status="unknown", canonical_ids=[])
        if len(ids) == 1:
            only = found[ids[0]]
            return MatchResult(
                status="matched",
                canonical_ids=ids,
                canonical=only,
            )
        for entity in found.values():
            if entity.status != CanonicalEntityStatus.CONFLICT.value:
                entity.status = CanonicalEntityStatus.CONFLICT.value
        await self.session.flush()
        return MatchResult(status="conflict", canonical_ids=ids)

    async def list_identifiers(
        self, org_id: str, canonical_id: str
    ) -> list[EntityIdentifier]:
        rows = await self.session.scalars(
            select(EntityIdentifier)
            .where(
                EntityIdentifier.org_id == org_id,
                EntityIdentifier.canonical_id == canonical_id,
            )
            .order_by(EntityIdentifier.system, EntityIdentifier.id_kind)
        )
        return list(rows)

    async def get_by_structured(
        self,
        org_id: str,
        *,
        structured_object_type: str,
        structured_object_id: str,
    ) -> CanonicalEntity | None:
        return await self.session.scalar(
            select(CanonicalEntity).where(
                CanonicalEntity.org_id == org_id,
                CanonicalEntity.structured_object_type
                == structured_object_type.strip().lower(),
                CanonicalEntity.structured_object_id == structured_object_id,
            )
        )

    async def ensure_for_structured(
        self,
        org_id: str,
        *,
        object_type: str,
        display_name: str,
        structured_object_id: str,
        system: str | None = None,
        external_id: str | None = None,
        id_kind: str = "external_id",
    ) -> CanonicalEntity:
        """Idempotent: mirror row → canonical (+ optional primary system id)."""
        existing = await self.get_by_structured(
            org_id,
            structured_object_type=object_type,
            structured_object_id=structured_object_id,
        )
        if existing is None:
            existing = await self.create_canonical(
                org_id,
                object_type=object_type,
                display_name=display_name,
                structured_object_type=object_type,
                structured_object_id=structured_object_id,
            )
        if system and external_id:
            await self.attach_identifier(
                existing.id,
                org_id=org_id,
                system=system,
                external_id=external_id,
                id_kind=id_kind,
                is_primary=True,
            )
        return existing
