"""Deterministic alias expansion for retrieval queries (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AliasEntry:
    entity_id: str
    canonical_name: str
    # All surface forms including canonical (display case preserved).
    forms: tuple[str, ...]


@dataclass
class QueryExpansion:
    """Result of expanding one or more queries with terminology aliases."""

    original: list[str]
    # Queries to actually retrieve (original first, then extras).
    queries: list[str]
    # Extra synonym phrases injected into a single search string (search path).
    extra_terms: list[str] = field(default_factory=list)
    # Human/debug: [{query, matched_alias, entity_id, canonical_name, added}]
    matches: list[dict[str, object]] = field(default_factory=list)

    def describe(self) -> dict[str, object]:
        return {
            "original": self.original,
            "queries": self.queries,
            "extra_terms": self.extra_terms,
            "matches": self.matches,
        }


def normalize_alias(text: str) -> str:
    return " ".join(text.strip().lower().split())


def build_alias_index(entries: list[AliasEntry]) -> list[tuple[str, AliasEntry]]:
    """Longest-first list of (normalized_form, entry) for substring matching."""
    pairs: list[tuple[str, AliasEntry]] = []
    for entry in entries:
        seen: set[str] = set()
        for form in entry.forms:
            key = normalize_alias(form)
            if not key or key in seen:
                continue
            seen.add(key)
            pairs.append((key, entry))
    pairs.sort(key=lambda p: (-len(p[0]), p[0]))
    return pairs


def _find_matches(
    text: str, index: list[tuple[str, AliasEntry]]
) -> list[tuple[str, AliasEntry]]:
    """Return non-overlapping matches (prefer longer aliases)."""
    hay = normalize_alias(text)
    if not hay:
        return []
    occupied = [False] * len(hay)
    found: list[tuple[str, AliasEntry]] = []
    seen_entities: set[str] = set()
    for key, entry in index:
        if entry.entity_id in seen_entities:
            continue
        start = 0
        while True:
            pos = hay.find(key, start)
            if pos < 0:
                break
            end = pos + len(key)
            # Require token-ish boundaries for short ASCII keys (avoid matching inside words).
            if _ok_boundary(hay, pos, end) and not any(occupied[pos:end]):
                for i in range(pos, end):
                    occupied[i] = True
                found.append((key, entry))
                seen_entities.add(entry.entity_id)
                break
            start = pos + 1
    return found


def match_entity_ids(text: str, index: list[tuple[str, AliasEntry]]) -> list[str]:
    """Return distinct terminology entity ids mentioned in `text` (ingest tagging)."""
    return [entry.entity_id for _, entry in _find_matches(text, index)]


def _ok_boundary(hay: str, start: int, end: int) -> bool:
    def is_word(ch: str) -> bool:
        return ch.isalnum() or ch in {"_", "-"}

    # CJK has no spaces; only enforce boundaries when both neighbors are ASCII word chars.
    left = hay[start - 1] if start > 0 else ""
    right = hay[end] if end < len(hay) else ""
    key = hay[start:end]
    if any(ord(c) > 127 for c in key):
        return True
    if left and is_word(left) and is_word(key[0]):
        return False
    return not (right and is_word(right) and is_word(key[-1]))


def expand_queries(
    texts: list[str],
    entries: list[AliasEntry],
    *,
    max_extra: int = 3,
) -> QueryExpansion:
    """Expand queries: keep originals, append up to `max_extra` synonym query strings."""
    index = build_alias_index(entries)
    originals = list(texts)
    extras: list[str] = []
    extra_terms: list[str] = []
    matches: list[dict[str, object]] = []
    already = {normalize_alias(t) for t in originals if t.strip()}

    for text in originals:
        for matched_key, entry in _find_matches(text, index):
            added_for_entity: list[str] = []
            candidates = [entry.canonical_name, *entry.forms]
            for cand in candidates:
                norm = normalize_alias(cand)
                if not norm or norm in already:
                    continue
                if len(extras) >= max_extra:
                    break
                extras.append(cand)
                extra_terms.append(cand)
                already.add(norm)
                added_for_entity.append(cand)
            matches.append(
                {
                    "query": text,
                    "matched_alias": matched_key,
                    "entity_id": entry.entity_id,
                    "canonical_name": entry.canonical_name,
                    "added": added_for_entity,
                }
            )
            if len(extras) >= max_extra:
                break
        if len(extras) >= max_extra:
            break

    return QueryExpansion(
        original=originals,
        queries=[*originals, *extras],
        extra_terms=extra_terms,
        matches=matches,
    )


def merge_search_text(text: str, expansion: QueryExpansion) -> str:
    """Append unused synonym terms to a single search string."""
    if not expansion.extra_terms:
        return text
    parts = [text, *expansion.extra_terms]
    return " ".join(parts)
