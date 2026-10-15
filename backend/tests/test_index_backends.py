import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from app.retrieval.opensearch import OpenSearchIndex, index_template
from app.retrieval.qdrant import QdrantIndex
from app.retrieval.records import ChunkRecord, chunk_id_from_point, point_id

CHUNK_ID = uuid.uuid4().hex


def record(**overrides: Any) -> ChunkRecord:
    values: dict[str, Any] = {
        "chunk_id": CHUNK_ID,
        "org_id": "o1",
        "kb_id": "kb1",
        "document_id": "d1",
        "doc_version": 2,
        "parent_id": "p1",
        "heading_path": ["第一章", "总则"],
        "chunk_type": "text",
        "tags": ["hr"],
        "created_at": datetime(2026, 10, 8, tzinfo=UTC),
        "acl_read_principals": ["org:o1", "user:u1"],
        "is_ko": False,
        "title": "员工手册",
        "content": "正文",
    }
    return ChunkRecord(**{**values, **overrides})


class Recorder:
    def __init__(self, responses: dict[tuple[str, str], Any] | None = None) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.responses = responses or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = None
        if request.content:
            raw = request.content.decode()
            try:
                body = json.loads(raw)
            except ValueError:
                body = [json.loads(line) for line in raw.splitlines() if line]
        self.requests.append((request.method, request.url.path, body))
        key = (request.method, request.url.path)
        status, payload = self.responses.get(key, (200, {"result": {}, "acknowledged": True}))
        return httpx.Response(status, json=payload)

    def find(self, method: str, path: str) -> list[Any]:
        return [b for m, p, b in self.requests if m == method and p == path]


def test_point_ids_round_trip() -> None:
    assert chunk_id_from_point(point_id(CHUNK_ID)) == CHUNK_ID


def test_record_payloads_follow_the_index_contract() -> None:
    payload = record().qdrant_payload()
    assert set(payload) == {
        "chunk_id",
        "org_id",
        "kb_id",
        "document_id",
        "doc_version",
        "parent_id",
        "heading_path",
        "chunk_type",
        "tags",
        "created_at",
        "acl_read_principals",
        "is_ko",
        "doc_type",
    }
    assert "content" not in payload, "PG stays the source of the text"
    doc = record().opensearch_doc()
    assert doc["heading_path"] == "第一章 / 总则" and doc["content"] == "正文"
    assert record().embedding_text() == "第一章 / 总则\n正文"


async def test_qdrant_collection_tenant_index_and_alias_switch() -> None:
    rec = Recorder(
        {
            ("GET", "/collections/kb_chunks_v2/exists"): (200, {"result": {"exists": False}}),
            ("GET", "/aliases"): (
                200,
                {
                    "result": {
                        "aliases": [{"alias_name": "kb_chunks", "collection_name": "kb_chunks_v1"}]
                    }
                },
            ),
        }
    )
    qdrant = QdrantIndex(
        "http://q", http=httpx.AsyncClient(base_url="http://q", transport=httpx.MockTransport(rec))
    )
    await qdrant.ensure_collection("kb_chunks_v2", 1024)
    created = rec.find("PUT", "/collections/kb_chunks_v2")[0]
    assert created["vectors"] == {"size": 1024, "distance": "Cosine"}
    indexes = {
        b["field_name"]: b["field_schema"]
        for b in rec.find("PUT", "/collections/kb_chunks_v2/index")
    }
    assert indexes["org_id"] == {"type": "keyword", "is_tenant": True}
    assert indexes["kb_id"] == {"type": "keyword"}
    assert indexes["acl_read_principals"] == {"type": "keyword"}

    assert await qdrant.get_alias("kb_chunks") == "kb_chunks_v1"
    await qdrant.switch_alias("kb_chunks", "kb_chunks_v2")
    actions = rec.find("POST", "/collections/aliases")[0]["actions"]
    assert actions == [
        {"delete_alias": {"alias_name": "kb_chunks"}},
        {"create_alias": {"collection_name": "kb_chunks_v2", "alias_name": "kb_chunks"}},
    ]

    await qdrant.upsert("kb_chunks_v2", [record()], [[0.1] * 4])
    point = rec.find("PUT", "/collections/kb_chunks_v2/points")[0]["points"][0]
    assert point["id"] == str(uuid.UUID(CHUNK_ID)) and point["payload"]["doc_version"] == 2

    await qdrant.set_acl("kb_chunks_v2", ["d1", "d2"], ["org:o1"])
    acl = rec.find("POST", "/collections/kb_chunks_v2/points/payload")[0]
    assert acl == {
        "payload": {"acl_read_principals": ["org:o1"]},
        "filter": {"must": [{"key": "document_id", "match": {"any": ["d1", "d2"]}}]},
    }
    await qdrant.delete_stale_versions("kb_chunks_v2", "d1", 2)
    stale = rec.find("POST", "/collections/kb_chunks_v2/points/delete")[0]["filter"]
    assert stale["must_not"] == [{"key": "doc_version", "match": {"value": 2}}]


def test_opensearch_template_uses_ik_and_reloadable_synonyms() -> None:
    body = index_template("kb_chunks", shards=1, replicas=0, synonyms_path="analysis/synonyms.txt")
    assert body["index_patterns"] == ["kb_chunks_v*"]
    analysis = body["template"]["settings"]["analysis"]
    assert analysis["analyzer"]["ekb_index"]["tokenizer"] == "ik_max_word"
    assert analysis["analyzer"]["ekb_search"]["tokenizer"] == "ik_smart"
    assert "ekb_synonym" in analysis["analyzer"]["ekb_search"]["filter"]
    assert "ekb_synonym" not in analysis["analyzer"]["ekb_index"]["filter"]
    assert analysis["filter"]["ekb_synonym"]["updateable"] is True
    props = body["template"]["mappings"]["properties"]
    for field in ("content", "title", "heading_path"):
        assert props[field]["analyzer"] == "ekb_index"
        assert props[field]["search_analyzer"] == "ekb_search"
    for field in ("org_id", "kb_id", "document_id", "acl_read_principals", "tags"):
        assert props[field] == {"type": "keyword"}
    assert props["created_at"] == {"type": "date"}


async def test_opensearch_bulk_alias_and_acl_update() -> None:
    rec = Recorder(
        {
            ("GET", "/_alias/kb_chunks"): (200, {"kb_chunks_v1": {"aliases": {"kb_chunks": {}}}}),
            ("POST", "/_bulk"): (200, {"errors": False, "items": []}),
            ("POST", "/kb_chunks_v2/_update_by_query"): (
                200,
                {"failures": [], "version_conflicts": 0},
            ),
        }
    )
    index = OpenSearchIndex(
        "http://os",
        alias="kb_chunks",
        http=httpx.AsyncClient(base_url="http://os", transport=httpx.MockTransport(rec)),
    )
    await index.upsert("kb_chunks_v2", [record()])
    action, source = rec.find("POST", "/_bulk")[0]
    assert action == {"index": {"_index": "kb_chunks_v2", "_id": CHUNK_ID}}
    assert source["acl_read_principals"] == ["org:o1", "user:u1"]

    await index.switch_alias("kb_chunks", "kb_chunks_v2")
    assert rec.find("POST", "/_aliases")[0]["actions"] == [
        {"remove": {"index": "kb_chunks_v1", "alias": "kb_chunks"}},
        {"add": {"index": "kb_chunks_v2", "alias": "kb_chunks"}},
    ]

    await index.set_acl("kb_chunks_v2", ["d1"], ["group:g1"])
    update = rec.find("POST", "/kb_chunks_v2/_update_by_query")[0]
    assert update["query"] == {"terms": {"document_id": ["d1"]}}
    assert update["script"]["params"] == {"principals": ["group:g1"]}

    await index.reload_search_analyzers("kb_chunks_v2")
    assert rec.find("POST", "/_plugins/_refresh_search_analyzers/kb_chunks_v2")
