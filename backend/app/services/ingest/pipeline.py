"""Ingestion steps run by workers: parse -> chunk. Every step is idempotent per (doc, version)."""

import asyncio
import hashlib
import json
import logging
import uuid
from posixpath import dirname

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.storage import ObjectStorage
from app.models import Chunk, Document, DocumentStatus
from app.models.base import utcnow
from app.services.ingest.chunker import Chunker
from app.services.ingest.parsers import ParserRegistry
from app.services.ingest.queue import TaskQueue
from app.services.ingest.sections import ParsedDocument
from app.services.outbox_service import DOCUMENT_CHUNKS_READY, OutboxService
from app.services.security.pii import PiiMasker

logger = logging.getLogger(__name__)
CHUNK_ID_NAMESPACE = uuid.UUID("5b0c2f4e-7d38-4f8a-9a8e-0c1d2e3f4a5b")
MAX_ERROR_LENGTH = 2000


def parsed_key(minio_key: str) -> str:
    return f"{dirname(minio_key)}/parsed.json"


def chunk_id(document_id: str, version: int, seq: int) -> str:
    return uuid.uuid5(CHUNK_ID_NAMESPACE, f"{document_id}:{version}:{seq}").hex


class IngestPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        parsers: ParserRegistry,
        chunker: Chunker,
        queue: TaskQueue,
        masker: PiiMasker | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.parsers = parsers
        self.chunker = chunker
        self.queue = queue
        # Sensitive data is masked before chunks are stored, so it never reaches any index.
        self.masker = masker

    def _text(self, content: str) -> str:
        return self.masker.mask(content) if self.masker else content

    @staticmethod
    async def _current(session: AsyncSession, document_id: str, version: int) -> Document | None:
        """The document if this task is still relevant (not deleted, not superseded)."""
        doc = await session.get(Document, document_id)
        if doc is None or doc.deleted_at is not None or doc.version != version:
            logger.info(
                "ingest_task_skipped", extra={"document_id": document_id, "version": version}
            )
            return None
        return doc

    async def parse(self, document_id: str, version: int) -> bool:
        async with self.session_factory() as session:
            doc = await self._current(session, document_id, version)
            if doc is None:
                return False
            doc.status = DocumentStatus.PARSING.value
            doc.error_message = None
            key, filename, mime_type = doc.minio_key, doc.filename, doc.mime_type
            await session.commit()

        data = await self.storage.get_bytes(key)
        parsed = await asyncio.to_thread(self.parsers.parse, data, filename, mime_type)
        await self.storage.put_bytes(
            parsed_key(key),
            json.dumps(parsed.to_dict(), ensure_ascii=False).encode("utf-8"),
            "application/json",
        )

        async with self.session_factory() as session:
            doc = await self._current(session, document_id, version)
            if doc is None:
                return False
            doc.status = DocumentStatus.PARSED.value
            doc.parsed_at = utcnow()
            doc.chunk_count = None
            doc.chunked_at = None
            doc.meta = {**doc.meta, "parse": {"parser": parsed.parser, **parsed.metadata}}
            await session.commit()
        self.queue.enqueue_chunk(document_id, version)
        logger.info("document_parsed", extra={"document_id": document_id, "version": version})
        return True

    async def chunk(self, document_id: str, version: int) -> bool:
        async with self.session_factory() as session:
            doc = await self._current(session, document_id, version)
            if doc is None:
                return False
            key = doc.minio_key

        raw = await self.storage.get_bytes(parsed_key(key))
        parsed = ParsedDocument.from_dict(json.loads(raw))
        drafts = await asyncio.to_thread(self.chunker.chunk, parsed)

        async with self.session_factory() as session:
            doc = await self._current(session, document_id, version)
            if doc is None:
                return False
            # Re-running overwrites this version; older versions' chunks are superseded.
            await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            ids = [chunk_id(document_id, version, d.seq) for d in drafts]
            texts = [self._text(d.content) for d in drafts]
            session.add_all(
                Chunk(
                    id=ids[d.seq],
                    org_id=doc.org_id,
                    kb_id=doc.kb_id,
                    document_id=document_id,
                    document_version=version,
                    parent_id=ids[d.parent_seq] if d.parent_seq is not None else None,
                    level=d.level,
                    seq=d.seq,
                    heading_path=d.heading_path,
                    content=texts[i],
                    token_count=d.token_count,
                    page_start=d.page_start,
                    page_end=d.page_end,
                    sheet_name=d.sheet_name,
                    slide_number=d.slide_number,
                    chunk_type=d.chunk_type,
                    content_hash=_sha256(texts[i]),
                )
                for i, d in enumerate(drafts)
            )
            doc.chunk_count = len(drafts)
            doc.chunked_at = utcnow()
            doc.status = DocumentStatus.PARSED.value
            await OutboxService(session).publish(
                doc.org_id,
                "document",
                document_id,
                DOCUMENT_CHUNKS_READY,
                {
                    "document_id": document_id,
                    "kb_id": doc.kb_id,
                    "version": version,
                    "chunk_count": len(drafts),
                },
            )
            await session.commit()
        logger.info(
            "document_chunked",
            extra={"document_id": document_id, "version": version, "chunks": len(drafts)},
        )
        return True

    async def mark_failed(self, document_id: str, version: int, error: str) -> None:
        async with self.session_factory() as session:
            doc = await self._current(session, document_id, version)
            if doc is None:
                return
            doc.status = DocumentStatus.FAILED.value
            doc.error_message = error[:MAX_ERROR_LENGTH]
            await session.commit()
        logger.warning(
            "document_ingest_failed",
            extra={"document_id": document_id, "version": version, "error": error[:300]},
        )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
