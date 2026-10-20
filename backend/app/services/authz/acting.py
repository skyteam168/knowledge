from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.authz.cache import AuthzCache
from app.services.authz.context import CurrentUser
from app.services.authz.principals import PermissionResolver, PrincipalResolver


async def current_user_of(session: AsyncSession, cache: AuthzCache, user: User) -> CurrentUser:
    """Another user's principals and permissions, e.g. to check what an owner can access."""
    principals = await PrincipalResolver(session, cache).resolve(user.org_id, user.id)
    return CurrentUser(
        id=user.id,
        org_id=user.org_id,
        username=user.username,
        display_name=user.display_name,
        principals=principals,
        permissions=await PermissionResolver(session, cache).resolve(principals),
    )
