"""Second PG permission check of the final answer context.

Expansion pulls in chunks that were never retrieved (parents, neighbors, KOs), and ACLs
may change while a request runs. Every chunk that reaches the prompt must belong to the
caller's org, be the current version of a live document, and be readable *now*; every
knowledge object must still be live in the cited version and readable now.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.repositories.search_repo import SearchRepository
from app.services.authz import CurrentUser
from app.services.chat.evidence import Evidence
from app.services.knowledge.access import KnowledgeAccess
from app.services.knowledge.ko_access import KoAccess

logger = logging.getLogger(__name__)


@dataclass
class AclCheckResult:
    kept: list[Evidence]
    dropped: list[dict[str, Any]] = field(default_factory=list)


class EvidenceAclChecker:
    def __init__(self, session: AsyncSession, user: CurrentUser) -> None:
        self.repo = SearchRepository(session)
        self.access = KnowledgeAccess(session)
        self.kos = KoAccess(session)
        self.user = user

    async def readable_chunks(self, chunk_ids: list[str]) -> dict[str, str]:
        """chunk_id -> reason for every chunk that must NOT be used (absent = allowed)."""
        ids = list(dict.fromkeys(chunk_ids))
        rows = await self.repo.chunks_with_documents(self.user.org_id, ids)
        denied: dict[str, str] = {cid: "not_found" for cid in ids}
        live = []
        for chunk, doc, kb in rows:
            if doc.deleted_at is not None or kb.deleted_at is not None:
                denied[chunk.id] = "deleted"
            elif chunk.document_version != doc.version:
                denied[chunk.id] = "stale_version"
            else:
                live.append((chunk, doc, kb))
                denied.pop(chunk.id)

        kbs = {kb.id: kb for _, _, kb in live}
        kb_perms = await self.access.kb_permissions(self.user, list(kbs.values()))
        docs_by_kb: dict[str, dict[str, Document]] = defaultdict(dict)
        for _, doc, kb in live:
            docs_by_kb[kb.id][doc.id] = doc
        readable: set[str] = set()
        for kb_id, docs in docs_by_kb.items():
            perms = await self.access.document_permissions(
                self.user, list(docs.values()), kb_perms.get(kb_id)
            )
            readable |= {doc_id for doc_id, perm in perms.items() if perm is not None}
        for chunk, doc, _ in live:
            if doc.id not in readable:
                denied[chunk.id] = "no_access"
        return denied

    async def denied_kos(self, evidences: list[Evidence]) -> dict[str, str]:
        """ko_id -> reason for KO evidences that must NOT be used."""
        wanted = {ev.document.id: ev.document.version for ev in evidences}
        live = (await self.kos.live_objects(self.user, list(wanted))).objects
        denied: dict[str, str] = {}
        for ko_id, version in wanted.items():
            obj = live.get(ko_id)
            if obj is None:
                denied[ko_id] = "ko_unavailable"
            elif obj.snapshot.version != version:
                denied[ko_id] = "stale_version"
        return denied

    async def check(self, evidences: list[Evidence]) -> AclCheckResult:
        ko_evs = [ev for ev in evidences if ev.is_ko]
        denied_kos = await self.denied_kos(ko_evs) if ko_evs else {}
        denied = await self.readable_chunks(
            [cid for ev in evidences if not ev.is_ko for cid in ev.chunk_ids]
        )
        result = AclCheckResult(kept=[])
        for ev in evidences:
            if ev.is_ko:
                reason = denied_kos.get(ev.document.id)
                reasons = {reason} if reason else set()
            else:
                reasons = {denied[cid] for cid in ev.chunk_ids if cid in denied}
            if not reasons:
                result.kept.append(ev)
                continue
            info = {
                "document_id": ev.document.id,
                "chunk_ids": ev.chunk_ids,
                "reasons": sorted(reasons),
            }
            result.dropped.append(info)
            logger.warning(
                "qa_acl_recheck_dropped",
                extra={"user_id": self.user.id, "org_id": self.user.org_id, **info},
            )
        return result
