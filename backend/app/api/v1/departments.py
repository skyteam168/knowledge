from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import provide, require_permission
from app.schemas.identity import DepartmentCreate, DepartmentNode, DepartmentOut, DepartmentUpdate
from app.services.admin.department_service import DepartmentService

router = APIRouter(prefix="/admin/departments", tags=["admin:departments"])
ServiceDep = Annotated[DepartmentService, Depends(provide(DepartmentService))]
CanManage = [Depends(require_permission("admin:dept"))]


@router.get(
    "/tree",
    response_model=list[DepartmentNode],
    dependencies=[Depends(require_permission("admin:dept", "admin:user"))],
)
async def department_tree(service: ServiceDep) -> list[DepartmentNode]:
    return await service.tree()


@router.post("", response_model=DepartmentOut, status_code=201, dependencies=CanManage)
async def create_department(data: DepartmentCreate, service: ServiceDep) -> DepartmentOut:
    return DepartmentOut.model_validate(await service.create(data))


@router.put("/{dept_id}", response_model=DepartmentOut, dependencies=CanManage)
async def update_department(
    dept_id: str, data: DepartmentUpdate, service: ServiceDep
) -> DepartmentOut:
    return DepartmentOut.model_validate(await service.update(dept_id, data))


@router.delete("/{dept_id}", status_code=204, dependencies=CanManage)
async def delete_department(dept_id: str, service: ServiceDep) -> Response:
    await service.delete(dept_id)
    return Response(status_code=204)
