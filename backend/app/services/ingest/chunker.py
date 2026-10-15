"""Heading-aware parent/child chunking.

Parents are section-level (~parent_target tokens, never above parent_max unless a single
table row is larger); children (~child_target, <= child_max) are the retrieval units and
carry parent links, heading paths and a sentence-level overlap. Tables are never cut inside
a row: oversized tables are split into row groups that repeat the header.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Literal

from app.core.config import Settings
from app.models.knowledge import ChunkType
from app.services.ingest.sections import Location, ParsedDocument, Section, TableData
from app.services.ingest.tokens import count_tokens

UnitKind = Literal["heading", "text", "table"]
PARENT_LEVEL = 1
CHILD_LEVEL = 2


@dataclass(frozen=True)
class ChunkingConfig:
    parent_target: int = 1500
    parent_max: int = 2000
    child_target: int = 400
    child_max: int = 500
    child_overlap: int = 60

    @classmethod
    def from_settings(cls, settings: Settings) -> "ChunkingConfig":
        return cls(
            parent_target=settings.chunk_parent_target_tokens,
            parent_max=settings.chunk_parent_max_tokens,
            child_target=settings.chunk_child_target_tokens,
            child_max=settings.chunk_child_max_tokens,
            child_overlap=settings.chunk_child_overlap_tokens,
        )


@dataclass(frozen=True)
class Unit:
    kind: UnitKind
    path: tuple[str, ...]
    text: str
    tokens: int
    location: Location = field(default_factory=Location)
    depth: int = 0
    table: TableData | None = None
    rows: tuple[tuple[str, ...], ...] | None = None
    overlap: bool = False


@dataclass
class ChunkDraft:
    level: int
    seq: int
    parent_seq: int | None
    heading_path: list[str]
    content: str
    token_count: int
    chunk_type: str
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None


# ---- unit construction / splitting -------------------------------------------------------


def _text_unit(text: str, path: tuple[str, ...], location: Location) -> Unit:
    return Unit("text", path, text, count_tokens(text), location)


def _table_unit(
    table: TableData,
    path: tuple[str, ...],
    location: Location,
    rows: list[list[str]] | None = None,
) -> Unit:
    markdown = table.to_markdown(rows)
    return Unit(
        "table",
        path,
        markdown,
        count_tokens(markdown),
        location,
        table=table,
        rows=tuple(tuple(r) for r in rows) if rows is not None else None,
    )


def split_table(unit: Unit, limit: int) -> list[Unit]:
    """Row groups of at most `limit` tokens, each repeating the header; rows stay whole."""
    if unit.tokens <= limit or unit.table is None:
        return [unit]
    table = unit.table
    rows = [list(r) for r in unit.rows] if unit.rows is not None else table.rows
    if len(rows) <= 1:
        return [unit]
    base = count_tokens(table.header_markdown()) + count_tokens(table.caption or "")
    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    used = base
    for row in rows:
        row_tokens = count_tokens(table.row_markdown(row))
        if current and used + row_tokens > limit:
            groups.append(current)
            current, used = [], base
        current.append(row)
        used += row_tokens
    if current:
        groups.append(current)
    return [_table_unit(table, unit.path, unit.location, g) for g in groups]


_SENTENCE_END = re.compile(r"(?<=[。！？!?；;\n])|(?<=[.] )")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s.strip()]


def _hard_cut(sentence: str, limit: int) -> list[str]:
    tokens = count_tokens(sentence)
    if tokens <= limit:
        return [sentence]
    step = max(1, int(len(sentence) * limit / tokens))
    return [sentence[i : i + step] for i in range(0, len(sentence), step)]


def split_text(unit: Unit, target: int, limit: int) -> list[Unit]:
    if unit.tokens <= limit:
        return [unit]
    pieces: list[str] = []
    current = ""
    for sentence in (p for s in split_sentences(unit.text) for p in _hard_cut(s, limit)):
        candidate = current + sentence
        if current and count_tokens(candidate) > target:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current.strip():
        pieces.append(current)
    return [_text_unit(p.strip(), unit.path, unit.location) for p in pieces if p.strip()]


def tail_text(text: str, budget: int) -> str:
    """Trailing sentences of `text` totalling about `budget` tokens (overlap seed)."""
    if budget <= 0:
        return ""
    picked: list[str] = []
    used = 0
    for sentence in reversed(split_sentences(text)):
        tokens = count_tokens(sentence)
        if picked and used + tokens > budget:
            break
        if not picked and tokens > budget * 2:
            step = max(1, int(len(sentence) * budget / tokens))
            return sentence[-step:].strip()
        picked.insert(0, sentence)
        used += tokens
    return "".join(picked).strip()


def _common_prefix(paths: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    paths = list(paths)
    if not paths:
        return ()
    prefix = paths[0]
    for path in paths[1:]:
        n = 0
        while n < min(len(prefix), len(path)) and prefix[n] == path[n]:
            n += 1
        prefix = prefix[:n]
    return prefix


def _draft(
    level: int,
    path: Iterable[str],
    content: str,
    chunk_type: ChunkType,
    units: Iterable[Unit],
) -> ChunkDraft:
    units = list(units)
    pages = [u.location.page for u in units if u.location.page is not None]
    return ChunkDraft(
        level=level,
        seq=0,
        parent_seq=None,
        heading_path=list(path),
        content=content,
        token_count=count_tokens(content),
        chunk_type=chunk_type.value,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        sheet_name=next((u.location.sheet for u in units if u.location.sheet), None),
        slide_number=next((u.location.slide for u in units if u.location.slide is not None), None),
    )


# ---- chunker -----------------------------------------------------------------------------


@dataclass
class _Group:
    units: list[Unit]
    path: tuple[str, ...]

    @property
    def tokens(self) -> int:
        return sum(u.tokens for u in self.units)


class Chunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, document: ParsedDocument) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for group in self._groups(document.root, ()):
            if not group.units:
                continue
            parent_seq = len(drafts)
            parent = self._parent_draft(group)
            parent.seq = parent_seq
            drafts.append(parent)
            for child in self._children(group):
                child.seq = len(drafts)
                child.parent_seq = parent_seq
                drafts.append(child)
        return drafts

    # -- parents --

    def _own_units(self, section: Section, path: tuple[str, ...]) -> list[Unit]:
        units: list[Unit] = []
        if section.level > 0 and section.title:
            units.append(
                Unit(
                    "heading",
                    path,
                    section.title,
                    count_tokens(section.title),
                    section.location,
                    depth=section.level,
                )
            )
        for block in section.blocks:
            if block.kind == "table" and block.table is not None:
                units.append(_table_unit(block.table, path, block.location))
            elif block.text.strip():
                units.append(_text_unit(block.text, path, block.location))
        return units

    def _subtree_units(self, section: Section, path: tuple[str, ...]) -> list[Unit]:
        units = self._own_units(section, path)
        for child in section.children:
            units += self._subtree_units(child, self._child_path(path, child))
        return units

    @staticmethod
    def _child_path(path: tuple[str, ...], child: Section) -> tuple[str, ...]:
        return (*path, child.title) if child.title else path

    def _groups(self, section: Section, path: tuple[str, ...]) -> list[_Group]:
        cfg = self.config
        subtree = self._subtree_units(section, path)
        if sum(u.tokens for u in subtree) <= cfg.parent_max:
            return [_Group(subtree, path)]

        own: list[Unit] = []
        for unit in self._own_units(section, path):
            if unit.kind == "table":
                own += split_table(unit, cfg.parent_target)
            elif unit.kind == "text":
                own += split_text(unit, cfg.parent_target, cfg.parent_max)
            else:
                own.append(unit)
        groups = self._pack(own, path)
        for child in section.children:
            groups += self._groups(child, self._child_path(path, child))
        return self._merge(groups)

    def _pack(self, units: list[Unit], path: tuple[str, ...]) -> list[_Group]:
        groups: list[_Group] = []
        current: list[Unit] = []
        used = 0
        for unit in units:
            if current and used + unit.tokens > self.config.parent_target:
                groups.append(_Group(current, path))
                current, used = [], 0
            current.append(unit)
            used += unit.tokens
        if current:
            groups.append(_Group(current, path))
        return groups

    def _merge(self, groups: list[_Group]) -> list[_Group]:
        merged: list[_Group] = []
        for group in groups:
            if merged and merged[-1].tokens + group.tokens <= self.config.parent_target:
                last = merged[-1]
                merged[-1] = _Group(
                    last.units + group.units, _common_prefix([last.path, group.path])
                )
            else:
                merged.append(group)
        return merged

    def _parent_draft(self, group: _Group) -> ChunkDraft:
        parts: list[str] = []
        for unit in group.units:
            if unit.kind == "heading":
                parts.append(f"{'#' * min(max(unit.depth, 1), 6)} {unit.text}")
            else:
                parts.append(unit.text)
        only_tables = all(u.kind == "table" for u in group.units if u.kind != "heading")
        has_body = any(u.kind != "heading" for u in group.units)
        chunk_type = (
            ChunkType.TITLE if not has_body else ChunkType.TABLE if only_tables else ChunkType.TEXT
        )
        return _draft(PARENT_LEVEL, group.path, "\n\n".join(parts), chunk_type, group.units)

    # -- children --

    def _children(self, group: _Group) -> list[ChunkDraft]:
        cfg = self.config
        units: list[Unit] = []
        for unit in group.units:
            if unit.kind == "table":
                units += split_table(unit, cfg.child_max)
            elif unit.kind == "text":
                units += split_text(unit, cfg.child_target, cfg.child_max)
            else:
                units.append(unit)

        children: list[ChunkDraft] = []
        buffer: list[Unit] = []

        def text_tokens() -> int:
            return sum(u.tokens for u in buffer if u.kind == "text")

        def has_content() -> bool:
            return any(u.kind == "text" and not u.overlap for u in buffer)

        def flush() -> None:
            # Headings after the last text belong to what follows, not to this chunk.
            last_text = max((i for i, u in enumerate(buffer) if u.kind == "text"), default=-1)
            body, carry = buffer[: last_text + 1], buffer[last_text + 1 :]
            if any(u.kind == "text" and not u.overlap for u in body):
                children.append(self._child_draft(body))
            buffer[:] = carry

        def boundary(unit: Unit) -> bool:
            last = next((u for u in reversed(buffer) if u.kind == "text"), None)
            return last is not None and (
                last.location.slide != unit.location.slide
                or last.location.sheet != unit.location.sheet
            )

        def drop_overlap() -> None:
            buffer[:] = [u for u in buffer if not u.overlap]

        for unit in units:
            if unit.kind == "table":
                flush()
                children.append(self._child_draft([unit]))
                continue
            if unit.kind == "heading":
                drop_overlap()
                if text_tokens() >= cfg.child_target // 2 or boundary(unit):
                    flush()
                buffer.append(unit)
                continue
            if boundary(unit):
                flush()
            if any(u.overlap for u in buffer) and (
                buffer[-1].path != unit.path or text_tokens() + unit.tokens > cfg.child_max
            ):
                drop_overlap()
            if has_content() and text_tokens() + unit.tokens > cfg.child_max:
                seed = self._overlap_seed(buffer, unit)
                flush()
                if seed:
                    buffer.append(seed)
            buffer.append(unit)
            if text_tokens() >= cfg.child_target:
                seed = self._overlap_seed(buffer, unit)
                flush()
                if seed:
                    buffer.append(seed)
        flush()

        if not children:
            headings = [u for u in group.units if u.kind == "heading"]
            if headings:
                content = "\n".join(u.text for u in headings)
                children.append(_draft(CHILD_LEVEL, group.path, content, ChunkType.TITLE, headings))
        return children

    def _overlap_seed(self, buffer: list[Unit], next_unit: Unit) -> Unit | None:
        last_text = next((u for u in reversed(buffer) if u.kind == "text"), None)
        if last_text is None or last_text.path != next_unit.path:
            return None
        seed = tail_text(last_text.text, self.config.child_overlap)
        if not seed:
            return None
        return replace(last_text, text=seed, tokens=count_tokens(seed), overlap=True)

    def _child_draft(self, units: list[Unit]) -> ChunkDraft:
        body = [u for u in units if u.kind != "heading"]
        if len(body) == 1 and body[0].kind == "table":
            unit = body[0]
            return _draft(CHILD_LEVEL, unit.path, unit.text, ChunkType.TABLE, [unit])
        parts: list[str] = []
        seen_text = False
        for unit in units:
            if unit.kind == "heading":
                # Leading headings are captured by heading_path; later ones mark a section switch.
                if seen_text:
                    parts.append(unit.text)
                continue
            parts.append(unit.text)
            seen_text = True
        return _draft(
            CHILD_LEVEL,
            _common_prefix(u.path for u in body),
            "\n".join(parts),
            ChunkType.TEXT,
            body,
        )
