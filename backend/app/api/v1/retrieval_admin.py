from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    SettingsDep,
    get_conversation_service,
    provide,
    require_permission,
)
from app.retrieval.config import RetrievalConfig
from app.schemas.chat import QaTraceOut
from app.schemas.common import Page
from app.schemas.search import (
    RetrievalProfileCreate,
    RetrievalProfileOut,
    RetrievalProfileUpdate,
    RetrievalTraceOut,
    RetrievalTraceSummaryOut,
)
from app.services.chat.conversation_service import ConversationService
from app.services.search.profile_service import RetrievalProfileService
from app.services.search.trace_service import RetrievalTraceService

router = APIRouter(
    prefix="/admin/retrieval",
    tags=["admin:retrieval"],
    dependencies=[Depends(require_permission("admin:retrieval"))],
)


def get_profile_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep, settings: SettingsDep
) -> RetrievalProfileService:
    return RetrievalProfileService(session, ctx, cache, settings=settings)


ProfileServiceDep = Annotated[RetrievalProfileService, Depends(get_profile_service)]
TraceServiceDep = Annotated[RetrievalTraceService, Depends(provide(RetrievalTraceService))]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


@router.get("/profiles", response_model=list[RetrievalProfileOut])
async def list_profiles(service: ProfileServiceDep) -> list[RetrievalProfileOut]:
    return await service.list()


@router.get("/profiles/defaults", response_model=RetrievalConfig)
async def default_config(service: ProfileServiceDep) -> RetrievalConfig:
    return await service.builtin_config()


@router.post("/profiles", response_model=RetrievalProfileOut, status_code=201)
async def create_profile(
    data: RetrievalProfileCreate, service: ProfileServiceDep
) -> RetrievalProfileOut:
    return await service.create(data)


@router.put("/profiles/{profile_id}", response_model=RetrievalProfileOut)
async def update_profile(
    profile_id: str, data: RetrievalProfileUpdate, service: ProfileServiceDep
) -> RetrievalProfileOut:
    return await service.update(profile_id, data)


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, service: ProfileServiceDep) -> Response:
    await service.delete(profile_id)
    return Response(status_code=204)


@router.post("/profiles/{profile_id}/activate", response_model=RetrievalProfileOut)
async def activate_profile(profile_id: str, service: ProfileServiceDep) -> RetrievalProfileOut:
    """`profile_id` = `builtin` reverts the org to the built-in defaults."""
    return await service.activate(profile_id)


@router.get("/traces", response_model=Page[RetrievalTraceSummaryOut])
async def list_traces(
    service: TraceServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    user_id: str | None = None,
    keyword: str | None = None,
    degraded_only: bool = False,
) -> Page[RetrievalTraceSummaryOut]:
    return await service.list(
        page=page, size=size, user_id=user_id, keyword=keyword, degraded_only=degraded_only
    )


@router.get("/traces/{trace_id}", response_model=RetrievalTraceOut)
async def get_trace(trace_id: str, service: TraceServiceDep) -> RetrievalTraceOut:
    return await service.get(trace_id)


@router.get("/qa-traces/{trace_id}", response_model=QaTraceOut)
async def get_qa_trace(trace_id: str, service: ConversationServiceDep) -> QaTraceOut:
    return QaTraceOut.model_validate(await service.qa_trace(trace_id))
