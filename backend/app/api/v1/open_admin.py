from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    require_permission,
)
from app.core.exceptions import NotFoundError
from app.models import ApiClient
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.common import Page
from app.schemas.open_api import (
    ApiCallLogOut,
    ApiClientCreate,
    ApiClientOut,
    ApiClientUpdate,
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    ApiUsageOut,
    OpenApiOptionsOut,
    OpenRetrieveIn,
    OpenRetrieveOut,
)
from app.services.context import RequestContext
from app.services.open_api.auth import build_caller, caller_user
from app.services.open_api.client_service import OpenApiClientService
from app.services.open_api.open_service import RESOURCE_API_CLIENT, OpenApiService

router = APIRouter(
    prefix="/admin/open-api",
    tags=["open-api-admin"],
    dependencies=[Depends(require_permission("admin:openapi"))],
)


def get_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep, settings: SettingsDep
) -> OpenApiClientService:
    return OpenApiClientService(session, ctx, cache, settings=settings)


ServiceDep = Annotated[OpenApiClientService, Depends(get_service)]


@router.get("/options", response_model=OpenApiOptionsOut)
async def options(service: ServiceDep) -> OpenApiOptionsOut:
    return await service.options()


@router.get("/clients", response_model=Page[ApiClientOut])
async def list_clients(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    status: Annotated[Literal["active", "disabled"] | None, Query()] = None,
) -> Page[ApiClientOut]:
    return await service.list_clients(page=page, size=size, keyword=keyword, status=status)


@router.post("/clients", response_model=ApiClientOut, status_code=201)
async def create_client(data: ApiClientCreate, service: ServiceDep) -> ApiClientOut:
    return await service.create(data)


@router.get("/clients/{client_id}", response_model=ApiClientOut)
async def get_client(client_id: str, service: ServiceDep) -> ApiClientOut:
    return await service.get(client_id)


@router.put("/clients/{client_id}", response_model=ApiClientOut)
async def update_client(client_id: str, data: ApiClientUpdate, service: ServiceDep) -> ApiClientOut:
    return await service.update(client_id, data)


@router.delete("/clients/{client_id}", status_code=204)
async def delete_client(client_id: str, service: ServiceDep) -> Response:
    await service.delete(client_id)
    return Response(status_code=204)


@router.get("/clients/{client_id}/keys", response_model=list[ApiKeyOut])
async def list_keys(client_id: str, service: ServiceDep) -> list[ApiKeyOut]:
    return await service.keys(client_id)


@router.post("/clients/{client_id}/keys", response_model=ApiKeyCreatedOut, status_code=201)
async def create_key(client_id: str, data: ApiKeyCreate, service: ServiceDep) -> ApiKeyCreatedOut:
    return await service.create_key(client_id, data)


@router.post("/clients/{client_id}/keys/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(client_id: str, key_id: str, service: ServiceDep) -> ApiKeyOut:
    return await service.revoke_key(client_id, key_id)


@router.get("/clients/{client_id}/logs", response_model=Page[ApiCallLogOut])
async def list_logs(
    client_id: str,
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    outcome: Annotated[Literal["ok", "error"] | None, Query()] = None,
) -> Page[ApiCallLogOut]:
    return await service.logs(client_id, page=page, size=size, outcome=outcome)


@router.get("/clients/{client_id}/usage", response_model=ApiUsageOut)
async def usage(
    client_id: str, service: ServiceDep, days: Annotated[int, Query(ge=1, le=90)] = 14
) -> ApiUsageOut:
    return await service.usage(client_id, days)


@router.post("/clients/{client_id}/preview", response_model=OpenRetrieveOut)
async def preview(
    client_id: str,
    data: OpenRetrieveIn,
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> OpenRetrieveOut:
    """Retrieve exactly as the client would (its identity and grants), for the admin to check."""
    client = await session.get(ApiClient, client_id)
    if client is None or client.org_id != ctx.org_id:
        raise NotFoundError("API client not found")
    user = await caller_user(session, client)
    caller = build_caller("preview", client, user, settings)
    service = OpenApiService(
        session,
        RequestContext(user=user, audit=ctx.audit),
        cache,
        caller=caller,
        pipeline=RetrievalPipeline.build(
            resources.indexing.backends, resources.llm, resources.cache
        ),
        gateway=resources.llm,
        settings=settings,
        storage=resources.storage,
    )
    out = await service.retrieve(data, audit=False)
    await service.audit.record(
        ctx.audit,
        "openapi.client.preview",
        RESOURCE_API_CLIENT,
        client.id,
        None,
        {"query": data.query, "kb_ids": out.kb_ids, "results": out.total},
    )
    return out
