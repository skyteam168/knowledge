from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from app.services.ingest.sections import ParsedDocument


class FileKind(StrEnum):
    PDF = "pdf"
    WORD = "word"
    EXCEL = "excel"
    CSV = "csv"
    PPT = "ppt"
    TEXT = "text"
    MARKDOWN = "markdown"
    HTML = "html"


EXTENSIONS: dict[str, FileKind] = {
    ".pdf": FileKind.PDF,
    ".docx": FileKind.WORD,
    ".xlsx": FileKind.EXCEL,
    ".xlsm": FileKind.EXCEL,
    ".csv": FileKind.CSV,
    ".pptx": FileKind.PPT,
    ".txt": FileKind.TEXT,
    ".log": FileKind.TEXT,
    ".md": FileKind.MARKDOWN,
    ".markdown": FileKind.MARKDOWN,
    ".html": FileKind.HTML,
    ".htm": FileKind.HTML,
}

MIME_TYPES: dict[FileKind, str] = {
    FileKind.PDF: "application/pdf",
    FileKind.WORD: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileKind.CSV: "text/csv",
    FileKind.PPT: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    FileKind.TEXT: "text/plain",
    FileKind.MARKDOWN: "text/markdown",
    FileKind.HTML: "text/html",
}

_MIME_KINDS = {mime: kind for kind, mime in MIME_TYPES.items()}


def detect_kind(filename: str, mime_type: str | None = None) -> FileKind | None:
    """Extension first (browsers report inconsistent MIME types), MIME as a fallback."""
    kind = EXTENSIONS.get(PurePosixPath(filename.lower()).suffix)
    if kind is None and mime_type:
        kind = _MIME_KINDS.get(mime_type.split(";")[0].strip().lower())
    return kind


def canonical_mime(kind: FileKind) -> str:
    return MIME_TYPES[kind]


class ParseError(Exception):
    """Permanent parse failure (corrupt/unsupported input): retrying will not help."""


class DocumentParser(Protocol):
    name: str

    def parse(self, data: bytes, filename: str) -> ParsedDocument:
        """Synchronous and CPU-bound; callers run it in a worker thread."""
        ...


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def stem(filename: str) -> str:
    return PurePosixPath(filename).stem or filename
