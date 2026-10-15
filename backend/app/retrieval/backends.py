from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.retrieval.records import ChunkRecord, IndexedRef


class IndexBackendError(Exception):
    pass


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class TextHit:
    chunk_id: str
    score: float
    source: dict[str, Any]
    # field -> highlighted fragments (HTML-escaped text with <em> marks)
    highlight: dict[str, list[str]] = field(default_factory=dict)


class ChunkIndex(Protocol):
    """Operations shared by the vector and the full-text index. Names are physical names."""

    async def exists(self, name: str) -> bool: ...

    async def drop(self, name: str) -> None: ...

    async def get_alias(self, alias: str) -> str | None: ...

    async def switch_alias(self, alias: str, name: str) -> None:
        """Atomically point `alias` at `name` (and only at it)."""
        ...

    async def delete_documents(self, name: str, document_ids: Sequence[str]) -> None: ...

    async def delete_stale_versions(self, name: str, document_id: str, keep_version: int) -> None:
        """Delete chunks of `document_id` whose doc_version differs from `keep_version`."""
        ...

    async def delete_ids(self, name: str, chunk_ids: Sequence[str]) -> None: ...

    async def set_acl(
        self, name: str, document_ids: Sequence[str], principals: Sequence[str]
    ) -> None: ...

    async def scan(self, name: str, org_id: str, kb_id: str) -> dict[str, IndexedRef]: ...

    async def count(self, name: str, org_id: str | None = None, kb_id: str | None = None) -> int:
        """Exact count; without org_id across all tenants (operations only)."""
        ...


class VectorIndex(ChunkIndex, Protocol):
    async def ensure_collection(self, name: str, dim: int) -> None: ...

    async def upsert(
        self, name: str, records: Sequence[ChunkRecord], vectors: Sequence[list[float]]
    ) -> None: ...

    async def search(
        self,
        name: str,
        vector: list[float],
        query_filter: dict[str, Any],
        limit: int,
        *,
        hnsw_ef: int | None = None,
    ) -> list[VectorHit]:
        """Nearest neighbours under a Qdrant filter (always carries org_id)."""
        ...


class TextIndex(ChunkIndex, Protocol):
    async def ensure_template(self) -> None: ...

    async def ensure_index(self, name: str) -> None: ...

    async def upsert(self, name: str, records: Sequence[ChunkRecord]) -> None: ...

    async def refresh(self, name: str) -> None: ...

    async def reload_search_analyzers(self, name: str) -> None: ...

    async def search(self, name: str, body: dict[str, Any]) -> list[TextHit]:
        """Run an OpenSearch _search body (query.bool.filter always carries org_id)."""
        ...


@dataclass
class SearchBackends:
    vector: VectorIndex
    text: TextIndex

    async def aclose(self) -> None:
        for backend in (self.vector, self.text):
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()
