"""Purge MinIO objects (and optionally PG rows) for soft-deleted documents past retention."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.storage import ObjectStorage
from app.models import Chunk, Document, DocumentPageAsset, DocumentVersion
from app.models.base import utcnow
from app.services.ingest.pipeline import parsed_key


@dataclass
class DocumentPurgeResult:
    documents: int = 0
    objects: int = 0
    rows: int = 0


def _object_keys(
    doc: Document, versions: list[DocumentVersion], assets: list[DocumentPageAsset]
) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: str | None) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    add(doc.minio_key)
    add(parsed_key(doc.minio_key) if doc.minio_key else None)
    for ver in versions:
        add(ver.minio_key)
        add(parsed_key(ver.minio_key) if ver.minio_key else None)
    for asset in assets:
        add(asset.minio_key)
    return keys


class SoftDeletedDocumentPurger:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.settings = settings

    async def run_once(self, now: datetime | None = None) -> DocumentPurgeResult:
        days = self.settings.retention_deleted_document_days
        result = DocumentPurgeResult()
        if days <= 0:
            return result
        cutoff = (now or utcnow()) - timedelta(days=days)
        batch = max(1, min(200, self.settings.retention_batch_size))
        while True:
            async with self.session_factory() as session:
                # minio_key == "" means blobs were already purged (tombstone kept).
                docs = list(
                    (
                        await session.execute(
                            select(Document)
                            .where(
                                Document.deleted_at.is_not(None),
                                Document.deleted_at < cutoff,
                                Document.minio_key != "",
                            )
                            .order_by(Document.deleted_at)
                            .limit(batch)
                        )
                    ).scalars()
                )
                if not docs:
                    return result
                for doc in docs:
                    versions = list(
                        (
                            await session.execute(
                                select(DocumentVersion).where(
                                    DocumentVersion.document_id == doc.id
                                )
                            )
                        ).scalars()
                    )
                    assets = list(
                        (
                            await session.execute(
                                select(DocumentPageAsset).where(
                                    DocumentPageAsset.document_id == doc.id
                                )
                            )
                        ).scalars()
                    )
                    for key in _object_keys(doc, versions, assets):
                        try:
                            await self.storage.delete(key)
                            result.objects += 1
                        except Exception:
                            # Missing object is fine; other errors still count as attempt.
                            pass
                    if self.settings.retention_purge_deleted_document_rows:
                        # Chunks / versions / assets CASCADE when the document row is deleted.
                        await session.delete(doc)
                        result.rows += 1
                    else:
                        # Drop chunk text + page assets; clear keys so the next run skips us.
                        # Keep the document tombstone (and version metadata) for audit.
                        await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
                        for asset in assets:
                            await session.delete(asset)
                        doc.minio_key = ""
                        for ver in versions:
                            ver.minio_key = ""
                    result.documents += 1
                await session.commit()
                if len(docs) < batch:
                    return result
