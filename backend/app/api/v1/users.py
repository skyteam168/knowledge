from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    AuthzCacheDep,
    DbSessionDep,
    RequestContextDep,
    ResourcesDep,
    SettingsDep,
    provide,
    require_permission,
)
from app.schemas.common import Page
from app.schemas.identity import (
    IdsPayload,
    PasswordLoginOut,
    UserCreate,
    UserDetail,
    UserOut,
    UserUpdate,
)
from app.services.admin.password_login import PasswordLoginService
from app.services.admin.user_service import UserService

router = APIRouter(prefix="/admin/users", tags=["admin:users"])
ServiceDep = Annotated[UserService, Depends(provide(UserService))]
CanManage = [Depends(require_permission("admin:user"))]


@router.get(
    "",
    response_model=Page[UserOut],
    dependencies=[Depends(require_permission("admin:user", "admin:group"))],
)
async def list_users(
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
    keyword: str | None = None,
    department_id: str | None = None,
    include_sub_departments: bool = True,
    group_id: str | None = None,
    is_active: bool | None = None,
) -> Page[UserOut]:
    return await service.search(
        page=page,
        size=size,
        keyword=keyword,
        department_id=department_id,
        include_sub_departments=include_sub_departments,
        group_id=group_id,
        is_active=is_active,
    )


@router.get("/{user_id}", response_model=UserDetail, dependencies=CanManage)
async def get_user(user_id: str, service: ServiceDep) -> UserDetail:
    return await service.detail(user_id)


@router.post("", response_model=UserOut, status_code=201, dependencies=CanManage)
async def create_user(data: UserCreate, service: ServiceDep) -> UserOut:
    return await service.out(await service.create(data))


@router.put("/{user_id}", response_model=UserOut, dependencies=CanManage)
async def update_user(user_id: str, data: UserUpdate, service: ServiceDep) -> UserOut:
    return await service.out(await service.update(user_id, data))


@router.delete("/{user_id}", response_model=UserOut, dependencies=CanManage)
async def disable_user(user_id: str, service: ServiceDep) -> UserOut:
    return await service.out(await service.disable(user_id))


@router.put(
    "/{user_id}/roles",
    response_model=UserDetail,
    dependencies=[Depends(require_permission("admin:role"))],
)
async def set_user_roles(user_id: str, payload: IdsPayload, service: ServiceDep) -> UserDetail:
    return await service.set_roles(user_id, payload.ids)


@router.put("/{user_id}/groups", response_model=UserDetail, dependencies=CanManage)
async def set_user_groups(user_id: str, payload: IdsPayload, service: ServiceDep) -> UserDetail:
    return await service.set_groups(user_id, payload.ids)


def get_password_login_service(
    session: DbSessionDep,
    ctx: RequestContextDep,
    cache: AuthzCacheDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> PasswordLoginService:
    return PasswordLoginService(session, ctx, cache, settings=settings, http=resources.http)


@router.post("/{user_id}/password-login", response_model=PasswordLoginOut, dependencies=CanManage)
async def open_password_login(
    user_id: str,
    service: Annotated[PasswordLoginService, Depends(get_password_login_service)],
) -> PasswordLoginOut:
    return await service.open(user_id)
