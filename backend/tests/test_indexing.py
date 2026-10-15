from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.cli import run as cli_run
from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.storage import MemoryStorage
from app.llm import EmbeddingSpec, LLMError
from app.llm.mock import MockEmbeddingClient
from app.models import Chunk, Document, OutboxEvent, OutboxStatus
from app.retrieval.backends import SearchBackends
from app.retrieval.memory import MemoryTextIndex, MemoryVectorIndex
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.chunker import Chunker
from app.services.ingest.parsers import ParserRegistry
from app.services.ingest.pipeline import IngestPipeline
from app.services.ingest.queue import RecordingTaskQueue
from tests.conftest import auth
from tests.samples import LOREM_ZH, make_markdown

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
ALIAS = "kb_chunks"


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
    )


def vector(backends: SearchBackends) -> MemoryVectorIndex:
    assert isinstance(backends.vector, MemoryVectorIndex)
    return backends.vector


def text(backends: SearchBackends) -> MemoryTextIndex:
    assert isinstance(backends.text, MemoryTextIndex)
    return backends.text


async def drain(indexing: IndexingRuntime) -> list[str]:
    """Dispatcher + worker in one loop: claim and process until nothing is due."""
    statuses: list[str] = []
    while ids := await indexing.processor.claim():
        for event_id in ids:
            statuses.append(await indexing.processor.process(event_id))
    return statuses


async def me(api: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    body = dict((await api.get("/api/v1/auth/me", headers=headers)).json())
    body["org_id"] = body["org"]["id"]
    return body


async def create_kb(
    api: httpx.AsyncClient, name: str, visibility: str = "restricted"
) -> dict[str, Any]:
    resp = await api.post(
        "/api/v1/knowledge-bases",
        json={"name": name, "visibility": visibility},
        headers=BOB,
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def ingest(
    api: httpx.AsyncClient,
    pipeline: IngestPipeline,
    kb_id: str,
    filename: str = "guide.md",
    content: bytes | None = None,
) -> dict[str, Any]:
    resp = await api.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content or make_markdown(), "text/markdown")},
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    doc = dict(resp.json()["document"])
    assert await pipeline.parse(doc["id"], doc["version"])
    assert await pipeline.chunk(doc["id"], doc["version"])
    return doc


async def child_chunks(engine: AsyncEngine, document_id: str) -> list[Chunk]:
    async with create_session_factory(engine)() as session:
        doc = await session.get(Document, document_id)
        assert doc is not None
        stmt = select(Chunk).where(
            Chunk.document_id == document_id,
            Chunk.document_version == doc.version,
            Chunk.level == 2,
        )
        return list((await session.execute(stmt)).scalars())


async def doc_status(engine: AsyncEngine, document_id: str) -> str:
    async with create_session_factory(engine)() as session:
        doc = await session.get(Document, document_id)
        assert doc is not None
        return doc.status


def docs_of(index: MemoryVectorIndex | MemoryTextIndex, document_id: str) -> dict[str, Any]:
    return {c: d for c, d in index.resolve(ALIAS).items() if d["document_id"] == document_id}


def acl_sets(index: MemoryVectorIndex | MemoryTextIndex, document_id: str) -> set[tuple[str, ...]]:
    return {tuple(d["acl_read_principals"]) for d in docs_of(index, document_id).values()}


async def test_upload_is_indexed_into_both_backends(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    bob = await me(api, BOB)
    kb = await create_kb(api, "索引库")
    doc = await ingest(api, pipeline, kb["id"])

    assert await drain(indexing) == ["done"]
    assert await doc_status(engine, doc["id"]) == "indexed"

    vec, txt = vector(search_backends), text(search_backends)
    assert vec.aliases[ALIAS] == f"{ALIAS}_v1" and txt.aliases[ALIAS] == f"{ALIAS}_v1"
    assert txt.template_installed
    expected = {c.id for c in await child_chunks(engine, doc["id"])}
    assert expected and set(docs_of(vec, doc["id"])) == expected == set(docs_of(txt, doc["id"]))

    payload = next(iter(docs_of(vec, doc["id"]).values()))
    assert payload["org_id"] == bob["org_id"] and payload["kb_id"] == kb["id"]
    assert payload["doc_version"] == 1 and payload["is_ko"] is False
    assert payload["acl_read_principals"] == [f"user:{bob['id']}"]
    assert isinstance(payload["heading_path"], list) and payload["parent_id"]
    assert {"chunk_type", "tags", "created_at"} <= set(payload)
    os_doc = next(iter(docs_of(txt, doc["id"]).values()))
    assert os_doc["content"] and os_doc["title"] == "guide"
    assert all(len(v) == 16 for v in vec.vectors[f"{ALIAS}_v1"].values())

    # Duplicate delivery is a no-op; a forced re-index rewrites the same ids.
    assert (await indexing.indexer.index_document(doc["id"], 1)).outcome == "already_indexed"
    forced = await indexing.indexer.index_document(doc["id"], 1, force=True)
    assert forced.outcome == "indexed" and forced.chunks == len(expected)
    assert set(docs_of(vec, doc["id"])) == expected == set(docs_of(txt, doc["id"]))

    report = await api.post(f"/api/v1/admin/index/kbs/{kb['id']}/check", headers=ALICE)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["consistent"] is True
    assert body["pg_count"] == body["qdrant"]["count"] == body["opensearch"]["count"]


async def test_acl_change_updates_payload_without_reembedding(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    bob = await me(api, BOB)
    await me(api, CAROL)
    kb = await create_kb(api, "权限库")
    doc = await ingest(api, pipeline, kb["id"])
    await drain(indexing)
    embedder = indexing.gateway.embedding(indexing.gateway.default_embedding).inner
    assert isinstance(embedder, MockEmbeddingClient)
    calls = len(embedder.calls)

    groups = await api.get(
        "/api/v1/directory/principals", params={"type": "group", "keyword": "sales"}, headers=BOB
    )
    sales = next(p["id"] for p in groups.json() if p["name"] == "sales")
    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}/acl",
        json={
            "visibility": "org",
            "entries": [
                {"principal_type": "user", "principal_id": bob["id"], "permission": "manage"},
                {"principal_type": "group", "principal_id": sales, "permission": "read"},
            ],
        },
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    assert await drain(indexing) == ["done"]

    expected = tuple(sorted([f"group:{sales}", f"org:{bob['org_id']}", f"user:{bob['id']}"]))
    for index in (vector(search_backends), text(search_backends)):
        assert acl_sets(index, doc["id"]) == {expected}
    assert len(embedder.calls) == calls, "ACL updates must not re-embed"

    # Own ACL: only its entries plus KB managers; org-wide visibility no longer applies.
    resp = await api.put(
        f"/api/v1/documents/{doc['id']}/acl", json={"inherit": False, "entries": []}, headers=BOB
    )
    assert resp.status_code == 200
    await drain(indexing)
    for index in (vector(search_backends), text(search_backends)):
        assert acl_sets(index, doc["id"]) == {(f"user:{bob['id']}",)}


async def test_delete_removes_document_from_both_backends(
    api: httpx.AsyncClient,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    await me(api, BOB)
    kb = await create_kb(api, "删除库")
    keep = await ingest(api, pipeline, kb["id"], "keep.md")
    gone = await ingest(api, pipeline, kb["id"], "gone.md", make_markdown() + b"\n\nextra")
    await drain(indexing)
    assert docs_of(vector(search_backends), gone["id"])

    assert (await api.delete(f"/api/v1/documents/{gone['id']}", headers=ALICE)).status_code == 204
    assert await drain(indexing) == ["done"]
    for index in (vector(search_backends), text(search_backends)):
        assert docs_of(index, gone["id"]) == {}
        assert docs_of(index, keep["id"])
    # Replaying the event is harmless.
    assert await indexing.indexer.delete_document(gone["id"]) is True


async def test_new_version_replaces_stale_chunks(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    await me(api, BOB)
    kb = await create_kb(api, "版本库")
    v1 = await ingest(api, pipeline, kb["id"], "policy.md")
    await drain(indexing)
    v2 = await ingest(api, pipeline, kb["id"], "policy.md", f"# 新版\n\n{LOREM_ZH}".encode())
    assert v2["id"] == v1["id"] and v2["version"] == 2

    # A late event for v1 is skipped (superseded) and must not resurrect v1 chunks.
    assert (await indexing.indexer.index_document(v1["id"], 1)).outcome == "skipped"
    await drain(indexing)
    expected = {c.id for c in await child_chunks(engine, v1["id"])}
    for index in (vector(search_backends), text(search_backends)):
        indexed = docs_of(index, v1["id"])
        assert set(indexed) == expected
        assert {d["doc_version"] for d in indexed.values()} == {2}


class HookedEmbedding:
    """Runs `hook` while embedding: simulates a concurrent change during the slow step."""

    def __init__(self, inner: MockEmbeddingClient, hook: Callable[[], Awaitable[None]]) -> None:
        self.inner = inner
        self.hook = hook

    @property
    def spec(self) -> EmbeddingSpec:
        return self.inner.spec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        await self.hook()
        return await self.inner.embed(texts)


def mock_embedder(indexing: IndexingRuntime) -> tuple[EmbeddingSpec, MockEmbeddingClient]:
    spec = indexing.gateway.default_embedding
    inner = indexing.gateway.embedding(spec).inner
    assert isinstance(inner, MockEmbeddingClient)
    return spec, inner


async def test_concurrent_acl_change_during_indexing_is_not_lost(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    bob = await me(api, BOB)
    kb = await create_kb(api, "竞态库")
    doc = await ingest(api, pipeline, kb["id"])
    spec, inner = mock_embedder(indexing)

    async def make_org_wide() -> None:
        # Committed after the indexer read the ACL, before it writes the points.
        resp = await api.put(
            f"/api/v1/knowledge-bases/{kb['id']}/acl",
            json={
                "visibility": "org",
                "entries": [
                    {"principal_type": "user", "principal_id": bob["id"], "permission": "manage"}
                ],
            },
            headers=BOB,
        )
        assert resp.status_code == 200

    indexing.gateway._embeddings[spec] = HookedEmbedding(inner, make_org_wide)
    result = await indexing.indexer.index_document(doc["id"], 1)
    assert result.outcome == "indexed"
    expected = tuple(sorted([f"org:{bob['org_id']}", f"user:{bob['id']}"]))
    for index in (vector(search_backends), text(search_backends)):
        assert acl_sets(index, doc["id"]) == {expected}


async def test_document_deleted_during_indexing_leaves_no_points(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    await me(api, BOB)
    kb = await create_kb(api, "删除竞态库")
    doc = await ingest(api, pipeline, kb["id"])
    spec, inner = mock_embedder(indexing)

    async def delete() -> None:
        resp = await api.delete(f"/api/v1/documents/{doc['id']}", headers=ALICE)
        assert resp.status_code == 204

    indexing.gateway._embeddings[spec] = HookedEmbedding(inner, delete)
    assert (await indexing.indexer.index_document(doc["id"], 1)).outcome == "skipped"
    for index in (vector(search_backends), text(search_backends)):
        assert docs_of(index, doc["id"]) == {}


class FailingEmbedding:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise LLMError("embedding service unavailable", retryable=True)


async def test_failures_back_off_then_dead_letter_and_manual_retry(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    await me(api, BOB)
    kb = await create_kb(api, "失败库")
    doc = await ingest(api, pipeline, kb["id"])
    spec, healthy = mock_embedder(indexing)
    indexing.gateway._embeddings[spec] = FailingEmbedding(spec)
    indexing.processor.max_attempts = 3

    assert await drain(indexing) == ["pending"]
    async with create_session_factory(engine)() as session:
        event = (await session.execute(select(OutboxEvent))).scalar_one()
        assert event.retry_count == 1 and event.next_attempt_at is not None
        assert "embedding service unavailable" in (event.last_error or "")
    # Backing off: not due yet.
    assert await indexing.processor.claim() == []

    async def force_due() -> None:
        async with create_session_factory(engine)() as session:
            ev = (await session.execute(select(OutboxEvent))).scalar_one()
            ev.next_attempt_at = None
            await session.commit()

    for expected in ("pending", "dead"):
        await force_due()
        assert await drain(indexing) == [expected]
    assert await doc_status(engine, doc["id"]) == "failed"

    stats = (await api.get("/api/v1/admin/index/outbox/stats", headers=ALICE)).json()
    assert stats["dead"] == 1
    dead = (await api.get("/api/v1/admin/index/outbox?status=dead", headers=ALICE)).json()
    assert dead["total"] == 1 and dead["items"][0]["retry_count"] == 3
    assert (await api.get("/api/v1/admin/index/outbox", headers=BOB)).status_code == 403

    indexing.gateway._embeddings[spec] = healthy
    event_id = dead["items"][0]["id"]
    retried = await api.post(f"/api/v1/admin/index/outbox/{event_id}/retry", headers=ALICE)
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
    assert await drain(indexing) == ["done"]
    assert await doc_status(engine, doc["id"]) == "indexed"
    assert docs_of(vector(search_backends), doc["id"])


async def test_unknown_event_type_is_dead_lettered_immediately(
    engine: AsyncEngine, indexing: IndexingRuntime
) -> None:
    async with create_session_factory(engine)() as session:
        session.add(
            OutboxEvent(
                org_id="o", aggregate_type="x", aggregate_id="1", event_type="x.unknown", payload={}
            )
        )
        await session.commit()
    assert await drain(indexing) == [OutboxStatus.DEAD.value]


async def test_consistency_check_and_repair(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
    task_queue: RecordingTaskQueue,
) -> None:
    bob = await me(api, BOB)
    kb = await create_kb(api, "校验库")
    doc = await ingest(api, pipeline, kb["id"])
    await drain(indexing)
    vec, txt = vector(search_backends), text(search_backends)
    ids = sorted(docs_of(vec, doc["id"]))

    # Drift: a point lost in Qdrant, an orphan in OpenSearch.
    await vec.delete_ids(f"{ALIAS}_v1", ids[:1])
    orphan = dict(next(iter(docs_of(txt, doc["id"]).values())), document_id="ghost")
    txt.resolve(ALIAS)["f" * 32] = orphan

    report = (await api.post(f"/api/v1/admin/index/kbs/{kb['id']}/check", headers=ALICE)).json()
    assert report["consistent"] is False
    assert report["qdrant"]["missing"] == ids[:1] and report["qdrant"]["extra_count"] == 0
    assert report["opensearch"]["extra"] == ["f" * 32]
    assert report["reindex_documents"] == [doc["id"]]

    queued = await api.post(f"/api/v1/admin/index/kbs/{kb['id']}/repair", headers=ALICE)
    assert queued.status_code == 202
    assert task_queue.repairs == [(bob["org_id"], kb["id"])]

    result = await indexing.consistency.repair(bob["org_id"], kb["id"])
    assert result.report.consistent and result.reindexed_documents == [doc["id"]]
    assert result.deleted_opensearch == 1
    assert await cli_run(["index", "check", "--kb", kb["id"]], indexing.settings, indexing) == 0


async def test_rebuild_dual_writes_then_switches_aliases(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
    search_backends: SearchBackends,
) -> None:
    await me(api, BOB)
    kb = await create_kb(api, "重建库")
    first = await ingest(api, pipeline, kb["id"], "a.md")
    await drain(indexing)
    vec, txt = vector(search_backends), text(search_backends)

    # A document indexed while v2 is being built lands in both generations.
    new_spec = EmbeddingSpec(model="new-embedding", dim=32, base_url="http://new/v1")
    building = await indexing.registry.create_building(new_spec)
    second = await ingest(api, pipeline, kb["id"], "b.md", make_markdown() + b"\n\nmore")
    await drain(indexing)
    assert docs_of(vec, second["id"])
    in_building = vec.indexes[building.qdrant_collection].values()
    assert any(d["document_id"] == second["id"] for d in in_building)
    assert vec.aliases[ALIAS] == f"{ALIAS}_v1", "readers stay on v1 while building"
    await indexing.registry.mark_failed(building.version, "test: abandon")

    result = await indexing.rebuilder.rebuild(new_spec)
    assert result.activated and result.version == 3
    assert result.pg_chunks == result.qdrant_points == result.opensearch_docs > 0
    assert vec.aliases[ALIAS] == f"{ALIAS}_v3" == txt.aliases[ALIAS]
    assert vec.dims[f"{ALIAS}_v3"] == 32
    assert f"{ALIAS}_v1" in vec.indexes, "old generation kept for rollback"
    for doc in (first, second):
        expected = {c.id for c in await child_chunks(engine, doc["id"])}
        assert set(docs_of(vec, doc["id"])) == expected

    gens = (await api.get("/api/v1/admin/index/generations", headers=ALICE)).json()
    assert [(g["version"], g["status"]) for g in gens] == [
        (3, "active"),
        (2, "failed"),
        (1, "retired"),
    ]
    assert gens[0]["embedding_model"] == "new-embedding"

    # Rollback is just an alias switch.
    assert await cli_run(["index", "activate", "1"], indexing.settings, indexing) == 0
    assert vec.aliases[ALIAS] == f"{ALIAS}_v1" == txt.aliases[ALIAS]
