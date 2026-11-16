"""Export terminology aliases into OpenSearch Solr-format synonyms.txt."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from app.models import TerminologyAlias, TerminologyEntity

BEGIN_MARKER = "# <<<ekb-terminology>>>"
END_MARKER = "# <<<end-ekb-terminology>>>"

_HEADER = """# Solr synonym format, used by the search-time `ekb_synonym` filter (updateable).
# After editing, call POST /api/v1/admin/index/synonyms/reload or
# `python -m app.cli index reload-synonyms`; no reindex is needed.
# The block between markers is overwritten by
# `python -m app.cli terminology sync-synonyms` / admin terminology sync.
"""


def _clean_token(text: str) -> str | None:
    """Drop empty / comma-bearing tokens (Solr synonym separator)."""
    token = " ".join(text.split()).strip()
    if not token or "," in token:
        return None
    return token


def format_synonym_lines(
    rows: Iterable[tuple[TerminologyEntity, Sequence[TerminologyAlias]]],
) -> list[str]:
    """One Solr line per entity that has at least two distinct forms."""
    lines: list[str] = []
    for entity, aliases in rows:
        forms: list[str] = []
        seen: set[str] = set()
        for raw in (entity.canonical_name, *(a.alias for a in aliases)):
            token = _clean_token(raw)
            if token is None:
                continue
            key = token.casefold()
            if key in seen:
                continue
            seen.add(key)
            forms.append(token)
        if len(forms) < 2:
            continue
        lines.append(", ".join(forms))
    return sorted(lines, key=lambda s: s.casefold())


def merge_synonyms_file(existing: str, managed_lines: Sequence[str]) -> str:
    """Replace or append the managed terminology block; keep manual lines."""
    body = "\n".join(managed_lines)
    block = f"{BEGIN_MARKER}\n{body}\n{END_MARKER}" if body else f"{BEGIN_MARKER}\n{END_MARKER}"

    if BEGIN_MARKER in existing and END_MARKER in existing:
        before, rest = existing.split(BEGIN_MARKER, 1)
        _, after = rest.split(END_MARKER, 1)
        return f"{before.rstrip()}\n\n{block}\n{after.lstrip()}"

    base = existing.strip() or _HEADER.strip()
    return f"{base}\n\n{block}\n"


def write_synonyms_file(path: Path, managed_lines: Sequence[str]) -> int:
    """Merge managed lines into ``path`` and return the number of managed lines."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merge_synonyms_file(existing, managed_lines), encoding="utf-8")
    return len(managed_lines)
