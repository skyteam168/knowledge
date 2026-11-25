"""Admin Ontology Studio APIs (OS1)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import AuthzCacheDep, DbSessionDep, RequestContextDep, require_permission
from app.schemas.semantic import (
    SchemaImportIn,
    SchemaImportOut,
    SemanticAttributeCreate,
    SemanticAttributeOut,
    SemanticAttributeUpdate,
    SemanticBatchStatusIn,
    SemanticBatchStatusOut,
    SemanticEntityCreate,
    SemanticEntityOut,
    SemanticItemStatusUpdate,
    SemanticMappingCreate,
    SemanticMappingOut,
    SemanticSuggestOut,
    SemanticVersionCreate,
    SemanticVersionDetailOut,
    SemanticVersionOut,
)
from app.services.ontology_studio.service import OntologyStudioService

router = APIRouter(
    prefix="/admin/ontology",
    tags=["admin:ontology"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_studio(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep
) -> OntologyStudioService:
    return OntologyStudioService(session, ctx, cache)


StudioDep = Annotated[OntologyStudioService, Depends(get_studio)]


@router.get("/versions", response_model=list[SemanticVersionOut])
async def list_versions(service: StudioDep) -> list[SemanticVersionOut]:
    return await service.list_versions()


@router.post("/versions", response_model=SemanticVersionOut, status_code=201)
async def create_version(
    data: SemanticVersionCreate, service: StudioDep
) -> SemanticVersionOut:
    return await service.create_version(data)


@router.get("/versions/{version_id}", response_model=SemanticVersionDetailOut)
async def get_version(
    version_id: str, service: StudioDep
) -> SemanticVersionDetailOut:
    return await service.get_version(version_id)


@router.post(
    "/versions/{version_id}/publish",
    response_model=SemanticVersionOut,
)
async def publish_version(
    version_id: str, service: StudioDep
) -> SemanticVersionOut:
    return await service.publish(version_id)


@router.post(
    "/versions/{version_id}/rollback",
    response_model=SemanticVersionOut,
)
async def rollback_version(
    version_id: str, service: StudioDep
) -> SemanticVersionOut:
    """Re-activate a prior published version (GATE Wave B Task10)."""
    return await service.rollback_publish(version_id)


@router.get("/published", response_model=SemanticVersionDetailOut | None)
async def get_published(service: StudioDep) -> SemanticVersionDetailOut | None:
    active = await service.get_active_published()
    if active is None:
        return None
    return await service.get_version(active.id)


@router.post("/schema-import", response_model=SchemaImportOut, status_code=201)
async def import_schema(data: SchemaImportIn, service: StudioDep) -> SchemaImportOut:
    """OS2: import table/column JSON into a draft semantic version (idempotent)."""
    return await service.import_schema(data)


@router.post(
    "/versions/{version_id}/suggest",
    response_model=SemanticSuggestOut,
)
async def suggest_labels(
    version_id: str, service: StudioDep
) -> SemanticSuggestOut:
    """OS3: generate label/description/type suggestions for draft items."""
    return await service.suggest_labels(version_id)


@router.post(
    "/versions/{version_id}/batch-status",
    response_model=SemanticBatchStatusOut,
)
async def batch_status(
    version_id: str, data: SemanticBatchStatusIn, service: StudioDep
) -> SemanticBatchStatusOut:
    """OS3: Approve / Reject / reset draft for selected items."""
    return await service.batch_set_status(version_id, data)


@router.post(
    "/versions/{version_id}/entities",
    response_model=SemanticEntityOut,
    status_code=201,
)
async def add_entity(
    version_id: str, data: SemanticEntityCreate, service: StudioDep
) -> SemanticEntityOut:
    return await service.add_entity(version_id, data)


@router.patch("/entities/{entity_id}/status", response_model=SemanticEntityOut)
async def set_entity_status(
    entity_id: str, data: SemanticItemStatusUpdate, service: StudioDep
) -> SemanticEntityOut:
    return await service.set_entity_status(entity_id, data.status)


@router.post(
    "/entities/{entity_id}/attributes",
    response_model=SemanticAttributeOut,
    status_code=201,
)
async def add_attribute(
    entity_id: str, data: SemanticAttributeCreate, service: StudioDep
) -> SemanticAttributeOut:
    return await service.add_attribute(entity_id, data)


@router.patch(
    "/attributes/{attribute_id}", response_model=SemanticAttributeOut
)
async def update_attribute(
    attribute_id: str, data: SemanticAttributeUpdate, service: StudioDep
) -> SemanticAttributeOut:
    return await service.update_attribute(attribute_id, data)


@router.patch(
    "/attributes/{attribute_id}/status", response_model=SemanticAttributeOut
)
async def set_attribute_status(
    attribute_id: str, data: SemanticItemStatusUpdate, service: StudioDep
) -> SemanticAttributeOut:
    return await service.set_attribute_status(attribute_id, data.status)


@router.post(
    "/attributes/{attribute_id}/mappings",
    response_model=SemanticMappingOut,
    status_code=201,
)
async def add_mapping(
    attribute_id: str, data: SemanticMappingCreate, service: StudioDep
) -> SemanticMappingOut:
    return await service.add_mapping(attribute_id, data)


@router.patch("/mappings/{mapping_id}/status", response_model=SemanticMappingOut)
async def set_mapping_status(
    mapping_id: str, data: SemanticItemStatusUpdate, service: StudioDep
) -> SemanticMappingOut:
    return await service.set_mapping_status(mapping_id, data.status)
