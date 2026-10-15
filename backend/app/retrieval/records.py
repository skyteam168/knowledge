import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ChunkRecord:
    """A chunk as written to the derived indexes (built from PG; never the other way round)."""

    chunk_id: str
    org_id: str
    kb_id: str
    document_id: str
    doc_version: int
    parent_id: str | None
    heading_path: list[str]
    chunk_type: str
    tags: list[str]
    created_at: datetime
    acl_read_principals: list[str]
    is_ko: bool
    title: str
    content: str
    page_start: int | None = None
    page_end: int | None = None
    # FileKind of the source document ("pdf", "word", ...).
    doc_type: str = ""

    def qdrant_payload(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "org_id": self.org_id,
            "kb_id": self.kb_id,
            "document_id": self.document_id,
            "doc_version": self.doc_version,
            "parent_id": self.parent_id,
            "heading_path": self.heading_path,
            "chunk_type": self.chunk_type,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "acl_read_principals": self.acl_read_principals,
            "is_ko": self.is_ko,
            "doc_type": self.doc_type,
        }

    def opensearch_doc(self) -> dict[str, Any]:
        return {
            **self.qdrant_payload(),
            "heading_path": " / ".join(self.heading_path),
            "title": self.title,
            "content": self.content,
            "page_start": self.page_start,
            "page_end": self.page_end,
        }

    def embedding_text(self) -> str:
        heading = " / ".join(self.heading_path)
        text = f"{heading}\n{self.content}" if heading else self.content
        return text.strip() or self.title or " "


@dataclass(frozen=True)
class IndexedRef:
    """What the consistency check needs to know about one indexed chunk."""

    document_id: str
    doc_version: int


def point_id(chunk_id: str) -> str:
    """Qdrant point ids must be UUIDs; chunk ids are UUID hex strings."""
    return str(uuid.UUID(hex=chunk_id))


def chunk_id_from_point(pid: str | int) -> str:
    return uuid.UUID(str(pid)).hex
