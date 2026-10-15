from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import DEFAULT_ROLE_CODES, DEFAULT_ROLES, PERMISSION_CATALOG
from app.models import Organization, Role
from app.repositories.org_repo import OrganizationRepository
from app.repositories.role_repo import PermissionRepository, RoleRepository


async def create_organization(session: AsyncSession, code: str, name: str) -> Organization:
    """Create a tenant and seed its system roles with default permissions."""
    org = await OrganizationRepository(session).add(Organization(code=code, name=name))
    await seed_default_roles(session, org.id)
    return org


async def seed_default_roles(session: AsyncSession, org_id: str) -> None:
    perm_repo = PermissionRepository(session)
    role_repo = RoleRepository(session)
    await perm_repo.ensure_catalog(PERMISSION_CATALOG)
    for code, (name, perm_codes) in DEFAULT_ROLES.items():
        role = await role_repo.get_by_code(org_id, code)
        if role is None:
            role = await role_repo.add(
                Role(
                    org_id=org_id,
                    code=code,
                    name=name,
                    is_system=True,
                    is_default=code in DEFAULT_ROLE_CODES,
                )
            )
            await role_repo.set_permissions(role, await perm_repo.list_by_codes(perm_codes))
