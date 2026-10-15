"""Published knowledge objects related to the retrieved documents (expansion source)."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KoEntry
from app.repositories.curation_repo import KnowledgeObjectRepository
from app.services.authz import CurrentUser
from app.services.chat.evidence import Evidence, EvidenceKind, Hit
from app.services.indexing.ko_indexer import ko_entry_id
from app.services.knowledge.ko_access import KoAccess, LiveEntry, LiveKo
from app.services.search.hydrator import ko_passage


class PublishedKnowledgeObjects:
    def __init__(self, session: AsyncSession, user: CurrentUser, limit: int) -> None:
        self.repo = KnowledgeObjectRepository(session)
        self.access = KoAccess(session)
        self.user = user
        self.limit = max(0, limit)

    async def related(self, hits: Sequence[Hit], exclude: set[str]) -> list[Evidence]:
        if self.limit == 0 or not hits:
            return []
        doc_rank: dict[str, int] = {}
        for hit in hits:
            doc_rank.setdefault(hit.passage.document.id, hit.rank)
        citing = await self.repo.published_citing(self.user.org_id, list(doc_rank), sorted(exclude))
        best: dict[str, int] = {}
        for document_id, ko_id in citing:
            rank = doc_rank[document_id]
            if ko_id not in best or rank < best[ko_id]:
                best[ko_id] = rank
        ordered = sorted(best, key=lambda k: (best[k], k))
        live = (await self.access.live_objects(self.user, ordered)).objects
        selected = [k for k in ordered if k in live][: self.limit]
        return [self._evidence(live[k], best[k]) for k in selected]

    @staticmethod
    def _evidence(obj: LiveKo, rank: int) -> Evidence:
        ko, snap = obj.ko, obj.snapshot
        entry = KoEntry(
            id=ko_entry_id(ko.id, snap.version, 0),
            org_id=ko.org_id,
            ko_id=ko.id,
            ko_version=snap.version,
            seq=0,
            question=snap.question,
        )
        p = ko_passage(LiveEntry(entry, obj))
        return Evidence(
            kind=EvidenceKind.KO,
            document=p.document,
            chunk_ids=[p.chunk_id],
            hit_chunk_ids=[],
            content=p.content,
            heading_path=[],
            score=None,
            best_rank=rank,
            quote=p.content,
            is_ko=True,
        )
