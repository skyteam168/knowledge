"""PG re-check of retrieval candidates (the indexes are only a pre-filter).

A candidate survives only if its chunk belongs to the caller's org, is the current version
of a live document in a live knowledge base, and the caller can read that document *now*
(index payloads may lag behind ACL changes until the outbox catches up).
Knowledge object entries are checked the same way against the KO's published version.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KnowledgeBase
from app.repositories.indexing_repo import INDEXED_CHUNK_LEVEL
from app.repositories.search_repo import SearchRepository
from app.retrieval.pipeline import KO_DOC_TYPE, DocumentInfo, HydrationResult, Passage
from app.services.authz import CurrentUser
from app.services.indexing.indexer import document_type
from app.services.indexing.ko_indexer import KO_CHUNK_TYPE, ko_entry_text
from app.services.knowledge.access import KnowledgeAccess
from app.services.knowledge.ko_access import KoAccess, LiveEntry


class PassageHydrator:
    def __init__(self, session: AsyncSession, user: CurrentUser) -> None:
        self.repo = SearchRepository(session)
        self.access = KnowledgeAccess(session)
        self.kos = KoAccess(session)
        self.user = user

    async def __call__(self, chunk_ids: Sequence[str]) -> HydrationResult:
        ids = list(dict.fromkeys(chunk_ids))
        rows = await self.repo.chunks_with_documents(self.user.org_id, ids)
        dropped: Counter[str] = Counter()

        found = {chunk.id for chunk, _, _ in rows}
        ko_entries, ko_dropped = await self.kos.live_entries(
            self.user, [i for i in ids if i not in found]
        )
        dropped.update(ko_dropped)
        dropped["not_found"] += len(ids) - len(rows) - len(ko_entries) - sum(ko_dropped.values())

        live = []
        for chunk, doc, kb in rows:
            if doc.deleted_at is not None or kb.deleted_at is not None:
                dropped["deleted"] += 1
            elif chunk.document_version != doc.version or chunk.level != INDEXED_CHUNK_LEVEL:
                dropped["stale_version"] += 1
            else:
                live.append((chunk, doc, kb))

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

        passages: dict[str, Passage] = {}
        for chunk, doc, kb in live:
            if doc.id not in readable:
                dropped["no_access"] += 1
                continue
            passages[chunk.id] = Passage(
                chunk_id=chunk.id,
                document=_document_info(doc, kb),
                content=chunk.content,
                heading_path=list(chunk.heading_path or []),
                chunk_type=chunk.chunk_type,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                sheet_name=chunk.sheet_name,
                slide_number=chunk.slide_number,
            )
        for entry_id, live_entry in ko_entries.items():
            passages[entry_id] = ko_passage(live_entry)
        return HydrationResult(passages, {k: v for k, v in dropped.items() if v > 0})


def ko_passage(live: LiveEntry) -> Passage:
    ko, snap, kb = live.live.ko, live.live.snapshot, live.live.kb
    return Passage(
        chunk_id=live.entry.id,
        document=DocumentInfo(
            id=ko.id,
            title=snap.title,
            filename="",
            kb_id=kb.id,
            kb_name=kb.name,
            version=snap.version,
            doc_type=KO_DOC_TYPE,
            tags=[snap.ko_type],
            updated_at=snap.published_at or ko.updated_at,
        ),
        content=ko_entry_text(live.entry.question, snap.answer),
        heading_path=[],
        chunk_type=KO_CHUNK_TYPE,
        is_ko=True,
    )


def _document_info(doc: Document, kb: KnowledgeBase) -> DocumentInfo:
    return DocumentInfo(
        id=doc.id,
        title=doc.title,
        filename=doc.filename,
        kb_id=kb.id,
        kb_name=kb.name,
        version=doc.version,
        doc_type=document_type(doc.filename, doc.mime_type),
        tags=list(doc.tags or []),
        updated_at=doc.updated_at,
    )
