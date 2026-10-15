"""Qdrant vector index over the REST API."""

from collections.abc import Sequence
from typing import Any

import httpx

from app.retrieval.backends import IndexBackendError, VectorHit
from app.retrieval.records import ChunkRecord, IndexedRef, chunk_id_from_point, point_id

SCROLL_PAGE = 1000
DELETE_BATCH = 1000

# (field, schema). org_id is the tenant key: Qdrant co-locates and indexes per tenant.
PAYLOAD_INDEXES: list[tuple[str, dict[str, Any] | str]] = [
    ("org_id", {"type": "keyword", "is_tenant": True}),
    ("kb_id", {"type": "keyword"}),
    ("acl_read_principals", {"type": "keyword"}),
    ("document_id", {"type": "keyword"}),
    ("doc_version", "integer"),
    ("tags", {"type": "keyword"}),
    ("chunk_type", {"type": "keyword"}),
    ("is_ko", "bool"),
    ("created_at", "datetime"),
    ("doc_type", {"type": "keyword"}),
]


def _match(key: str, values: Sequence[str]) -> dict[str, Any]:
    return {"key": key, "match": {"any": list(values)}}


def _kb_filter(org_id: str | None, kb_id: str | None) -> dict[str, Any]:
    must: list[dict[str, Any]] = []
    if org_id is not None:
        must.append({"key": "org_id", "match": {"value": org_id}})
    if kb_id is not None:
        must.append({"key": "kb_id", "match": {"value": kb_id}})
    return {"must": must}


class QdrantIndex:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
        batch_size: int = 128,
    ) -> None:
        headers = {"api-key": api_key} if api_key else {}
        self.http = http or httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)
        self.batch_size = batch_size

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        params: dict[str, Any] | None = None,
        allow: Sequence[int] = (),
    ) -> Any:
        try:
            resp = await self.http.request(method, path, json=body, params=params)
        except httpx.HTTPError as exc:
            raise IndexBackendError(f"qdrant {method} {path}: {exc}") from exc
        if resp.status_code in allow:
            return None
        if resp.status_code >= 400:
            raise IndexBackendError(f"qdrant {method} {path}: {resp.status_code} {resp.text[:500]}")
        return resp.json().get("result")

    # ---- collections / aliases ----

    async def exists(self, name: str) -> bool:
        result = await self._call("GET", f"/collections/{name}/exists")
        return bool(result and result.get("exists"))

    async def ensure_collection(self, name: str, dim: int) -> None:
        if await self.exists(name):
            info = await self._call("GET", f"/collections/{name}")
            size = info["config"]["params"]["vectors"]["size"]
            if size != dim:
                raise IndexBackendError(f"qdrant collection {name} has dim {size}, expected {dim}")
        else:
            await self._call(
                "PUT",
                f"/collections/{name}",
                {
                    "vectors": {"size": dim, "distance": "Cosine"},
                    "hnsw_config": {"payload_m": 16},
                    "on_disk_payload": True,
                },
                allow=(409,),
            )
        for field, schema in PAYLOAD_INDEXES:
            await self._call(
                "PUT",
                f"/collections/{name}/index",
                {"field_name": field, "field_schema": schema},
                params={"wait": "true"},
            )

    async def drop(self, name: str) -> None:
        await self._call("DELETE", f"/collections/{name}", allow=(404,))

    async def get_alias(self, alias: str) -> str | None:
        result = await self._call("GET", "/aliases")
        for item in (result or {}).get("aliases", []):
            if item["alias_name"] == alias:
                return str(item["collection_name"])
        return None

    async def switch_alias(self, alias: str, name: str) -> None:
        actions: list[dict[str, Any]] = []
        if await self.get_alias(alias) is not None:
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"collection_name": name, "alias_name": alias}})
        await self._call("POST", "/collections/aliases", {"actions": actions})

    # ---- writes ----

    async def upsert(
        self, name: str, records: Sequence[ChunkRecord], vectors: Sequence[list[float]]
    ) -> None:
        if len(records) != len(vectors):
            raise ValueError("records and vectors differ in length")
        for i in range(0, len(records), self.batch_size):
            points = [
                {"id": point_id(r.chunk_id), "vector": v, "payload": r.qdrant_payload()}
                for r, v in zip(
                    records[i : i + self.batch_size], vectors[i : i + self.batch_size], strict=True
                )
            ]
            await self._call(
                "PUT", f"/collections/{name}/points", {"points": points}, params={"wait": "true"}
            )

    async def _delete(self, name: str, selector: dict[str, Any]) -> None:
        await self._call(
            "POST", f"/collections/{name}/points/delete", selector, params={"wait": "true"}
        )

    async def delete_documents(self, name: str, document_ids: Sequence[str]) -> None:
        if document_ids:
            await self._delete(name, {"filter": {"must": [_match("document_id", document_ids)]}})

    async def delete_stale_versions(self, name: str, document_id: str, keep_version: int) -> None:
        await self._delete(
            name,
            {
                "filter": {
                    "must": [{"key": "document_id", "match": {"value": document_id}}],
                    "must_not": [{"key": "doc_version", "match": {"value": keep_version}}],
                }
            },
        )

    async def delete_ids(self, name: str, chunk_ids: Sequence[str]) -> None:
        ids = list(chunk_ids)
        for i in range(0, len(ids), DELETE_BATCH):
            await self._delete(name, {"points": [point_id(c) for c in ids[i : i + DELETE_BATCH]]})

    async def set_acl(
        self, name: str, document_ids: Sequence[str], principals: Sequence[str]
    ) -> None:
        if not document_ids:
            return
        await self._call(
            "POST",
            f"/collections/{name}/points/payload",
            {
                "payload": {"acl_read_principals": list(principals)},
                "filter": {"must": [_match("document_id", document_ids)]},
            },
            params={"wait": "true"},
        )

    # ---- reads ----

    async def search(
        self,
        name: str,
        vector: list[float],
        query_filter: dict[str, Any],
        limit: int,
        *,
        hnsw_ef: int | None = None,
    ) -> list[VectorHit]:
        body: dict[str, Any] = {
            "vector": vector,
            "filter": query_filter,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if hnsw_ef:
            body["params"] = {"hnsw_ef": hnsw_ef}
        result = await self._call("POST", f"/collections/{name}/points/search", body)
        return [
            VectorHit(
                chunk_id=chunk_id_from_point(p["id"]),
                score=float(p["score"]),
                payload=p.get("payload") or {},
            )
            for p in result or []
        ]

    async def scan(self, name: str, org_id: str, kb_id: str) -> dict[str, IndexedRef]:
        found: dict[str, IndexedRef] = {}
        offset: Any = None
        while True:
            body: dict[str, Any] = {
                "filter": _kb_filter(org_id, kb_id),
                "limit": SCROLL_PAGE,
                "with_payload": ["document_id", "doc_version"],
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            result = await self._call("POST", f"/collections/{name}/points/scroll", body)
            for point in result.get("points", []):
                payload = point.get("payload") or {}
                found[chunk_id_from_point(point["id"])] = IndexedRef(
                    document_id=str(payload.get("document_id", "")),
                    doc_version=int(payload.get("doc_version", 0)),
                )
            offset = result.get("next_page_offset")
            if offset is None:
                return found

    async def count(self, name: str, org_id: str | None = None, kb_id: str | None = None) -> int:
        result = await self._call(
            "POST",
            f"/collections/{name}/points/count",
            {"filter": _kb_filter(org_id, kb_id), "exact": True},
        )
        return int(result["count"])
