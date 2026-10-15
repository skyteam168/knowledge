from app.core.config import Settings
from app.retrieval.backends import SearchBackends
from app.retrieval.opensearch import OpenSearchIndex
from app.retrieval.qdrant import QdrantIndex


def build_search_backends(settings: Settings) -> SearchBackends:
    return SearchBackends(
        vector=QdrantIndex(
            settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout_seconds,
            batch_size=settings.index_write_batch_size,
        ),
        text=OpenSearchIndex(
            settings.opensearch_url,
            alias=settings.index_alias,
            user=settings.opensearch_user,
            password=settings.opensearch_password,
            timeout=settings.opensearch_timeout_seconds,
            shards=settings.opensearch_shards,
            replicas=settings.opensearch_replicas,
            synonyms_path=settings.opensearch_synonyms_path,
            batch_size=settings.index_write_batch_size,
        ),
    )
