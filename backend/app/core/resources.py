from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.cache import KeyValueCache, RedisCache
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.security import JwksTokenVerifier, TokenVerifier
from app.core.storage import MinioStorage, ObjectStorage
from app.llm import LLMGateway, build_llm_gateway
from app.llm.routing import RoutedChatClient
from app.retrieval.factory import build_search_backends
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.queue import DramatiqTaskQueue, TaskQueue
from app.services.models import attach_chat_routing
from app.services.usage import DbUsageRecorder, attach_usage_recorder


@dataclass
class AppResources:
    """Process-wide clients created at startup and closed on shutdown."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    cache: KeyValueCache
    http: httpx.AsyncClient
    token_verifier: TokenVerifier
    storage: ObjectStorage
    task_queue: TaskQueue
    llm: LLMGateway
    indexing: IndexingRuntime
    usage_recorder: DbUsageRecorder | None = None
    chat_router: RoutedChatClient | None = None

    @classmethod
    def create(cls, settings: Settings) -> "AppResources":
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        http = httpx.AsyncClient(timeout=settings.ready_check_timeout_seconds)
        llm = build_llm_gateway(settings)
        usage_recorder = attach_usage_recorder(llm, session_factory, settings)
        chat_router = attach_chat_routing(llm, session_factory, settings)
        cache = RedisCache.from_url(settings.redis_url)
        return cls(
            engine=engine,
            session_factory=session_factory,
            cache=cache,
            http=http,
            token_verifier=JwksTokenVerifier(settings, http),
            storage=MinioStorage(settings),
            task_queue=DramatiqTaskQueue(),
            llm=llm,
            indexing=IndexingRuntime(
                settings=settings,
                session_factory=session_factory,
                backends=build_search_backends(settings),
                gateway=llm,
                cache=cache,
            ),
            usage_recorder=usage_recorder,
            chat_router=chat_router,
        )

    async def close(self) -> None:
        await self.indexing.backends.aclose()
        if self.usage_recorder is not None:
            await self.usage_recorder.aclose()
        await self.llm.aclose()
        await self.http.aclose()
        await self.cache.close()
        await self.engine.dispose()
