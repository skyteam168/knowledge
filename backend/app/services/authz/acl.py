from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResourceAcl
from app.repositories.acl_repo import ResourceAclRepository
from app.services.authz.context import CurrentUser
from app.services.authz.principals import Principals


class AclPermission(StrEnum):
    READ = "read"
    EDIT = "edit"
    MANAGE = "manage"

    @property
    def level(self) -> int:
        return _LEVELS[self]


_LEVELS = {AclPermission.READ: 1, AclPermission.EDIT: 2, AclPermission.MANAGE: 3}


class PrincipalType(StrEnum):
    USER = "user"
    GROUP = "group"
    ROLE = "role"
    DEPT = "dept"
    ORG = "org"


@dataclass(frozen=True)
class ResourceRef:
    type: str
    id: str


# Index contract (Qdrant payload / OpenSearch fields) of the derived search indexes:
#   org_id: str, kb_id: str,
#   acl_read_principals: list[str] of "<principal_type>:<id>" holding >= read, e.g.
#   ["org:1", "dept:5", "group:9", "role:3", "user:12"] ("org:<id>" = visible org-wide).
ACL_PRINCIPALS_FIELD = "acl_read_principals"


@dataclass(frozen=True)
class AclFilter:
    """Backend-neutral read pre-filter; render with to_qdrant() / to_opensearch()."""

    org_id: str
    principals: tuple[str, ...]
    kb_ids: tuple[str, ...] = ()
    bypass_acl: bool = False

    def to_qdrant(self) -> dict[str, Any]:
        must: list[dict[str, Any]] = [{"key": "org_id", "match": {"value": self.org_id}}]
        if self.kb_ids:
            must.append({"key": "kb_id", "match": {"any": list(self.kb_ids)}})
        if not self.bypass_acl:
            must.append({"key": ACL_PRINCIPALS_FIELD, "match": {"any": list(self.principals)}})
        return {"must": must}

    def to_opensearch(self) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [{"term": {"org_id": self.org_id}}]
        if self.kb_ids:
            filters.append({"terms": {"kb_id": list(self.kb_ids)}})
        if not self.bypass_acl:
            filters.append({"terms": {ACL_PRINCIPALS_FIELD: list(self.principals)}})
        return {"bool": {"filter": filters}}


class AclService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ResourceAclRepository(session)

    async def effective_permission(
        self, principals: Principals, resource: ResourceRef
    ) -> AclPermission | None:
        rows = await self.repo.list_matching(
            principals.org_id, resource.type, resource.id, principals.pairs()
        )
        best: AclPermission | None = None
        for row in rows:
            perm = AclPermission(row.permission)
            if best is None or perm.level > best.level:
                best = perm
        return best

    async def can(self, user: CurrentUser, resource: ResourceRef, perm: AclPermission) -> bool:
        if user.is_superuser:
            return True
        effective = await self.effective_permission(user.principals, resource)
        return effective is not None and effective.level >= perm.level

    async def grant(
        self,
        org_id: str,
        resource: ResourceRef,
        principal_type: PrincipalType,
        principal_id: str,
        perm: AclPermission,
        granted_by: str | None = None,
    ) -> ResourceAcl:
        existing = await self.repo.find(
            org_id, resource.type, resource.id, principal_type, principal_id, perm
        )
        if existing:
            return existing
        return await self.repo.add(
            ResourceAcl(
                org_id=org_id,
                resource_type=resource.type,
                resource_id=resource.id,
                principal_type=principal_type.value,
                principal_id=principal_id,
                permission=perm.value,
                created_by=granted_by,
            )
        )

    async def revoke(
        self,
        org_id: str,
        resource: ResourceRef,
        principal_type: PrincipalType,
        principal_id: str,
        perm: AclPermission | None = None,
    ) -> int:
        return await self.repo.delete_entry(
            org_id,
            resource.type,
            resource.id,
            principal_type,
            principal_id,
            perm.value if perm else None,
        )

    async def list_entries(self, org_id: str, resource: ResourceRef) -> list[ResourceAcl]:
        return await self.repo.list_for_resource(org_id, resource.type, resource.id)

    @staticmethod
    def build_filter(
        principals: Principals,
        *,
        kb_ids: Iterable[str] | None = None,
        bypass_acl: bool = False,
    ) -> AclFilter:
        """Read-access pre-filter for retrieval. Results must still be re-checked against PG.

        `bypass_acl` (superusers) drops the principal condition but never the tenant one.
        """
        return AclFilter(
            org_id=principals.org_id,
            principals=tuple(f"{ptype}:{pid}" for ptype, pid in principals.pairs()),
            kb_ids=tuple(sorted(set(kb_ids or ()))),
            bypass_acl=bypass_acl,
        )
