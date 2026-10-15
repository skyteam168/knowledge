from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.org_repo import DepartmentRepository, OrganizationRepository
from app.repositories.user_repo import UserRepository
from app.schemas.identity import (
    DepartmentOut,
    GroupBrief,
    MeResponse,
    OrganizationOut,
    RoleBrief,
)
from app.services.authz.context import CurrentUser


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.users = UserRepository(session)
        self.orgs = OrganizationRepository(session)
        self.departments = DepartmentRepository(session)

    async def me(self, user: CurrentUser) -> MeResponse:
        db_user = await self.users.get(user.org_id, user.id)
        org = await self.orgs.get(user.org_id)
        if db_user is None or org is None:
            raise NotFoundError("User not found")
        dept = (
            await self.departments.get(user.org_id, db_user.department_id)
            if db_user.department_id
            else None
        )
        roles = await self.users.list_roles(user.org_id, user.id)
        groups = await self.users.list_groups(user.org_id, user.id)
        return MeResponse(
            id=db_user.id,
            username=db_user.username,
            display_name=db_user.display_name,
            email=db_user.email,
            org=OrganizationOut.model_validate(org),
            department=DepartmentOut.model_validate(dept) if dept else None,
            roles=[RoleBrief.model_validate(r) for r in roles],
            groups=[GroupBrief.model_validate(g) for g in groups],
            permissions=sorted(user.permissions),
            is_platform_admin=user.is_platform_admin,
        )
