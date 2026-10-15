from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import provide, require_permission
from app.schemas.knowledge import DirectoryDepartment, GrantablePrincipal, PrincipalOption
from app.services.knowledge.directory import DirectoryService

router = APIRouter(prefix="/directory", tags=["directory"])
ServiceDep = Annotated[DirectoryService, Depends(provide(DirectoryService))]
CanGrant = [Depends(require_permission("kb:create", "kb:update", "doc:upload"))]


@router.get("/departments", response_model=list[DirectoryDepartment], dependencies=CanGrant)
async def departments(service: ServiceDep) -> list[DirectoryDepartment]:
    return await service.departments()


@router.get("/principals", response_model=list[PrincipalOption], dependencies=CanGrant)
async def principals(
    service: ServiceDep,
    type: GrantablePrincipal,
    keyword: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[PrincipalOption]:
    return await service.principals(type, keyword, limit)
