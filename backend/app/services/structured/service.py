from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    EquipDevice,
    EquipSparePart,
    EquipWorkOrder,
    StructuredDomain,
    StructuredDomainKind,
    StructuredEntityLink,
    StructuredObjectType,
    StructuredRecord,
    StructuredSource,
    StructuredSourceType,
)
from app.repositories.structured_repo import StructuredRepository
from app.schemas.common import Page
from app.schemas.structured import (
    EquipDeviceOut,
    EquipSparePartOut,
    EquipWorkOrderOut,
    StructuredDomainCreate,
    StructuredDomainOut,
    StructuredLinkCreate,
    StructuredLinkOut,
    StructuredObjectAclOut,
    StructuredObjectAclUpdate,
    StructuredRecordCreate,
    StructuredRecordOut,
    StructuredResolveOut,
    StructuredSourceCreate,
    StructuredSourceOut,
)
from app.ontology.attributes import (
    event_timeline_fields,
    schema_catalog_payload,
    schema_for,
    validate_attrs,
)
from app.ontology.catalog import (
    EQUIP_TABLE_OBJECT_TYPES,
    INDUSTRIAL_RECORD_OBJECT_TYPES,
    derive_parent_ref,
)
from app.services.authz.cache import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.knowledge.directory import PrincipalDirectory
from app.services.structured.access import RESOURCE_STRUCTURED, StructuredAccess

RESOURCE_SOURCE = "structured_source"
RESOURCE_DOMAIN = "structured_domain"
RESOURCE_RECORD = "structured_record"
RESOURCE_LINK = "structured_entity_link"

_SOURCE_TYPES = {t.value for t in StructuredSourceType}
# Only kinds with dedicated equip_* tables are reserved; ISA-95 kinds use structured_records until O1.3.
_EQUIP_OBJECT_TYPES = set(EQUIP_TABLE_OBJECT_TYPES)

_DEFAULT_DOMAINS: tuple[tuple[str, str, str, str | None], ...] = (
    ("equipment", "设备维保", StructuredDomainKind.EQUIPMENT.value, "设备 / 工单 / 备件专用表"),
    ("process", "工艺", StructuredDomainKind.GENERIC.value, "配方、工序、工艺参数"),
    ("material", "物料", StructuredDomainKind.GENERIC.value, "料号、规格、批次"),
    ("quality", "质检", StructuredDomainKind.GENERIC.value, "检验单、不合格项、标准"),
)

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OBJECT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class StructuredService(BaseService):
    def __init__(
        self, session: AsyncSession, ctx: RequestContext, authz_cache: AuthzCache
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.object_acl = StructuredAccess(session)
        self.repo = StructuredRepository(session)

    # ---- sources ------------------------------------------------------------------

    @staticmethod
    def _source_out(row: StructuredSource) -> StructuredSourceOut:
        return StructuredSourceOut(
            id=row.id,
            name=row.name,
            type=row.type,
            enabled=row.enabled,
            meta=dict(row.meta or {}),
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_sources(self) -> list[StructuredSourceOut]:
        return [self._source_out(s) for s in await self.repo.list_sources(self.org_id)]

    async def create_source(self, data: StructuredSourceCreate) -> StructuredSourceOut:
        if data.type not in _SOURCE_TYPES:
            raise ValidationAppError(
                "Unknown source type", detail={"allowed": sorted(_SOURCE_TYPES)}
            )
        if await self.repo.get_source_by_name(self.org_id, data.name.strip()):
            raise ConflictError("Source name already exists")
        row = StructuredSource(
            org_id=self.org_id,
            name=data.name.strip(),
            type=data.type,
            enabled=data.enabled,
            meta=dict(data.meta or {}),
            created_by=self.ctx.user.id,
        )
        self.repo.add_source(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "structured_source.create",
            RESOURCE_SOURCE,
            row.id,
            None,
            self._source_out(row).model_dump(mode="json"),
        )
        return self._source_out(row)

    async def sync_source(
        self, source_id: str, *, dry_run: bool = False, force_full: bool = False
    ) -> dict[str, Any]:
        from app.services.structured.sync import StructuredSyncExecutor

        result = await StructuredSyncExecutor(self.session).sync_source(
            self.org_id,
            source_id,
            dry_run=dry_run,
            force_full=force_full,
            triggered_by=self.ctx.user.id,
        )
        await self.audit.record(
            self.audit_ctx,
            "structured_source.sync",
            RESOURCE_SOURCE,
            source_id,
            None,
            {
                "status": result.get("status"),
                "connector": result.get("connector"),
                "dry_run": dry_run,
                "force_full": force_full,
                "mode": result.get("mode"),
                "stats": result.get("stats"),
            },
        )
        return result

    # ---- domains ------------------------------------------------------------------

    @staticmethod
    def _domain_out(row: StructuredDomain) -> StructuredDomainOut:
        return StructuredDomainOut(
            id=row.id,
            code=row.code,
            name=row.name,
            kind=row.kind,
            description=row.description,
            enabled=row.enabled,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def ensure_default_domains(self) -> None:
        for code, name, kind, description in _DEFAULT_DOMAINS:
            if await self.repo.get_domain_by_code(self.org_id, code) is not None:
                continue
            self.repo.add_domain(
                StructuredDomain(
                    org_id=self.org_id,
                    code=code,
                    name=name,
                    kind=kind,
                    description=description,
                    enabled=True,
                    created_by=None,
                )
            )
        await self.session.flush()

    async def list_domains(self) -> list[StructuredDomainOut]:
        await self.ensure_default_domains()
        return [self._domain_out(d) for d in await self.repo.list_domains(self.org_id)]

    async def create_domain(self, data: StructuredDomainCreate) -> StructuredDomainOut:
        await self.ensure_default_domains()
        code = data.code.strip().lower()
        if not _CODE_RE.match(code):
            raise ValidationAppError(
                "Invalid domain code",
                detail={"pattern": "^[a-z][a-z0-9_]{0,63}$"},
            )
        if code == "equipment":
            raise ValidationAppError("equipment is a built-in domain code")
        if await self.repo.get_domain_by_code(self.org_id, code) is not None:
            raise ConflictError("Domain code already exists")
        row = StructuredDomain(
            org_id=self.org_id,
            code=code,
            name=data.name.strip(),
            kind=StructuredDomainKind.GENERIC.value,
            description=(data.description or "").strip() or None,
            enabled=data.enabled,
            created_by=self.ctx.user.id,
        )
        self.repo.add_domain(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "structured_domain.create",
            RESOURCE_DOMAIN,
            row.id,
            None,
            self._domain_out(row).model_dump(mode="json"),
        )
        return self._domain_out(row)

    # ---- generic records ----------------------------------------------------------

    @staticmethod
    def _record_out(row: StructuredRecord) -> StructuredRecordOut:
        return StructuredRecordOut(
            id=row.id,
            domain_id=row.domain_id,
            source_id=row.source_id,
            object_type=row.object_type,
            external_id=row.external_id,
            title=row.title,
            status=row.status,
            parent_object_type=row.parent_object_type,
            parent_external_id=row.parent_external_id,
            occurred_at=row.occurred_at,
            ended_at=row.ended_at,
            event_type=row.event_type,
            attrs=dict(row.attrs or {}),
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_records(
        self,
        *,
        domain_id: str,
        page: int,
        size: int,
        q: str | None = None,
        source_id: str | None = None,
        object_type: str | None = None,
    ) -> Page[StructuredRecordOut]:
        domain = await self.repo.get_domain(self.org_id, domain_id)
        if domain is None:
            raise NotFoundError("Domain not found")
        if domain.kind != StructuredDomainKind.GENERIC.value:
            raise ValidationAppError("Domain does not use generic records")
        rows, total = await self.repo.list_records(
            self.org_id,
            domain_id=domain_id,
            page=page,
            size=size,
            q=q,
            source_id=source_id,
            object_type=object_type,
        )
        return Page(
            items=[self._record_out(r) for r in rows], total=total, page=page, size=size
        )

    async def create_record(self, data: StructuredRecordCreate) -> StructuredRecordOut:
        domain = await self.repo.get_domain(self.org_id, data.domain_id)
        if domain is None:
            raise NotFoundError("Domain not found")
        object_type = data.object_type.strip().lower()
        if not _OBJECT_TYPE_RE.match(object_type):
            raise ValidationAppError(
                "Invalid object_type",
                detail={"pattern": "^[a-z][a-z0-9_]{0,63}$"},
            )
        if object_type in _EQUIP_OBJECT_TYPES:
            raise ValidationAppError(
                "Reserved object_type for equipment tables",
                detail={"reserved": sorted(_EQUIP_OBJECT_TYPES)},
            )
        industrial = object_type in INDUSTRIAL_RECORD_OBJECT_TYPES
        if domain.kind == StructuredDomainKind.EQUIPMENT.value and not industrial:
            raise ValidationAppError(
                "Only industrial object types may be added to the equipment domain",
                detail={"allowed": sorted(INDUSTRIAL_RECORD_OBJECT_TYPES)},
            )
        if (
            domain.kind != StructuredDomainKind.GENERIC.value
            and domain.kind != StructuredDomainKind.EQUIPMENT.value
        ):
            raise ValidationAppError("Unsupported domain kind for records")
        if await self.repo.get_source(self.org_id, data.source_id) is None:
            raise NotFoundError("Source not found")
        attrs = dict(data.attrs or {})
        self._require_valid_attrs(object_type, attrs)
        parent_type = (data.parent_object_type or "").strip().lower() or None
        parent_ext = (data.parent_external_id or "").strip() or None
        if parent_type is None and parent_ext is None:
            parent_type, parent_ext = derive_parent_ref(object_type, attrs)
        elif (parent_type is None) ^ (parent_ext is None):
            raise ValidationAppError(
                "parent_object_type and parent_external_id must be set together"
            )
        external_id = data.external_id.strip()
        existing = await self.repo.get_record_by_external(
            self.org_id, object_type, external_id, source_id=data.source_id
        )
        if existing is not None:
            raise ConflictError("Record already exists for this source/type/external_id")
        occurred_at, ended_at, event_type = self._timeline_denorm(object_type, attrs)
        row = StructuredRecord(
            org_id=self.org_id,
            domain_id=data.domain_id,
            source_id=data.source_id,
            object_type=object_type,
            external_id=external_id,
            title=data.title.strip(),
            status=data.status.strip() or "active",
            parent_object_type=parent_type,
            parent_external_id=parent_ext,
            occurred_at=occurred_at,
            ended_at=ended_at,
            event_type=event_type,
            attrs=attrs,
            created_by=self.ctx.user.id,
        )
        self.repo.add_record(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "structured_record.create",
            RESOURCE_RECORD,
            row.id,
            None,
            self._record_out(row).model_dump(mode="json"),
        )
        return self._record_out(row)

    # ---- equipment listings -------------------------------------------------------

    @staticmethod
    def _device_out(row: EquipDevice) -> EquipDeviceOut:
        return EquipDeviceOut(
            id=row.id,
            source_id=row.source_id,
            external_id=row.external_id,
            name=row.name,
            status=row.status,
            location=row.location,
            meta=dict(row.meta or {}),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _wo_out(row: EquipWorkOrder) -> EquipWorkOrderOut:
        return EquipWorkOrderOut(
            id=row.id,
            source_id=row.source_id,
            external_id=row.external_id,
            device_external_id=row.device_external_id,
            title=row.title,
            status=row.status,
            opened_at=row.opened_at,
            meta=dict(row.meta or {}),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _part_out(row: EquipSparePart) -> EquipSparePartOut:
        return EquipSparePartOut(
            id=row.id,
            source_id=row.source_id,
            external_id=row.external_id,
            name=row.name,
            sku=row.sku,
            qty_on_hand=row.qty_on_hand,
            meta=dict(row.meta or {}),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_devices(
        self, *, page: int, size: int, q: str | None = None, source_id: str | None = None
    ) -> Page[EquipDeviceOut]:
        rows, total = await self.repo.list_devices(
            self.org_id, page=page, size=size, q=q, source_id=source_id
        )
        return Page(
            items=[self._device_out(r) for r in rows], total=total, page=page, size=size
        )

    async def list_work_orders(
        self, *, page: int, size: int, q: str | None = None, source_id: str | None = None
    ) -> Page[EquipWorkOrderOut]:
        rows, total = await self.repo.list_work_orders(
            self.org_id, page=page, size=size, q=q, source_id=source_id
        )
        return Page(items=[self._wo_out(r) for r in rows], total=total, page=page, size=size)

    async def list_spare_parts(
        self, *, page: int, size: int, q: str | None = None, source_id: str | None = None
    ) -> Page[EquipSparePartOut]:
        rows, total = await self.repo.list_spare_parts(
            self.org_id, page=page, size=size, q=q, source_id=source_id
        )
        return Page(
            items=[self._part_out(r) for r in rows], total=total, page=page, size=size
        )

    # ---- links --------------------------------------------------------------------

    async def _link_outs(self, links: list[StructuredEntityLink]) -> list[StructuredLinkOut]:
        term_ids = [l.terminology_entity_id for l in links if l.terminology_entity_id]
        ko_ids = [l.ko_id for l in links if l.ko_id]
        names = await self.repo.terminology_names(self.org_id, term_ids)
        titles = await self.repo.ko_titles(self.org_id, ko_ids)
        return [
            StructuredLinkOut(
                id=link.id,
                object_type=link.object_type,
                object_id=link.object_id,
                terminology_entity_id=link.terminology_entity_id,
                terminology_name=(
                    names.get(link.terminology_entity_id) if link.terminology_entity_id else None
                ),
                ko_id=link.ko_id,
                ko_title=titles.get(link.ko_id) if link.ko_id else None,
                created_by=link.created_by,
                created_at=link.created_at,
            )
            for link in links
        ]

    async def list_links(self, object_type: str, object_id: str) -> list[StructuredLinkOut]:
        await self._require_object(object_type, object_id)
        return await self._link_outs(
            await self.repo.list_links_for(self.org_id, object_type, object_id)
        )

    async def _require_object(self, object_type: str, object_id: str) -> Any:
        if object_type == StructuredObjectType.DEVICE.value:
            row: Any = await self.repo.get_device(self.org_id, object_id)
        elif object_type == StructuredObjectType.WORK_ORDER.value:
            row = await self.repo.get_work_order(self.org_id, object_id)
        elif object_type == StructuredObjectType.SPARE_PART.value:
            row = await self.repo.get_spare_part(self.org_id, object_id)
        else:
            row = await self.repo.get_record(self.org_id, object_id)
            if row is not None and row.object_type != object_type:
                row = None
        if row is None:
            raise NotFoundError("Structured object not found")
        return row

    async def create_link(self, data: StructuredLinkCreate) -> StructuredLinkOut:
        await self._require_object(data.object_type, data.object_id)
        if data.terminology_entity_id:
            if await self.repo.get_terminology(self.org_id, data.terminology_entity_id) is None:
                raise NotFoundError("Terminology entity not found")
        if data.ko_id and await self.repo.get_ko(self.org_id, data.ko_id) is None:
            raise NotFoundError("Knowledge object not found")
        existing = await self.repo.find_link(
            self.org_id,
            object_type=data.object_type,
            object_id=data.object_id,
            terminology_entity_id=data.terminology_entity_id,
            ko_id=data.ko_id,
        )
        if existing is not None:
            raise ConflictError("Link already exists")
        row = StructuredEntityLink(
            org_id=self.org_id,
            object_type=data.object_type,
            object_id=data.object_id,
            terminology_entity_id=data.terminology_entity_id,
            ko_id=data.ko_id,
            created_by=self.ctx.user.id,
        )
        self.repo.add_link(row)
        await self.session.flush()
        outs = await self._link_outs([row])
        await self.audit.record(
            self.audit_ctx,
            "structured_link.create",
            RESOURCE_LINK,
            row.id,
            None,
            outs[0].model_dump(mode="json"),
        )
        return outs[0]

    async def delete_link(self, link_id: str) -> None:
        row = await self.repo.get_link(self.org_id, link_id)
        if row is None:
            raise NotFoundError("Link not found")
        before = (await self._link_outs([row]))[0].model_dump(mode="json")
        await self.repo.delete_link(row)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "structured_link.delete", RESOURCE_LINK, link_id, before, None
        )

    # ---- resolve ------------------------------------------------------------------

    async def resolve(
        self,
        object_type: str,
        external_id: str,
        *,
        source_id: str | None = None,
    ) -> StructuredResolveOut:
        object_type = object_type.strip().lower()
        external_id = external_id.strip()
        if not object_type or not external_id:
            raise ValidationAppError("object_type and external_id are required")

        if object_type == StructuredObjectType.DEVICE.value:
            row = await self.repo.get_device_by_external(
                self.org_id, external_id, source_id=source_id
            )
            if row is None:
                raise NotFoundError("Device not found")
            label, status = row.name, row.status
            object_id, src = row.id, row.source_id
        elif object_type == StructuredObjectType.WORK_ORDER.value:
            row = await self.repo.get_work_order_by_external(
                self.org_id, external_id, source_id=source_id
            )
            if row is None:
                raise NotFoundError("Work order not found")
            label, status = row.title, row.status
            object_id, src = row.id, row.source_id
        elif object_type == StructuredObjectType.SPARE_PART.value:
            part = await self.repo.get_spare_part_by_external(
                self.org_id, external_id, source_id=source_id
            )
            if part is None:
                raise NotFoundError("Spare part not found")
            label = part.name
            status = "in_stock" if part.qty_on_hand > 0 else "out_of_stock"
            object_id, src = part.id, part.source_id
        else:
            rec = await self.repo.get_record_by_external(
                self.org_id, object_type, external_id, source_id=source_id
            )
            if rec is None:
                raise NotFoundError("Structured record not found")
            label, status = rec.title, rec.status
            object_id, src = rec.id, rec.source_id

        links = await self._link_outs(
            await self.repo.list_links_for(self.org_id, object_type, object_id)
        )
        return StructuredResolveOut(
            object_type=object_type,
            object_id=object_id,
            external_id=external_id,
            source_id=src,
            label=label,
            status=status,
            links=links,
        )

    async def _require_object_row(self, object_type: str, object_id: str) -> None:
        object_type = object_type.strip().lower()
        if object_type in _EQUIP_OBJECT_TYPES:
            if object_type == "device":
                row = await self.repo.get_device(self.org_id, object_id)
            elif object_type == "work_order":
                row = await self.repo.get_work_order(self.org_id, object_id)
            else:
                row = await self.repo.get_spare_part(self.org_id, object_id)
            if row is None:
                raise NotFoundError("Structured object not found")
            return
        rec = await self.repo.get_record(self.org_id, object_id)
        if rec is None or rec.object_type != object_type:
            raise NotFoundError("Structured object not found")

    async def get_object_acl(
        self, object_type: str, object_id: str
    ) -> StructuredObjectAclOut:
        await self._require_object_row(object_type, object_id)
        rows = await self.object_acl.entries(self.org_id, object_id)
        directory = PrincipalDirectory(self.session, self.org_id)
        return StructuredObjectAclOut(
            object_type=object_type.strip().lower(),
            object_id=object_id,
            entries=await directory.describe(
                [
                    (r.principal_type, r.principal_id, r.permission, r.effect or "allow")
                    for r in rows
                ]
            ),
        )

    async def set_object_acl(
        self, object_type: str, object_id: str, data: StructuredObjectAclUpdate
    ) -> StructuredObjectAclOut:
        await self._require_object_row(object_type, object_id)
        directory = PrincipalDirectory(self.session, self.org_id)
        validated = await directory.validate(list(data.entries))
        before = [
            {
                "principal_type": r.principal_type,
                "principal_id": r.principal_id,
                "permission": r.permission,
                "effect": r.effect,
            }
            for r in await self.object_acl.entries(self.org_id, object_id)
        ]
        await self.object_acl.replace_entries(
            self.org_id,
            object_id,
            [
                (e.principal_type, e.principal_id, e.permission, e.effect)
                for e in validated
            ],
            self.ctx.user.id,
        )
        out = await self.get_object_acl(object_type, object_id)
        await self.audit.record(
            self.audit_ctx,
            "structured_object.acl",
            RESOURCE_STRUCTURED,
            object_id,
            {"entries": before},
            {"object_type": object_type, "entries": [e.model_dump() for e in out.entries]},
        )
        return out

    async def list_children(
        self,
        *,
        parent_object_type: str,
        parent_external_id: str,
        object_type: str | None = None,
        source_id: str | None = None,
        limit: int = 200,
    ) -> list[StructuredRecordOut]:
        parent_object_type = parent_object_type.strip().lower()
        parent_external_id = parent_external_id.strip()
        if not parent_object_type or not parent_external_id:
            raise ValidationAppError("parent_object_type and parent_external_id are required")
        rows = await self.repo.list_records_by_parent(
            self.org_id,
            parent_object_type=parent_object_type,
            parent_external_id=parent_external_id,
            object_type=object_type.strip().lower() if object_type else None,
            source_id=source_id,
            limit=limit,
        )
        return [self._record_out(r) for r in rows]

    def list_attribute_schemas(self) -> list[dict[str, Any]]:
        return schema_catalog_payload()

    def get_attribute_schema(self, object_type: str) -> dict[str, Any]:
        object_type = object_type.strip().lower()
        schema = schema_for(object_type)
        if schema is None:
            raise NotFoundError(
                "No attribute schema for this object_type",
                detail={"object_type": object_type},
            )
        for row in schema_catalog_payload():
            if row["object_type"] == object_type:
                return row
        raise NotFoundError("No attribute schema for this object_type")

    @staticmethod
    def _require_valid_attrs(object_type: str, attrs: dict[str, Any]) -> None:
        issues = validate_attrs(object_type, attrs, strict_unknown=True)
        if not issues:
            return
        raise ValidationAppError(
            "Structured attrs failed schema validation",
            detail={
                "object_type": object_type,
                "issues": [
                    {"code": i.code, "path": i.path, "message": i.message} for i in issues
                ],
            },
        )

    @staticmethod
    def _timeline_denorm(
        object_type: str, attrs: dict[str, Any]
    ) -> tuple[datetime | None, datetime | None, str | None]:
        if object_type != "event":
            return None, None, None
        try:
            return event_timeline_fields(attrs)
        except ValueError as exc:
            raise ValidationAppError(
                "Invalid event timeline timestamp",
                detail={"message": str(exc)},
            ) from exc
