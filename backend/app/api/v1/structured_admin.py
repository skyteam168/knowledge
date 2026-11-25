from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AuthzCacheDep, DbSessionDep, RequestContextDep, require_permission
from app.schemas.common import Page
from app.schemas.structured import (
    EquipDeviceOut,
    EquipSparePartOut,
    EquipWorkOrderOut,
    ObjectRelationCreate,
    ObjectRelationOut,
    StructuredAttrSchemaOut,
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
    StructuredSyncResult,
)
from app.services.structured.object_relations import ObjectRelationService
from app.services.structured.service import StructuredService

router = APIRouter(
    prefix="/admin/structured",
    tags=["admin:structured"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_structured_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep
) -> StructuredService:
    return StructuredService(session, ctx, cache)


ServiceDep = Annotated[StructuredService, Depends(get_structured_service)]


def get_object_relation_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep
) -> ObjectRelationService:
    return ObjectRelationService(session, ctx, cache)


RelationServiceDep = Annotated[ObjectRelationService, Depends(get_object_relation_service)]


@router.get("/sources", response_model=list[StructuredSourceOut])
async def list_sources(service: ServiceDep) -> list[StructuredSourceOut]:
    return await service.list_sources()


@router.post("/sources", response_model=StructuredSourceOut, status_code=201)
async def create_source(
    data: StructuredSourceCreate, service: ServiceDep
) -> StructuredSourceOut:
    return await service.create_source(data)


@router.post("/sources/{source_id}/sync", response_model=StructuredSyncResult)
async def sync_source(
    source_id: str,
    service: ServiceDep,
    dry_run: Annotated[bool, Query()] = False,
    force_full: Annotated[bool, Query()] = False,
) -> StructuredSyncResult:
    result = await service.sync_source(
        source_id, dry_run=dry_run, force_full=force_full
    )
    return StructuredSyncResult.model_validate(result)


@router.get("/domains", response_model=list[StructuredDomainOut])
async def list_domains(service: ServiceDep) -> list[StructuredDomainOut]:
    return await service.list_domains()


@router.post("/domains", response_model=StructuredDomainOut, status_code=201)
async def create_domain(
    data: StructuredDomainCreate, service: ServiceDep
) -> StructuredDomainOut:
    return await service.create_domain(data)


@router.get("/records", response_model=Page[StructuredRecordOut])
async def list_records(
    service: ServiceDep,
    domain_id: Annotated[str, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    q: str | None = None,
    source_id: str | None = None,
    object_type: str | None = None,
) -> Page[StructuredRecordOut]:
    return await service.list_records(
        domain_id=domain_id,
        page=page,
        size=size,
        q=q,
        source_id=source_id,
        object_type=object_type,
    )


@router.post("/records", response_model=StructuredRecordOut, status_code=201)
async def create_record(
    data: StructuredRecordCreate, service: ServiceDep
) -> StructuredRecordOut:
    return await service.create_record(data)


@router.get("/records/children", response_model=list[StructuredRecordOut])
async def list_record_children(
    service: ServiceDep,
    parent_object_type: Annotated[str, Query()],
    parent_external_id: Annotated[str, Query()],
    object_type: str | None = None,
    source_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[StructuredRecordOut]:
    return await service.list_children(
        parent_object_type=parent_object_type,
        parent_external_id=parent_external_id,
        object_type=object_type,
        source_id=source_id,
        limit=limit,
    )


@router.get("/devices", response_model=Page[EquipDeviceOut])
async def list_devices(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    q: str | None = None,
    source_id: str | None = None,
) -> Page[EquipDeviceOut]:
    return await service.list_devices(page=page, size=size, q=q, source_id=source_id)


@router.get("/work-orders", response_model=Page[EquipWorkOrderOut])
async def list_work_orders(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    q: str | None = None,
    source_id: str | None = None,
) -> Page[EquipWorkOrderOut]:
    return await service.list_work_orders(page=page, size=size, q=q, source_id=source_id)


@router.get("/spare-parts", response_model=Page[EquipSparePartOut])
async def list_spare_parts(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    q: str | None = None,
    source_id: str | None = None,
) -> Page[EquipSparePartOut]:
    return await service.list_spare_parts(page=page, size=size, q=q, source_id=source_id)


@router.get("/links", response_model=list[StructuredLinkOut])
async def list_links(
    service: ServiceDep,
    object_type: Annotated[str, Query()],
    object_id: Annotated[str, Query()],
) -> list[StructuredLinkOut]:
    return await service.list_links(object_type, object_id)


@router.post("/links", response_model=StructuredLinkOut, status_code=201)
async def create_link(data: StructuredLinkCreate, service: ServiceDep) -> StructuredLinkOut:
    return await service.create_link(data)


@router.delete("/links/{link_id}", status_code=204, response_class=Response)
async def delete_link(link_id: str, service: ServiceDep) -> None:
    await service.delete_link(link_id)


@router.get("/resolve", response_model=StructuredResolveOut)
async def resolve(
    service: ServiceDep,
    object_type: Annotated[str, Query()],
    external_id: Annotated[str, Query()],
    source_id: str | None = None,
) -> StructuredResolveOut:
    return await service.resolve(object_type, external_id, source_id=source_id)


@router.get("/attribute-schemas", response_model=list[StructuredAttrSchemaOut])
async def list_attribute_schemas(service: ServiceDep) -> list[StructuredAttrSchemaOut]:
    return [StructuredAttrSchemaOut.model_validate(row) for row in service.list_attribute_schemas()]


@router.get(
    "/attribute-schemas/{object_type}",
    response_model=StructuredAttrSchemaOut,
)
async def get_attribute_schema(
    object_type: str, service: ServiceDep
) -> StructuredAttrSchemaOut:
    return StructuredAttrSchemaOut.model_validate(service.get_attribute_schema(object_type))


@router.get("/object-relations", response_model=list[ObjectRelationOut])
async def list_object_relations(
    service: RelationServiceDep,
    relation_type: str | None = None,
    from_kind: str | None = None,
    from_id: str | None = None,
    to_kind: str | None = None,
    to_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[ObjectRelationOut]:
    return await service.list_relations(
        relation_type=relation_type,
        from_kind=from_kind,
        from_id=from_id,
        to_kind=to_kind,
        to_id=to_id,
        limit=limit,
    )


@router.post("/object-relations", response_model=ObjectRelationOut, status_code=201)
async def create_object_relation(
    data: ObjectRelationCreate, service: RelationServiceDep
) -> ObjectRelationOut:
    return await service.create(data)


@router.delete("/object-relations/{relation_id}", status_code=204, response_class=Response)
async def delete_object_relation(relation_id: str, service: RelationServiceDep) -> None:
    await service.delete(relation_id)


@router.get(
    "/objects/{object_type}/{object_id}/acl",
    response_model=StructuredObjectAclOut,
)
async def get_object_acl(
    object_type: str, object_id: str, service: ServiceDep
) -> StructuredObjectAclOut:
    return await service.get_object_acl(object_type, object_id)


@router.put(
    "/objects/{object_type}/{object_id}/acl",
    response_model=StructuredObjectAclOut,
)
async def set_object_acl(
    object_type: str,
    object_id: str,
    data: StructuredObjectAclUpdate,
    service: ServiceDep,
) -> StructuredObjectAclOut:
    return await service.set_object_acl(object_type, object_id, data)
