import os

os.environ["APP_ENV"] = "test"

from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.cache import MemoryCache
from app.core.config import Settings, get_settings
from app.core.db import create_session_factory
from app.core.exceptions import UnauthorizedError
from app.core.resources import AppResources
from app.core.security import TokenClaims
from app.core.storage import MemoryStorage
from app.llm import LLMGateway, build_mock_gateway
from app.main import create_app
from app.models import Base
from app.retrieval.backends import SearchBackends
from app.retrieval.memory import MemoryTextIndex, MemoryVectorIndex
from app.services.authz import AuthzCache
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.queue import RecordingTaskQueue

ACL_MODULES = {
    "test_acl_regression",
    "test_acl_service",
    "test_search_acl",
    "test_principal_resolver",
}
ACL_TESTS = {
    "test_restricted_scope_without_readable_kb_refuses",
    "test_acl_recheck_drops_evidence_the_user_cannot_read",
    "test_chat_requires_permission",
    "test_profiles_require_admin_permission",
    "test_acl_change_updates_payload_without_reembedding",
    "test_concurrent_acl_change_during_indexing_is_not_lost",
    "test_restricted_kb_is_invisible_without_acl",
    "test_document_acl_override",
    "test_forbidden_without_permission",
    "test_role_permission_change_takes_effect_immediately",
    "test_run_respects_creator_acl",
    "test_analytics_requires_permission",
    "test_evaluation_requires_admin_retrieval",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        mod = getattr(item, "module", None)
        module = mod.__name__.rsplit(".", 1)[-1] if mod else ""
        if module in ACL_MODULES or getattr(item, "originalname", None) in ACL_TESTS:
            item.add_marker(pytest.mark.acl)


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---- database / cache -------------------------------------------------------


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    # pysqlite's implicit transactions break SAVEPOINT semantics; take over BEGIN ourselves.
    # https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
    @event.listens_for(eng.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, _: Any) -> None:
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(eng.sync_engine, "begin")
    def _on_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN")

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with create_session_factory(engine)() as s:
        yield s


@pytest.fixture
def memory_cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture
def authz_cache(memory_cache: MemoryCache) -> AuthzCache:
    return AuthzCache(memory_cache, ttl_seconds=600)


# ---- authenticated API ------------------------------------------------------


def make_claims(
    sub: str,
    username: str,
    roles: tuple[str, ...] = (),
    groups: tuple[str, ...] = (),
    org_code: str = "org-demo",
) -> TokenClaims:
    return TokenClaims(
        sub=sub,
        username=username,
        org_code=org_code,
        email=f"{username}@example.com",
        name=username.title(),
        groups=groups,
        roles=roles,
    )


TEST_IDENTITIES: dict[str, TokenClaims] = {
    "alice-token": make_claims(
        "sub-alice", "alice", ("kb_admin", "platform_admin"), ("engineering",)
    ),
    "bob-token": make_claims("sub-bob", "bob", ("kb_editor",), ("engineering",)),
    "carol-token": make_claims("sub-carol", "carol", ("kb_viewer",), ("sales",)),
    "other-org-token": make_claims("sub-dave", "dave", ("kb_admin",), (), org_code="org-other"),
}


class FakeTokenVerifier:
    def __init__(self, identities: dict[str, TokenClaims]) -> None:
        self.identities = identities

    async def verify(self, token: str) -> TokenClaims:
        claims = self.identities.get(token)
        if claims is None:
            raise UnauthorizedError("Invalid token", code="INVALID_TOKEN")
        return claims


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def task_queue() -> RecordingTaskQueue:
    return RecordingTaskQueue()


@pytest.fixture
def search_backends() -> SearchBackends:
    return SearchBackends(vector=MemoryVectorIndex(), text=MemoryTextIndex())


@pytest.fixture
def llm_gateway(settings: Settings) -> LLMGateway:
    return build_mock_gateway(settings.model_copy(update={"embedding_dim": 16}))


@pytest.fixture
def indexing(
    settings: Settings,
    engine: AsyncEngine,
    search_backends: SearchBackends,
    llm_gateway: LLMGateway,
    memory_cache: MemoryCache,
) -> IndexingRuntime:
    return IndexingRuntime(
        settings=settings,
        session_factory=create_session_factory(engine),
        backends=search_backends,
        gateway=llm_gateway,
        cache=memory_cache,
    )


@pytest.fixture
async def api(
    settings: Settings,
    engine: AsyncEngine,
    memory_cache: MemoryCache,
    storage: MemoryStorage,
    task_queue: RecordingTaskQueue,
    llm_gateway: LLMGateway,
    indexing: IndexingRuntime,
) -> AsyncIterator[httpx.AsyncClient]:
    resources = AppResources(
        engine=engine,
        session_factory=create_session_factory(engine),
        cache=memory_cache,
        http=httpx.AsyncClient(),
        token_verifier=FakeTokenVerifier(dict(TEST_IDENTITIES)),
        storage=storage,
        task_queue=task_queue,
        llm=llm_gateway,
        indexing=indexing,
    )
    application = create_app(settings, resources_factory=lambda _: resources)
    application.state.resources = resources
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await resources.http.aclose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
