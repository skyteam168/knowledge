"""Soft-deleted documents: MinIO blob purge after retention window."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.storage import MemoryStorage
from app.models import (
    Chunk,
    Document,
    DocumentPageAsset,
    DocumentVersion,
    KnowledgeBase,
    PageAssetKind,
)
from app.models.base import new_id, utcnow
from app.services.ingest.pipeline import parsed_key
from app.services.maintenance import RetentionService
from app.services.maintenance.document_purge import SoftDeletedDocumentPurger


async def _seed_deleted(
    engine: AsyncEngine, *, age_days: int, with_assets: bool = True
) -> tuple[str, list[str]]:
    org_id = "org-purge"
    keys: list[str] = []
    async with create_session_factory(engine)() as session:
        kb = KnowledgeBase(id=new_id(), org_id=org_id, name="purge-kb", visibility="org")
        session.add(kb)
        await session.flush()
        key = f"docs/{new_id()}.pdf"
        keys.append(key)
        keys.append(parsed_key(key))
        doc = Document(
            id=new_id(),
            org_id=org_id,
            kb_id=kb.id,
            title="gone",
            filename="gone.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
            minio_key=key,
            version=1,
            status="ready",
            acl_inherit=True,
            tags=[],
            meta={},
            deleted_at=utcnow() - timedelta(days=age_days),
            deleted_by="u1",
        )
        session.add(doc)
        await session.flush()
        ver_key = f"docs/{doc.id}/v1.pdf"
        keys.append(ver_key)
        keys.append(parsed_key(ver_key))
        session.add(
            DocumentVersion(
                org_id=org_id,
                document_id=doc.id,
                version=1,
                filename="gone.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                sha256="a" * 64,
                minio_key=ver_key,
            )
        )
        session.add(
            Chunk(
                id=new_id(),
                org_id=org_id,
                kb_id=kb.id,
                document_id=doc.id,
                document_version=1,
                level=2,
                seq=0,
                heading_path=[],
                content="secret text",
                token_count=2,
                chunk_type="text",
                content_hash="b" * 64,
            )
        )
        if with_assets:
            asset_key = f"pages/{doc.id}/v1/page-1.png"
            keys.append(asset_key)
            session.add(
                DocumentPageAsset(
                    org_id=org_id,
                    document_id=doc.id,
                    document_version=1,
                    kind=PageAssetKind.PAGE.value,
                    page_index=1,
                    minio_key=asset_key,
                    mime_type="image/png",
                    width=10,
                    height=10,
                    size_bytes=4,
                    content_hash="c" * 64,
                )
            )
        await session.commit()
        return doc.id, keys


@pytest.mark.asyncio
async def test_purges_objects_and_chunks_keeps_tombstone(engine: AsyncEngine) -> None:
    doc_id, keys = await _seed_deleted(engine, age_days=40)
    storage = MemoryStorage()
    for key in keys:
        await storage.put_bytes(key, b"x", "application/octet-stream")

    settings = Settings(
        retention_deleted_document_days=30,
        retention_purge_deleted_document_rows=False,
        retention_trace_days=0,
        retention_outbox_days=0,
        retention_api_call_log_days=0,
        retention_llm_usage_days=0,
        retention_audit_days=0,
    )
    factory = create_session_factory(engine)
    result = await SoftDeletedDocumentPurger(factory, storage, settings).run_once()
    assert result.documents == 1
    assert result.objects >= 3
    assert result.rows == 0
    for key in keys:
        assert await storage.stat(key) is None

    async with factory() as session:
        doc = await session.get(Document, doc_id)
        assert doc is not None and doc.minio_key == "" and doc.deleted_at is not None
        chunks = int(
            await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
            )
            or 0
        )
        assets = int(
            await session.scalar(
                select(func.count())
                .select_from(DocumentPageAsset)
                .where(DocumentPageAsset.document_id == doc_id)
            )
            or 0
        )
    assert chunks == 0 and assets == 0

    # Idempotent: already purged tombstones are skipped.
    again = await SoftDeletedDocumentPurger(factory, storage, settings).run_once()
    assert again.documents == 0


@pytest.mark.asyncio
async def test_retention_service_wires_document_purge(engine: AsyncEngine) -> None:
    await _seed_deleted(engine, age_days=60, with_assets=False)
    storage = MemoryStorage()
    settings = Settings(
        retention_deleted_document_days=30,
        retention_trace_days=0,
        retention_outbox_days=0,
        retention_api_call_log_days=0,
        retention_llm_usage_days=0,
        retention_audit_days=0,
    )
    result = await RetentionService(
        create_session_factory(engine), settings, storage=storage
    ).run_once()
    assert result.deleted["soft_deleted_documents"] == 1


@pytest.mark.asyncio
async def test_recent_soft_delete_is_kept(engine: AsyncEngine) -> None:
    doc_id, keys = await _seed_deleted(engine, age_days=5)
    storage = MemoryStorage()
    for key in keys:
        await storage.put_bytes(key, b"x", "application/octet-stream")
    settings = Settings(retention_deleted_document_days=30)
    result = await SoftDeletedDocumentPurger(
        create_session_factory(engine), storage, settings
    ).run_once()
    assert result.documents == 0
    assert await storage.stat(keys[0]) is not None
    async with create_session_factory(engine)() as session:
        doc = await session.get(Document, doc_id)
        assert doc is not None and doc.minio_key == keys[0]
