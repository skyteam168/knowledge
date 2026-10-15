"""Retrieval caches on the shared key-value store.

- Query embeddings: keyed by model + dim + endpoint + instruction + text.
- Fused candidates: the key carries org_id and a hash of the caller's principals, so a cached
  ranking is only ever served to callers with the same permission scope. Cached rankings
  are still re-checked against PG (hydration) before anything is returned, so revocations
  apply immediately; grants apply immediately because ACL refreshes bump the org's
  generation, which is part of every key.
"""

import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

from app.core.cache import KeyValueCache
from app.llm import EmbeddingSpec

logger = logging.getLogger(__name__)

EMBEDDING_PREFIX = "retrieval:emb"
RESULT_PREFIX = "retrieval:res"
RESULT_GENERATION_PREFIX = "retrieval:res-gen"


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def principals_hash(principals: Iterable[str], *, bypass_acl: bool = False) -> str:
    tokens = sorted(set(principals))
    return _sha(json.dumps({"p": tokens, "bypass": bypass_acl}, separators=(",", ":")))


class EmbeddingCache:
    def __init__(self, store: KeyValueCache) -> None:
        self.store = store

    @staticmethod
    def key(spec: EmbeddingSpec, text: str) -> str:
        return f"{EMBEDDING_PREFIX}:{_sha(f'{spec.model}|{spec.dim}|{spec.base_url}|{text}')}"

    async def get(self, spec: EmbeddingSpec, text: str) -> list[float] | None:
        try:
            raw = await self.store.get(self.key(spec, text))
        except Exception:
            logger.warning("embedding_cache_unavailable", exc_info=True)
            return None
        if raw is None:
            return None
        vector = json.loads(raw)
        return vector if isinstance(vector, list) and len(vector) == spec.dim else None

    async def set(self, spec: EmbeddingSpec, text: str, vector: list[float], ttl: int) -> None:
        if ttl <= 0:
            return
        try:
            await self.store.set(self.key(spec, text), json.dumps(vector), ttl)
        except Exception:
            logger.warning("embedding_cache_unavailable", exc_info=True)


class ResultCache:
    def __init__(self, store: KeyValueCache) -> None:
        self.store = store

    @staticmethod
    def key(org_id: str, scope_hash: str, request: dict[str, Any], generation: str = "0") -> str:
        body = _sha(json.dumps(request, sort_keys=True, ensure_ascii=False, default=str))
        return f"{RESULT_PREFIX}:{org_id}:g{generation}:{scope_hash}:{body}"

    async def generation(self, org_id: str) -> str | None:
        """None when the store is unreachable (callers then skip the cache)."""
        try:
            return await self.store.get(f"{RESULT_GENERATION_PREFIX}:{org_id}") or "0"
        except Exception:
            logger.warning("result_cache_unavailable", exc_info=True)
            return None

    async def invalidate_org(self, org_id: str) -> None:
        """Orphan every cached ranking of the org (they expire by TTL)."""
        try:
            await self.store.incr(f"{RESULT_GENERATION_PREFIX}:{org_id}")
        except Exception:
            logger.warning("result_cache_invalidate_failed", exc_info=True)

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self.store.get(key)
        except Exception:
            logger.warning("result_cache_unavailable", exc_info=True)
            return None
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        if ttl <= 0:
            return
        try:
            await self.store.set(key, json.dumps(value, ensure_ascii=False), ttl)
        except Exception:
            logger.warning("result_cache_unavailable", exc_info=True)
