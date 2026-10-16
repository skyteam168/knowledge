"""Query normalization and extraction of explicit filters written inline in the query.

Inline syntax (full-width colons/quotes are accepted; values may be quoted):
  kb:<name> / 知识库:<name>     tag:<t> / 标签:<t>      type:pdf / 类型:word
  after:2026-01-01 / 之后:...   before:2026-06-30 / 之前:...
  date:2026 | date:2026-03 | date:2026-01-01..2026-03-31 / 日期:...
Quoted text ("..." or “...”) and code-like tokens (HR-2024-001, ISO9001) become exact terms.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

MAX_QUERY_LENGTH = 512

DOC_TYPE_ALIASES: dict[str, str] = {
    "pdf": "pdf",
    "word": "word",
    "doc": "word",
    "docx": "word",
    "excel": "excel",
    "xls": "excel",
    "xlsx": "excel",
    "csv": "csv",
    "ppt": "ppt",
    "pptx": "ppt",
    "txt": "text",
    "text": "text",
    "md": "markdown",
    "markdown": "markdown",
    "html": "html",
    "htm": "html",
    "image": "image",
    "img": "image",
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
}
DOC_TYPES = tuple(sorted(set(DOC_TYPE_ALIASES.values())))

_KEYS = {
    "kb": "kb",
    "知识库": "kb",
    "tag": "tag",
    "标签": "tag",
    "type": "type",
    "类型": "type",
    "after": "after",
    "since": "after",
    "之后": "after",
    "before": "before",
    "until": "before",
    "之前": "before",
    "date": "date",
    "日期": "date",
}
_OPERATOR = re.compile(
    r"(?<!\S)(?P<key>" + "|".join(map(re.escape, _KEYS)) + r'):(?P<value>"[^"]*"|\S*)',
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"([^"]+)"')
_CODE = re.compile(r"(?<![\w-])(?=[\w\-./]*\d)[A-Za-z0-9][\w\-./]*[A-Za-z0-9](?![\w-])")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class QueryFilters:
    kb_ids: tuple[str, ...] = ()
    kb_names: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    date_from: datetime | None = None
    date_to: datetime | None = None

    def merge(self, other: "QueryFilters") -> "QueryFilters":
        """Union of list filters, intersection of the date windows."""

        def union(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(dict.fromkeys([*a, *b]))

        starts = [d for d in (self.date_from, other.date_from) if d is not None]
        ends = [d for d in (self.date_to, other.date_to) if d is not None]
        return QueryFilters(
            kb_ids=union(self.kb_ids, other.kb_ids),
            kb_names=union(self.kb_names, other.kb_names),
            tags=union(self.tags, other.tags),
            doc_types=union(self.doc_types, other.doc_types),
            date_from=max(starts) if starts else None,
            date_to=min(ends) if ends else None,
        )


@dataclass(frozen=True)
class ParsedQuery:
    raw: str
    # Normalized free text with inline operators removed (what the engines search for).
    text: str
    exact_terms: tuple[str, ...] = ()
    filters: QueryFilters = field(default_factory=QueryFilters)
    # Operators that could not be understood (reported back, never silently applied).
    ignored: tuple[str, ...] = ()


class QueryParseError(ValueError):
    pass


def normalize(text: str) -> str:
    # NFKC folds full-width forms (ＡＢＣ１２３：) into ASCII; Chinese quotes become ASCII.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("“", '"').replace("”", '"').replace("「", '"').replace("」", '"')
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    return _WHITESPACE.sub(" ", text).strip()[:MAX_QUERY_LENGTH]


def _parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


def _date_window(value: str) -> tuple[datetime | None, datetime | None]:
    """'2026' | '2026-03' | '2026-03-01' | 'a..b' -> [start, end) as UTC datetimes."""
    if ".." in value:
        first, _, last = value.partition("..")
        lo = _date_window(first)[0] if first else None
        hi = _date_window(last)[1] if last else None
        if lo is None and hi is None:
            raise QueryParseError(value)
        return lo, hi
    if re.fullmatch(r"\d{4}", value):
        year = int(value)
        return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)
    if re.fullmatch(r"\d{4}-\d{1,2}", value):
        year, month = map(int, value.split("-"))
        month_start = datetime(year, month, 1, tzinfo=UTC)
        month_end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
        return month_start, month_end
    day = _parse_day(value)
    return day, day + timedelta(days=1)


class QueryPreprocessor:
    def parse(self, raw: str, explicit: QueryFilters | None = None) -> ParsedQuery:
        text = normalize(raw)
        kb_names: list[str] = []
        tags: list[str] = []
        doc_types: list[str] = []
        date_from: datetime | None = None
        date_to: datetime | None = None
        ignored: list[str] = []

        for match in _OPERATOR.finditer(text):
            key = _KEYS[match["key"].lower()]
            value = match["value"].strip('"').strip()
            if not value:
                ignored.append(match.group(0))
                continue
            try:
                if key == "kb":
                    kb_names.append(value)
                elif key == "tag":
                    tags.append(value)
                elif key == "type":
                    doc_type = DOC_TYPE_ALIASES.get(value.lower().lstrip("."))
                    if doc_type is None:
                        raise QueryParseError(value)
                    doc_types.append(doc_type)
                elif key == "after":
                    date_from = _date_window(value)[0]
                elif key == "before":
                    date_to = _date_window(value)[1]
                else:
                    date_from, date_to = _date_window(value)
            except (ValueError, QueryParseError):
                ignored.append(match.group(0))
        remaining = _WHITESPACE.sub(" ", _OPERATOR.sub(" ", text)).strip()

        exact = [q.strip() for q in _QUOTED.findall(remaining) if q.strip()]
        free = _WHITESPACE.sub(" ", remaining.replace('"', " ")).strip()
        exact += [c for c in _CODE.findall(free) if len(c) >= 3]

        inline = QueryFilters(
            kb_names=tuple(dict.fromkeys(kb_names)),
            tags=tuple(dict.fromkeys(tags)),
            doc_types=tuple(dict.fromkeys(doc_types)),
            date_from=date_from,
            date_to=date_to,
        )
        filters = (explicit or QueryFilters()).merge(inline)
        if filters.doc_types:
            filters = replace(
                filters,
                doc_types=tuple(
                    dict.fromkeys(
                        DOC_TYPE_ALIASES.get(t.lower(), t.lower()) for t in filters.doc_types
                    )
                ),
            )
        return ParsedQuery(
            raw=raw,
            text=free,
            exact_terms=tuple(dict.fromkeys(exact)),
            filters=filters,
            ignored=tuple(ignored),
        )
