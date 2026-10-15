from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import provide, require_permission, require_platform_admin
from app.schemas.identity import OrganizationCreate, OrganizationOut, OrganizationUpdate
from app.services.admin.organization_service import OrganizationService

router = APIRouter(tags=["admin:organizations"])
ServiceDep = Annotated[OrganizationService, Depends(provide(OrganizationService))]


@router.get(
    "/admin/organization",
    response_model=OrganizationOut,
    dependencies=[Depends(require_permission("admin:org"))],
)
async def get_current_org(service: ServiceDep) -> OrganizationOut:
    return OrganizationOut.model_validate(await service.current())


@router.put(
    "/admin/organization",
    response_model=OrganizationOut,
    dependencies=[Depends(require_permission("admin:org"))],
)
async def update_current_org(data: OrganizationUpdate, service: ServiceDep) -> OrganizationOut:
    return OrganizationOut.model_validate(await service.update_current(data))


platform = APIRouter(
    prefix="/platform/organizations",
    tags=["platform"],
    dependencies=[Depends(require_platform_admin)],
)


@platform.get("", response_model=list[OrganizationOut])
async def list_orgs(service: ServiceDep) -> list[OrganizationOut]:
    return [OrganizationOut.model_validate(o) for o in await service.list_all()]


@platform.post("", response_model=OrganizationOut, status_code=201)
async def create_org(data: OrganizationCreate, service: ServiceDep) -> OrganizationOut:
    return OrganizationOut.model_validate(await service.create(data))


@platform.put("/{org_id}", response_model=OrganizationOut)
async def update_org(org_id: str, data: OrganizationUpdate, service: ServiceDep) -> OrganizationOut:
    return OrganizationOut.model_validate(await service.update(org_id, data))


@platform.delete("/{org_id}", response_model=OrganizationOut)
async def disable_org(org_id: str, service: ServiceDep) -> OrganizationOut:
    return OrganizationOut.model_validate(await service.disable(org_id))


router.include_router(platform)
