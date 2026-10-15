import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.cache import MemoryCache
from app.retrieval.cache import ResultCache, principals_hash
from app.retrieval.config import RetrievalConfig, Route
from app.retrieval.filters import SearchFilter
from app.retrieval.fusion import rrf_fuse
from app.retrieval.highlight import POST_TAG, PRE_TAG, highlight, mark, query_terms
from app.retrieval.memory import opensearch_bool_matches, qdrant_filter_matches
from app.retrieval.query import QueryFilters, QueryPreprocessor
from app.retrieval.trace import truncate_stages
from app.services.authz.acl import AclFilter

D, S = Route.DENSE, Route.SPARSE

# ---- RRF ------------------------------------------------------------------------------


def test_rrf_formula_matches_definition() -> None:
    fused = rrf_fuse({D: [("a", 0.9), ("b", 0.8)], S: [("b", 12.0), ("c", 7.0)]}, k=60)
    by_id = {c.chunk_id: c for c in fused}
    assert by_id["a"].rrf_score == pytest.approx(1 / 61)
    assert by_id["b"].rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert by_id["c"].rrf_score == pytest.approx(1 / 62)
    assert [c.chunk_id for c in fused] == ["b", "a", "c"]
    assert [c.rrf_rank for c in fused] == [1, 2, 3]


def test_rrf_keeps_original_ranks_and_scores_per_route() -> None:
    fused = rrf_fuse({D: [("x", 0.5), ("y", 0.4)], S: [("y", 3.0)]})
    y = next(c for c in fused if c.chunk_id == "y")
    assert y.ranks == {D: 2, S: 1}
    assert y.scores == {D: 0.4, S: 3.0}
    x = next(c for c in fused if c.chunk_id == "x")
    assert x.ranks == {D: 1} and S not in x.scores


def test_rrf_dedupes_by_chunk_id_within_a_route() -> None:
    fused = rrf_fuse({D: [("a", 0.9), ("a", 0.1), ("b", 0.05)]}, k=10)
    assert [c.chunk_id for c in fused] == ["a", "b"]
    a = fused[0]
    assert a.ranks == {D: 1} and a.scores == {D: 0.9}
    assert a.rrf_score == pytest.approx(1 / 11)
    # Positions are not compacted: "b" was the 3rd entry of the route.
    assert fused[1].ranks == {D: 3}


def test_rrf_weights_change_the_order() -> None:
    rankings = {D: [("dense-top", 0.9)], S: [("sparse-top", 20.0)]}
    favour_sparse = rrf_fuse(rankings, weights={D: 1.0, S: 2.0})
    assert favour_sparse[0].chunk_id == "sparse-top"
    assert favour_sparse[0].rrf_score == pytest.approx(2 / 61)
    favour_dense = rrf_fuse(rankings, weights={D: 3.0, S: 1.0})
    assert favour_dense[0].chunk_id == "dense-top"
    # Weight 0 keeps the rank for debugging but adds nothing to the score.
    muted = rrf_fuse(rankings, weights={D: 0.0, S: 1.0})
    dense_top = next(c for c in muted if c.chunk_id == "dense-top")
    assert dense_top.rrf_score == 0 and dense_top.ranks == {D: 1}


def test_rrf_ties_are_deterministic() -> None:
    # Same score (1/61 each): best single rank ties too, so chunk_id decides.
    fused = rrf_fuse({D: [("b", 1.0)], S: [("a", 1.0)]})
    assert [c.chunk_id for c in fused] == ["a", "b"]
    # z: 1/(1+1) = 0.5 (rank 1), a: 1.5/(1+2) = 0.5 (rank 2): best single rank wins over id.
    fused = rrf_fuse({D: [("z", 1.0)], S: [("x", 1.0), ("a", 1.0)]}, k=1, weights={D: 1.0, S: 1.5})
    assert [c.chunk_id for c in fused] == ["x", "z", "a"]
    assert fused[1].rrf_score == fused[2].rrf_score == 0.5


def test_rrf_rejects_invalid_k_and_handles_empty_input() -> None:
    with pytest.raises(ValueError):
        rrf_fuse({D: [("a", 1.0)]}, k=0)
    assert rrf_fuse({}) == []
    assert rrf_fuse({D: [], S: []}) == []


# ---- query preprocessing --------------------------------------------------------------

P = QueryPreprocessor()


def test_normalizes_full_width_and_whitespace() -> None:
    parsed = P.parse("  ＨＲ－２０２４　 报销　 制度 ")
    assert parsed.text == "HR-2024 报销 制度"
    assert "HR-2024" in parsed.exact_terms


def test_extracts_inline_filters() -> None:
    parsed = P.parse('差旅 报销 kb:"财务 制度" 标签：报销 type:docx 类型:PDF after:2026-01-01')
    assert parsed.text == "差旅 报销"
    f = parsed.filters
    assert f.kb_names == ("财务 制度",)
    assert f.tags == ("报销",)
    assert f.doc_types == ("word", "pdf")
    assert f.date_from == datetime(2026, 1, 1, tzinfo=UTC) and f.date_to is None
    assert parsed.ignored == ()


@pytest.mark.parametrize(
    ("expr", "start", "end"),
    [
        ("date:2025", datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        ("日期:2025-12", datetime(2025, 12, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        ("date:2025-02-28", datetime(2025, 2, 28, tzinfo=UTC), datetime(2025, 3, 1, tzinfo=UTC)),
        (
            "date:2025-01..2025-03",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 4, 1, tzinfo=UTC),
        ),
        ("date:..2025", None, datetime(2026, 1, 1, tzinfo=UTC)),
        ("before:2025-06-30", None, datetime(2025, 7, 1, tzinfo=UTC)),
    ],
)
def test_date_windows_are_half_open(expr: str, start: datetime | None, end: datetime) -> None:
    f = P.parse(f"合同 {expr}").filters
    assert (f.date_from, f.date_to) == (start, end)


def test_bad_operators_are_reported_not_applied() -> None:
    parsed = P.parse("安全 type:exe date:2025-13 标签:")
    assert parsed.filters.doc_types == () and parsed.filters.date_from is None
    assert set(parsed.ignored) == {"type:exe", "date:2025-13", "标签:"}
    assert parsed.text == "安全"


def test_exact_terms_from_quotes_and_codes() -> None:
    parsed = P.parse("“数据 分级” 规范 GB/T-35273 ISO9001 第3条 v2")
    assert "数据 分级" in parsed.exact_terms
    assert "GB/T-35273" in parsed.exact_terms and "ISO9001" in parsed.exact_terms
    assert "v2" not in parsed.exact_terms  # too short to be a code
    assert '"' not in parsed.text


def test_explicit_filters_merge_with_inline() -> None:
    explicit = QueryFilters(
        kb_ids=("kb-1",),
        tags=("a",),
        doc_types=("PDF",),
        date_from=datetime(2025, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 1, 1, tzinfo=UTC),
    )
    f = P.parse("x tag:b date:2025-06", explicit).filters
    assert f.kb_ids == ("kb-1",) and f.tags == ("a", "b") and f.doc_types == ("pdf",)
    # Date windows intersect.
    assert f.date_from == datetime(2025, 6, 1, tzinfo=UTC)
    assert f.date_to == datetime(2025, 7, 1, tzinfo=UTC)


# ---- ACL / search filter rendering ----------------------------------------------------

ACL = AclFilter(org_id="org-1", principals=("user:u1", "group:g1"), kb_ids=("kb-1",))


def test_filters_always_carry_org_id_and_principals() -> None:
    flt = SearchFilter(acl=ACL, tags=("t",), doc_types=("pdf",))
    q = flt.to_qdrant()
    assert {"key": "org_id", "match": {"value": "org-1"}} in q["must"]
    assert any(c.get("key") == "acl_read_principals" for c in q["must"])
    os = flt.to_opensearch()
    assert {"term": {"org_id": "org-1"}} in os
    assert any("acl_read_principals" in c.get("terms", {}) for c in os)

    bypass = SearchFilter(acl=AclFilter(org_id="org-1", principals=(), bypass_acl=True))
    assert {"key": "org_id", "match": {"value": "org-1"}} in bypass.to_qdrant()["must"]
    assert {"term": {"org_id": "org-1"}} in bypass.to_opensearch()


def test_filters_select_the_same_documents_in_both_engines() -> None:
    flt = SearchFilter(
        acl=ACL,
        tags=("制度",),
        doc_types=("pdf",),
        date_from=datetime(2025, 1, 1, tzinfo=UTC),
        date_to=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base = {
        "org_id": "org-1",
        "kb_id": "kb-1",
        "acl_read_principals": ["group:g1"],
        "tags": ["制度", "财务"],
        "doc_type": "pdf",
        "created_at": "2025-05-01T00:00:00+00:00",
    }
    variants: dict[str, tuple[dict[str, Any], bool]] = {
        "ok": ({}, True),
        "other org": ({"org_id": "org-2"}, False),
        "other kb": ({"kb_id": "kb-2"}, False),
        "no principal": ({"acl_read_principals": ["user:u9"]}, False),
        "tag": ({"tags": ["财务"]}, False),
        "type": ({"doc_type": "word"}, False),
        "too old": ({"created_at": "2024-12-31T23:59:59+00:00"}, False),
        "end exclusive": ({"created_at": "2026-01-01T00:00:00+00:00"}, False),
    }
    os_query = {"filter": flt.to_opensearch()}
    for name, (patch, expected) in variants.items():
        doc = {**base, **patch}
        assert qdrant_filter_matches(doc, flt.to_qdrant()) is expected, name
        assert opensearch_bool_matches(doc, os_query) is expected, name


# ---- caches ---------------------------------------------------------------------------


def test_principals_hash_is_order_insensitive_and_scope_sensitive() -> None:
    assert principals_hash(["user:a", "group:g"]) == principals_hash(["group:g", "user:a"])
    assert principals_hash(["user:a"]) != principals_hash(["user:a", "group:g"])
    assert principals_hash([], bypass_acl=True) != principals_hash([])


def test_result_cache_key_contains_org_and_scope() -> None:
    req = {"text": "报销"}
    scope = principals_hash(["user:a"])
    key = ResultCache.key("org-1", scope, req)
    assert key.startswith(f"retrieval:res:org-1:g0:{scope}:")
    assert key != ResultCache.key("org-2", scope, req)
    assert key != ResultCache.key("org-1", principals_hash(["user:b"]), req)
    assert key != ResultCache.key("org-1", scope, req, "1")
    assert key == ResultCache.key("org-1", scope, {"text": "报销"})


async def test_result_cache_generation_bumps_per_org() -> None:
    cache = ResultCache(MemoryCache())
    assert await cache.generation("org-1") == "0"
    await cache.invalidate_org("org-1")
    assert await cache.generation("org-1") == "1"
    assert await cache.generation("org-2") == "0"


def test_config_fingerprint_ignores_cache_ttls() -> None:
    a = RetrievalConfig()
    b = RetrievalConfig.model_validate({"cache": {"result_ttl_seconds": 0}})
    c = RetrievalConfig.model_validate({"fusion": {"k": 30}})
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()


def test_config_validation() -> None:
    with pytest.raises(ValidationError):
        RetrievalConfig.model_validate({"dense": {"enabled": False}, "sparse": {"enabled": False}})
    with pytest.raises(ValidationError):
        RetrievalConfig.model_validate({"sparse": {"field_boosts": {"body": 1}}})
    with pytest.raises(ValidationError):
        RetrievalConfig.model_validate({"unknown": 1})
    cfg = RetrievalConfig.model_validate({"fusion": {"weights": {"dense": 0.5, "sparse": 2}}})
    assert cfg.fusion.weight(Route.SPARSE) == 2


# ---- trace truncation / highlighting ----------------------------------------------------


def test_trace_truncation_caps_size_and_keeps_head_of_lists() -> None:
    stages: dict[str, Any] = {
        "query": {"text": "q"},
        "routes": {"dense": {"hits": [{"chunk_id": f"c{i}", "rank": i} for i in range(400)]}},
        "fusion": {"candidates": [{"chunk_id": f"c{i}", "rrf": 0.1} for i in range(400)]},
        "results": [{"rank": 1, "chunk_id": "c0"}],
    }
    small, truncated = truncate_stages(stages, 64 * 1024)
    assert not truncated and small is stages

    doc, truncated = truncate_stages(stages, 4000)
    assert truncated and doc["truncated"] is True
    assert len(json.dumps(doc).encode()) <= 4000
    hits = doc["routes"]["dense"]["hits"]
    assert 0 < len(hits) < 400 and hits[0]["chunk_id"] == "c0"
    assert len(stages["routes"]["dense"]["hits"]) == 400  # input untouched

    tiny, _ = truncate_stages(stages, 10)
    assert set(tiny) == {"query", "truncated"}


def test_highlight_escapes_html_and_marks_terms() -> None:
    terms = query_terms("报销制度 HR-2024")
    assert {"报销", "制度"} <= set(terms)
    out = mark("<b>差旅报销</b> 见 HR-2024", ["报销", "HR-2024"])
    assert "<b>" not in out and "&lt;b&gt;" in out
    assert f"{PRE_TAG}报销{POST_TAG}" in out and f"{PRE_TAG}HR-2024{POST_TAG}" in out
    fragments = highlight(
        "前文" * 200 + "关键报销条款" + "后文" * 200, ["报销"], fragment_size=60, max_fragments=2
    )
    assert fragments and all(len(f) < 200 for f in fragments)
    assert any(f"{PRE_TAG}报销{POST_TAG}" in f for f in fragments)
