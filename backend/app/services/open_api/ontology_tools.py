"""Open/MCP ontology + structured object tools (O4)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from datetime import datetime

from app.models import (
    EquipDevice,
    EquipSparePart,
    EquipWorkOrder,
    SemanticAttribute,
    SemanticEntity,
    SemanticMapping,
    SemanticModelStatus,
    SemanticModelVersion,
    StructuredRecord,
)
from app.ontology.attributes import list_schemas
from app.ontology.catalog import EQUIP_TABLE_OBJECT_TYPES, NS, OntologyCatalog
from app.ontology.constraints import object_relation_constraint
from app.ontology.freshness import compute_freshness
from app.ontology.state_machines import normalize_device_status
from app.models.structured import ObjectRelationType
from app.models.semantic import SemanticItemStatus
from app.retrieval.graph import traverse_ko_relations
from app.retrieval.object_graph import ObjectGraphSeed, traverse_object_relations
from app.schemas.open_api import (
    OpenAggregateObjectsIn,
    OpenAggregateObjectsOut,
    OpenGetObjectIn,
    OpenGetObjectOut,
    OpenObjectIdentifierOut,
    OpenObjectLinkOut,
    OpenObjectNeighborOut,
    OpenOntologyDescribeOut,
    OpenQueryObjectItem,
    OpenQueryObjectsIn,
    OpenQueryObjectsOut,
    OpenTraverseIn,
    OpenTraverseNeighborOut,
    OpenTraverseOut,
)
from app.services.authz import AuthzCache
from app.services.context import RequestContext
from app.services.knowledge.ko_access import KoAccess
from app.services.open_api.auth import ApiCaller
from app.services.structured.access import StructuredAccess
from app.services.structured.identity import EntityIdentityService
from app.services.structured.service import StructuredService


class OpenOntologyTools:
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        caller: ApiCaller,
    ) -> None:
        self.session = session
        self.ctx = ctx
        self.authz_cache = authz_cache
        self.caller = caller
        self.kos = KoAccess(session)
        self.structured = StructuredService(session, ctx, authz_cache)
        self.object_acl = StructuredAccess(session)
        self.identity = EntityIdentityService(session)

    @property
    def org_id(self) -> str:
        return self.ctx.user.org_id

    async def describe_ontology(
        self,
        *,
        scope: str = "summary",
        version: str = "published",
    ) -> OpenOntologyDescribeOut:
        """Platform TBox + optional published org extension.

        scope:
          - summary (default): classes + relations + constraints; no attribute dump
          - classes / relations / attributes / equipment / all
        version:
          - published (default): merge active published org semantics
          - platform: platform TBox only
          - <version_id>: only if that version is the active published (drafts hidden)
        """
        scope = (scope or "summary").strip().lower()
        version = (version or "published").strip().lower()
        if scope not in {
            "summary",
            "classes",
            "relations",
            "attributes",
            "equipment",
            "all",
        }:
            raise ValidationAppError(
                "Invalid scope",
                detail={
                    "allowed": [
                        "summary",
                        "classes",
                        "relations",
                        "attributes",
                        "equipment",
                        "all",
                    ]
                },
            )

        cat = OntologyCatalog.from_enums()
        hard: list[str] = []
        soft: list[str] = []
        for rel in ObjectRelationType:
            c = object_relation_constraint(rel)
            if c is None:
                continue
            (hard if c.hard else soft).append(rel.value)

        include_classes = scope in ("summary", "classes", "all", "equipment")
        include_relations = scope in ("summary", "relations", "all", "equipment")
        include_attrs = scope in ("attributes", "all", "equipment")

        platform_attrs: list[dict[str, Any]] = []
        if include_attrs:
            schemas = list_schemas()
            if scope == "equipment":
                schemas = [
                    s
                    for s in schemas
                    if s.object_type
                    in {
                        "equipment",
                        "device",
                        "component",
                        "failure_mode",
                        "work_order",
                        "spare_part",
                        "site",
                        "area",
                        "line",
                        "event",
                    }
                ]
            platform_attrs = [
                {
                    "object_type": s.object_type,
                    "label": s.label,
                    "description": s.description,
                    "attributes": [
                        {
                            "name": a.name,
                            "kind": a.kind.value
                            if hasattr(a.kind, "value")
                            else str(a.kind),
                            "required": a.required,
                            "unit": a.unit,
                        }
                        for a in s.attributes
                    ],
                    "source": "platform",
                }
                for s in schemas
            ]

        org_entities: list[dict[str, Any]] = []
        org_attrs: list[dict[str, Any]] = []
        version_id: str | None = None
        version_name: str | None = None
        published_at: str | None = None
        version_label: str | None = "platform"

        if version != "platform":
            from app.services.ontology_studio.service import OntologyStudioService

            studio = OntologyStudioService(self.session, self.ctx, self.authz_cache)
            active = await studio.get_active_published()
            if version == "published":
                if active is not None:
                    ext = await studio.load_published_extension()
                    version_id = ext["version_id"]  # type: ignore[assignment]
                    version_name = ext["version_name"]  # type: ignore[assignment]
                    published_at = ext["published_at"]  # type: ignore[assignment]
                    org_entities = list(ext["entities"])  # type: ignore[arg-type]
                    org_attrs = list(ext["attribute_schemas"])  # type: ignore[arg-type]
                    version_label = "published"
            else:
                # explicit version_id — only if it is the active published
                if active is None or active.id != version:
                    raise NotFoundError("Published semantic model version not found")
                ext = await studio.load_published_extension()
                version_id = ext["version_id"]  # type: ignore[assignment]
                version_name = ext["version_name"]  # type: ignore[assignment]
                published_at = ext["published_at"]  # type: ignore[assignment]
                org_entities = list(ext["entities"])  # type: ignore[arg-type]
                org_attrs = list(ext["attribute_schemas"])  # type: ignore[arg-type]
                version_label = "published"

        classes = sorted(cat.all_required_classes()) if include_classes else []
        if include_classes and org_entities:
            for ent in org_entities:
                name = ent.get("local_name")
                if isinstance(name, str) and name and name not in classes:
                    classes.append(name)
            classes = sorted(classes)

        attribute_schemas: list[dict[str, Any]] = []
        if include_attrs:
            attribute_schemas = [*platform_attrs, *org_attrs]

        return OpenOntologyDescribeOut(
            namespace=NS,
            classes=classes,
            ko_relation_properties=sorted(cat.relation_properties)
            if include_relations
            else [],
            industrial_relation_properties=sorted(cat.industrial_relation_properties)
            if include_relations
            else [],
            attribute_schemas=attribute_schemas,
            hard_object_relations=sorted(hard) if include_relations else [],
            soft_object_relations=sorted(soft) if include_relations else [],
            scope=scope,
            version=version_label,
            version_id=version_id,
            version_name=version_name,
            published_at=published_at,
            org_entities=org_entities if include_classes else [],
        )

    async def get_object(self, data: OpenGetObjectIn) -> OpenGetObjectOut:
        obj = await self._load_structured(
            data.object_type, object_id=data.object_id, external_id=data.external_id,
            source_id=data.source_id,
        )
        await self.object_acl.require_read(self.ctx.user, obj["object_id"])
        neighbors: list[OpenObjectNeighborOut] = []
        if data.include_neighbors and data.neighbor_hops > 0:
            seed = ObjectGraphSeed("structured", obj["object_id"], obj["object_type"])
            walked = await traverse_object_relations(
                self.session,
                self.org_id,
                [seed],
                max_hops=data.neighbor_hops,
                limit=40,
                direction="both",
            )
            visible = set(
                await self.object_acl.filter_readable(
                    self.ctx.user, [n.object_id for n in walked]
                )
            )
            neighbors = [
                OpenObjectNeighborOut(
                    kind=n.kind,
                    object_id=n.object_id,
                    object_type=n.object_type,
                    hops=n.hops,
                    path=n.path,
                    via_relation_types=n.via_relation_types,
                )
                for n in walked
                if n.object_id in visible
            ]
        link_rows = await self.structured.list_links(obj["object_type"], obj["object_id"])
        links = [
            OpenObjectLinkOut(
                id=link.id,
                terminology_entity_id=link.terminology_entity_id,
                terminology_name=link.terminology_name,
                ko_id=link.ko_id,
                ko_title=link.ko_title,
            )
            for link in link_rows
        ]
        canonical = await self.identity.get_by_structured(
            self.org_id,
            structured_object_type=obj["object_type"],
            structured_object_id=obj["object_id"],
        )
        identifiers: list[OpenObjectIdentifierOut] = []
        if canonical is not None:
            id_rows = await self.identity.list_identifiers(self.org_id, canonical.id)
            identifiers = [
                OpenObjectIdentifierOut(
                    system=row.system,
                    id_kind=row.id_kind,
                    external_id=row.external_id,
                    is_primary=row.is_primary,
                )
                for row in id_rows
            ]
        standard_status: str | None = None
        status_label: str | None = None
        if obj["object_type"] == "device":
            normalized = normalize_device_status(obj.get("status"))
            standard_status = normalized.standard_status.value
            status_label = normalized.status_label
        attrs = dict(
            await self.object_acl.filter_attrs(
                self.ctx.user, obj["object_id"], dict(obj["attrs"] or {})
            )
        )
        freshness = await self._freshness_meta(
            object_type=obj["object_type"],
            updated_at=obj.get("updated_at"),
        )
        if freshness is not None:
            meta = dict(attrs.get("_meta") or {})
            meta["freshness"] = freshness
            attrs["_meta"] = meta
        return OpenGetObjectOut(
            object_type=obj["object_type"],
            object_id=obj["object_id"],
            external_id=obj["external_id"],
            title=obj["title"],
            status=obj["status"],
            standard_status=standard_status,
            status_label=status_label,
            attrs=attrs,
            neighbors=neighbors,
            links=links,
            canonical_id=canonical.id if canonical else None,
            identifiers=identifiers,
        )

    async def query_objects(self, data: OpenQueryObjectsIn) -> OpenQueryObjectsOut:
        ot = data.object_type
        if ot in EQUIP_TABLE_OBJECT_TYPES:
            return await self._query_equip(data)
        filters = self._record_query_filters(data)
        order = (StructuredRecord.occurred_at.desc(), StructuredRecord.external_id)
        # Over-fetch when ACL may drop rows; events use SQL filters so total is closer.
        fetch = data.size * 3
        rows = list(
            await self.session.scalars(
                select(StructuredRecord)
                .where(*filters)
                .order_by(*order)
                .offset((data.page - 1) * data.size)
                .limit(fetch)
            )
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(StructuredRecord).where(*filters)
            )
            or 0
        )
        items: list[OpenQueryObjectItem] = []
        for row in rows:
            attrs = dict(row.attrs or {})
            if data.line_external_id and attrs.get("line_external_id") != data.line_external_id:
                # Prefer denorm parent when present; fall back to attrs.
                if not (
                    row.parent_object_type == "line"
                    and row.parent_external_id == data.line_external_id
                ):
                    continue
            if data.equipment_external_id:
                if not (
                    (
                        row.parent_object_type == "equipment"
                        and row.parent_external_id == data.equipment_external_id
                    )
                    or attrs.get("equipment_external_id") == data.equipment_external_id
                ):
                    continue
            items.append(self._query_item(row, attrs))
            if len(items) >= fetch:
                break
        visible = set(
            await self.object_acl.filter_readable(
                self.ctx.user, [i.object_id for i in items]
            )
        )
        items = [i for i in items if i.object_id in visible][: data.size]
        return OpenQueryObjectsOut(
            items=items,
            total=total,
            page=data.page,
            size=data.size,
        )

    async def aggregate_objects(
        self, data: OpenAggregateObjectsIn
    ) -> OpenAggregateObjectsOut:
        if data.metric != "count":
            raise ValidationAppError("Unsupported aggregate metric")
        ot = data.object_type
        if ot in EQUIP_TABLE_OBJECT_TYPES:
            raise ValidationAppError(
                "Aggregate count for equipment tables is not supported; use query_objects"
            )
        filters = self._record_query_filters(
            OpenQueryObjectsIn(
                object_type=data.object_type,
                status=data.status,
                event_type=data.event_type,
                equipment_external_id=data.equipment_external_id,
                line_external_id=data.line_external_id,
                occurred_from=data.occurred_from,
                occurred_to=data.occurred_to,
                page=1,
                size=100,
            )
        )
        # Cap scan then ACL-filter for accurate visible count.
        rows = list(
            await self.session.scalars(
                select(StructuredRecord.id).where(*filters).limit(5000)
            )
        )
        visible = await self.object_acl.filter_readable(self.ctx.user, list(rows))
        filters_out: dict[str, Any] = {"object_type": ot}
        if data.event_type:
            filters_out["event_type"] = data.event_type
        if data.equipment_external_id:
            filters_out["equipment_external_id"] = data.equipment_external_id
        if data.line_external_id:
            filters_out["line_external_id"] = data.line_external_id
        if data.occurred_from is not None:
            filters_out["occurred_from"] = data.occurred_from.isoformat()
        if data.occurred_to is not None:
            filters_out["occurred_to"] = data.occurred_to.isoformat()
        if data.status:
            filters_out["status"] = data.status
        return OpenAggregateObjectsOut(
            object_type=ot,
            metric="count",
            value=len(visible),
            filters=filters_out,
        )

    def _record_query_filters(self, data: OpenQueryObjectsIn) -> list[Any]:
        filters: list[Any] = [
            StructuredRecord.org_id == self.org_id,
            StructuredRecord.object_type == data.object_type,
        ]
        if data.status:
            filters.append(StructuredRecord.status == data.status)
        if data.q:
            like = f"%{data.q.strip()}%"
            filters.append(
                or_(
                    StructuredRecord.title.ilike(like),
                    StructuredRecord.external_id.ilike(like),
                )
            )
        if data.event_type:
            filters.append(StructuredRecord.event_type == data.event_type)
        if data.occurred_from is not None:
            filters.append(StructuredRecord.occurred_at >= data.occurred_from)
        if data.occurred_to is not None:
            filters.append(StructuredRecord.occurred_at < data.occurred_to)
        # Prefer denorm parent (SQLite-safe); attrs still checked in post-filter.
        if data.equipment_external_id:
            filters.append(StructuredRecord.parent_object_type == "equipment")
            filters.append(
                StructuredRecord.parent_external_id == data.equipment_external_id
            )
        return filters

    @staticmethod
    def _query_item(row: StructuredRecord, attrs: dict[str, Any]) -> OpenQueryObjectItem:
        return OpenQueryObjectItem(
            object_type=row.object_type,
            object_id=row.id,
            external_id=row.external_id,
            title=row.title,
            status=row.status,
            attrs=attrs,
            occurred_at=row.occurred_at,
            ended_at=row.ended_at,
            event_type=row.event_type,
        )

    async def traverse(self, data: OpenTraverseIn) -> OpenTraverseOut:
        if data.mode == "ko":
            return await self._traverse_ko(data)
        return await self._traverse_object(data)

    async def _traverse_ko(self, data: OpenTraverseIn) -> OpenTraverseOut:
        assert data.ko_id
        kb_bound = self.caller.kb_ids
        if data.kb_ids:
            kb_bound = kb_bound & frozenset(data.kb_ids)
        if not kb_bound:
            raise NotFoundError("Knowledge object not found")
        seed_check = await self.kos.live_objects(self.ctx.user, [data.ko_id])
        seed_live = seed_check.objects.get(data.ko_id)
        if seed_live is None or seed_live.kb.id not in kb_bound:
            raise NotFoundError("Knowledge object not found")
        neighbors = await traverse_ko_relations(
            self.session,
            self.org_id,
            [data.ko_id],
            max_hops=data.max_hops,
            limit=40,
            kb_ids=sorted(kb_bound),
            relation_types=data.relation_types or None,
            direction=data.direction,
        )
        check = await self.kos.live_objects(self.ctx.user, [n.ko_id for n in neighbors])
        out: list[OpenTraverseNeighborOut] = []
        for n in neighbors:
            live = check.objects.get(n.ko_id)
            if live is None or live.kb.id not in kb_bound:
                continue
            out.append(
                OpenTraverseNeighborOut(
                    kind="ko",
                    object_id=live.ko.id,
                    object_type=None,
                    title=live.ko.title,
                    hops=n.hops,
                    path=n.path,
                    ko_type=live.ko.ko_type,
                    kb_id=live.kb.id,
                )
            )
        return OpenTraverseOut(
            mode="ko",
            direction=data.direction,
            max_hops=data.max_hops,
            seed={
                "kind": "ko",
                "id": seed_live.ko.id,
                "title": seed_live.ko.title,
                "ko_type": seed_live.ko.ko_type,
                "kb_id": seed_live.kb.id,
            },
            neighbors=out,
        )

    async def _traverse_object(self, data: OpenTraverseIn) -> OpenTraverseOut:
        assert data.kind and data.object_id
        if data.kind == "structured":
            await self.object_acl.require_read(self.ctx.user, data.object_id)
        seed = ObjectGraphSeed(data.kind, data.object_id, data.object_type)
        walked = await traverse_object_relations(
            self.session,
            self.org_id,
            [seed],
            max_hops=data.max_hops,
            limit=40,
            relation_types=data.relation_types or None,
            direction=data.direction,
        )
        visible = set(
            await self.object_acl.filter_readable(
                self.ctx.user, [n.object_id for n in walked]
            )
        )
        return OpenTraverseOut(
            mode="object",
            direction=data.direction,
            max_hops=data.max_hops,
            seed={
                "kind": data.kind,
                "object_id": data.object_id,
                "object_type": data.object_type,
            },
            neighbors=[
                OpenTraverseNeighborOut(
                    kind=n.kind,
                    object_id=n.object_id,
                    object_type=n.object_type,
                    hops=n.hops,
                    path=n.path,
                    via_relation_types=n.via_relation_types,
                )
                for n in walked
                if n.object_id in visible
            ],
        )

    async def _acl_filter_items(
        self, items: list[OpenQueryObjectItem], *, page: int, size: int, total: int
    ) -> OpenQueryObjectsOut:
        visible = set(
            await self.object_acl.filter_readable(
                self.ctx.user, [i.object_id for i in items]
            )
        )
        filtered = [i for i in items if i.object_id in visible]
        return OpenQueryObjectsOut(
            items=filtered[:size],
            total=total,
            page=page,
            size=size,
        )

    async def _query_equip(self, data: OpenQueryObjectsIn) -> OpenQueryObjectsOut:
        ot = data.object_type
        if ot == "device":
            page = await self.structured.list_devices(
                page=data.page, size=data.size * 3, q=data.q
            )
            items = [
                OpenQueryObjectItem(
                    object_type="device",
                    object_id=r.id,
                    external_id=r.external_id,
                    title=r.name,
                    status=r.status,
                    attrs=dict(r.meta or {}),
                )
                for r in page.items
                if not data.status or r.status == data.status
            ]
            return await self._acl_filter_items(
                items, page=data.page, size=data.size, total=page.total
            )
        if ot == "work_order":
            page = await self.structured.list_work_orders(
                page=data.page, size=data.size * 3, q=data.q
            )
            items = [
                OpenQueryObjectItem(
                    object_type="work_order",
                    object_id=r.id,
                    external_id=r.external_id,
                    title=r.title,
                    status=r.status,
                    attrs={
                        "device_external_id": r.device_external_id,
                        **dict(r.meta or {}),
                    },
                )
                for r in page.items
                if (not data.status or r.status == data.status)
                and (
                    not data.equipment_external_id
                    or r.device_external_id == data.equipment_external_id
                )
            ]
            return await self._acl_filter_items(
                items,
                page=data.page,
                size=data.size,
                total=len(items) if data.status or data.equipment_external_id else page.total,
            )
        if ot == "spare_part":
            page = await self.structured.list_spare_parts(
                page=data.page, size=data.size * 3, q=data.q
            )
            items = [
                OpenQueryObjectItem(
                    object_type="spare_part",
                    object_id=r.id,
                    external_id=r.external_id,
                    title=r.name,
                    status="active",
                    attrs={"sku": r.sku, "qty_on_hand": r.qty_on_hand, **dict(r.meta or {})},
                )
                for r in page.items
            ]
            return await self._acl_filter_items(
                items, page=data.page, size=data.size, total=page.total
            )
        raise ValidationAppError("Unsupported equipment object_type")

    async def _freshness_meta(
        self,
        *,
        object_type: str,
        updated_at: datetime | None,
    ) -> dict[str, Any] | None:
        """Attach freshness from active published mappings for this object_type."""
        version = await self.session.scalar(
            select(SemanticModelVersion).where(
                SemanticModelVersion.org_id == self.org_id,
                SemanticModelVersion.status == SemanticModelStatus.PUBLISHED.value,
                SemanticModelVersion.is_active.is_(True),
            )
        )
        if version is None:
            return None
        entities = list(
            await self.session.scalars(
                select(SemanticEntity).where(
                    SemanticEntity.org_id == self.org_id,
                    SemanticEntity.version_id == version.id,
                    SemanticEntity.status == SemanticItemStatus.APPROVED.value,
                    or_(
                        SemanticEntity.object_type == object_type,
                        SemanticEntity.local_name.ilike(object_type),
                    ),
                )
            )
        )
        if not entities:
            return None
        entity_ids = [e.id for e in entities]
        attrs = list(
            await self.session.scalars(
                select(SemanticAttribute).where(
                    SemanticAttribute.org_id == self.org_id,
                    SemanticAttribute.entity_id.in_(entity_ids),
                    SemanticAttribute.status == SemanticItemStatus.APPROVED.value,
                )
            )
        )
        if not attrs:
            return None
        attr_ids = [a.id for a in attrs]
        mappings = list(
            await self.session.scalars(
                select(SemanticMapping).where(
                    SemanticMapping.org_id == self.org_id,
                    SemanticMapping.attribute_id.in_(attr_ids),
                    SemanticMapping.status == SemanticItemStatus.APPROVED.value,
                )
            )
        )
        if not mappings:
            return None
        sot = [
            {
                "table": m.table_name,
                "column": m.column_name,
                "source_id": m.source_id,
            }
            for m in mappings
            if m.source_of_truth
        ]
        sla_candidates = [
            m.freshness_sla_seconds
            for m in mappings
            if m.freshness_sla_seconds is not None
        ]
        sla = min(sla_candidates) if sla_candidates else None
        if sla is None and not sot:
            return None
        return compute_freshness(
            updated_at=updated_at,
            sla_seconds=sla,
            source_of_truth=sot,
        ).as_meta()

    async def _load_structured(
        self,
        object_type: str,
        *,
        object_id: str | None,
        external_id: str | None,
        source_id: str | None,
    ) -> dict[str, Any]:
        if external_id:
            resolved = await self.structured.resolve(
                object_type, external_id, source_id=source_id
            )
            attrs: dict[str, Any] = {}
            if object_type in EQUIP_TABLE_OBJECT_TYPES:
                equip = await self._get_equip_row(object_type, resolved.object_id)
                if isinstance(equip, EquipDevice):
                    attrs = {
                        "location": equip.location,
                        **dict(equip.meta or {}),
                    }
                elif isinstance(equip, EquipWorkOrder):
                    attrs = {
                        "device_external_id": equip.device_external_id,
                        **dict(equip.meta or {}),
                    }
                elif isinstance(equip, EquipSparePart):
                    attrs = {
                        "sku": equip.sku,
                        "qty_on_hand": equip.qty_on_hand,
                        **dict(equip.meta or {}),
                    }
            else:
                row = await self.session.scalar(
                    select(StructuredRecord).where(
                        StructuredRecord.org_id == self.org_id,
                        StructuredRecord.id == resolved.object_id,
                    )
                )
                if row is not None:
                    attrs = dict(row.attrs or {})
            updated_at = None
            if object_type in EQUIP_TABLE_OBJECT_TYPES:
                equip = await self._get_equip_row(object_type, resolved.object_id)
                if equip is not None:
                    updated_at = getattr(equip, "updated_at", None)
            else:
                rec = await self.session.scalar(
                    select(StructuredRecord).where(
                        StructuredRecord.org_id == self.org_id,
                        StructuredRecord.id == resolved.object_id,
                    )
                )
                if rec is not None:
                    updated_at = rec.updated_at
            return {
                "object_type": resolved.object_type,
                "object_id": resolved.object_id,
                "external_id": resolved.external_id,
                "title": resolved.label,
                "status": resolved.status,
                "attrs": attrs,
                "updated_at": updated_at,
            }
        assert object_id
        if object_type in EQUIP_TABLE_OBJECT_TYPES:
            row = await self._get_equip_row(object_type, object_id)
            if row is None:
                raise NotFoundError("Structured object not found")
            if object_type == "device":
                assert isinstance(row, EquipDevice)
                return {
                    "object_type": "device",
                    "object_id": row.id,
                    "external_id": row.external_id,
                    "title": row.name,
                    "status": row.status,
                    "attrs": dict(row.meta or {}),
                    "updated_at": row.updated_at,
                }
            if object_type == "work_order":
                assert isinstance(row, EquipWorkOrder)
                return {
                    "object_type": "work_order",
                    "object_id": row.id,
                    "external_id": row.external_id,
                    "title": row.title,
                    "status": row.status,
                    "attrs": {
                        "device_external_id": row.device_external_id,
                        **dict(row.meta or {}),
                    },
                    "updated_at": row.updated_at,
                }
            assert isinstance(row, EquipSparePart)
            return {
                "object_type": "spare_part",
                "object_id": row.id,
                "external_id": row.external_id,
                "title": row.name,
                "status": "active",
                "attrs": {
                    "sku": row.sku,
                    "qty_on_hand": row.qty_on_hand,
                    **dict(row.meta or {}),
                },
                "updated_at": row.updated_at,
            }
        row = await self.session.scalar(
            select(StructuredRecord).where(
                StructuredRecord.org_id == self.org_id,
                StructuredRecord.id == object_id,
                StructuredRecord.object_type == object_type,
            )
        )
        if row is None:
            raise NotFoundError("Structured object not found")
        return {
            "object_type": row.object_type,
            "object_id": row.id,
            "external_id": row.external_id,
            "title": row.title,
            "status": row.status,
            "attrs": dict(row.attrs or {}),
            "updated_at": row.updated_at,
        }

    async def _get_equip_row(self, object_type: str, object_id: str) -> object | None:
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
