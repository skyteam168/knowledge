from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import provide, require_permission
from app.schemas.identity import (
    PermissionAssign,
    PermissionOut,
    RoleBulkAssign,
    RoleBulkResult,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from app.services.admin.role_service import RoleService

router = APIRouter(prefix="/admin", tags=["admin:roles"])
ServiceDep = Annotated[RoleService, Depends(provide(RoleService))]
CanManage = [Depends(require_permission("admin:role"))]


@router.get(
    "/roles",
    response_model=list[RoleOut],
    dependencies=[Depends(require_permission("admin:role", "admin:user"))],
)
async def list_roles(service: ServiceDep) -> list[RoleOut]:
    return await service.list_roles()


@router.get("/permissions", response_model=list[PermissionOut], dependencies=CanManage)
async def list_permissions(service: ServiceDep) -> list[PermissionOut]:
    return await service.list_permissions()


@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=CanManage)
async def create_role(data: RoleCreate, service: ServiceDep) -> RoleOut:
    return await service.to_out(await service.create(data))


@router.put("/roles/{role_id}", response_model=RoleOut, dependencies=CanManage)
async def update_role(role_id: str, data: RoleUpdate, service: ServiceDep) -> RoleOut:
    return await service.to_out(await service.update(role_id, data))


@router.delete("/roles/{role_id}", status_code=204, dependencies=CanManage)
async def delete_role(role_id: str, service: ServiceDep) -> Response:
    await service.delete(role_id)
    return Response(status_code=204)


@router.put("/roles/{role_id}/permissions", response_model=RoleOut, dependencies=CanManage)
async def set_role_permissions(
    role_id: str, payload: PermissionAssign, service: ServiceDep
) -> RoleOut:
    return await service.set_permissions(role_id, payload.permissions)


@router.post("/roles/{role_id}/bulk", response_model=RoleBulkResult, dependencies=CanManage)
async def bulk_assign_role(
    role_id: str, payload: RoleBulkAssign, service: ServiceDep
) -> RoleBulkResult:
    return await service.bulk_assign(role_id, payload)
