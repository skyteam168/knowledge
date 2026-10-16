import hashlib
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.storage import MemoryStorage
from app.models import Chunk, OutboxEvent
from app.services.ingest.chunker import Chunker
from app.services.ingest.parsers import ParseError, ParserRegistry
from app.services.ingest.pipeline import IngestPipeline
from app.services.ingest.queue import RecordingTaskQueue
from tests.conftest import auth
from tests.samples import make_docx, make_markdown, make_xlsx

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
OTHER_ORG = auth("other-org-token")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def pipeline(
    settings: Settings, engine: AsyncEngine, storage: MemoryStorage, task_queue: RecordingTaskQueue
) -> IngestPipeline:
    return IngestPipeline(
        session_factory=create_session_factory(engine),
        storage=storage,
        parsers=ParserRegistry(settings.model_copy(update={"pdf_parser": "basic"})),
        chunker=Chunker(),
        queue=task_queue,
        settings=settings,
    )


async def outbox(engine: AsyncEngine, event_type: str) -> list[OutboxEvent]:
    async with create_session_factory(engine)() as session:
        stmt = select(OutboxEvent).where(OutboxEvent.event_type == event_type)
        return list((await session.execute(stmt)).scalars())


async def login_all(api: httpx.AsyncClient) -> None:
    for headers in (ALICE, BOB, CAROL):
        assert (await api.get("/api/v1/auth/me", headers=headers)).status_code == 200


async def create_kb(
    api: httpx.AsyncClient, name: str, headers: dict[str, str] = BOB, visibility: str = "restricted"
) -> dict[str, Any]:
    resp = await api.post(
        "/api/v1/knowledge-bases",
        json={"name": name, "description": "desc", "visibility": visibility},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def upload(
    api: httpx.AsyncClient,
    kb_id: str,
    filename: str,
    content: bytes,
    headers: dict[str, str] = BOB,
    mime: str = "application/octet-stream",
) -> httpx.Response:
    return await api.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, mime)},
        headers=headers,
    )


async def group_id(api: httpx.AsyncClient, name: str) -> str:
    resp = await api.get(
        "/api/v1/directory/principals", params={"type": "group", "keyword": name}, headers=BOB
    )
    assert resp.status_code == 200
    return str(next(p["id"] for p in resp.json() if p["name"] == name))


async def test_restricted_kb_is_invisible_without_acl(
    api: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await login_all(api)
    kb = await create_kb(api, "研发库")
    assert kb["my_permission"] == "manage" and kb["visibility"] == "restricted"

    carol_list = (await api.get("/api/v1/knowledge-bases", headers=CAROL)).json()
    assert carol_list["total"] == 0
    assert (await api.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=CAROL)).status_code == 404
    docs = await api.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=CAROL)
    assert docs.status_code == 404
    other = await api.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=OTHER_ORG)
    assert other.status_code == 404
    admin = (await api.get("/api/v1/knowledge-bases", headers=ALICE)).json()
    assert admin["items"][0]["my_permission"] == "manage"

    sales = await group_id(api, "sales")
    me = (await api.get("/api/v1/auth/me", headers=BOB)).json()
    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}/acl",
        json={
            "visibility": "restricted",
            "entries": [
                {"principal_type": "user", "principal_id": me["id"], "permission": "manage"},
                {"principal_type": "group", "principal_id": sales, "permission": "read"},
            ],
        },
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    names = {e["principal_name"] for e in resp.json()["entries"]}
    assert "sales" in names

    carol_list = (await api.get("/api/v1/knowledge-bases", headers=CAROL)).json()
    assert carol_list["total"] == 1 and carol_list["items"][0]["my_permission"] == "read"
    # Read-only: carol cannot change the KB or its ACL.
    assert (
        await api.put(f"/api/v1/knowledge-bases/{kb['id']}", json={"name": "x"}, headers=CAROL)
    ).status_code == 403

    events = await outbox(engine, "acl.changed")
    assert [e.payload["resource_id"] for e in events] == [kb["id"]]


async def test_acl_validation(api: httpx.AsyncClient) -> None:
    await login_all(api)
    kb = await create_kb(api, "校验库")
    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}/acl",
        json={
            "visibility": "org",
            "entries": [{"principal_type": "group", "principal_id": "nope", "permission": "read"}],
        },
        headers=BOB,
    )
    assert resp.status_code == 422
    # Removing every manager would lock the KB.
    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}/acl",
        json={"visibility": "org", "entries": []},
        headers=BOB,
    )
    assert resp.status_code == 409


async def test_upload_dedup_version_and_pipeline(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    storage: MemoryStorage,
    task_queue: RecordingTaskQueue,
    pipeline: IngestPipeline,
) -> None:
    await login_all(api)
    kb = await create_kb(api, "制度库")
    content = make_docx(80)
    resp = await upload(api, kb["id"], "handbook.docx", content)
    assert resp.status_code == 200, resp.text
    first = resp.json()
    doc = first["document"]
    assert first["duplicate"] is False and first["new_version"] is False
    assert doc["status"] == "uploaded" and doc["version"] == 1 and doc["title"] == "handbook"
    assert doc["mime_type"] == DOCX_MIME
    assert doc["sha256"] == hashlib.sha256(content).hexdigest()
    assert task_queue.calls == [("parse", doc["id"], 1)]
    assert any(k.endswith(f"/{doc['id']}/v1/handbook.docx") for k in storage.objects)
    assert not any(k.startswith("staging/") for k in storage.objects)

    # Same bytes (any filename) -> deduplicated.
    dup = (await upload(api, kb["id"], "copy.docx", content)).json()
    assert dup["duplicate"] is True and dup["document"]["id"] == doc["id"]
    assert len(task_queue.calls) == 1

    # parse -> chunk
    assert await pipeline.parse(doc["id"], 1) is True
    assert task_queue.calls[-1] == ("chunk", doc["id"], 1)
    assert await pipeline.chunk(doc["id"], 1) is True
    detail = (await api.get(f"/api/v1/documents/{doc['id']}", headers=CAROL)).status_code
    assert detail == 404
    detail = (await api.get(f"/api/v1/documents/{doc['id']}", headers=BOB)).json()
    assert detail["status"] == "parsed" and detail["chunk_count"] > 0
    assert detail["metadata"]["parse"]["parser"] == "docx"
    chunks = (await api.get(f"/api/v1/documents/{doc['id']}/chunks", headers=BOB)).json()
    assert len(chunks) == detail["chunk_count"]
    parent_ids = {c["id"] for c in chunks if c["level"] == 1}
    kids = [c for c in chunks if c["level"] == 2]
    assert kids and all(c["parent_id"] in parent_ids for c in kids)
    assert any(c["chunk_type"] == "table" for c in kids)
    ready = await outbox(engine, "document.chunks_ready")
    assert len(ready) == 1 and ready[0].payload["chunk_count"] == len(chunks)

    # Idempotent re-run: same deterministic ids, no duplicates.
    assert await pipeline.chunk(doc["id"], 1) is True
    again = (await api.get(f"/api/v1/documents/{doc['id']}/chunks", headers=BOB)).json()
    assert [c["id"] for c in again] == [c["id"] for c in chunks]

    # Same filename, new content -> new version.
    resp = (await upload(api, kb["id"], "handbook.docx", make_docx(20))).json()
    assert resp["new_version"] is True and resp["document"]["id"] == doc["id"]
    assert resp["document"]["version"] == 2 and resp["document"]["chunk_count"] is None
    assert task_queue.calls[-1] == ("parse", doc["id"], 2)
    detail = (await api.get(f"/api/v1/documents/{doc['id']}", headers=BOB)).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    # Tasks for a superseded version are skipped.
    assert await pipeline.parse(doc["id"], 1) is False
    assert await pipeline.parse(doc["id"], 2) is True
    assert await pipeline.chunk(doc["id"], 2) is True
    async with create_session_factory(engine)() as session:
        versions = (
            await session.execute(
                select(Chunk.document_version).where(Chunk.document_id == doc["id"]).distinct()
            )
        ).scalars()
        assert list(versions) == [2]

    preview = (await api.get(f"/api/v1/documents/{doc['id']}/preview-url", headers=BOB)).json()
    assert preview["filename"] == "handbook.docx" and "/v2/handbook.docx" in preview["url"]


async def test_presigned_upload_flow(api: httpx.AsyncClient, storage: MemoryStorage) -> None:
    await login_all(api)
    kb = await create_kb(api, "直传库")
    content = make_markdown()
    sha = hashlib.sha256(content).hexdigest()
    init = await api.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/upload-url",
        json={"filename": "deploy.md", "size_bytes": len(content), "sha256": sha},
        headers=BOB,
    )
    assert init.status_code == 200, init.text
    body = init.json()
    assert body["duplicate"] is False and body["upload_url"]
    staging = body["upload_url"].split("?")[0].split("/", 3)[3]
    complete_url = f"/api/v1/knowledge-bases/{kb['id']}/documents/complete"

    # Not uploaded yet.
    resp = await api.post(complete_url, json={"ticket": body["ticket"]}, headers=BOB)
    assert resp.status_code == 422

    await storage.put_bytes(staging, content, "text/markdown")
    # Another user cannot complete someone else's ticket.
    resp = await api.post(complete_url, json={"ticket": body["ticket"]}, headers=ALICE)
    assert resp.status_code == 404
    resp = await api.post(
        complete_url, json={"ticket": body["ticket"], "tags": ["运维"]}, headers=BOB
    )
    assert resp.status_code == 200, resp.text
    doc = resp.json()["document"]
    assert doc["filename"] == "deploy.md" and doc["tags"] == ["运维"]

    again = await api.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/upload-url",
        json={"filename": "other.md", "size_bytes": len(content), "sha256": sha},
        headers=BOB,
    )
    assert again.json()["duplicate"] is True and again.json()["document"]["id"] == doc["id"]


async def test_presigned_upload_rejects_tampered_content(
    api: httpx.AsyncClient, storage: MemoryStorage
) -> None:
    await login_all(api)
    kb = await create_kb(api, "校验和库")
    content = make_markdown()
    init = (
        await api.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents/upload-url",
            json={
                "filename": "a.md",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(b"something else").hexdigest(),
            },
            headers=BOB,
        )
    ).json()
    staging = init["upload_url"].split("?")[0].split("/", 3)[3]
    await storage.put_bytes(staging, content, "text/markdown")
    resp = await api.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/complete",
        json={"ticket": init["ticket"]},
        headers=BOB,
    )
    assert resp.status_code == 422
    assert staging not in storage.objects


async def test_upload_validation(api: httpx.AsyncClient) -> None:
    await login_all(api)
    kb = await create_kb(api, "类型库")
    assert (await upload(api, kb["id"], "tool.exe", b"MZ")).status_code == 415
    assert (await upload(api, kb["id"], "empty.txt", b"")).status_code == 422
    # Viewer role has no doc:upload.
    assert (await upload(api, kb["id"], "a.txt", b"hi", headers=CAROL)).status_code == 403


async def test_document_acl_override(api: httpx.AsyncClient, engine: AsyncEngine) -> None:
    await login_all(api)
    kb = await create_kb(api, "公开库", visibility="org")
    public = (await upload(api, kb["id"], "public.md", make_markdown())).json()["document"]
    secret = (await upload(api, kb["id"], "secret.xlsx", make_xlsx(5))).json()["document"]

    listing = (await api.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=CAROL)).json()
    assert listing["total"] == 2

    resp = await api.put(
        f"/api/v1/documents/{secret['id']}/acl", json={"inherit": False, "entries": []}, headers=BOB
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["inherit"] is False

    listing = (await api.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=CAROL)).json()
    assert [d["id"] for d in listing["items"]] == [public["id"]]
    assert (await api.get(f"/api/v1/documents/{secret['id']}", headers=CAROL)).status_code == 404
    chunks = await api.get(f"/api/v1/documents/{secret['id']}/chunks", headers=CAROL)
    assert chunks.status_code == 404
    # The KB manager keeps access.
    bob_view = await api.get(f"/api/v1/documents/{secret['id']}", headers=BOB)
    assert bob_view.status_code == 200

    sales = await group_id(api, "sales")
    await api.put(
        f"/api/v1/documents/{secret['id']}/acl",
        json={
            "inherit": False,
            "entries": [{"principal_type": "group", "principal_id": sales, "permission": "read"}],
        },
        headers=BOB,
    )
    carol_view = (await api.get(f"/api/v1/documents/{secret['id']}", headers=CAROL)).json()
    assert carol_view["my_permission"] == "read"
    assert (
        await api.get(f"/api/v1/documents/{secret['id']}/acl", headers=CAROL)
    ).status_code == 403

    events = await outbox(engine, "acl.changed")
    assert [e.payload["resource_type"] for e in events] == ["document", "document"]


async def test_delete_document_and_kb(api: httpx.AsyncClient, engine: AsyncEngine) -> None:
    await login_all(api)
    kb = await create_kb(api, "待删库")
    doc = (await upload(api, kb["id"], "a.md", make_markdown())).json()["document"]

    # Editors without doc:delete cannot delete.
    assert (await api.delete(f"/api/v1/documents/{doc['id']}", headers=BOB)).status_code == 403
    assert (
        await api.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=ALICE)
    ).status_code == 409
    assert (await api.delete(f"/api/v1/documents/{doc['id']}", headers=ALICE)).status_code == 204
    assert (await api.get(f"/api/v1/documents/{doc['id']}", headers=ALICE)).status_code == 404
    listing = (await api.get(f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=BOB)).json()
    assert listing["total"] == 0
    deleted = await outbox(engine, "document.deleted")
    assert deleted[0].payload == {"document_id": doc["id"], "kb_id": kb["id"], "version": 1}

    # Re-uploading the same bytes after deletion creates a fresh document.
    again = (await upload(api, kb["id"], "a.md", make_markdown())).json()
    assert again["duplicate"] is False and again["document"]["id"] != doc["id"]
    await api.delete(f"/api/v1/documents/{again['document']['id']}", headers=ALICE)

    assert (
        await api.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=ALICE)
    ).status_code == 204
    assert (await api.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=ALICE)).status_code == 404
    # The name can be reused.
    await create_kb(api, "待删库")


async def test_failed_parse_and_reprocess(
    api: httpx.AsyncClient, task_queue: RecordingTaskQueue, pipeline: IngestPipeline
) -> None:
    await login_all(api)
    kb = await create_kb(api, "失败库")
    # Passes content sniffing (ZIP magic) but is not a valid archive.
    broken = b"PK\x03\x04 not a zip file"
    doc = (await upload(api, kb["id"], "broken.docx", broken)).json()["document"]
    with pytest.raises(ParseError):
        await pipeline.parse(doc["id"], 1)
    await pipeline.mark_failed(doc["id"], 1, "解析失败：broken")
    detail = (await api.get(f"/api/v1/documents/{doc['id']}", headers=BOB)).json()
    assert detail["status"] == "failed" and detail["error_message"] == "解析失败：broken"

    resp = await api.post(f"/api/v1/documents/{doc['id']}/reprocess", headers=BOB)
    assert resp.status_code == 200
    assert resp.json()["status"] == "uploaded" and resp.json()["error_message"] is None
    assert task_queue.calls[-1] == ("parse", doc["id"], 1)

    filtered = await api.get(
        f"/api/v1/knowledge-bases/{kb['id']}/documents", params={"status": "failed"}, headers=BOB
    )
    assert filtered.json()["total"] == 0


async def test_update_document_metadata(api: httpx.AsyncClient) -> None:
    await login_all(api)
    kb = await create_kb(api, "元数据库")
    doc = (await upload(api, kb["id"], "a.md", make_markdown())).json()["document"]
    resp = await api.put(
        f"/api/v1/documents/{doc['id']}",
        json={
            "title": "部署指南",
            "tags": ["运维", "运维", " "],
            "metadata": {"owner": "ops"},
            "effective_from": "2026-01-01T00:00:00Z",
        },
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "部署指南" and body["tags"] == ["运维"]
    assert body["metadata"] == {"owner": "ops"}
    bad = await api.put(
        f"/api/v1/documents/{doc['id']}",
        json={"effective_to": "2025-01-01T00:00:00Z"},
        headers=BOB,
    )
    assert bad.status_code == 422
    assert (
        await api.put(f"/api/v1/documents/{doc['id']}", json={"title": "x"}, headers=CAROL)
    ).status_code == 403
