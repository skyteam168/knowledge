from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import provide, require_permission
from app.schemas.common import Page
from app.schemas.identity import GroupCreate, GroupOut, GroupUpdate, IdsPayload, UserOut
from app.services.admin.group_service import GroupService

router = APIRouter(prefix="/admin/groups", tags=["admin:groups"])
ServiceDep = Annotated[GroupService, Depends(provide(GroupService))]
CanManage = [Depends(require_permission("admin:group"))]


@router.get(
    "",
    response_model=Page[GroupOut],
    dependencies=[Depends(require_permission("admin:group", "admin:user"))],
)
async def list_groups(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    keyword: str | None = None,
) -> Page[GroupOut]:
    return await service.search(page=page, size=size, keyword=keyword)


@router.post("", response_model=GroupOut, status_code=201, dependencies=CanManage)
async def create_group(data: GroupCreate, service: ServiceDep) -> GroupOut:
    return GroupOut.model_validate(await service.create(data))


@router.put("/{group_id}", response_model=GroupOut, dependencies=CanManage)
async def update_group(group_id: str, data: GroupUpdate, service: ServiceDep) -> GroupOut:
    return GroupOut.model_validate(await service.update(group_id, data))


@router.delete("/{group_id}", status_code=204, dependencies=CanManage)
async def delete_group(group_id: str, service: ServiceDep) -> Response:
    await service.delete(group_id)
    return Response(status_code=204)


@router.get("/{group_id}/members", response_model=list[UserOut], dependencies=CanManage)
async def list_members(group_id: str, service: ServiceDep) -> list[UserOut]:
    return await service.members(group_id)


@router.put("/{group_id}/members", response_model=list[UserOut], dependencies=CanManage)
async def set_members(group_id: str, payload: IdsPayload, service: ServiceDep) -> list[UserOut]:
    return await service.set_members(group_id, payload.ids)
