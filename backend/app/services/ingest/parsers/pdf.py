import io
import re
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.ingest.parsers.base import ParseError, stem
from app.services.ingest.parsers.ocr import OcrEngine
from app.services.ingest.parsers.text import parse_markdown
from app.services.ingest.sections import (
    Location,
    ParsedDocument,
    SectionBuilder,
    TableData,
    table_from_rows,
)

_CJK_END = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]$")
_CJK_START = re.compile(r"^[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")
HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 80
MAX_HEADING_LEVELS = 3


def join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and not out.endswith(" -"):
            out = out[:-1] + line
        elif _CJK_END.search(out) and _CJK_START.search(line):
            out += line
        else:
            out += " " + line
    return out


@dataclass
class _Line:
    text: str
    size: float | None
    top: float
    bottom: float


@dataclass
class _Item:
    top: float
    line: _Line | None = None
    table: TableData | None = None


class BasicPdfParser:
    """pdfplumber text + table extraction; font size drives heading detection.

    Pages without a text layer (scans) are rendered and OCR'd when an engine is available.
    """

    name = "pdfplumber"

    def __init__(
        self,
        ocr_factory: Callable[[], OcrEngine | None] | None = None,
        *,
        ocr_min_page_chars: int = 20,
        ocr_resolution: int = 200,
    ) -> None:
        self._ocr_factory = ocr_factory
        self._ocr: OcrEngine | None = None
        self._ocr_loaded = False
        self.ocr_min_page_chars = ocr_min_page_chars
        self.ocr_resolution = ocr_resolution

    def _ocr_engine(self) -> OcrEngine | None:
        if not self._ocr_loaded:
            self._ocr = self._ocr_factory() if self._ocr_factory else None
            self._ocr_loaded = True
        return self._ocr

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        import pdfplumber

        try:
            pdf = pdfplumber.open(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(f"Cannot open PDF: {type(exc).__name__}: {exc}") from exc

        with pdf:
            title = str((pdf.metadata or {}).get("Title") or "").strip() or stem(filename)
            pages: list[tuple[int, list[_Item]]] = []
            size_weights: Counter[float] = Counter()
            ocr_pages: list[int] = []
            scanned_without_ocr: list[int] = []
            for number, page in enumerate(pdf.pages, start=1):
                items, chars = self._page_items(page)
                for item in items:
                    if item.line and item.line.size:
                        size_weights[item.line.size] += len(item.line.text)
                if chars < self.ocr_min_page_chars and not any(i.table for i in items):
                    engine = self._ocr_engine()
                    if engine is None:
                        scanned_without_ocr.append(number)
                    else:
                        items = self._ocr_items(page, engine)
                        ocr_pages.append(number)
                pages.append((number, items))
            page_count = len(pdf.pages)

        builder = SectionBuilder(title)
        heading_levels = self._heading_levels(size_weights)
        for number, items in pages:
            self._emit(builder, items, heading_levels, Location(page=number))
        document = builder.build(
            self.name,
            {
                "pages": page_count,
                "ocr_pages": ocr_pages,
                "scanned_pages_without_ocr": scanned_without_ocr,
            },
        )
        if not document.iter_blocks() and not document.root.children and scanned_without_ocr:
            raise ParseError("Scanned PDF needs OCR, but no OCR engine is installed")
        return document

    @staticmethod
    def _page_items(page: Any) -> tuple[list[_Item], int]:
        tables = page.find_tables()
        boxes = [t.bbox for t in tables]

        def outside(obj: dict[str, Any]) -> bool:
            if "x0" not in obj or "top" not in obj:
                return True
            cx = (obj["x0"] + obj.get("x1", obj["x0"])) / 2
            cy = (obj["top"] + obj.get("bottom", obj["top"])) / 2
            return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

        text_page = page.filter(outside) if boxes else page
        items: list[_Item] = []
        chars = 0
        for raw in text_page.extract_text_lines(return_chars=True):
            text = (raw.get("text") or "").strip()
            if not text:
                continue
            sizes = [c["size"] for c in raw.get("chars", []) if c.get("size")]
            size = round(statistics.median(sizes), 1) if sizes else None
            chars += len(text)
            items.append(_Item(raw["top"], line=_Line(text, size, raw["top"], raw["bottom"])))
        for table in tables:
            rows = [[c or "" for c in row] for row in table.extract()]
            parsed = table_from_rows(rows)
            if parsed:
                items.append(_Item(table.bbox[1], table=parsed))
        items.sort(key=lambda i: i.top)
        return items, chars

    def _ocr_items(self, page: Any, engine: OcrEngine) -> list[_Item]:
        image = page.to_image(resolution=self.ocr_resolution).original
        return [
            _Item(float(i), line=_Line(text, None, float(i), float(i) + 1))
            for i, text in enumerate(engine.recognize(image))
        ]

    @staticmethod
    def _heading_levels(size_weights: Counter[float]) -> dict[float, int]:
        if not size_weights:
            return {}
        body = size_weights.most_common(1)[0][0]
        larger = sorted((s for s in size_weights if s >= body * HEADING_SIZE_RATIO), reverse=True)
        return {size: min(i + 1, MAX_HEADING_LEVELS) for i, size in enumerate(larger)}

    @staticmethod
    def _emit(
        builder: SectionBuilder,
        items: list[_Item],
        heading_levels: dict[float, int],
        location: Location,
    ) -> None:
        paragraph: list[str] = []
        heading: list[str] = []
        heading_level = 0
        previous: _Line | None = None

        def flush_paragraph() -> None:
            if paragraph:
                builder.text(join_lines(paragraph), location)
                paragraph.clear()

        def flush_heading() -> None:
            nonlocal heading_level
            if heading:
                builder.heading(join_lines(heading), heading_level, location)
                heading.clear()
                heading_level = 0

        for item in items:
            if item.table is not None:
                flush_heading()
                flush_paragraph()
                builder.table(item.table, location)
                previous = None
                continue
            line = item.line
            assert line is not None
            level = heading_levels.get(line.size) if line.size is not None else None
            if level is not None and len(line.text) <= MAX_HEADING_CHARS:
                flush_paragraph()
                if heading and level != heading_level:
                    flush_heading()
                heading.append(line.text)
                heading_level = level
                previous = line
                continue
            flush_heading()
            if previous is not None and paragraph:
                height = max(line.bottom - line.top, 1.0)
                if line.top - previous.bottom > height * 0.8:
                    flush_paragraph()
            paragraph.append(line.text)
            previous = line
        flush_heading()
        flush_paragraph()


class DoclingPdfParser:
    """Docling layout + table-structure models (`docling` extra); OCR for scanned pages."""

    name = "docling"

    def __init__(self, *, ocr_enabled: bool = True) -> None:
        self.ocr_enabled = ocr_enabled
        self._converter: Any = None

    def _get_converter(self) -> Any:
        if self._converter is None:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            options = PdfPipelineOptions()
            options.do_ocr = self.ocr_enabled
            options.do_table_structure = True
            self._converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
        return self._converter

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        from docling.datamodel.base_models import DocumentStream

        try:
            result = self._get_converter().convert(
                DocumentStream(name=filename, stream=io.BytesIO(data))
            )
        except Exception as exc:
            raise ParseError(f"Docling failed: {type(exc).__name__}: {exc}") from exc
        doc = result.document
        builder = SectionBuilder(stem(filename))
        for item, _depth in doc.iterate_items():
            kind = type(item).__name__
            label = str(getattr(item, "label", ""))
            if label.endswith(("page_header", "page_footer")):
                continue
            prov = getattr(item, "prov", None)
            location = Location(page=prov[0].page_no if prov else None)
            if kind == "TitleItem":
                builder.root.title = item.text.strip() or builder.root.title
            elif kind == "SectionHeaderItem":
                builder.heading(item.text, int(getattr(item, "level", 1) or 1), location)
            elif kind == "TableItem":
                try:
                    frame = item.export_to_dataframe(doc)
                except TypeError:
                    frame = item.export_to_dataframe()
                rows = [[str(c) for c in frame.columns], *frame.astype(str).values.tolist()]
                table = table_from_rows(rows)
                if table:
                    builder.table(table, location)
            elif hasattr(item, "text") and kind not in ("PictureItem",):
                builder.text(item.text, location)
        return builder.build(self.name, {"pages": len(getattr(doc, "pages", {}) or {})})


class MinerUPdfParser:
    """Delegates to a MinerU API server (`mineru-api`) and parses its Markdown output."""

    name = "mineru"

    def __init__(self, api_url: str, timeout_seconds: float = 600.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout_seconds

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        resp = httpx.post(
            f"{self.api_url}/file_parse",
            files={"files": (filename, data, "application/pdf")},
            data={"return_md": "true", "lang_list": "ch", "backend": "pipeline"},
            timeout=self.timeout,
        )
        if 400 <= resp.status_code < 500:
            raise ParseError(f"MinerU rejected the file: {resp.status_code} {resp.text[:300]}")
        resp.raise_for_status()
        results = resp.json().get("results") or {}
        if not results:
            raise ParseError("MinerU returned no result")
        markdown = str(next(iter(results.values())).get("md_content") or "")
        builder = SectionBuilder(stem(filename))
        parse_markdown(markdown, builder)
        return builder.build(self.name)
