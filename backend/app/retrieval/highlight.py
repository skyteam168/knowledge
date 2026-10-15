"""Query-term extraction and HTML-safe snippet highlighting (same markup as OpenSearch)."""

import html
import re

PRE_TAG = "<em>"
POST_TAG = "</em>"

_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_TOKEN = re.compile(rf"[{_CJK}]+|[0-9A-Za-z][0-9A-Za-z\-_./]*")
_CJK_RUN = re.compile(rf"^[{_CJK}]+$")


def query_terms(text: str) -> list[str]:
    """Lower-cased terms: latin words / codes as-is, CJK runs as bigrams (single char kept)."""
    terms: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if _CJK_RUN.match(token) and len(token) > 2:
            terms.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            terms.append(token)
    return list(dict.fromkeys(terms))


def _spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    lowered = text.lower()
    spans: list[tuple[int, int]] = []
    for term in {t.lower() for t in terms if t}:
        start = lowered.find(term)
        while start != -1:
            spans.append((start, start + len(term)))
            start = lowered.find(term, start + 1)
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _mark(text: str, spans: list[tuple[int, int]], offset: int) -> str:
    out: list[str] = []
    pos = 0
    for s, e in spans:
        s, e = max(s - offset, 0), min(e - offset, len(text))
        if e <= pos or s >= len(text):
            continue
        s = max(s, pos)
        out.append(html.escape(text[pos:s]))
        out.append(PRE_TAG + html.escape(text[s:e]) + POST_TAG)
        pos = e
    out.append(html.escape(text[pos:]))
    return "".join(out)


def mark(text: str, terms: list[str]) -> str:
    """The whole text, HTML-escaped, with every term occurrence wrapped in <em>."""
    return _mark(text, _spans(text, terms), 0)


def highlight(
    text: str, terms: list[str], *, fragment_size: int = 160, max_fragments: int = 2
) -> list[str]:
    """Fragments around matches, HTML-escaped with <em> marks; [] when nothing matches."""
    spans = _spans(text, terms)
    if not spans:
        return []
    fragments: list[str] = []
    covered_until = -1
    for s, _ in spans:
        if s < covered_until:
            continue
        start = max(0, s - fragment_size // 4)
        end = min(len(text), start + fragment_size)
        piece = text[start:end]
        inner = [(a, b) for a, b in spans if a < end and b > start]
        fragment = _mark(piece, inner, start)
        fragments.append(("…" if start > 0 else "") + fragment + ("…" if end < len(text) else ""))
        covered_until = end
        if len(fragments) >= max_fragments:
            break
    return fragments


def snippet(text: str, terms: list[str], *, fragment_size: int = 160) -> str:
    """Best-effort snippet: highlighted fragment, else the escaped beginning of the text."""
    fragments = highlight(text, terms, fragment_size=fragment_size, max_fragments=1)
    if fragments:
        return fragments[0]
    head = text[:fragment_size]
    return html.escape(head) + ("…" if len(text) > fragment_size else "")
