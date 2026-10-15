from typing import Any

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Organization
from app.repositories.base import apply_updates
from app.repositories.org_repo import OrganizationRepository
from app.schemas.identity import OrganizationCreate, OrganizationUpdate
from app.services.audit_service import audited
from app.services.context import BaseService
from app.services.org_bootstrap import create_organization


async def _load_current(self: "OrganizationService", *_: Any, **__: Any) -> Organization:
    return await self.current()


async def _load_org(self: "OrganizationService", org_id: str, *_: Any, **__: Any) -> Organization:
    return await self.get(org_id)


class OrganizationService(BaseService):
    @property
    def repo(self) -> OrganizationRepository:
        return OrganizationRepository(self.session)

    async def current(self) -> Organization:
        return await self.get(self.org_id)

    async def get(self, org_id: str) -> Organization:
        org = await self.repo.get(org_id)
        if org is None:
            raise NotFoundError("Organization not found")
        return org

    @audited("organization.update", "organization", load=_load_current)
    async def update_current(self, data: OrganizationUpdate) -> Organization:
        org = await self.current()
        values = data.model_dump(exclude_unset=True, exclude={"status"})
        apply_updates(org, values)
        await self.session.flush()
        return org

    # ---- platform-level (cross-tenant) operations ---------------------------

    async def list_all(self) -> list[Organization]:
        return await self.repo.list_all()

    @audited("organization.create", "organization")
    async def create(self, data: OrganizationCreate) -> Organization:
        if await self.repo.get_by_code(data.code):
            raise ConflictError(f"Organization code '{data.code}' already exists")
        return await create_organization(self.session, data.code, data.name)

    @audited("organization.update", "organization", load=_load_org)
    async def update(self, org_id: str, data: OrganizationUpdate) -> Organization:
        org = await self.get(org_id)
        if data.status == "disabled" and org_id == self.org_id:
            raise ConflictError("Cannot disable your own organization")
        apply_updates(org, data.model_dump(exclude_unset=True))
        await self.session.flush()
        return org

    @audited("organization.disable", "organization", load=_load_org)
    async def disable(self, org_id: str) -> Organization:
        if org_id == self.org_id:
            raise ConflictError("Cannot disable your own organization")
        org = await self.get(org_id)
        org.status = "disabled"
        await self.session.flush()
        return org
