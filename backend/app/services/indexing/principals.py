"""Materializes who may read a document / KO as `acl_read_principals` tokens for the indexes.

Mirrors KnowledgeAccess.resource_permissions (any ACL entry grants at least `read`):
- acl_inherit: KB entries, plus `org:<id>` when the KB is visible org-wide;
- own ACL: the resource's entries, plus KB `manage` holders (they always keep access).
Tokens are `<principal_type>:<id>`, matched against Principals.pairs() at query time.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KbVisibility, ResourceAcl
from app.repositories.indexing_repo import IndexingRepository
from app.services.authz import AclPermission, PrincipalType
from app.services.knowledge.access import RESOURCE_DOCUMENT, RESOURCE_KB


class IndexedResource(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def org_id(self) -> str: ...

    @property
    def kb_id(self) -> str: ...

    @property
    def acl_inherit(self) -> bool: ...


def principal_token(principal_type: str, principal_id: str) -> str:
    return f"{principal_type}:{principal_id}"


def _tokens(rows: Sequence[ResourceAcl]) -> set[str]:
    return {principal_token(r.principal_type, r.principal_id) for r in rows}


async def compute_read_principals(
    session: AsyncSession,
    items: Sequence[IndexedResource],
    resource_type: str = RESOURCE_DOCUMENT,
) -> dict[str, list[str]]:
    repo = IndexingRepository(session)
    kb_ids = sorted({d.kb_id for d in items})
    kbs = {kb.id: kb for kb in await repo.knowledge_bases(kb_ids)}

    kb_rows: dict[str, list[ResourceAcl]] = defaultdict(list)
    for row in await repo.acl_rows(RESOURCE_KB, kb_ids):
        kb_rows[row.resource_id].append(row)
    own_ids = [d.id for d in items if not d.acl_inherit]
    own_rows: dict[str, list[ResourceAcl]] = defaultdict(list)
    for row in await repo.acl_rows(resource_type, own_ids):
        own_rows[row.resource_id].append(row)

    result: dict[str, list[str]] = {}
    for item in items:
        kb = kbs.get(item.kb_id)
        # Rows are matched on org too: resource ids are global, but never trust cross-tenant rows.
        kb_entries = [r for r in kb_rows.get(item.kb_id, []) if r.org_id == item.org_id]
        if item.acl_inherit:
            tokens = _tokens(kb_entries)
            if kb is not None and kb.visibility == KbVisibility.ORG.value:
                tokens.add(principal_token(PrincipalType.ORG.value, item.org_id))
        else:
            own = [r for r in own_rows.get(item.id, []) if r.org_id == item.org_id]
            managers = [r for r in kb_entries if r.permission == AclPermission.MANAGE.value]
            tokens = _tokens(own) | _tokens(managers)
        result[item.id] = sorted(tokens)
    return result
