from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import provide, require_permission
from app.schemas.collab import (
    CommentCreate,
    CommentOut,
    CommentResolveIn,
    CommentUpdate,
    FavoriteStateOut,
    RecentViewIn,
    ResourceType,
    SavedItemOut,
)
from app.services.collab.comments import CommentService
from app.services.collab.favorites import FavoriteService

router = APIRouter(tags=["collaboration"], dependencies=[Depends(require_permission("kb:read"))])
FavoritesDep = Annotated[FavoriteService, Depends(provide(FavoriteService))]
CommentsDep = Annotated[CommentService, Depends(provide(CommentService))]
ResourceId = Annotated[str, Path(min_length=1, max_length=32)]


@router.get("/me/favorites", response_model=list[SavedItemOut])
async def list_favorites(service: FavoritesDep) -> list[SavedItemOut]:
    return await service.favorites()


@router.get("/me/favorites/{resource_type}/{resource_id}", response_model=FavoriteStateOut)
async def favorite_state(
    resource_type: ResourceType, resource_id: ResourceId, service: FavoritesDep
) -> FavoriteStateOut:
    return FavoriteStateOut(favorited=await service.is_favorite(resource_type, resource_id))


@router.put("/me/favorites/{resource_type}/{resource_id}", response_model=FavoriteStateOut)
async def add_favorite(
    resource_type: ResourceType, resource_id: ResourceId, service: FavoritesDep
) -> FavoriteStateOut:
    await service.add(resource_type, resource_id)
    return FavoriteStateOut(favorited=True)


@router.delete("/me/favorites/{resource_type}/{resource_id}", response_model=FavoriteStateOut)
async def remove_favorite(
    resource_type: ResourceType, resource_id: ResourceId, service: FavoritesDep
) -> FavoriteStateOut:
    await service.remove(resource_type, resource_id)
    return FavoriteStateOut(favorited=False)


@router.get("/me/recent", response_model=list[SavedItemOut])
async def list_recent(
    service: FavoritesDep, limit: Annotated[int, Query(ge=1, le=50)] = 20
) -> list[SavedItemOut]:
    return await service.recent(limit)


@router.post("/me/recent", status_code=204)
async def record_view(data: RecentViewIn, service: FavoritesDep) -> Response:
    await service.touch(data.resource_type, data.resource_id)
    return Response(status_code=204)


@router.get("/documents/{document_id}/comments", response_model=list[CommentOut])
async def list_comments(document_id: str, service: CommentsDep) -> list[CommentOut]:
    return await service.threads(document_id)


@router.post("/documents/{document_id}/comments", response_model=CommentOut, status_code=201)
async def create_comment(document_id: str, data: CommentCreate, service: CommentsDep) -> CommentOut:
    return await service.create(document_id, data)


@router.put("/comments/{comment_id}", response_model=CommentOut)
async def update_comment(comment_id: str, data: CommentUpdate, service: CommentsDep) -> CommentOut:
    return await service.update(comment_id, data)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: str, service: CommentsDep) -> Response:
    await service.delete(comment_id)
    return Response(status_code=204)


@router.post("/comments/{comment_id}/resolve", response_model=CommentOut)
async def resolve_comment(
    comment_id: str, data: CommentResolveIn, service: CommentsDep
) -> CommentOut:
    return await service.resolve(comment_id, data.resolved)
