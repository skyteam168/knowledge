"""Re-tag existing chunks with terminology entity ids (idempotent)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk
from app.services.terminology.tagger import load_alias_index, tag_texts


async def retag_chunks(
    session: AsyncSession,
    org_id: str,
    *,
    document_id: str | None = None,
    batch_size: int = 200,
) -> dict[str, int]:
    """Rewrite `entity_ids` for all chunks of an org (or one document)."""
    index = await load_alias_index(session, org_id)
    scanned = 0
    updated = 0
    with_entities = 0
    after_id = ""
    while True:
        filters = [Chunk.org_id == org_id]
        if document_id:
            filters.append(Chunk.document_id == document_id)
        if after_id:
            filters.append(Chunk.id > after_id)
        stmt = select(Chunk).where(*filters).order_by(Chunk.id).limit(batch_size)
        rows = list((await session.execute(stmt)).scalars())
        if not rows:
            break
        texts = [c.content for c in rows]
        id_lists = tag_texts(texts, index)
        for chunk, ids in zip(rows, id_lists, strict=True):
            scanned += 1
            before = list(chunk.entity_ids or [])
            if before != ids:
                chunk.entity_ids = ids
                updated += 1
            if ids:
                with_entities += 1
        after_id = rows[-1].id
        if len(rows) < batch_size:
            break
    return {"scanned": scanned, "updated": updated, "with_entities": with_entities}
