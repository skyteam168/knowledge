from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    require_permission,
    require_platform_admin,
)
from app.models import OutboxStatus
from app.schemas.common import Page
from app.schemas.indexing import (
    ConsistencyReportOut,
    IndexGenerationOut,
    OutboxEventOut,
    OutboxStatsOut,
    RepairQueuedOut,
    RetryResultOut,
)
from app.services.indexing.admin_service import IndexAdminService

router = APIRouter(
    prefix="/admin/index",
    tags=["admin:index"],
    dependencies=[Depends(require_permission("admin:index"))],
)


def get_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    resources: ResourcesDep,
) -> IndexAdminService:
    return IndexAdminService(
        session, ctx, cache, runtime=resources.indexing, queue=resources.task_queue
    )


ServiceDep = Annotated[IndexAdminService, Depends(get_service)]


@router.get("/outbox/stats", response_model=OutboxStatsOut)
async def outbox_stats(service: ServiceDep) -> OutboxStatsOut:
    return await service.outbox_stats()


@router.get("/outbox", response_model=Page[OutboxEventOut])
async def list_outbox(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    status_: Annotated[OutboxStatus | None, Query(alias="status")] = None,
    event_type: str | None = None,
) -> Page[OutboxEventOut]:
    return await service.list_outbox(
        page=page,
        size=size,
        status=status_.value if status_ else None,
        event_type=event_type,
    )


@router.post("/outbox/retry-dead", response_model=RetryResultOut)
async def retry_all_dead(service: ServiceDep) -> RetryResultOut:
    return await service.retry_all_dead()


@router.post("/outbox/{event_id}/retry", response_model=OutboxEventOut)
async def retry_event(event_id: str, service: ServiceDep) -> OutboxEventOut:
    return await service.retry_event(event_id)


@router.get("/generations", response_model=list[IndexGenerationOut])
async def list_generations(service: ServiceDep) -> list[IndexGenerationOut]:
    return await service.generations()


@router.post("/kbs/{kb_id}/check", response_model=ConsistencyReportOut)
async def check_kb(kb_id: str, service: ServiceDep) -> ConsistencyReportOut:
    return await service.check_kb(kb_id)


@router.post(
    "/kbs/{kb_id}/repair", response_model=RepairQueuedOut, status_code=status.HTTP_202_ACCEPTED
)
async def repair_kb(kb_id: str, service: ServiceDep) -> RepairQueuedOut:
    return await service.queue_repair(kb_id)


@router.post(
    "/synonyms/reload",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_platform_admin)],
)
async def reload_synonyms(service: ServiceDep) -> None:
    await service.reload_synonyms()
