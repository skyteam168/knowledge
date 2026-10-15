from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import provide
from app.schemas.common import Page
from app.schemas.curation import NotificationOut, NotificationReadIn, UnreadCountOut
from app.services.curation.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

ServiceDep = Annotated[NotificationService, Depends(provide(NotificationService))]


@router.get("", response_model=Page[NotificationOut])
async def list_notifications(
    service: ServiceDep,
    unread_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[NotificationOut]:
    return await service.list_page(unread_only=unread_only, page=page, size=size)


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(service: ServiceDep) -> UnreadCountOut:
    return UnreadCountOut(unread=await service.unread_count())


@router.post("/read", response_model=UnreadCountOut)
async def mark_read(data: NotificationReadIn, service: ServiceDep) -> UnreadCountOut:
    await service.mark_read(data.ids)
    return UnreadCountOut(unread=await service.unread_count())
