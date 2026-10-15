from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.cache import KeyValueCache, RedisCache
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.llm import LLMGateway, build_llm_gateway
from app.retrieval.backends import SearchBackends
from app.retrieval.cache import ResultCache
from app.retrieval.factory import build_search_backends
from app.services.indexing.consistency import ConsistencyChecker
from app.services.indexing.generations import GenerationRegistry
from app.services.indexing.handlers import IndexEventHandlers
from app.services.indexing.indexer import DocumentIndexer
from app.services.indexing.ko_indexer import KnowledgeObjectIndexer
from app.services.indexing.outbox import OutboxProcessor
from app.services.indexing.rebuild import IndexRebuilder
from app.services.usage import DbUsageRecorder, attach_usage_recorder


@dataclass
class IndexingRuntime:
    """Wires the indexing components; one per worker / dispatcher / CLI process."""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    backends: SearchBackends
    gateway: LLMGateway
    engine: AsyncEngine | None = None
    cache: KeyValueCache | None = None
    owns_cache: bool = False
    # Only set when the runtime owns its gateway (worker / dispatcher / CLI processes).
    usage_recorder: DbUsageRecorder | None = None
    registry: GenerationRegistry = field(init=False)
    indexer: DocumentIndexer = field(init=False)
    ko_indexer: KnowledgeObjectIndexer = field(init=False)
    handlers: IndexEventHandlers = field(init=False)
    processor: OutboxProcessor = field(init=False)
    consistency: ConsistencyChecker = field(init=False)
    rebuilder: IndexRebuilder = field(init=False)

    def __post_init__(self) -> None:
        sf, backends = self.session_factory, self.backends
        self.registry = GenerationRegistry(
            sf, backends, self.settings, self.gateway.default_embedding
        )
        self.indexer = DocumentIndexer(sf, backends, self.gateway, self.registry)
        self.ko_indexer = KnowledgeObjectIndexer(sf, self.indexer)
        self.handlers = IndexEventHandlers(
            sf,
            self.indexer,
            self.ko_indexer,
            ResultCache(self.cache) if self.cache is not None else None,
        )
        self.processor = OutboxProcessor(
            sf, self.handlers.mapping(), self.settings, on_dead=self.handlers.on_dead
        )
        self.consistency = ConsistencyChecker(
            sf, backends, self.registry, self.indexer, self.ko_indexer
        )
        self.rebuilder = IndexRebuilder(sf, backends, self.registry, self.indexer, self.ko_indexer)

    @classmethod
    def create(cls, settings: Settings) -> "IndexingRuntime":
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        gateway = build_llm_gateway(settings)
        return cls(
            settings=settings,
            session_factory=session_factory,
            backends=build_search_backends(settings),
            gateway=gateway,
            engine=engine,
            cache=RedisCache.from_url(settings.redis_url),
            owns_cache=True,
            usage_recorder=attach_usage_recorder(gateway, session_factory, settings),
        )

    async def aclose(self) -> None:
        await self.backends.aclose()
        if self.usage_recorder is not None:
            await self.usage_recorder.aclose()
        await self.gateway.aclose()
        if self.cache is not None and self.owns_cache:
            await self.cache.close()
        if self.engine is not None:
            await self.engine.dispose()
