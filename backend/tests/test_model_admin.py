"""Model admin: providers, model sync and checks, and runtime switching of the chat model."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.resources import AppResources
from app.llm import ChatMessage, ChatResult, LLMGateway
from app.llm.mock import MockChatClient
from app.llm.routing import ChatRoute, ChatTarget, RoutedChatClient
from app.main import create_app
from app.models import AuditLog, LlmModel, LlmProvider
from app.services.indexing.runtime import IndexingRuntime
from app.services.models import attach_chat_routing, import_env_config
from app.services.models import service as service_module
from app.services.models.checker import ModelChecker, guess_kind
from app.services.models.runtime import decrypt_api_key
from tests.conftest import TEST_IDENTITIES, FakeTokenVerifier, auth

ALICE, BOB, DAVE = auth("alice-token"), auth("bob-token"), auth("other-org-token")
API_KEY = "sk-test-1234567890abcd"
BASE = "http://provider/v1"
LISTED = ["chat-a", "chat-b", "chat-bad", "text-embedding-x"]


def sse(*texts: str) -> httpx.Response:
    events = [{"choices": [{"index": 0, "delta": {"content": t}}]} for t in texts]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


class FakeProvider:
    """OpenAI-compatible endpoints; only requests with API_KEY are served."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {API_KEY}":
            return httpx.Response(401, json={"error": "bad key"})
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.requests.append((path, body))
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": n} for n in LISTED]})
        if path == "/v1/chat/completions":
            if body["model"] == "chat-bad":
                return httpx.Response(404, json={"error": {"message": "Model not exist."}})
            return sse("O", "K")
        if path == "/v1/embeddings":
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 4}]})
        if path == "/api/v1/reranks":
            return httpx.Response(
                200, json={"results": [{"index": 0, "relevance_score": 0.9}], "usage": {}}
            )
        return httpx.Response(404, json={"error": path})


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    fake = FakeProvider()
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(
        service_module, "ModelChecker", lambda settings: ModelChecker(settings, transport)
    )
    return fake


@pytest.fixture
def chat_router(
    settings: Settings, engine: AsyncEngine, llm_gateway: LLMGateway
) -> RoutedChatClient:
    routed = attach_chat_routing(
        llm_gateway,
        create_session_factory(engine),
        settings.model_copy(update={"llm_route_refresh_seconds": 3600}),
        factory=lambda route: MockChatClient(route.primary.model),
    )
    assert routed is not None
    return routed


@pytest.fixture
async def admin_api(
    settings: Settings,
    engine: AsyncEngine,
    memory_cache: Any,
    storage: Any,
    task_queue: Any,
    llm_gateway: LLMGateway,
    indexing: IndexingRuntime,
    chat_router: RoutedChatClient,
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
        chat_router=chat_router,
    )
    application = create_app(settings, resources_factory=lambda _: resources)
    application.state.resources = resources
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await resources.http.aclose()


async def served_model(gateway: LLMGateway) -> str:
    text = "".join([t async for t in gateway.stream([ChatMessage(role="user", content="hi")])])
    assert text
    return gateway.chat.model


async def setup_provider(api: httpx.AsyncClient) -> dict[str, str]:
    resp = await api.post(
        "/api/v1/admin/models/providers",
        headers=ALICE,
        json={"name": "阿里云百炼", "base_url": BASE + "/", "api_key": API_KEY},
    )
    assert resp.status_code == 201, resp.text
    provider = resp.json()
    assert provider["base_url"] == BASE
    assert provider["api_key_hint"] == "sk-****abcd" and API_KEY not in resp.text
    synced = await api.post(f"/api/v1/admin/models/providers/{provider['id']}/sync", headers=ALICE)
    assert synced.status_code == 200, synced.text
    assert synced.json() == {"listed": 4, "added": 4, "missing": []}
    rerank = await api.post(
        "/api/v1/admin/models",
        headers=ALICE,
        json={
            "provider_id": provider["id"],
            "name": "qwen3-rerank",
            "kind": "rerank",
            "base_url": "http://provider/api/v1",
            "path": "/reranks",
        },
    )
    assert rerank.status_code == 201, rerank.text
    models = (await api.get("/api/v1/admin/models", headers=ALICE)).json()
    assert models["total"] == 5
    ids = {m["name"]: m["id"] for m in models["items"]}
    kinds = {m["name"]: m["kind"] for m in models["items"]}
    assert kinds == {
        "chat-a": "chat",
        "chat-b": "chat",
        "chat-bad": "chat",
        "text-embedding-x": "embedding",
        "qwen3-rerank": "rerank",
    }
    return {"provider": provider["id"], **ids}


async def test_provider_sync_and_checks(
    admin_api: httpx.AsyncClient, provider: FakeProvider, engine: AsyncEngine
) -> None:
    ids = await setup_provider(admin_api)

    chat = await admin_api.post(f"/api/v1/admin/models/{ids['chat-a']}/check", headers=ALICE)
    assert chat.json()["ok"] is True and chat.json()["sample"] == "OK"
    emb = await admin_api.post(
        f"/api/v1/admin/models/{ids['text-embedding-x']}/check", headers=ALICE
    )
    assert emb.json()["ok"] is True and emb.json()["dim"] == 4
    rerank = await admin_api.post(
        f"/api/v1/admin/models/{ids['qwen3-rerank']}/check", headers=ALICE
    )
    assert rerank.json()["ok"] is True, rerank.text
    bad = await admin_api.post(f"/api/v1/admin/models/{ids['chat-bad']}/check", headers=ALICE)
    assert bad.json()["ok"] is False and "Model not exist" in bad.json()["message"]

    listed = (await admin_api.get("/api/v1/admin/models?kind=chat", headers=ALICE)).json()
    status = {m["name"]: m["last_check_status"] for m in listed["items"]}
    assert status == {"chat-a": "ok", "chat-b": None, "chat-bad": "error"}

    async with create_session_factory(engine)() as session:
        stored = (await session.execute(select(LlmProvider))).scalar_one()
        assert API_KEY not in (stored.api_key_encrypted or "")
        logs = (await session.execute(select(AuditLog))).scalars().all()
    assert {"llm_provider.create", "llm_provider.sync", "llm_model.create"} <= {
        log.action for log in logs
    }
    assert all(API_KEY not in json.dumps([log.before, log.after, log.diff]) for log in logs)


async def test_chat_model_switch_takes_effect_immediately(
    admin_api: httpx.AsyncClient, provider: FakeProvider, llm_gateway: LLMGateway
) -> None:
    ids = await setup_provider(admin_api)
    assert await served_model(llm_gateway) == "mock-chat"
    overview = (await admin_api.get("/api/v1/admin/models/overview", headers=ALICE)).json()
    scenes = {s["scene"]: s for s in overview["scenes"]}
    assert scenes["chat"]["source"] == "config" and scenes["chat"]["model"] == "mock-chat"
    assert scenes["embedding"]["editable"] is False and scenes["rerank"]["editable"] is False

    saved = await admin_api.put(
        "/api/v1/admin/models/routes",
        headers=ALICE,
        json={"chat_model_id": ids["chat-a"], "chat_fallback_model_id": ids["chat-b"]},
    )
    assert saved.status_code == 200, saved.text
    scenes = {s["scene"]: s for s in saved.json()["scenes"]}
    assert (scenes["chat"]["source"], scenes["chat"]["model"]) == ("page", "chat-a")
    assert scenes["chat_fallback"]["model"] == "chat-b"
    assert await served_model(llm_gateway) == "chat-a"

    failed = await admin_api.put(
        "/api/v1/admin/models/routes", headers=ALICE, json={"chat_model_id": ids["chat-bad"]}
    )
    assert failed.status_code == 422 and failed.json()["code"] == "MODEL_CHECK_FAILED"
    assert failed.json()["detail"][0]["model"] == "chat-bad"
    assert await served_model(llm_gateway) == "chat-a"

    forced = await admin_api.put(
        "/api/v1/admin/models/routes",
        headers=ALICE,
        json={"chat_model_id": ids["chat-bad"], "force": True},
    )
    assert forced.status_code == 200
    assert await served_model(llm_gateway) == "chat-bad"

    for method, url, body in (
        ("DELETE", f"/api/v1/admin/models/providers/{ids['provider']}", None),
        ("PUT", f"/api/v1/admin/models/providers/{ids['provider']}", {"enabled": False}),
        ("DELETE", f"/api/v1/admin/models/{ids['chat-bad']}", None),
        ("PUT", f"/api/v1/admin/models/{ids['chat-bad']}", {"kind": "embedding"}),
    ):
        resp = await admin_api.request(method, url, headers=ALICE, json=body)
        assert resp.status_code == 409, (method, url, resp.text)
    unused = await admin_api.delete(f"/api/v1/admin/models/{ids['chat-b']}", headers=ALICE)
    assert unused.status_code == 204

    reset = await admin_api.put(
        "/api/v1/admin/models/routes", headers=ALICE, json={"chat_model_id": None}
    )
    scenes = {s["scene"]: s for s in reset.json()["scenes"]}
    assert scenes["chat"]["source"] == "config"
    assert await served_model(llm_gateway) == "mock-chat"


async def test_access_is_restricted(admin_api: httpx.AsyncClient, provider: FakeProvider) -> None:
    assert (await admin_api.get("/api/v1/admin/models/overview", headers=ALICE)).status_code == 200
    assert (await admin_api.get("/api/v1/admin/models/overview", headers=BOB)).status_code == 403
    # A second organization exists now: only platform administrators manage platform models.
    resp = await admin_api.get("/api/v1/admin/models/overview", headers=DAVE)
    assert resp.status_code == 403


class FakeChat:
    def __init__(self, model: str) -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        return ChatResult(content=self._model, model=self._model)

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        yield self._model
        yield "!"


async def test_routed_client_keeps_running_on_errors_and_in_flight_streams() -> None:
    state: dict[str, Any] = {"route": None, "fail": False, "loads": 0}

    async def loader() -> ChatRoute | None:
        state["loads"] += 1
        if state["fail"]:
            raise RuntimeError("db down")
        return state["route"]

    routed = RoutedChatClient(
        FakeChat("default"), loader, lambda r: FakeChat(r.primary.model), refresh_seconds=3600
    )
    await routed.refresh()
    await routed.refresh()
    assert routed.model == "default" and state["loads"] == 1

    state["route"] = ChatRoute(primary=ChatTarget(model="new", base_url=BASE))
    old_stream = routed.stream([])
    assert await anext(old_stream) == "default"
    routed.invalidate()
    await routed.refresh()
    assert routed.model == "new"
    assert await anext(old_stream) == "!"
    assert (await routed.complete([])).content == "new"

    state["fail"] = True
    routed.invalidate()
    await routed.refresh()
    assert routed.model == "new"


async def test_env_config_is_imported_once(settings: Settings, engine: AsyncEngine) -> None:
    env = settings.model_copy(
        update={
            "llm_provider": "openai",
            "llm_api_key": API_KEY,
            "chat_base_url": BASE + "/",
            "chat_model": "chat-a",
            "embedding_base_url": BASE,
            "embedding_model": "text-embedding-x",
            "embedding_dim": 1024,
            "rerank_base_url": "http://provider/api/v1",
            "rerank_model": "qwen3-rerank",
            "rerank_path": "/reranks",
        }
    )
    factory = create_session_factory(engine)
    assert await import_env_config(factory, env) is True
    assert await import_env_config(factory, env) is False
    async with factory() as session:
        provider = (await session.execute(select(LlmProvider))).scalar_one()
        models = {m.name: m for m in (await session.execute(select(LlmModel))).scalars()}
    assert provider.base_url == BASE and provider.source == "env"
    assert decrypt_api_key(env, provider) == API_KEY and provider.api_key_hint == "sk-****abcd"
    assert {n: m.kind for n, m in models.items()} == {
        "chat-a": "chat",
        "text-embedding-x": "embedding",
        "qwen3-rerank": "rerank",
    }
    assert models["text-embedding-x"].base_url is None
    assert models["text-embedding-x"].detected_dim == 1024
    assert (models["qwen3-rerank"].base_url, models["qwen3-rerank"].path) == (
        "http://provider/api/v1",
        "/reranks",
    )


async def test_mock_provider_imports_nothing(settings: Settings, engine: AsyncEngine) -> None:
    mock = settings.model_copy(update={"llm_provider": "mock"})
    assert await import_env_config(create_session_factory(engine), mock) is False


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("deepseek-v4.1-flash", "chat"),
        ("text-embedding-v4", "embedding"),
        ("qwen3.7-text-embedding", "embedding"),
        ("qwen3-rerank", "rerank"),
        ("gte-rerank-v2", "rerank"),
    ],
)
def test_guess_kind(name: str, kind: str) -> None:
    assert guess_kind(name).value == kind
