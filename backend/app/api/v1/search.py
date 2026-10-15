from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    require_permission,
)
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.search import SearchOptionsOut, SearchResponse
from app.services.search.search_service import SearchParams, SearchService

router = APIRouter(
    prefix="/search",
    tags=["search"],
    dependencies=[Depends(require_permission("search:use"))],
)


def get_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> SearchService:
    pipeline = RetrievalPipeline.build(resources.indexing.backends, resources.llm, resources.cache)
    return SearchService(session, ctx, cache, pipeline=pipeline, settings=settings)


ServiceDep = Annotated[SearchService, Depends(get_service)]


@router.get("", response_model=SearchResponse)
async def search(
    service: ServiceDep,
    q: Annotated[str, Query(min_length=1, max_length=1000, description="query text")],
    kb_ids: Annotated[list[str] | None, Query()] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    doc_types: Annotated[list[str] | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(description="inclusive")] = None,
    date_to: Annotated[datetime | None, Query(description="exclusive")] = None,
    top_k: Annotated[int | None, Query(ge=1, le=100)] = None,
    profile_id: Annotated[str | None, Query(description="admin:retrieval only")] = None,
    debug: Annotated[bool, Query(description="admin:retrieval only")] = False,
) -> SearchResponse:
    return await service.search(
        SearchParams(
            q=q,
            kb_ids=tuple(kb_ids or ()),
            tags=tuple(tags or ()),
            doc_types=tuple(doc_types or ()),
            date_from=date_from,
            date_to=date_to,
            top_k=top_k,
            profile_id=profile_id,
            debug=debug,
        )
    )


@router.get("/options", response_model=SearchOptionsOut)
async def search_options(service: ServiceDep) -> SearchOptionsOut:
    return await service.options()
