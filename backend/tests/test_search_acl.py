"""Security: search results never contain chunks the caller may not read."""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.retrieval.backends import SearchBackends
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.pipeline import IngestPipeline
from tests.conftest import auth
from tests.samples import LOREM_ZH
from tests.test_indexing import (
    ALIAS,
    child_chunks,
    create_kb,
    drain,
    ingest,
    me,
    pipeline,
    text,
    vector,
)

__all__ = ["pipeline"]

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
DAVE = auth("other-org-token")

QUERIES = [
    "FX-9001",
    "飞织 配方",
    "机密配方 工艺参数",
    "内部备忘 配方",
    '"FX-9001" 鞋面',
    "kb:机密库 配方",
    "配方 type:markdown",
]


def md(title: str, body: str) -> bytes:
    return f"# {title}\n\n## 说明\n\n{body}\n\n## 背景\n\n{LOREM_ZH}\n".encode()


async def search(
    api: httpx.AsyncClient, headers: dict[str, str], q: str, **params: Any
) -> httpx.Response:
    return await api.get("/api/v1/search", params={"q": q, "top_k": 100, **params}, headers=headers)


async def hit_ids(
    api: httpx.AsyncClient, headers: dict[str, str], q: str, **params: Any
) -> set[str]:
    resp = await search(api, headers, q, **params)
    assert resp.status_code == 200, resp.text
    return {item["chunk_id"] for item in resp.json()["items"]}


@pytest.fixture
async def corpus(
    api: httpx.AsyncClient,
    engine: AsyncEngine,
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
) -> dict[str, Any]:
    bob = await me(api, BOB)
    await me(api, CAROL)
    await me(api, DAVE)
    secret_kb = await create_kb(api, "机密库", visibility="restricted")
    public_kb = await create_kb(api, "公开库", visibility="org")
    secret = await ingest(
        api,
        pipeline,
        secret_kb["id"],
        "secret.md",
        md("机密配方", "飞织鞋面机密配方 FX-9001 工艺参数"),
    )
    public = await ingest(
        api, pipeline, public_kb["id"], "public.md", md("公开说明", "飞织鞋面配方 FX-9001 公开介绍")
    )
    private = await ingest(
        api, pipeline, public_kb["id"], "memo.md", md("内部备忘", "配方 FX-9001 内部备忘录 鞋面")
    )
    resp = await api.put(
        f"/api/v1/documents/{private['id']}/acl",
        json={"inherit": False, "entries": []},
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    assert set(await drain(indexing)) == {"done"}

    def ids(doc: dict[str, Any]) -> set[str]:
        return {c.id for c in chunks[doc["id"]]}

    chunks = {d["id"]: await child_chunks(engine, d["id"]) for d in (secret, public, private)}
    return {
        "bob": bob,
        "secret_kb": secret_kb,
        "public_kb": public_kb,
        "secret": ids(secret),
        "public": ids(public),
        "private": ids(private),
        "private_doc": private,
    }


async def test_two_users_same_query_never_leak(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    forbidden = corpus["secret"] | corpus["private"]
    assert corpus["secret"] and corpus["private"] and corpus["public"]
    bob_seen: set[str] = set()
    carol_seen: set[str] = set()
    # Bob first, so Carol's identical queries would hit his cache entries if scoping failed.
    for q in QUERIES:
        bob_seen |= await hit_ids(api, BOB, q)
        got = await hit_ids(api, CAROL, q)
        assert not got & forbidden, f"leak for {q!r}: {got & forbidden}"
        carol_seen |= got
        # Repeat: served from cache now, still clean.
        assert not await hit_ids(api, CAROL, q) & forbidden

    assert bob_seen & corpus["secret"] and bob_seen & corpus["private"], "positive control"
    assert carol_seen & corpus["public"], "carol must still find what she may read"
    # Other tenant sees nothing at all.
    for q in QUERIES[:3]:
        assert await hit_ids(api, DAVE, q) == set()


async def test_kb_filter_cannot_widen_access(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    secret_kb = corpus["secret_kb"]
    resp = await search(api, CAROL, "FX-9001", kb_ids=[secret_kb["id"]])
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == [] and body["filters"]["kbs"] == []
    assert body["filters"]["unresolved_kbs"] == [secret_kb["id"]]

    body = (await search(api, CAROL, "kb:机密库 FX-9001")).json()
    assert body["items"] == [] and body["filters"]["unresolved_kbs"] == ["机密库"]

    # Bob restricted to the secret KB only gets that KB.
    got = await hit_ids(api, BOB, "FX-9001", kb_ids=[secret_kb["id"]])
    assert got and got <= corpus["secret"]


async def test_grant_is_visible_immediately_despite_result_cache(
    api: httpx.AsyncClient, corpus: dict[str, Any], indexing: IndexingRuntime
) -> None:
    q = "机密配方 FX-9001 工艺参数"
    assert not await hit_ids(api, CAROL, q) & corpus["secret"]
    assert not await hit_ids(api, CAROL, q) & corpus["secret"]  # now served from the cache

    kb = corpus["secret_kb"]
    acl = (await api.get(f"/api/v1/knowledge-bases/{kb['id']}/acl", headers=BOB)).json()
    entries = [
        {k: e[k] for k in ("principal_type", "principal_id", "permission")} for e in acl["entries"]
    ]
    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}/acl",
        json={"visibility": "org", "entries": entries},
        headers=BOB,
    )
    assert resp.status_code == 200, resp.text
    assert set(await drain(indexing)) == {"done"}

    assert await hit_ids(api, CAROL, q) & corpus["secret"]


async def test_stale_index_payload_is_caught_by_pg_recheck(
    api: httpx.AsyncClient, corpus: dict[str, Any], search_backends: SearchBackends
) -> None:
    # Simulate an index that lags behind an ACL change: the payload claims org-wide access.
    org_principal = f"org:{corpus['bob']['org_id']}"
    for index in (vector(search_backends), text(search_backends)):
        for cid, doc in index.resolve(ALIAS).items():
            if cid in corpus["private"] or cid in corpus["secret"]:
                doc["acl_read_principals"] = [*doc["acl_read_principals"], org_principal]

    resp = await search(api, CAROL, "内部 备忘录 机密 FX-9001")
    assert resp.status_code == 200
    got = {i["chunk_id"] for i in resp.json()["items"]}
    assert not got & (corpus["private"] | corpus["secret"])

    trace = await api.get(
        f"/api/v1/admin/retrieval/traces/{resp.json()['trace_id']}", headers=ALICE
    )
    assert trace.status_code == 200, trace.text
    assert trace.json()["stages"]["hydration"]["dropped"].get("no_access", 0) >= 1


async def test_debug_requires_admin_and_shows_score_chain(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    assert (await search(api, CAROL, "FX-9001", debug=True)).status_code == 403
    assert (await search(api, CAROL, "FX-9001", profile_id="builtin")).status_code == 403
    no_debug = (await search(api, CAROL, "FX-9001")).json()
    assert no_debug["debug"] is None

    body = (await search(api, ALICE, "FX-9001 配方", debug=True)).json()
    assert body["items"] and body["debug"]["stages"]["fusion"]["candidates"]
    stages = body["debug"]["stages"]
    assert {"routes", "fusion", "hydration", "rerank", "results"} <= set(stages)
    first = body["items"][0]
    assert first["ranks"]["rrf"] >= 1 and first["scores"]["rrf"] > 0
    assert first["scores"]["bm25"] is not None or first["scores"]["dense"] is not None
    assert first["ranks"]["rerank"] == 1 and first["scores"]["rerank"] is not None
    assert "<em>" in first["snippet"]
    options = (await api.get("/api/v1/search/options", headers=ALICE)).json()
    assert options["can_debug"] is True and "markdown" in options["doc_types"]
    carol_options = (await api.get("/api/v1/search/options", headers=CAROL)).json()
    assert carol_options["can_debug"] is False


async def test_trace_is_recorded_per_search(api: httpx.AsyncClient, corpus: dict[str, Any]) -> None:
    body = (await search(api, CAROL, "飞织 配方 FX-9001")).json()
    listing = await api.get(
        "/api/v1/admin/retrieval/traces", params={"keyword": "飞织"}, headers=ALICE
    )
    assert listing.status_code == 200
    page = listing.json()
    assert page["total"] >= 1 and body["trace_id"] in {t["id"] for t in page["items"]}
    detail = (
        await api.get(f"/api/v1/admin/retrieval/traces/{body['trace_id']}", headers=ALICE)
    ).json()
    assert detail["normalized_query"] == "飞织 配方 FX-9001"
    assert detail["filters"]["org_id"] == corpus["bob"]["org_id"]
    assert set(detail["stages"]["routes"]) == {"dense", "sparse"}
    assert (await api.get("/api/v1/admin/retrieval/traces", headers=CAROL)).status_code == 403
