"""Tag chunk text with terminology entity ids (deterministic; no LLM)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.terminology_repo import TerminologyRepository
from app.services.terminology.expander import (
    AliasEntry,
    build_alias_index,
    match_entity_ids,
)


async def load_alias_index(session: AsyncSession, org_id: str) -> list[tuple[str, AliasEntry]]:
    rows = await TerminologyRepository(session).load_active_alias_map(org_id)
    entries: list[AliasEntry] = []
    for entity, aliases in rows:
        forms = [entity.canonical_name, *[a.alias for a in aliases]]
        entries.append(
            AliasEntry(
                entity_id=entity.id,
                canonical_name=entity.canonical_name,
                forms=tuple(dict.fromkeys(f for f in forms if f.strip())),
            )
        )
    return build_alias_index(entries)


def tag_texts(
    texts: list[str], index: list[tuple[str, AliasEntry]]
) -> list[list[str]]:
    """Map each text to the list of matched entity ids (stable order)."""
    if not index:
        return [[] for _ in texts]
    return [match_entity_ids(text, index) for text in texts]
