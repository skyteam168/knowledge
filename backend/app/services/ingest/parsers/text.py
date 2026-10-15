import re

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from app.services.ingest.parsers.base import decode_text, stem
from app.services.ingest.sections import ParsedDocument, SectionBuilder, table_from_rows


class PlainTextParser:
    name = "text"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        builder = SectionBuilder(stem(filename))
        for paragraph in re.split(r"\n\s*\n", decode_text(data).replace("\r\n", "\n")):
            builder.text(paragraph)
        return builder.build(self.name)


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def parse_markdown(text: str, builder: SectionBuilder) -> None:
    lines = text.replace("\r\n", "\n").split("\n")
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            builder.text("\n".join(paragraph))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line.strip()):
            flush()
            fence = line.strip()[:3]
            block = [line]
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
            builder.text("\n".join(block))
        elif m := _HEADING.match(line):
            flush()
            builder.heading(m.group(2), len(m.group(1)))
        elif line.lstrip().lower().startswith("<table"):
            flush()
            block = [line]
            while "</table>" not in block[-1].lower() and i + 1 < len(lines):
                i += 1
                block.append(lines[i])
            soup = BeautifulSoup("\n".join(block), "html.parser")
            html_table = soup.find("table")
            if isinstance(html_table, Tag):
                table = table_from_rows(_html_table(html_table))
                if table:
                    builder.table(table)
        elif "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            rows = [_split_row(line)]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            table = table_from_rows(rows)
            if table:
                builder.table(table)
            continue
        elif not line.strip():
            flush()
        else:
            paragraph.append(line)
        i += 1
    flush()


class MarkdownParser:
    name = "markdown"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        builder = SectionBuilder(stem(filename))
        parse_markdown(decode_text(data), builder)
        return builder.build(self.name)


_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
_TEXT_TAGS = {"p", "li", "pre", "blockquote", "dd", "dt", "figcaption", "caption", "address"}
_SKIP_TAGS = {"script", "style", "noscript", "template", "head", "nav", "footer", "svg"}


def _html_table(tag: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tag.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        rows.append([c.get_text(" ", strip=True) for c in cells])
    return rows


class HtmlParser:
    name = "html"

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        soup = BeautifulSoup(decode_text(data), "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else None
        builder = SectionBuilder(title or stem(filename))
        self._walk(soup.body or soup, builder)
        return builder.build(self.name)

    def _walk(self, node: Tag, builder: SectionBuilder) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:
                    builder.text(str(child))
                continue
            if not isinstance(child, Tag) or child.name in _SKIP_TAGS:
                continue
            if child.name in _HEADING_TAGS:
                builder.heading(child.get_text(" ", strip=True), _HEADING_TAGS[child.name])
            elif child.name == "table":
                caption = child.find("caption")
                table = table_from_rows(
                    _html_table(child), caption.get_text(" ", strip=True) if caption else None
                )
                if table:
                    builder.table(table)
            elif child.name in _TEXT_TAGS:
                prefix = "- " if child.name == "li" else ""
                text = child.get_text("\n" if child.name == "pre" else " ", strip=True)
                builder.text(prefix + text)
            else:
                self._walk(child, builder)
