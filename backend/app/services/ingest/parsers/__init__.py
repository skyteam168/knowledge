import importlib.util
import threading
from collections.abc import Callable

from app.core.config import Settings
from app.services.ingest.parsers.base import (
    DocumentParser,
    FileKind,
    ParseError,
    canonical_mime,
    detect_kind,
)
from app.services.ingest.parsers.image import ImageParser
from app.services.ingest.parsers.ocr import OcrEngine, load_ocr_engine
from app.services.ingest.parsers.office import (
    CsvParser,
    ExcelParser,
    PowerPointParser,
    WordParser,
)
from app.services.ingest.parsers.pdf import BasicPdfParser, DoclingPdfParser, MinerUPdfParser
from app.services.ingest.parsers.text import HtmlParser, MarkdownParser, PlainTextParser
from app.services.ingest.sections import ParsedDocument

__all__ = [
    "DocumentParser",
    "FileKind",
    "ParseError",
    "ParserRegistry",
    "canonical_mime",
    "detect_kind",
]


class ParserRegistry:
    """Dispatches by file kind; the PDF backend is chosen by `settings.pdf_parser`."""

    def __init__(
        self,
        settings: Settings,
        ocr_factory: Callable[[], OcrEngine | None] = load_ocr_engine,
    ) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        ocr = ocr_factory if settings.ocr_enabled else None
        self._parsers: dict[FileKind, DocumentParser] = {
            FileKind.PDF: self._pdf_parser(ocr),
            FileKind.WORD: WordParser(soffice_path=settings.page_image_soffice_path),
            FileKind.EXCEL: ExcelParser(),
            FileKind.CSV: CsvParser(),
            FileKind.PPT: PowerPointParser(),
            FileKind.TEXT: PlainTextParser(),
            FileKind.MARKDOWN: MarkdownParser(),
            FileKind.HTML: HtmlParser(),
            FileKind.IMAGE: ImageParser(ocr),
        }

    def _pdf_parser(self, ocr: Callable[[], OcrEngine | None] | None) -> DocumentParser:
        backend = self.settings.pdf_parser
        if backend == "auto":
            backend = "docling" if importlib.util.find_spec("docling") else "basic"
        if backend == "docling":
            return DoclingPdfParser(ocr_enabled=self.settings.ocr_enabled)
        if backend == "mineru":
            if not self.settings.mineru_api_url:
                raise ValueError("PDF_PARSER=mineru requires MINERU_API_URL")
            return MinerUPdfParser(
                self.settings.mineru_api_url, self.settings.mineru_timeout_seconds
            )
        return BasicPdfParser(ocr, ocr_min_page_chars=self.settings.ocr_min_page_chars)

    def parser_for(self, kind: FileKind) -> DocumentParser:
        return self._parsers[kind]

    def parse(self, data: bytes, filename: str, mime_type: str | None = None) -> ParsedDocument:
        kind = detect_kind(filename, mime_type)
        if kind is None:
            raise ParseError(f"Unsupported file type: {filename}")
        parser = self._parsers[kind]
        if kind is FileKind.PDF:
            # Model-backed PDF parsers (docling / OCR) are not safe for concurrent use.
            with self._lock:
                document = parser.parse(data, filename)
        else:
            document = parser.parse(data, filename)
        if not document.iter_blocks() and not document.root.children:
            raise ParseError("No text content could be extracted")
        return document
