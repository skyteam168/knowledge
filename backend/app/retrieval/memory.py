"""In-process index backends with the same semantics as Qdrant / OpenSearch (tests, offline dev).

Searches interpret the rendered Qdrant filter / OpenSearch query DSL (the subset the retrieval
module emits), so tests exercise the exact filters sent to the real engines. Unsupported
clauses raise instead of being ignored: a silently dropped ACL clause must never pass a test.
"""

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.retrieval.backends import IndexBackendError, TextHit, VectorHit
from app.retrieval.highlight import highlight, query_terms
from app.retrieval.records import ChunkRecord, IndexedRef


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _comparable(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _in_range(value: Any, bounds: dict[str, Any]) -> bool:
    if value is None:
        return False
    v = _comparable(value)
    checks = {
        "gte": lambda b: v >= b,
        "gt": lambda b: v > b,
        "lte": lambda b: v <= b,
        "lt": lambda b: v < b,
    }
    for op, bound in bounds.items():
        if op not in checks:
            raise IndexBackendError(f"unsupported range operator {op}")
        if bound is not None and not checks[op](_comparable(bound)):
            return False
    return True


def qdrant_filter_matches(payload: dict[str, Any], flt: dict[str, Any]) -> bool:
    unknown = set(flt) - {"must", "must_not", "should"}
    if unknown:
        raise IndexBackendError(f"unsupported qdrant filter keys {unknown}")
    if not all(_qdrant_condition(payload, c) for c in flt.get("must", [])):
        return False
    if any(_qdrant_condition(payload, c) for c in flt.get("must_not", [])):
        return False
    should = flt.get("should")
    return not should or any(_qdrant_condition(payload, c) for c in should)


def _qdrant_condition(payload: dict[str, Any], cond: dict[str, Any]) -> bool:
    if {"must", "must_not", "should"} & set(cond):
        return qdrant_filter_matches(payload, cond)
    values = _as_list(payload.get(cond["key"]))
    if "match" in cond:
        match = cond["match"]
        if "value" in match:
            return match["value"] in values
        if "any" in match:
            return any(v in match["any"] for v in values)
        raise IndexBackendError(f"unsupported qdrant match {match}")
    if "range" in cond:
        return any(_in_range(v, cond["range"]) for v in values)
    raise IndexBackendError(f"unsupported qdrant condition {cond}")


def opensearch_clause_matches(doc: dict[str, Any], clause: dict[str, Any]) -> bool:
    (kind, spec), *rest = clause.items()
    if rest:
        raise IndexBackendError(f"one query type per clause expected: {clause}")
    if kind == "bool":
        return opensearch_bool_matches(doc, spec)
    if kind in ("term", "terms", "range"):
        ((field, arg),) = spec.items()
        values = _as_list(doc.get(field))
        if kind == "term":
            expected = arg["value"] if isinstance(arg, dict) else arg
            return expected in values
        if kind == "terms":
            return any(v in arg for v in values)
        return any(_in_range(v, arg) for v in values)
    raise IndexBackendError(f"unsupported opensearch filter clause {kind}")


def opensearch_bool_matches(doc: dict[str, Any], spec: dict[str, Any]) -> bool:
    return all(
        opensearch_clause_matches(doc, c) for c in _as_list(spec.get("filter", []))
    ) and not any(opensearch_clause_matches(doc, c) for c in _as_list(spec.get("must_not", [])))


class _MemoryChunkIndex:
    def __init__(self) -> None:
        # physical name -> chunk_id -> stored document (payload / source)
        self.indexes: dict[str, dict[str, dict[str, Any]]] = {}
        self.aliases: dict[str, str] = {}

    def _index(self, name: str) -> dict[str, dict[str, Any]]:
        index = self.indexes.get(name)
        if index is None:
            raise IndexBackendError(f"index {name} does not exist")
        return index

    def resolve(self, name_or_alias: str) -> dict[str, dict[str, Any]]:
        return self._index(self.aliases.get(name_or_alias, name_or_alias))

    async def exists(self, name: str) -> bool:
        return name in self.indexes

    async def drop(self, name: str) -> None:
        self.indexes.pop(name, None)
        self.aliases = {a: n for a, n in self.aliases.items() if n != name}

    async def get_alias(self, alias: str) -> str | None:
        return self.aliases.get(alias)

    async def switch_alias(self, alias: str, name: str) -> None:
        self._index(name)
        self.aliases[alias] = name

    async def delete_documents(self, name: str, document_ids: Sequence[str]) -> None:
        ids = set(document_ids)
        index = self._index(name)
        for cid in [c for c, d in index.items() if d["document_id"] in ids]:
            del index[cid]

    async def delete_stale_versions(self, name: str, document_id: str, keep_version: int) -> None:
        index = self._index(name)
        stale = [
            c
            for c, d in index.items()
            if d["document_id"] == document_id and d["doc_version"] != keep_version
        ]
        for cid in stale:
            del index[cid]

    async def delete_ids(self, name: str, chunk_ids: Sequence[str]) -> None:
        index = self._index(name)
        for cid in chunk_ids:
            index.pop(cid, None)

    async def set_acl(
        self, name: str, document_ids: Sequence[str], principals: Sequence[str]
    ) -> None:
        ids = set(document_ids)
        for doc in self._index(name).values():
            if doc["document_id"] in ids:
                doc["acl_read_principals"] = list(principals)

    async def scan(self, name: str, org_id: str, kb_id: str) -> dict[str, IndexedRef]:
        return {
            cid: IndexedRef(d["document_id"], d["doc_version"])
            for cid, d in self._index(name).items()
            if d["org_id"] == org_id and d["kb_id"] == kb_id
        }

    async def count(self, name: str, org_id: str | None = None, kb_id: str | None = None) -> int:
        return sum(
            1
            for d in self._index(name).values()
            if (org_id is None or d["org_id"] == org_id) and (kb_id is None or d["kb_id"] == kb_id)
        )


class MemoryVectorIndex(_MemoryChunkIndex):
    def __init__(self) -> None:
        super().__init__()
        self.dims: dict[str, int] = {}
        self.vectors: dict[str, dict[str, list[float]]] = {}

    async def ensure_collection(self, name: str, dim: int) -> None:
        if name in self.indexes:
            if self.dims[name] != dim:
                raise IndexBackendError(f"collection {name} has dim {self.dims[name]}")
            return
        self.indexes[name] = {}
        self.vectors[name] = {}
        self.dims[name] = dim

    async def drop(self, name: str) -> None:
        await super().drop(name)
        self.vectors.pop(name, None)
        self.dims.pop(name, None)

    async def upsert(
        self, name: str, records: Sequence[ChunkRecord], vectors: Sequence[list[float]]
    ) -> None:
        index = self._index(name)
        for record, vector in zip(records, vectors, strict=True):
            if len(vector) != self.dims[name]:
                raise IndexBackendError(f"vector dim {len(vector)} != {self.dims[name]}")
            index[record.chunk_id] = record.qdrant_payload()
            self.vectors[name][record.chunk_id] = vector

    async def search(
        self,
        name: str,
        vector: list[float],
        query_filter: dict[str, Any],
        limit: int,
        *,
        hnsw_ef: int | None = None,
    ) -> list[VectorHit]:
        physical = self.aliases.get(name, name)
        index = self._index(physical)
        if len(vector) != self.dims[physical]:
            raise IndexBackendError(f"query dim {len(vector)} != {self.dims[physical]}")
        qnorm = math.sqrt(sum(v * v for v in vector)) or 1.0
        hits: list[VectorHit] = []
        for cid, payload in index.items():
            if not qdrant_filter_matches(payload, query_filter):
                continue
            stored = self.vectors[physical][cid]
            snorm = math.sqrt(sum(v * v for v in stored)) or 1.0
            score = sum(a * b for a, b in zip(vector, stored, strict=True)) / (qnorm * snorm)
            hits.append(VectorHit(chunk_id=cid, score=score, payload=dict(payload)))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:limit]


class MemoryTextIndex(_MemoryChunkIndex):
    def __init__(self) -> None:
        super().__init__()
        self.template_installed = False
        self.analyzer_reloads: list[str] = []

    async def ensure_template(self) -> None:
        self.template_installed = True

    async def ensure_index(self, name: str) -> None:
        self.indexes.setdefault(name, {})

    async def upsert(self, name: str, records: Sequence[ChunkRecord]) -> None:
        index = self._index(name)
        for record in records:
            index[record.chunk_id] = record.opensearch_doc()

    async def refresh(self, name: str) -> None:
        self._index(name)

    async def reload_search_analyzers(self, name: str) -> None:
        self.analyzer_reloads.append(name)

    async def search(self, name: str, body: dict[str, Any]) -> list[TextHit]:
        """Term-overlap scoring stand-in for BM25 over the query DSL emitted by retrieval."""
        index = self.resolve(name)
        query = body["query"]["bool"]
        unknown = set(query) - {"filter", "must", "should", "must_not"}
        if unknown:
            raise IndexBackendError(f"unsupported bool keys {unknown}")
        multi = [c["multi_match"] for c in query.get("must", []) if "multi_match" in c]
        if len(multi) != len(query.get("must", [])):
            raise IndexBackendError("only multi_match is supported in bool.must")
        phrases = [c["match_phrase"] for c in query.get("should", []) if "match_phrase" in c]
        hl_fields = (body.get("highlight") or {}).get("fields", {})

        hits: list[TextHit] = []
        for cid, doc in index.items():
            if not opensearch_bool_matches(
                doc, {"filter": query.get("filter", []), "must_not": query.get("must_not", [])}
            ):
                continue
            score = 0.0
            terms: list[str] = []
            for mm in multi:
                terms = query_terms(mm["query"])
                for spec in mm["fields"]:
                    field, _, boost = spec.partition("^")
                    text = str(doc.get(field) or "").lower()
                    score += float(boost or 1) * sum(text.count(t) for t in terms)
            if multi and score == 0:
                continue
            for phrase in phrases:
                ((field, arg),) = phrase.items()
                if str(arg["query"]).lower() in str(doc.get(field) or "").lower():
                    score += float(arg.get("boost", 1))
            marks = {
                f: frags
                for f, opts in hl_fields.items()
                if (
                    frags := highlight(
                        str(doc.get(f) or ""),
                        terms,
                        fragment_size=int(opts.get("fragment_size", 160)),
                        max_fragments=int(opts.get("number_of_fragments", 2)) or 1,
                    )
                )
            }
            hits.append(TextHit(chunk_id=cid, score=score, source=dict(doc), highlight=marks))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[: int(body.get("size", 10))]
