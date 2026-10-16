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
    IMAGE = "image"


EXTENSIONS: dict[str, FileKind] = {
    ".pdf": FileKind.PDF,
    ".docx": FileKind.WORD,
    ".doc": FileKind.WORD,
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
    ".jpg": FileKind.IMAGE,
    ".jpeg": FileKind.IMAGE,
    ".png": FileKind.IMAGE,
}

MIME_TYPES: dict[FileKind, str] = {
    FileKind.PDF: "application/pdf",
    # Canonical WORD MIME is OOXML; legacy .doc still maps to FileKind.WORD by extension.
    FileKind.WORD: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileKind.CSV: "text/csv",
    FileKind.PPT: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    FileKind.TEXT: "text/plain",
    FileKind.MARKDOWN: "text/markdown",
    FileKind.HTML: "text/html",
    FileKind.IMAGE: "image/png",
}

# Extension-specific MIME when the canonical kind MIME is wrong (e.g. .doc / .jpg).
EXTENSION_MIME: dict[str, str] = {
    ".doc": "application/msword",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_MIME_KINDS = {
    **{mime: kind for kind, mime in MIME_TYPES.items()},
    "application/msword": FileKind.WORD,
    "image/jpeg": FileKind.IMAGE,
    "image/jpg": FileKind.IMAGE,
    "image/png": FileKind.IMAGE,
}


def detect_kind(filename: str, mime_type: str | None = None) -> FileKind | None:
    """Extension first (browsers report inconsistent MIME types), MIME as a fallback."""
    kind = EXTENSIONS.get(PurePosixPath(filename.lower()).suffix)
    if kind is None and mime_type:
        kind = _MIME_KINDS.get(mime_type.split(";")[0].strip().lower())
    return kind


def canonical_mime(kind: FileKind, filename: str | None = None) -> str:
    if filename:
        suffix = PurePosixPath(filename.lower()).suffix
        if suffix in EXTENSION_MIME:
            return EXTENSION_MIME[suffix]
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
