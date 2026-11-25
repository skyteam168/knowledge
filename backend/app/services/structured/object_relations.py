"""CRUD for directed object_relations (O2.1)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    EquipDevice,
    EquipSparePart,
    EquipWorkOrder,
    KnowledgeObject,
    ObjectEndpointKind,
    ObjectRelation,
    ObjectRelationType,
    StructuredRecord,
    TerminologyEntity,
)
from app.models.structured import RelationCardinality
from app.ontology.catalog import EQUIP_TABLE_OBJECT_TYPES, property_local_name
from app.ontology.constraints import (
    cardinality_limits_outgoing,
    default_relation_cardinality,
    validate_object_relation_endpoints,
)
from app.schemas.structured import ObjectRelationCreate, ObjectRelationOut
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext

RESOURCE = "object_relation"

_RELATION_TYPES = {t.value for t in ObjectRelationType}
_KINDS = {t.value for t in ObjectEndpointKind}


class ObjectRelationService(BaseService):
    def __init__(
        self, session: AsyncSession, ctx: RequestContext, authz_cache: AuthzCache
    ) -> None:
        super().__init__(session, ctx, authz_cache)

    async def list_relations(
        self,
        *,
        relation_type: str | None = None,
        from_kind: str | None = None,
        from_id: str | None = None,
        to_kind: str | None = None,
        to_id: str | None = None,
        limit: int = 200,
    ) -> list[ObjectRelationOut]:
        filters = [ObjectRelation.org_id == self.org_id]
        if relation_type:
            filters.append(ObjectRelation.relation_type == relation_type.strip().lower())
        if from_kind:
            filters.append(ObjectRelation.from_kind == from_kind.strip().lower())
        if from_id:
            filters.append(ObjectRelation.from_id == from_id.strip())
        if to_kind:
            filters.append(ObjectRelation.to_kind == to_kind.strip().lower())
        if to_id:
            filters.append(ObjectRelation.to_id == to_id.strip())
        rows = await self.session.scalars(
            select(ObjectRelation)
            .where(*filters)
            .order_by(ObjectRelation.relation_type, ObjectRelation.id)
            .limit(max(1, min(limit, 500)))
        )
        return [self._out(r) for r in rows]

    async def create(self, data: ObjectRelationCreate) -> ObjectRelationOut:
        relation_type = data.relation_type.strip().lower()
        if relation_type not in _RELATION_TYPES:
            raise ValidationAppError(
                "Invalid relation_type",
                detail={"allowed": sorted(_RELATION_TYPES)},
            )
        from_kind, from_id, from_ot = await self._resolve_endpoint(
            data.from_kind, data.from_id, data.from_object_type, side="from"
        )
        to_kind, to_id, to_ot = await self._resolve_endpoint(
            data.to_kind, data.to_id, data.to_object_type, side="to"
        )
        if (
            from_kind == to_kind
            and from_id == to_id
            and (from_ot or "") == (to_ot or "")
        ):
            raise ValidationAppError("Self-loop object relations are not allowed")

        soft_warnings = validate_object_relation_endpoints(
            relation_type,
            from_kind=from_kind,
            from_object_type=from_ot or None,
            to_kind=to_kind,
            to_object_type=to_ot or None,
        )

        existing = await self.session.scalar(
            select(ObjectRelation).where(
                ObjectRelation.org_id == self.org_id,
                ObjectRelation.relation_type == relation_type,
                ObjectRelation.from_kind == from_kind,
                ObjectRelation.from_id == from_id,
                ObjectRelation.from_object_type == from_ot,
                ObjectRelation.to_kind == to_kind,
                ObjectRelation.to_id == to_id,
                ObjectRelation.to_object_type == to_ot,
            )
        )
        if existing is not None:
            raise ConflictError("Object relation already exists")

        cardinality = (data.cardinality or "").strip().lower() or None
        if cardinality is None:
            cardinality = default_relation_cardinality(relation_type).value
        allowed_card = {c.value for c in RelationCardinality}
        if cardinality not in allowed_card:
            raise ValidationAppError(
                "Invalid cardinality",
                detail={"allowed": sorted(allowed_card)},
            )
        if cardinality_limits_outgoing(cardinality):
            prior = await self.session.scalar(
                select(ObjectRelation.id).where(
                    ObjectRelation.org_id == self.org_id,
                    ObjectRelation.relation_type == relation_type,
                    ObjectRelation.from_kind == from_kind,
                    ObjectRelation.from_id == from_id,
                    ObjectRelation.from_object_type == from_ot,
                )
            )
            if prior is not None:
                raise ValidationAppError(
                    "Object relation cardinality exceeded",
                    detail={
                        "relation_type": relation_type,
                        "cardinality": cardinality,
                        "from_id": from_id,
                    },
                )

        row = ObjectRelation(
            org_id=self.org_id,
            relation_type=relation_type,
            from_kind=from_kind,
            from_id=from_id,
            from_object_type=from_ot,
            to_kind=to_kind,
            to_id=to_id,
            to_object_type=to_ot,
            cardinality=cardinality,
            attrs=dict(data.attrs or {}),
            valid_from=data.valid_from,
            valid_to=data.valid_to,
            created_by=self.ctx.user.id,
        )
        self.session.add(row)
        await self.session.flush()
        out = self._out(row, warnings=soft_warnings)
        after = out.model_dump(mode="json")
        if soft_warnings:
            after["ontology_warnings"] = soft_warnings
        await self.audit.record(
            self.audit_ctx,
            "object_relation.create",
            RESOURCE,
            row.id,
            None,
            after,
        )
        return out

    async def delete(self, relation_id: str) -> None:
        row = await self.session.scalar(
            select(ObjectRelation).where(
                ObjectRelation.org_id == self.org_id, ObjectRelation.id == relation_id
            )
        )
        if row is None:
            raise NotFoundError("Object relation not found")
        before = self._out(row).model_dump(mode="json")
        await self.session.delete(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "object_relation.delete",
            RESOURCE,
            relation_id,
            before,
            None,
        )

    async def _resolve_endpoint(
        self,
        kind_raw: str,
        id_raw: str,
        object_type_raw: str | None,
        *,
        side: str,
    ) -> tuple[str, str, str]:
        kind = kind_raw.strip().lower()
        endpoint_id = id_raw.strip()
        object_type = (object_type_raw or "").strip().lower() or None
        if kind not in _KINDS:
            raise ValidationAppError(
                f"Invalid {side}_kind",
                detail={"allowed": sorted(_KINDS)},
            )
        if not endpoint_id:
            raise ValidationAppError(f"{side}_id is required")

        if kind == ObjectEndpointKind.TERMINOLOGY.value:
            row = await self.session.scalar(
                select(TerminologyEntity).where(
                    TerminologyEntity.org_id == self.org_id,
                    TerminologyEntity.id == endpoint_id,
                )
            )
            if row is None:
                raise NotFoundError(f"{side} terminology entity not found")
            return kind, endpoint_id, ""

        if kind == ObjectEndpointKind.KO.value:
            row = await self.session.scalar(
                select(KnowledgeObject).where(
                    KnowledgeObject.org_id == self.org_id,
                    KnowledgeObject.id == endpoint_id,
                )
            )
            if row is None:
                raise NotFoundError(f"{side} knowledge object not found")
            return kind, endpoint_id, ""

        # structured
        if not object_type:
            raise ValidationAppError(
                f"{side}_object_type is required when {side}_kind=structured"
            )
        if object_type in EQUIP_TABLE_OBJECT_TYPES:
            found = await self._get_equip(object_type, endpoint_id)
        else:
            found = await self.session.scalar(
                select(StructuredRecord).where(
                    StructuredRecord.org_id == self.org_id,
                    StructuredRecord.id == endpoint_id,
                    StructuredRecord.object_type == object_type,
                )
            )
        if found is None:
            raise NotFoundError(f"{side} structured object not found")
        return kind, endpoint_id, object_type

    async def _get_equip(self, object_type: str, object_id: str) -> object | None:
        if object_type == "device":
            return await self.session.scalar(
                select(EquipDevice).where(
                    EquipDevice.org_id == self.org_id, EquipDevice.id == object_id
                )
            )
        if object_type == "work_order":
            return await self.session.scalar(
                select(EquipWorkOrder).where(
                    EquipWorkOrder.org_id == self.org_id, EquipWorkOrder.id == object_id
                )
            )
        if object_type == "spare_part":
            return await self.session.scalar(
                select(EquipSparePart).where(
                    EquipSparePart.org_id == self.org_id, EquipSparePart.id == object_id
                )
            )
        return None

    @staticmethod
    def _out(
        row: ObjectRelation, *, warnings: list[str] | None = None
    ) -> ObjectRelationOut:
        return ObjectRelationOut(
            id=row.id,
            relation_type=row.relation_type,
            relation_local_name=property_local_name(row.relation_type),
            from_kind=row.from_kind,
            from_id=row.from_id,
            from_object_type=row.from_object_type or None,
            to_kind=row.to_kind,
            to_id=row.to_id,
            to_object_type=row.to_object_type or None,
            cardinality=row.cardinality or RelationCardinality.ONE_TO_MANY.value,
            attrs=dict(row.attrs or {}),
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
            warnings=list(warnings or ()),
        )
