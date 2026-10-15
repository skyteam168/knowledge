"""OpenSearch full-text index (IK analyzers + hot-reloadable synonyms) over the REST API."""

import json
from collections.abc import Sequence
from typing import Any

import httpx

from app.retrieval.backends import IndexBackendError, TextHit
from app.retrieval.records import ChunkRecord, IndexedRef

SCAN_PAGE = 1000
TERMS_BATCH = 1000

INDEX_ANALYZER = "ekb_index"
SEARCH_ANALYZER = "ekb_search"


def _text(with_raw: bool = False) -> dict[str, Any]:
    field: dict[str, Any] = {
        "type": "text",
        "analyzer": INDEX_ANALYZER,
        "search_analyzer": SEARCH_ANALYZER,
    }
    if with_raw:
        field["fields"] = {"raw": {"type": "keyword", "ignore_above": 1024}}
    return field


def mapping_properties() -> dict[str, Any]:
    keyword = {"type": "keyword"}
    return {
        "chunk_id": keyword,
        "org_id": keyword,
        "kb_id": keyword,
        "document_id": keyword,
        "doc_version": {"type": "integer"},
        "parent_id": keyword,
        "title": _text(with_raw=True),
        "heading_path": _text(with_raw=True),
        "content": _text(),
        "chunk_type": keyword,
        "tags": keyword,
        "created_at": {"type": "date"},
        "acl_read_principals": keyword,
        "is_ko": {"type": "boolean"},
        "page_start": {"type": "integer"},
        "page_end": {"type": "integer"},
        "doc_type": keyword,
    }


def index_template(alias: str, *, shards: int, replicas: int, synonyms_path: str) -> dict[str, Any]:
    return {
        "index_patterns": [f"{alias}_v*"],
        "priority": 100,
        "template": {
            "settings": {
                "number_of_shards": shards,
                "number_of_replicas": replicas,
                "analysis": {
                    "filter": {
                        # updateable: reloadable via _refresh_search_analyzers without
                        # reindexing; such filters may only appear in search analyzers.
                        "ekb_synonym": {
                            "type": "synonym_graph",
                            "synonyms_path": synonyms_path,
                            "updateable": True,
                            "lenient": True,
                        }
                    },
                    "analyzer": {
                        INDEX_ANALYZER: {
                            "type": "custom",
                            "tokenizer": "ik_max_word",
                            "filter": ["lowercase"],
                        },
                        SEARCH_ANALYZER: {
                            "type": "custom",
                            "tokenizer": "ik_smart",
                            "filter": ["lowercase", "ekb_synonym"],
                        },
                    },
                },
            },
            "mappings": {"dynamic": "strict", "properties": mapping_properties()},
        },
    }


def _kb_query(org_id: str | None, kb_id: str | None) -> dict[str, Any]:
    filters: list[dict[str, Any]] = []
    if org_id is not None:
        filters.append({"term": {"org_id": org_id}})
    if kb_id is not None:
        filters.append({"term": {"kb_id": kb_id}})
    return {"bool": {"filter": filters}}


def _batches(values: Sequence[str], size: int = TERMS_BATCH) -> list[list[str]]:
    items = list(values)
    return [items[i : i + size] for i in range(0, len(items), size)]


class OpenSearchIndex:
    def __init__(
        self,
        base_url: str,
        *,
        alias: str,
        user: str | None = None,
        password: str | None = None,
        timeout: float = 60.0,
        shards: int = 1,
        replicas: int = 0,
        synonyms_path: str = "analysis/synonyms.txt",
        http: httpx.AsyncClient | None = None,
        batch_size: int = 500,
    ) -> None:
        auth = (user, password) if user and password else None
        self.http = http or httpx.AsyncClient(base_url=base_url, auth=auth, timeout=timeout)
        self.alias = alias
        self.shards = shards
        self.replicas = replicas
        self.synonyms_path = synonyms_path
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
        content: bytes | None = None,
    ) -> Any:
        try:
            if content is not None:
                resp = await self.http.request(
                    method,
                    path,
                    content=content,
                    params=params,
                    headers={"Content-Type": "application/x-ndjson"},
                )
            else:
                resp = await self.http.request(method, path, json=body, params=params)
        except httpx.HTTPError as exc:
            raise IndexBackendError(f"opensearch {method} {path}: {exc}") from exc
        if resp.status_code in allow:
            return None
        if resp.status_code >= 400:
            raise IndexBackendError(
                f"opensearch {method} {path}: {resp.status_code} {resp.text[:500]}"
            )
        return resp.json() if resp.content else None

    # ---- indexes / aliases ----

    async def ensure_template(self) -> None:
        body = index_template(
            self.alias,
            shards=self.shards,
            replicas=self.replicas,
            synonyms_path=self.synonyms_path,
        )
        await self._call("PUT", f"/_index_template/{self.alias}_template", body)

    async def exists(self, name: str) -> bool:
        try:
            resp = await self.http.head(f"/{name}")
        except httpx.HTTPError as exc:
            raise IndexBackendError(f"opensearch HEAD /{name}: {exc}") from exc
        return resp.status_code == 200

    async def ensure_index(self, name: str) -> None:
        if await self.exists(name):
            # Additive upgrade of indexes created by an older template (new fields only).
            await self._call("PUT", f"/{name}/_mapping", {"properties": mapping_properties()})
            return
        result = await self._call("PUT", f"/{name}", {}, allow=(400,))
        if result is None and not await self.exists(name):
            raise IndexBackendError(f"opensearch: failed to create index {name}")

    async def drop(self, name: str) -> None:
        await self._call("DELETE", f"/{name}", allow=(404,))

    async def get_alias(self, alias: str) -> str | None:
        result = await self._call("GET", f"/_alias/{alias}", allow=(404,))
        if not result:
            return None
        return str(next(iter(result)))

    async def switch_alias(self, alias: str, name: str) -> None:
        actions: list[dict[str, Any]] = []
        current = await self._call("GET", f"/_alias/{alias}", allow=(404,))
        for index in current or {}:
            if index != name:
                actions.append({"remove": {"index": index, "alias": alias}})
        actions.append({"add": {"index": name, "alias": alias}})
        await self._call("POST", "/_aliases", {"actions": actions})

    async def refresh(self, name: str) -> None:
        await self._call("POST", f"/{name}/_refresh")

    async def reload_search_analyzers(self, name: str) -> None:
        await self._call("POST", f"/_plugins/_refresh_search_analyzers/{name}")

    # ---- writes ----

    async def _bulk(self, lines: list[dict[str, Any]], refresh: bool = False) -> None:
        payload = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
        result = await self._call(
            "POST",
            "/_bulk",
            content=payload.encode("utf-8"),
            params={"refresh": "true"} if refresh else None,
        )
        if result and result.get("errors"):
            for item in result.get("items", []):
                op = next(iter(item.values()))
                error = op.get("error")
                if error and not (op.get("status") == 404 and "delete" in item):
                    raise IndexBackendError(f"opensearch bulk: {json.dumps(error)[:500]}")

    async def upsert(self, name: str, records: Sequence[ChunkRecord]) -> None:
        for i in range(0, len(records), self.batch_size):
            lines: list[dict[str, Any]] = []
            for r in records[i : i + self.batch_size]:
                lines.append({"index": {"_index": name, "_id": r.chunk_id}})
                lines.append(r.opensearch_doc())
            await self._bulk(lines)

    async def _by_query(self, name: str, action: str, body: dict[str, Any]) -> None:
        result = await self._call("POST", f"/{name}/{action}", body, params={"refresh": "true"})
        failures = (result or {}).get("failures") or []
        conflicts = (result or {}).get("version_conflicts") or 0
        if failures or conflicts:
            raise IndexBackendError(
                f"opensearch {action}: {conflicts} conflicts, failures={json.dumps(failures)[:500]}"
            )

    async def delete_documents(self, name: str, document_ids: Sequence[str]) -> None:
        for batch in _batches(document_ids):
            await self._by_query(
                name, "_delete_by_query", {"query": {"terms": {"document_id": batch}}}
            )

    async def delete_stale_versions(self, name: str, document_id: str, keep_version: int) -> None:
        await self._by_query(
            name,
            "_delete_by_query",
            {
                "query": {
                    "bool": {
                        "filter": [{"term": {"document_id": document_id}}],
                        "must_not": [{"term": {"doc_version": keep_version}}],
                    }
                }
            },
        )

    async def delete_ids(self, name: str, chunk_ids: Sequence[str]) -> None:
        for batch in _batches(chunk_ids):
            await self._bulk([{"delete": {"_index": name, "_id": cid}} for cid in batch], True)

    async def set_acl(
        self, name: str, document_ids: Sequence[str], principals: Sequence[str]
    ) -> None:
        for batch in _batches(document_ids):
            await self._by_query(
                name,
                "_update_by_query",
                {
                    "query": {"terms": {"document_id": batch}},
                    "script": {
                        "lang": "painless",
                        "source": "ctx._source.acl_read_principals = params.principals",
                        "params": {"principals": list(principals)},
                    },
                },
            )

    # ---- reads ----

    async def search(self, name: str, body: dict[str, Any]) -> list[TextHit]:
        result = await self._call("POST", f"/{name}/_search", body)
        return [
            TextHit(
                chunk_id=str(hit["_id"]),
                score=float(hit.get("_score") or 0.0),
                source=hit.get("_source") or {},
                highlight={k: list(v) for k, v in (hit.get("highlight") or {}).items()},
            )
            for hit in result["hits"]["hits"]
        ]

    async def scan(self, name: str, org_id: str, kb_id: str) -> dict[str, IndexedRef]:
        found: dict[str, IndexedRef] = {}
        search_after: list[Any] | None = None
        while True:
            body: dict[str, Any] = {
                "size": SCAN_PAGE,
                "_source": ["document_id", "doc_version"],
                "query": _kb_query(org_id, kb_id),
                "sort": [{"chunk_id": "asc"}],
                "track_total_hits": False,
            }
            if search_after is not None:
                body["search_after"] = search_after
            result = await self._call("POST", f"/{name}/_search", body)
            hits = result["hits"]["hits"]
            for hit in hits:
                src = hit.get("_source") or {}
                found[hit["_id"]] = IndexedRef(
                    document_id=str(src.get("document_id", "")),
                    doc_version=int(src.get("doc_version", 0)),
                )
            if len(hits) < SCAN_PAGE:
                return found
            search_after = hits[-1]["sort"]

    async def count(self, name: str, org_id: str | None = None, kb_id: str | None = None) -> int:
        result = await self._call("POST", f"/{name}/_count", {"query": _kb_query(org_id, kb_id)})
        return int(result["count"])
