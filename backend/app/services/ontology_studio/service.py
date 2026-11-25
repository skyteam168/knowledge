"""OS1: semantic model versions, entities, attributes, mappings, publish."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import utcnow
from app.models.semantic import (
    SemanticAttribute,
    SemanticEntity,
    SemanticItemStatus,
    SemanticMapping,
    SemanticModelStatus,
    SemanticModelVersion,
)
from app.schemas.semantic import (
    SchemaImportIn,
    SchemaImportOut,
    SchemaImportStats,
    SemanticAttributeCreate,
    SemanticAttributeOut,
    SemanticAttributeUpdate,
    SemanticBatchStatusIn,
    SemanticBatchStatusOut,
    SemanticEntityCreate,
    SemanticEntityOut,
    SemanticMappingCreate,
    SemanticMappingOut,
    SemanticSuggestOut,
    SemanticVersionCreate,
    SemanticVersionDetailOut,
    SemanticVersionOut,
)
from app.services.context import BaseService, RequestContext
from app.services.authz.cache import AuthzCache

RESOURCE = "semantic_model"

_APPROVED = SemanticItemStatus.APPROVED.value


class OntologyStudioService(BaseService):
    def __init__(
        self, session: AsyncSession, ctx: RequestContext, authz_cache: AuthzCache
    ) -> None:
        super().__init__(session, ctx, authz_cache)

    async def list_versions(self) -> list[SemanticVersionOut]:
        rows = await self.session.scalars(
            select(SemanticModelVersion)
            .where(SemanticModelVersion.org_id == self.org_id)
            .order_by(SemanticModelVersion.created_at.desc())
        )
        return [self._version_out(r) for r in rows]

    async def get_version(self, version_id: str) -> SemanticVersionDetailOut:
        row = await self._get_version_row(version_id)
        entities = list(
            await self.session.scalars(
                select(SemanticEntity)
                .where(
                    SemanticEntity.org_id == self.org_id,
                    SemanticEntity.version_id == version_id,
                )
                .order_by(SemanticEntity.local_name)
            )
        )
        attrs = list(
            await self.session.scalars(
                select(SemanticAttribute)
                .where(
                    SemanticAttribute.org_id == self.org_id,
                    SemanticAttribute.version_id == version_id,
                )
                .order_by(SemanticAttribute.name)
            )
        )
        mappings = list(
            await self.session.scalars(
                select(SemanticMapping)
                .where(
                    SemanticMapping.org_id == self.org_id,
                    SemanticMapping.version_id == version_id,
                )
                .order_by(SemanticMapping.table_name, SemanticMapping.column_name)
            )
        )
        base = self._version_out(row)
        return SemanticVersionDetailOut(
            **base.model_dump(),
            entities=[self._entity_out(e) for e in entities],
            attributes=[self._attr_out(a) for a in attrs],
            mappings=[self._map_out(m) for m in mappings],
        )

    async def get_active_published(self) -> SemanticModelVersion | None:
        return await self.session.scalar(
            select(SemanticModelVersion).where(
                SemanticModelVersion.org_id == self.org_id,
                SemanticModelVersion.status == SemanticModelStatus.PUBLISHED.value,
                SemanticModelVersion.is_active.is_(True),
            )
        )

    async def create_version(self, data: SemanticVersionCreate) -> SemanticVersionOut:
        row = SemanticModelVersion(
            org_id=self.org_id,
            name=data.name.strip(),
            status=SemanticModelStatus.DRAFT.value,
            is_active=False,
            notes=(data.notes or "").strip() or None,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        out = self._version_out(row)
        await self.audit.record(
            self.audit_ctx,
            "semantic_model.create",
            RESOURCE,
            row.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def add_entity(
        self, version_id: str, data: SemanticEntityCreate
    ) -> SemanticEntityOut:
        version = await self._require_draft(version_id)
        local = data.local_name.strip()
        existing = await self.session.scalar(
            select(SemanticEntity).where(
                SemanticEntity.org_id == self.org_id,
                SemanticEntity.version_id == version.id,
                SemanticEntity.local_name == local,
            )
        )
        if existing is not None:
            raise ConflictError("Entity local_name already exists in this version")
        row = SemanticEntity(
            org_id=self.org_id,
            version_id=version.id,
            local_name=local,
            label=data.label.strip(),
            description=(data.description or "").strip() or None,
            object_type=(data.object_type or "").strip().lower() or None,
            owners=[o.strip() for o in (data.owners or []) if o and o.strip()],
            status=SemanticItemStatus.DRAFT.value,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        return self._entity_out(row)

    async def add_attribute(
        self, entity_id: str, data: SemanticAttributeCreate
    ) -> SemanticAttributeOut:
        entity = await self.session.scalar(
            select(SemanticEntity).where(
                SemanticEntity.org_id == self.org_id, SemanticEntity.id == entity_id
            )
        )
        if entity is None:
            raise NotFoundError("Semantic entity not found")
        await self._require_draft(entity.version_id)
        name = data.name.strip()
        existing = await self.session.scalar(
            select(SemanticAttribute).where(
                SemanticAttribute.org_id == self.org_id,
                SemanticAttribute.entity_id == entity_id,
                SemanticAttribute.name == name,
            )
        )
        if existing is not None:
            raise ConflictError("Attribute name already exists on this entity")
        row = SemanticAttribute(
            org_id=self.org_id,
            version_id=entity.version_id,
            entity_id=entity.id,
            name=name,
            label=data.label.strip(),
            description=(data.description or "").strip() or None,
            attr_kind=(data.attr_kind or "string").strip().lower() or "string",
            unit=(data.unit or None),
            enum_map=dict(data.enum_map or {}),
            labels={str(k): str(v) for k, v in (data.labels or {}).items()},
            status=SemanticItemStatus.DRAFT.value,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        return self._attr_out(row)

    async def update_attribute(
        self, attribute_id: str, data: SemanticAttributeUpdate
    ) -> SemanticAttributeOut:
        attr = await self.session.scalar(
            select(SemanticAttribute).where(
                SemanticAttribute.org_id == self.org_id,
                SemanticAttribute.id == attribute_id,
            )
        )
        if attr is None:
            raise NotFoundError("Semantic attribute not found")
        await self._require_draft(attr.version_id)
        if data.label is not None:
            attr.label = data.label.strip()
        if data.description is not None:
            attr.description = data.description.strip() or None
        if data.attr_kind is not None:
            attr.attr_kind = data.attr_kind.strip().lower() or "string"
        if data.unit is not None:
            attr.unit = data.unit
        if data.enum_map is not None:
            attr.enum_map = dict(data.enum_map)
        if data.labels is not None:
            attr.labels = {str(k): str(v) for k, v in data.labels.items()}
        await self.session.flush()
        return self._attr_out(attr)

    async def add_mapping(
        self, attribute_id: str, data: SemanticMappingCreate
    ) -> SemanticMappingOut:
        attr = await self.session.scalar(
            select(SemanticAttribute).where(
                SemanticAttribute.org_id == self.org_id,
                SemanticAttribute.id == attribute_id,
            )
        )
        if attr is None:
            raise NotFoundError("Semantic attribute not found")
        await self._require_draft(attr.version_id)
        table = data.table_name.strip()
        column = data.column_name.strip()
        existing = await self.session.scalar(
            select(SemanticMapping).where(
                SemanticMapping.org_id == self.org_id,
                SemanticMapping.attribute_id == attribute_id,
                SemanticMapping.table_name == table,
                SemanticMapping.column_name == column,
            )
        )
        if existing is not None:
            raise ConflictError("Mapping already exists")
        row = SemanticMapping(
            org_id=self.org_id,
            version_id=attr.version_id,
            attribute_id=attr.id,
            source_id=(data.source_id or "").strip() or None,
            table_name=table,
            column_name=column,
            source_of_truth=bool(data.source_of_truth),
            freshness_sla_seconds=data.freshness_sla_seconds,
            status=SemanticItemStatus.DRAFT.value,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        return self._map_out(row)

    async def set_entity_status(
        self, entity_id: str, status: str
    ) -> SemanticEntityOut:
        entity = await self.session.scalar(
            select(SemanticEntity).where(
                SemanticEntity.org_id == self.org_id, SemanticEntity.id == entity_id
            )
        )
        if entity is None:
            raise NotFoundError("Semantic entity not found")
        await self._require_draft(entity.version_id)
        entity.status = status
        await self.session.flush()
        return self._entity_out(entity)

    async def set_attribute_status(
        self, attribute_id: str, status: str
    ) -> SemanticAttributeOut:
        attr = await self.session.scalar(
            select(SemanticAttribute).where(
                SemanticAttribute.org_id == self.org_id,
                SemanticAttribute.id == attribute_id,
            )
        )
        if attr is None:
            raise NotFoundError("Semantic attribute not found")
        await self._require_draft(attr.version_id)
        attr.status = status
        await self.session.flush()
        return self._attr_out(attr)

    async def set_mapping_status(
        self, mapping_id: str, status: str
    ) -> SemanticMappingOut:
        row = await self.session.scalar(
            select(SemanticMapping).where(
                SemanticMapping.org_id == self.org_id, SemanticMapping.id == mapping_id
            )
        )
        if row is None:
            raise NotFoundError("Semantic mapping not found")
        await self._require_draft(row.version_id)
        row.status = status
        await self.session.flush()
        return self._map_out(row)

    async def publish(self, version_id: str) -> SemanticVersionOut:
        version = await self._get_version_row(version_id)
        if version.status == SemanticModelStatus.PUBLISHED.value and version.is_active:
            return self._version_out(version)
        if version.status == SemanticModelStatus.ARCHIVED.value:
            raise ValidationAppError("Cannot publish an archived version")

        entities = list(
            await self.session.scalars(
                select(SemanticEntity).where(
                    SemanticEntity.org_id == self.org_id,
                    SemanticEntity.version_id == version_id,
                )
            )
        )
        if not entities:
            raise ValidationAppError("Cannot publish an empty semantic model")
        if not any(e.status == _APPROVED for e in entities):
            raise ValidationAppError(
                "Publish requires at least one approved entity",
                detail={"hint": "Approve entities before publish"},
            )

        # Deactivate previous active published
        await self.session.execute(
            update(SemanticModelVersion)
            .where(
                SemanticModelVersion.org_id == self.org_id,
                SemanticModelVersion.is_active.is_(True),
            )
            .values(
                is_active=False,
                status=SemanticModelStatus.ARCHIVED.value,
            )
        )
        version.status = SemanticModelStatus.PUBLISHED.value
        version.is_active = True
        version.published_at = utcnow()
        version.published_by = self.ctx.user.id
        await self.session.flush()
        out = self._version_out(version)
        await self.audit.record(
            self.audit_ctx,
            "semantic_model.publish",
            RESOURCE,
            version.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def rollback_publish(self, version_id: str) -> SemanticVersionOut:
        """Re-activate a previously published (archived) version as the active published."""
        version = await self._get_version_row(version_id)
        if version.status not in {
            SemanticModelStatus.PUBLISHED.value,
            SemanticModelStatus.ARCHIVED.value,
        }:
            raise ValidationAppError(
                "Only published/archived versions can be rolled back to"
            )
        if version.status == SemanticModelStatus.PUBLISHED.value and version.is_active:
            return self._version_out(version)

        await self.session.execute(
            update(SemanticModelVersion)
            .where(
                SemanticModelVersion.org_id == self.org_id,
                SemanticModelVersion.is_active.is_(True),
            )
            .values(
                is_active=False,
                status=SemanticModelStatus.ARCHIVED.value,
            )
        )
        version.status = SemanticModelStatus.PUBLISHED.value
        version.is_active = True
        version.published_at = utcnow()
        version.published_by = self.ctx.user.id
        await self.session.flush()
        out = self._version_out(version)
        await self.audit.record(
            self.audit_ctx,
            "semantic_model.rollback",
            RESOURCE,
            version.id,
            None,
            out.model_dump(mode="json"),
        )
        return out

    async def suggest_labels(
        self, version_id: str, *, dry_run: bool = False
    ) -> SemanticSuggestOut:
        """OS3: generate Chinese labels/descriptions for draft items (heuristic; LLM later).

        When ``dry_run`` is True, return proposed changes without writing.
        """
        version = await self._require_draft(version_id)
        entities = list(
            await self.session.scalars(
                select(SemanticEntity).where(
                    SemanticEntity.org_id == self.org_id,
                    SemanticEntity.version_id == version_id,
                )
            )
        )
        attrs = list(
            await self.session.scalars(
                select(SemanticAttribute).where(
                    SemanticAttribute.org_id == self.org_id,
                    SemanticAttribute.version_id == version_id,
                )
            )
        )
        suggestions: list[dict[str, object]] = []
        entities_updated = 0
        attributes_updated = 0
        for ent in entities:
            if ent.status == SemanticItemStatus.REJECTED.value:
                continue
            before_label = ent.label
            before_desc = ent.description or ""
            before_ot = ent.object_type
            label, desc = _suggest_entity_copy(ent.local_name, ent.label, ent.description)
            guessed = before_ot or _guess_object_type(ent.local_name)
            changed = (
                label != before_label
                or (bool(desc) and desc != before_desc)
                or (guessed != before_ot)
            )
            if not changed:
                continue
            entities_updated += 1
            suggestions.append(
                {
                    "kind": "entity",
                    "id": ent.id,
                    "local_name": ent.local_name,
                    "before_label": before_label,
                    "label": label,
                    "before_description": before_desc,
                    "description": desc or before_desc,
                    "before_object_type": before_ot,
                    "object_type": guessed,
                }
            )
            if not dry_run:
                ent.label = label
                if desc:
                    ent.description = desc
                if guessed and not ent.object_type:
                    ent.object_type = guessed
        for attr in attrs:
            if attr.status == SemanticItemStatus.REJECTED.value:
                continue
            before_label = attr.label
            before_desc = attr.description or ""
            before_kind = attr.attr_kind
            label, desc, kind = _suggest_attr_copy(
                attr.name, attr.label, attr.description, attr.attr_kind
            )
            changed = (
                label != before_label
                or (bool(desc) and desc != before_desc)
                or kind != before_kind
            )
            if not changed:
                continue
            attributes_updated += 1
            suggestions.append(
                {
                    "kind": "attribute",
                    "id": attr.id,
                    "name": attr.name,
                    "before_label": before_label,
                    "label": label,
                    "before_description": before_desc,
                    "description": desc or before_desc,
                    "before_attr_kind": before_kind,
                    "attr_kind": kind,
                }
            )
            if not dry_run:
                attr.label = label
                if desc:
                    attr.description = desc
                attr.attr_kind = kind
        if not dry_run:
            await self.session.flush()
            await self.audit.record(
                self.audit_ctx,
                "semantic_model.suggest",
                RESOURCE,
                version.id,
                None,
                {
                    "entities_updated": entities_updated,
                    "attributes_updated": attributes_updated,
                },
            )
        return SemanticSuggestOut(
            version_id=version.id,
            entities_updated=entities_updated,
            attributes_updated=attributes_updated,
            suggestions=suggestions,
        )

    async def batch_set_status(
        self, version_id: str, data: SemanticBatchStatusIn
    ) -> SemanticBatchStatusOut:
        await self._require_draft(version_id)
        status = data.status
        entities_updated = 0
        attributes_updated = 0
        mappings_updated = 0
        for eid in dict.fromkeys(data.entity_ids):
            row = await self.session.scalar(
                select(SemanticEntity).where(
                    SemanticEntity.org_id == self.org_id,
                    SemanticEntity.version_id == version_id,
                    SemanticEntity.id == eid,
                )
            )
            if row is None:
                continue
            row.status = status
            entities_updated += 1
        for aid in dict.fromkeys(data.attribute_ids):
            row = await self.session.scalar(
                select(SemanticAttribute).where(
                    SemanticAttribute.org_id == self.org_id,
                    SemanticAttribute.version_id == version_id,
                    SemanticAttribute.id == aid,
                )
            )
            if row is None:
                continue
            row.status = status
            attributes_updated += 1
        for mid in dict.fromkeys(data.mapping_ids):
            row = await self.session.scalar(
                select(SemanticMapping).where(
                    SemanticMapping.org_id == self.org_id,
                    SemanticMapping.version_id == version_id,
                    SemanticMapping.id == mid,
                )
            )
            if row is None:
                continue
            row.status = status
            mappings_updated += 1
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "semantic_model.batch_status",
            RESOURCE,
            version_id,
            None,
            {
                "status": status,
                "entities_updated": entities_updated,
                "attributes_updated": attributes_updated,
                "mappings_updated": mappings_updated,
            },
        )
        return SemanticBatchStatusOut(
            entities_updated=entities_updated,
            attributes_updated=attributes_updated,
            mappings_updated=mappings_updated,
        )

    async def import_schema(self, data: SchemaImportIn) -> SchemaImportOut:
        """Idempotent import of table/column lists into draft entities+attrs+mappings."""
        if data.version_id:
            version = await self._require_draft(data.version_id)
        else:
            name = (data.version_name or "").strip() or f"schema-import-{utcnow().strftime('%Y%m%d%H%M%S')}"
            created = await self.create_version(SemanticVersionCreate(name=name))
            version = await self._get_version_row(created.id)

        stats = SchemaImportStats(
            version_id=version.id,
            entities_created=0,
            entities_unchanged=0,
            attributes_created=0,
            attributes_unchanged=0,
            mappings_created=0,
            mappings_unchanged=0,
        )
        item_status = (
            SemanticItemStatus.APPROVED.value
            if data.auto_approve
            else SemanticItemStatus.DRAFT.value
        )
        source_id = (data.source_id or "").strip() or None

        for table in data.tables:
            table_name = table.name.strip()
            local_name = _table_to_local_name(table_name)
            entity = await self.session.scalar(
                select(SemanticEntity).where(
                    SemanticEntity.org_id == self.org_id,
                    SemanticEntity.version_id == version.id,
                    SemanticEntity.local_name == local_name,
                )
            )
            if entity is None:
                entity = SemanticEntity(
                    org_id=self.org_id,
                    version_id=version.id,
                    local_name=local_name,
                    label=table.comment.strip() if table.comment else local_name,
                    description=f"Imported from table `{table_name}`",
                    object_type=None,
                    owners=[],
                    status=item_status,
                    created_by=self.ctx.user.id,
                )
                self.session.add(entity)
                await self.session.flush()
                stats.entities_created += 1
            else:
                stats.entities_unchanged += 1

            for col in table.columns:
                col_name = col.name.strip()
                attr_name = _column_to_attr_name(col_name)
                attr = await self.session.scalar(
                    select(SemanticAttribute).where(
                        SemanticAttribute.org_id == self.org_id,
                        SemanticAttribute.entity_id == entity.id,
                        SemanticAttribute.name == attr_name,
                    )
                )
                if attr is None:
                    kind = _guess_attr_kind(col.data_type)
                    attr = SemanticAttribute(
                        org_id=self.org_id,
                        version_id=version.id,
                        entity_id=entity.id,
                        name=attr_name,
                        label=col.comment.strip() if col.comment else attr_name,
                        description=col.comment,
                        attr_kind=kind,
                        unit=None,
                        enum_map={},
                        labels={},
                        status=item_status,
                        created_by=self.ctx.user.id,
                    )
                    self.session.add(attr)
                    await self.session.flush()
                    stats.attributes_created += 1
                else:
                    stats.attributes_unchanged += 1

                mapping = await self.session.scalar(
                    select(SemanticMapping).where(
                        SemanticMapping.org_id == self.org_id,
                        SemanticMapping.attribute_id == attr.id,
                        SemanticMapping.table_name == table_name,
                        SemanticMapping.column_name == col_name,
                    )
                )
                if mapping is None:
                    self.session.add(
                        SemanticMapping(
                            org_id=self.org_id,
                            version_id=version.id,
                            attribute_id=attr.id,
                            source_id=source_id,
                            table_name=table_name,
                            column_name=col_name,
                            source_of_truth=False,
                            freshness_sla_seconds=None,
                            status=item_status,
                            created_by=self.ctx.user.id,
                        )
                    )
                    await self.session.flush()
                    stats.mappings_created += 1
                else:
                    stats.mappings_unchanged += 1

        await self.audit.record(
            self.audit_ctx,
            "semantic_model.import_schema",
            RESOURCE,
            version.id,
            None,
            stats.model_dump(mode="json"),
        )
        return SchemaImportOut(version=self._version_out(version), stats=stats)

    async def load_published_extension(self) -> dict[str, object]:
        """Approved entities/attrs/mappings from active published version (Agent view)."""
        version = await self.get_active_published()
        if version is None:
            return {
                "version_id": None,
                "version_name": None,
                "published_at": None,
                "entities": [],
                "attribute_schemas": [],
            }
        detail = await self.get_version(version.id)
        approved_entities = [e for e in detail.entities if e.status == _APPROVED]
        approved_ids = {e.id for e in approved_entities}
        approved_attrs = [
            a
            for a in detail.attributes
            if a.status == _APPROVED and a.entity_id in approved_ids
        ]
        attr_ids = {a.id for a in approved_attrs}
        approved_maps = [
            m
            for m in detail.mappings
            if m.status == _APPROVED and m.attribute_id in attr_ids
        ]
        by_entity: dict[str, list[SemanticAttributeOut]] = {}
        for a in approved_attrs:
            by_entity.setdefault(a.entity_id, []).append(a)
        maps_by_attr: dict[str, list[SemanticMappingOut]] = {}
        for m in approved_maps:
            maps_by_attr.setdefault(m.attribute_id, []).append(m)

        schemas = []
        for ent in approved_entities:
            attrs_out = []
            for a in by_entity.get(ent.id, []):
                represented = [
                    {
                        "table": m.table_name,
                        "column": m.column_name,
                        "source_id": m.source_id,
                        "source_of_truth": m.source_of_truth,
                        "freshness_sla_seconds": m.freshness_sla_seconds,
                    }
                    for m in maps_by_attr.get(a.id, [])
                ]
                attrs_out.append(
                    {
                        "name": a.name,
                        "label": a.label,
                        "kind": a.attr_kind,
                        "description": a.description,
                        "unit": a.unit,
                        "enum_map": a.enum_map or {},
                        "labels": a.labels or {},
                        "represented_by": represented,
                    }
                )
            schemas.append(
                {
                    "object_type": ent.object_type or ent.local_name.lower(),
                    "label": ent.label,
                    "description": ent.description or "",
                    "local_name": ent.local_name,
                    "attributes": attrs_out,
                    "source": "org_published",
                }
            )
        return {
            "version_id": version.id,
            "version_name": version.name,
            "published_at": version.published_at.isoformat()
            if version.published_at
            else None,
            "entities": [
                {
                    "local_name": e.local_name,
                    "label": e.label,
                    "description": e.description,
                    "object_type": e.object_type,
                    "owners": e.owners or [],
                }
                for e in approved_entities
            ],
            "attribute_schemas": schemas,
        }

    async def _get_version_row(self, version_id: str) -> SemanticModelVersion:
        row = await self.session.scalar(
            select(SemanticModelVersion).where(
                SemanticModelVersion.org_id == self.org_id,
                SemanticModelVersion.id == version_id,
            )
        )
        if row is None:
            raise NotFoundError("Semantic model version not found")
        return row

    async def _require_draft(self, version_id: str) -> SemanticModelVersion:
        row = await self._get_version_row(version_id)
        if row.status != SemanticModelStatus.DRAFT.value:
            raise ValidationAppError("Only draft versions can be edited")
        return row

    @staticmethod
    def _version_out(row: SemanticModelVersion) -> SemanticVersionOut:
        return SemanticVersionOut(
            id=row.id,
            name=row.name,
            status=row.status,
            is_active=row.is_active,
            notes=row.notes,
            published_at=row.published_at,
            published_by=row.published_by,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _entity_out(row: SemanticEntity) -> SemanticEntityOut:
        return SemanticEntityOut(
            id=row.id,
            version_id=row.version_id,
            local_name=row.local_name,
            label=row.label,
            description=row.description,
            object_type=row.object_type,
            owners=[str(o) for o in (row.owners or [])],
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _attr_out(row: SemanticAttribute) -> SemanticAttributeOut:
        return SemanticAttributeOut(
            id=row.id,
            version_id=row.version_id,
            entity_id=row.entity_id,
            name=row.name,
            label=row.label,
            description=row.description,
            attr_kind=row.attr_kind,
            unit=row.unit,
            enum_map=dict(row.enum_map or {}),
            labels={str(k): str(v) for k, v in (row.labels or {}).items()},
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _map_out(row: SemanticMapping) -> SemanticMappingOut:
        return SemanticMappingOut(
            id=row.id,
            version_id=row.version_id,
            attribute_id=row.attribute_id,
            source_id=row.source_id,
            table_name=row.table_name,
            column_name=row.column_name,
            source_of_truth=bool(row.source_of_truth),
            freshness_sla_seconds=row.freshness_sla_seconds,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _table_to_local_name(table: str) -> str:
    parts = [p for p in table.replace("-", "_").split("_") if p]
    if not parts:
        return "Table"
    return "".join(p[:1].upper() + p[1:] for p in parts)


def _column_to_attr_name(column: str) -> str:
    parts = [p for p in column.replace("-", "_").split("_") if p]
    if not parts:
        return "field"
    head, *rest = parts
    return head.lower() + "".join(p[:1].upper() + p[1:].lower() for p in rest)


def _guess_attr_kind(data_type: str | None) -> str:
    raw = (data_type or "").strip().lower()
    if not raw:
        return "string"
    if any(t in raw for t in ("int", "float", "double", "numeric", "decimal", "number")):
        return "number"
    if any(t in raw for t in ("bool", "bit")):
        return "boolean"
    if any(t in raw for t in ("date", "time")):
        return "datetime"
    if any(t in raw for t in ("json", "jsonb")):
        return "json"
    return "string"


# Heuristic bilingual glossary for industrial / common columns (OS3 without LLM).
_ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "EquipDevices": ("设备", "设备主数据（equip_devices）"),
    "EquipWorkOrders": ("工单", "维保/维修工单"),
    "EquipSpareParts": ("备件", "备件库存"),
    "Device": ("设备", "设备对象"),
    "WorkOrder": ("工单", "工单对象"),
    "SparePart": ("备件", "备件对象"),
    "Equipment": ("层级设备", "ISA-95 Equipment"),
    "FailureMode": ("故障模式", "FMEA 故障模式"),
    "Component": ("部件", "设备部件"),
    "Line": ("产线", "产线"),
    "Area": ("车间", "车间/区域"),
    "Site": ("工厂", "工厂/厂区"),
}

_ATTR_LABELS: dict[str, tuple[str, str, str]] = {
    "externalId": ("外部编号", "源系统主键或业务编号", "string"),
    "name": ("名称", "显示名称", "string"),
    "title": ("标题", "标题或摘要", "string"),
    "status": ("状态", "业务状态", "string"),
    "location": ("位置", "安装或存放位置", "string"),
    "sku": ("料号", "SKU / 料号", "string"),
    "qtyOnHand": ("库存数量", "现有库存", "number"),
    "qty": ("数量", "数量", "number"),
    "deviceExternalId": ("设备外部编号", "关联设备编号", "string"),
    "openedAt": ("开单时间", "工单创建时间", "datetime"),
    "model": ("型号", "设备型号", "string"),
    "code": ("编码", "业务编码", "string"),
    "severity": ("严重度", "FMEA 严重度", "number"),
}


def _guess_object_type(local_name: str) -> str | None:
    key = local_name.lower().replace("_", "")
    mapping = {
        "equipdevices": "device",
        "device": "device",
        "equipworkorders": "work_order",
        "workorder": "work_order",
        "equipspareparts": "spare_part",
        "sparepart": "spare_part",
        "equipment": "equipment",
        "failuremode": "failure_mode",
        "component": "component",
        "line": "line",
        "area": "area",
        "site": "site",
    }
    return mapping.get(key)


def _suggest_entity_copy(
    local_name: str, label: str, description: str | None
) -> tuple[str, str | None]:
    hit = _ENTITY_LABELS.get(local_name)
    if hit:
        return hit[0], description or hit[1]
    # already looks localized
    if label and label != local_name and not label.isascii():
        return label, description
    spaced = _split_camel(local_name)
    return label if label and label != local_name else spaced, description


def _suggest_attr_copy(
    name: str, label: str, description: str | None, attr_kind: str
) -> tuple[str, str | None, str]:
    hit = _ATTR_LABELS.get(name)
    if hit:
        return hit[0], description or hit[1], hit[2] if attr_kind == "string" else attr_kind
    if label and label != name and not label.isascii():
        return label, description, attr_kind
    return label if label and label != name else _split_camel(name), description, attr_kind


def _split_camel(value: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(value):
        if i and ch.isupper() and (value[i - 1].islower() or (i + 1 < len(value) and value[i + 1].islower())):
            out.append(" ")
        out.append(ch)
    return "".join(out).replace("_", " ").strip() or value
