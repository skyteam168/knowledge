"""Parse and validate [n] citation markers of a generated answer."""

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.chat.evidence import Evidence

# [1] / [1,2] / [1、2] / [1][2] / 【1】; not markdown links "[1](url)".
_MARKER = re.compile(r"[\[【]\s*(\d{1,3}(?:\s*[,，、]\s*\d{1,3})*)\s*[\]】](?!\()")
# Code is left untouched: `inline` and fenced blocks.
_CODE = re.compile(r"```.*?(?:```|$)|`[^`\n]*`", re.DOTALL)
_NUMBER = re.compile(r"\d+")


@dataclass
class CitationResult:
    answer: str
    citations: list[dict[str, Any]]
    # Valid material numbers in order of first use.
    used: list[int] = field(default_factory=list)
    # Numbers that point at no material (removed from the answer).
    invalid: list[int] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return bool(self.used)


def strip_citations(text: str) -> str:
    """Remove every [n] marker (history fed back to the model must not carry stale numbers)."""
    return _replace_outside_code(text, lambda _: "")


def _replace_outside_code(text: str, repl: Any) -> str:
    out: list[str] = []
    pos = 0
    for code in _CODE.finditer(text):
        out.append(_MARKER.sub(repl, text[pos : code.start()]))
        out.append(code.group(0))
        pos = code.end()
    out.append(_MARKER.sub(repl, text[pos:]))
    return "".join(out)


class CitationValidator:
    def __init__(self, quote_max_chars: int = 300) -> None:
        self.quote_max_chars = quote_max_chars

    def validate(self, answer: str, evidences: list[Evidence]) -> CitationResult:
        used: list[int] = []
        invalid: list[int] = []

        def repl(match: re.Match[str]) -> str:
            numbers = [int(n) for n in _NUMBER.findall(match.group(1))]
            valid: list[int] = []
            for n in numbers:
                if 1 <= n <= len(evidences):
                    if n not in valid:
                        valid.append(n)
                    if n not in used:
                        used.append(n)
                elif n not in invalid:
                    invalid.append(n)
            return "".join(f"[{n}]" for n in valid)

        cleaned = _replace_outside_code(answer, repl)
        citations = [self.citation(n, evidences[n - 1]) for n in sorted(used)]
        return CitationResult(answer=cleaned, citations=citations, used=used, invalid=invalid)

    def citation(self, n: int, ev: Evidence) -> dict[str, Any]:
        quote = ev.quote.strip()
        if len(quote) > self.quote_max_chars:
            quote = quote[: self.quote_max_chars].rstrip() + "…"
        doc = ev.document
        return {
            "n": n,
            "document_id": doc.id,
            "chunk_id": ev.anchor_chunk_id,
            "chunk_ids": ev.chunk_ids,
            "hit_chunk_ids": ev.hit_chunk_ids,
            "title": doc.title,
            "filename": doc.filename,
            "kb_id": doc.kb_id,
            "kb_name": doc.kb_name,
            "doc_version": doc.version,
            "heading_path": ev.heading_path,
            "page_start": ev.page_start,
            "page_end": ev.page_end,
            "sheet_name": ev.sheet_name,
            "slide_number": ev.slide_number,
            "quote": quote,
            "score": ev.score,
            "is_ko": ev.is_ko,
            "ko_type": doc.tags[0] if ev.is_ko and doc.tags else None,
        }
