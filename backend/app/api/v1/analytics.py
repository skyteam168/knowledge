from datetime import date
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
from app.schemas.analytics import (
    AnalyticsContentOut,
    AnalyticsFiltersOut,
    AnalyticsOverviewOut,
    AnalyticsRefreshIn,
    AnalyticsRefreshOut,
    LlmUsageOut,
)
from app.services.analytics.aggregator import AnalyticsAggregator
from app.services.analytics.analytics_service import AnalyticsService
from app.services.analytics.usage_service import LlmUsageService

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_permission("analytics:view"))],
)


def get_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep, settings: SettingsDep
) -> AnalyticsService:
    return AnalyticsService(session, ctx, cache, settings=settings)


ServiceDep = Annotated[AnalyticsService, Depends(get_service)]
OrgQuery = Annotated[str | None, Query(max_length=32, description="Platform admins only")]
KbQuery = Annotated[str | None, Query(max_length=32)]


@router.get("/filters", response_model=AnalyticsFiltersOut)
async def filters(service: ServiceDep, org_id: OrgQuery = None) -> AnalyticsFiltersOut:
    return await service.filters(org_id)


@router.get("/overview", response_model=AnalyticsOverviewOut)
async def overview(
    service: ServiceDep,
    org_id: OrgQuery = None,
    kb_id: KbQuery = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AnalyticsOverviewOut:
    """Usage, quality and latency of [date_from, date_to] (days in the analytics timezone)."""
    return await service.overview(org_id, kb_id, date_from, date_to)


@router.get("/content", response_model=AnalyticsContentOut)
async def content(
    service: ServiceDep, org_id: OrgQuery = None, kb_id: KbQuery = None
) -> AnalyticsContentOut:
    return await service.content(org_id, kb_id)


def get_usage_service(
    session: DbSessionDep, ctx: RequestContextDep, cache: AuthzCacheDep, settings: SettingsDep
) -> LlmUsageService:
    return LlmUsageService(session, ctx, cache, settings=settings)


@router.get(
    "/llm-usage",
    response_model=LlmUsageOut,
    dependencies=[Depends(require_permission("analytics:usage"))],
)
async def llm_usage(
    service: Annotated[LlmUsageService, Depends(get_usage_service)],
    org_id: OrgQuery = None,
    user_id: Annotated[str | None, Query(max_length=32)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> LlmUsageOut:
    """Model calls and tokens of [date_from, date_to] per day, model, feature and user."""
    return await service.usage(org_id, date_from, date_to, user_id)


@router.post("/refresh", response_model=AnalyticsRefreshOut)
async def refresh(
    data: AnalyticsRefreshIn,
    service: ServiceDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> AnalyticsRefreshOut:
    """Recompute the caller's org summaries of the last `days` days now."""
    aggregator = AnalyticsAggregator(resources.session_factory, settings)
    return await service.refresh(aggregator, data.days)
