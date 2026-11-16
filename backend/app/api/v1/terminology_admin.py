from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    require_permission,
)
from app.schemas.common import Page
from app.schemas.terminology import (
    TerminologyAliasCreate,
    TerminologyAliasOut,
    TerminologyEntityCreate,
    TerminologyEntityOut,
    TerminologyEntityUpdate,
    TerminologyNeighborhoodOut,
    TerminologySynonymsSyncOut,
)
from app.services.terminology.service import TerminologyService

router = APIRouter(
    prefix="/admin/terminology",
    tags=["admin:terminology"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_terminology_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep, settings: SettingsDep
) -> TerminologyService:
    return TerminologyService(session, ctx, cache, settings)


ServiceDep = Annotated[TerminologyService, Depends(get_terminology_service)]


@router.get("/entities", response_model=Page[TerminologyEntityOut])
async def list_entities(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    q: str | None = None,
    entity_type: str | None = None,
    status: str | None = None,
) -> Page[TerminologyEntityOut]:
    return await service.list_entities(
        page=page, size=size, q=q, entity_type=entity_type, status=status
    )


@router.get("/entities/{entity_id}", response_model=TerminologyEntityOut)
async def get_entity(entity_id: str, service: ServiceDep) -> TerminologyEntityOut:
    return await service.get_entity(entity_id)


@router.get(
    "/entities/{entity_id}/neighborhood",
    response_model=TerminologyNeighborhoodOut,
)
async def entity_neighborhood(
    entity_id: str, service: ServiceDep
) -> TerminologyNeighborhoodOut:
    return await service.neighborhood(entity_id)


@router.post("/entities", response_model=TerminologyEntityOut, status_code=201)
async def create_entity(
    data: TerminologyEntityCreate, service: ServiceDep
) -> TerminologyEntityOut:
    return await service.create_entity(data)


@router.patch("/entities/{entity_id}", response_model=TerminologyEntityOut)
async def update_entity(
    entity_id: str, data: TerminologyEntityUpdate, service: ServiceDep
) -> TerminologyEntityOut:
    return await service.update_entity(entity_id, data)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(entity_id: str, service: ServiceDep) -> Response:
    await service.delete_entity(entity_id)
    return Response(status_code=204)


@router.post(
    "/entities/{entity_id}/aliases", response_model=TerminologyAliasOut, status_code=201
)
async def add_alias(
    entity_id: str, data: TerminologyAliasCreate, service: ServiceDep
) -> TerminologyAliasOut:
    return await service.add_alias(entity_id, data)


@router.delete("/aliases/{alias_id}", status_code=204)
async def delete_alias(alias_id: str, service: ServiceDep) -> Response:
    await service.delete_alias(alias_id)
    return Response(status_code=204)


@router.post("/synonyms/sync", response_model=TerminologySynonymsSyncOut)
async def sync_synonyms(
    service: ServiceDep,
    resources: ResourcesDep,
    reload: Annotated[bool, Query()] = True,
) -> TerminologySynonymsSyncOut:
    """Export active terminology into OpenSearch synonyms.txt and reload analyzers."""
    return await service.sync_opensearch_synonyms(
        reload=reload, runtime=resources.indexing
    )
