"""Text of a parsed document version and a line diff between two versions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from app.services.ingest.sections import ParsedDocument, Section

MAX_LINES = 10_000
MAX_DIFF_LINES = 3_000
CONTEXT_LINES = 3

DiffOp = Literal["equal", "add", "del"]


@dataclass(frozen=True)
class DiffLine:
    op: DiffOp
    text: str
    old_no: int | None
    new_no: int | None


@dataclass
class DiffResult:
    hunks: list[list[DiffLine]] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    truncated: bool = False


def document_lines(
    parsed: ParsedDocument, mask: Callable[[str], str] | None = None
) -> tuple[list[str], bool]:
    """Headings as markdown, blocks line by line (tables as markdown rows); blank lines dropped."""
    lines: list[str] = []
    clean = mask or (lambda s: s)

    def walk(section: Section) -> None:
        if section.title and section.level > 0:
            lines.append(f"{'#' * section.level} {clean(section.title)}")
        for block in section.blocks:
            lines.extend(
                line.rstrip() for line in clean(block.content).splitlines() if line.strip()
            )
        for child in section.children:
            walk(child)

    walk(parsed.root)
    return lines[:MAX_LINES], len(lines) > MAX_LINES


def diff_lines(
    old: list[str], new: list[str], *, context: int = CONTEXT_LINES, limit: int = MAX_DIFF_LINES
) -> DiffResult:
    result = DiffResult()
    emitted = 0
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        hunk: list[DiffLine] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                hunk.extend(
                    DiffLine("equal", old[i], i + 1, j1 + i - i1 + 1) for i in range(i1, i2)
                )
                continue
            if tag in {"replace", "delete"}:
                hunk.extend(DiffLine("del", old[i], i + 1, None) for i in range(i1, i2))
                result.removed += i2 - i1
            if tag in {"replace", "insert"}:
                hunk.extend(DiffLine("add", new[j], None, j + 1) for j in range(j1, j2))
                result.added += j2 - j1
        if all(line.op == "equal" for line in hunk):
            continue
        if emitted + len(hunk) > limit:
            result.truncated = True
            continue
        result.hunks.append(hunk)
        emitted += len(hunk)
    return result
