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
from app.schemas.models_admin import (
    CheckOut,
    KindLiteral,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    OverviewOut,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    RoutesIn,
    SyncResultOut,
)
from app.services.models.service import ModelAdminService

router = APIRouter(
    prefix="/admin/models",
    tags=["models-admin"],
    dependencies=[Depends(require_permission("admin:model"))],
)


def get_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> ModelAdminService:
    return ModelAdminService(session, ctx, cache, settings=settings, router=resources.chat_router)


ServiceDep = Annotated[ModelAdminService, Depends(get_service)]


@router.get("/overview", response_model=OverviewOut)
async def overview(service: ServiceDep) -> OverviewOut:
    return await service.overview()


@router.put("/routes", response_model=OverviewOut)
async def save_routes(data: RoutesIn, service: ServiceDep) -> OverviewOut:
    return await service.save_routes(data)


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(service: ServiceDep) -> list[ProviderOut]:
    return await service.list_providers()


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(data: ProviderCreate, service: ServiceDep) -> ProviderOut:
    return await service.create_provider(data)


@router.put("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str, data: ProviderUpdate, service: ServiceDep
) -> ProviderOut:
    return await service.update_provider(provider_id, data)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, service: ServiceDep) -> Response:
    await service.delete_provider(provider_id)
    return Response(status_code=204)


@router.post("/providers/{provider_id}/sync", response_model=SyncResultOut)
async def sync_models(provider_id: str, service: ServiceDep) -> SyncResultOut:
    return await service.sync_models(provider_id)


@router.get("", response_model=Page[ModelOut])
async def list_models(
    service: ServiceDep,
    provider_id: str | None = None,
    kind: KindLiteral | None = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[ModelOut]:
    return await service.list_models(provider_id, kind, keyword, page, size)


@router.post("", response_model=ModelOut, status_code=201)
async def create_model(data: ModelCreate, service: ServiceDep) -> ModelOut:
    return await service.create_model(data)


@router.put("/{model_id}", response_model=ModelOut)
async def update_model(model_id: str, data: ModelUpdate, service: ServiceDep) -> ModelOut:
    return await service.update_model(model_id, data)


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: str, service: ServiceDep) -> Response:
    await service.delete_model(model_id)
    return Response(status_code=204)


@router.post("/{model_id}/check", response_model=CheckOut)
async def check_model(model_id: str, service: ServiceDep) -> CheckOut:
    return await service.check_model(model_id)
