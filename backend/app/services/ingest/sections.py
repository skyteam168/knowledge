"""Parser-neutral intermediate structure: a tree of sections holding text and table blocks."""

from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["text", "table"]


@dataclass
class Location:
    page: int | None = None
    sheet: str | None = None
    slide: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in (("page", self.page), ("sheet", self.sheet), ("slide", self.slide))
            if v is not None
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Location":
        data = data or {}
        return cls(page=data.get("page"), sheet=data.get("sheet"), slide=data.get("slide"))


def _cell(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


@dataclass
class TableData:
    header: list[str]
    rows: list[list[str]]
    caption: str | None = None

    @property
    def width(self) -> int:
        return max([len(self.header), *(len(r) for r in self.rows)], default=0)

    def header_markdown(self) -> str:
        width = self.width
        header = [*self.header, *[""] * (width - len(self.header))]
        return "\n".join(
            [
                "| " + " | ".join(_cell(c) for c in header) + " |",
                "| " + " | ".join("---" for _ in range(width)) + " |",
            ]
        )

    def row_markdown(self, row: list[str]) -> str:
        cells = [*row, *[""] * (self.width - len(row))]
        return "| " + " | ".join(_cell(c) for c in cells) + " |"

    def to_markdown(self, rows: list[list[str]] | None = None) -> str:
        body = [self.row_markdown(r) for r in (self.rows if rows is None else rows)]
        parts = [self.header_markdown(), *body]
        if self.caption:
            parts.insert(0, self.caption)
        return "\n".join(parts)


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    table: TableData | None = None
    location: Location = field(default_factory=Location)

    @property
    def content(self) -> str:
        if self.kind == "table" and self.table is not None:
            return self.table.to_markdown()
        return self.text

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "location": self.location.to_dict()}
        if self.kind == "table" and self.table is not None:
            data["table"] = {
                "header": self.table.header,
                "rows": self.table.rows,
                "caption": self.table.caption,
            }
        else:
            data["text"] = self.text
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        table = data.get("table")
        return cls(
            kind=data["kind"],
            text=data.get("text", ""),
            table=TableData(table["header"], table["rows"], table.get("caption"))
            if table
            else None,
            location=Location.from_dict(data.get("location")),
        )


@dataclass
class Section:
    title: str | None
    level: int
    blocks: list[Block] = field(default_factory=list)
    children: list["Section"] = field(default_factory=list)
    location: Location = field(default_factory=Location)

    def is_empty(self) -> bool:
        return not self.title and not self.blocks and all(c.is_empty() for c in self.children)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "level": self.level,
            "location": self.location.to_dict(),
            "blocks": [b.to_dict() for b in self.blocks],
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Section":
        return cls(
            title=data.get("title"),
            level=data["level"],
            location=Location.from_dict(data.get("location")),
            blocks=[Block.from_dict(b) for b in data.get("blocks", [])],
            children=[cls.from_dict(c) for c in data.get("children", [])],
        )


@dataclass
class ParsedDocument:
    root: Section
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"parser": self.parser, "metadata": self.metadata, "root": self.root.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParsedDocument":
        return cls(
            root=Section.from_dict(data["root"]),
            parser=data["parser"],
            metadata=data.get("metadata", {}),
        )

    def iter_blocks(self) -> list[Block]:
        out: list[Block] = []

        def walk(section: Section) -> None:
            out.extend(section.blocks)
            for child in section.children:
                walk(child)

        walk(self.root)
        return out


class SectionBuilder:
    """Builds a section tree from a linear stream of headings and blocks."""

    def __init__(self, title: str | None = None) -> None:
        self.root = Section(title=title, level=0)
        self._stack: list[Section] = [self.root]

    @property
    def current(self) -> Section:
        return self._stack[-1]

    def heading(self, title: str, level: int, location: Location | None = None) -> None:
        title = " ".join(title.split())
        if not title:
            return
        level = max(1, level)
        while len(self._stack) > 1 and self._stack[-1].level >= level:
            self._stack.pop()
        section = Section(title=title, level=level, location=location or Location())
        self.current.children.append(section)
        self._stack.append(section)

    def text(self, text: str, location: Location | None = None) -> None:
        text = text.strip()
        if text:
            self.current.blocks.append(Block("text", text=text, location=location or Location()))

    def table(self, table: TableData, location: Location | None = None) -> None:
        if table.header or table.rows:
            self.current.blocks.append(Block("table", table=table, location=location or Location()))

    def build(self, parser: str, metadata: dict[str, Any] | None = None) -> ParsedDocument:
        return ParsedDocument(root=self.root, parser=parser, metadata=metadata or {})


def table_from_rows(rows: list[list[str]], caption: str | None = None) -> TableData | None:
    """First non-empty row becomes the header; fully empty rows/columns are dropped."""
    cleaned = [[(c or "").strip() for c in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return None
    width = max(len(r) for r in cleaned)
    padded = [[*r, *[""] * (width - len(r))] for r in cleaned]
    keep = [i for i in range(width) if any(row[i] for row in padded)]
    padded = [[row[i] for i in keep] for row in padded]
    return TableData(header=padded[0], rows=padded[1:], caption=caption)
