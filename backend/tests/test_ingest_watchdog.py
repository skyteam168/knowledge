"""Stuck parsing/indexing documents are marked failed by the ingest watchdog."""

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import Document, DocumentStatus, KnowledgeBase
from app.models.base import new_id, utcnow
from app.services.ingest.watchdog import IngestWatchdog


@pytest.mark.asyncio
async def test_watchdog_fails_stuck_parsing(engine: AsyncEngine, settings: Settings) -> None:
    org_id = "org-watch"
    async with create_session_factory(engine)() as session:
        kb = KnowledgeBase(id=new_id(), org_id=org_id, name="w", visibility="org")
        session.add(kb)
        await session.flush()
        stuck = Document(
            id=new_id(),
            org_id=org_id,
            kb_id=kb.id,
            title="stuck",
            filename="s.md",
            mime_type="text/markdown",
            size_bytes=1,
            sha256="d" * 64,
            minio_key="k/s",
            version=1,
            status=DocumentStatus.PARSING.value,
            acl_inherit=True,
            tags=[],
            meta={},
        )
        fresh = Document(
            id=new_id(),
            org_id=org_id,
            kb_id=kb.id,
            title="fresh",
            filename="f.md",
            mime_type="text/markdown",
            size_bytes=1,
            sha256="e" * 64,
            minio_key="k/f",
            version=1,
            status=DocumentStatus.PARSING.value,
            acl_inherit=True,
            tags=[],
            meta={},
        )
        session.add_all([stuck, fresh])
        await session.flush()
        stuck.updated_at = utcnow() - timedelta(hours=2)
        fresh.updated_at = utcnow()
        await session.commit()
        stuck_id, fresh_id = stuck.id, fresh.id

    cfg = settings.model_copy(update={"ingest_stuck_timeout_seconds": 600})
    result = await IngestWatchdog(create_session_factory(engine), cfg).run_once()
    assert result.failed == 1

    async with create_session_factory(engine)() as session:
        s = await session.get(Document, stuck_id)
        f = await session.get(Document, fresh_id)
        assert s is not None and s.status == DocumentStatus.FAILED.value
        assert s.error_message and "超时" in s.error_message
        assert f is not None and f.status == DocumentStatus.PARSING.value
