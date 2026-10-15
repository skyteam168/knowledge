"""Open platform: admin-issued API keys, grant bounds, identity-scoped ACL, limits, MCP."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.core.db import create_session_factory
from app.core.rate_limit import RateLimitedError
from app.models import ApiCallLog, ApiClient, ApiKey, AuditLog, User
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.pipeline import IngestPipeline
from app.services.open_api import auth as open_auth
from tests.test_chat_api import (
    ALICE,
    CAROL,
    LEAVE_MD,
    ScriptedChat,
    answerable,
    chat,
    corpus,
    parse_sse,
)
from tests.test_indexing import create_kb, drain, ingest, pipeline

__all__ = ["answerable", "chat", "corpus", "pipeline"]

ADMIN = "/api/v1/admin/open-api"
OPEN = "/api/v1/open"

FINANCE_MD = f"""# 财务制度

## 付款审批

单笔付款超过 50 万元需财务总监 FIN-7788 审批。

{LEAVE_MD.decode().split("## 背景")[1]}
""".encode()


async def options(api: httpx.AsyncClient) -> dict[str, Any]:
    resp = await api.get(f"{ADMIN}/options", headers=ALICE)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def named(items: list[dict[str, str]], name: str) -> str:
    return next(i["id"] for i in items if i["name"] == name)


async def create_client(api: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    resp = await api.post(f"{ADMIN}/clients", json=body, headers=ALICE)
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def issue_key(api: httpx.AsyncClient, client_id: str, **body: Any) -> dict[str, Any]:
    resp = await api.post(
        f"{ADMIN}/clients/{client_id}/keys", json={"name": "k", **body}, headers=ALICE
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def key_headers(secret: str) -> dict[str, str]:
    return {"X-API-Key": secret}


@pytest.fixture
async def agent(api: httpx.AsyncClient, corpus: dict[str, Any]) -> dict[str, Any]:
    """Client bound to the `sales` group, granted both the public and the restricted KB."""
    opts = await options(api)
    client = await create_client(
        api,
        name="销售部 Agent",
        kb_ids=[corpus["public_kb"]["id"], corpus["secret_kb"]["id"]],
        principals=[{"type": "group", "id": named(opts["groups"], "sales")}],
        scopes=["retrieve", "chat", "mcp"],
    )
    key = await issue_key(api, client["id"])
    return {"client": client, "key": key, "headers": key_headers(key["secret"])}


async def retrieve(api: httpx.AsyncClient, headers: dict[str, str], **body: Any) -> httpx.Response:
    return await api.post(f"{OPEN}/retrieve", json=body, headers=headers)


async def logs(engine: AsyncEngine) -> list[ApiCallLog]:
    async with create_session_factory(engine)() as session:
        stmt = select(ApiCallLog).order_by(ApiCallLog.created_at)
        return list((await session.execute(stmt)).scalars())


# ---- admin -------------------------------------------------------------------------------


async def test_admin_requires_permission(api: httpx.AsyncClient, corpus: dict[str, Any]) -> None:
    for method, path in [("GET", "/clients"), ("GET", "/options"), ("POST", "/clients")]:
        resp = await api.request(method, f"{ADMIN}{path}", headers=CAROL, json={})
        assert resp.status_code == 403, (path, resp.text)


async def test_key_secret_shown_once_and_only_hash_stored(
    api: httpx.AsyncClient, agent: dict[str, Any], engine: AsyncEngine
) -> None:
    secret = agent["key"]["secret"]
    assert secret.startswith("ekb_sk_") and len(secret) > 40
    listed = (await api.get(f"{ADMIN}/clients/{agent['client']['id']}/keys", headers=ALICE)).json()
    assert listed and all("secret" not in k for k in listed)
    assert listed[0]["prefix"] == secret[:14]
    async with create_session_factory(engine)() as session:
        stored = (await session.execute(select(ApiKey))).scalar_one()
        assert secret not in stored.key_hash and stored.key_hash != secret
        user = await session.get(User, agent["client"]["service_user_id"])
        assert user is not None and user.username.startswith("agent:")
        actions = set((await session.execute(select(AuditLog.action))).scalars())
    assert {"openapi.client.create", "openapi.key.create"} <= actions
    # Service users stay out of the admin user list.
    users = (await api.get("/api/v1/admin/users?size=100", headers=ALICE)).json()["items"]
    assert not any(u["username"].startswith("agent:") for u in users)


async def test_create_rejects_unknown_kb_and_bad_cidr(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    opts = await options(api)
    group = {"type": "group", "id": named(opts["groups"], "sales")}
    resp = await api.post(
        f"{ADMIN}/clients",
        json={"name": "x", "kb_ids": ["nope"], "principals": [group], "scopes": ["retrieve"]},
        headers=ALICE,
    )
    assert resp.status_code == 422, resp.text
    resp = await api.post(
        f"{ADMIN}/clients",
        json={
            "name": "x",
            "kb_ids": [corpus["public_kb"]["id"]],
            "principals": [group],
            "scopes": ["retrieve"],
            "ip_allowlist": ["not-an-ip"],
        },
        headers=ALICE,
    )
    assert resp.status_code == 422, resp.text


# ---- authentication ----------------------------------------------------------------------


async def test_invalid_forged_revoked_expired_keys(
    api: httpx.AsyncClient, agent: dict[str, Any], engine: AsyncEngine
) -> None:
    body = {"query": "年假"}
    cases = {
        "missing": {},
        "malformed": key_headers("hello"),
        "forged": key_headers("ekb_sk_" + "A" * 43),
        "user_jwt": ALICE,
    }
    for name, headers in cases.items():
        resp = await retrieve(api, headers, **body)
        assert resp.status_code == 401, (name, resp.text)
        assert resp.json()["code"] == "INVALID_API_KEY", name

    client_id = agent["client"]["id"]
    resp = await api.post(
        f"{ADMIN}/clients/{client_id}/keys/{agent['key']['id']}/revoke", headers=ALICE
    )
    assert resp.status_code == 200 and resp.json()["status"] == "revoked"
    resp = await retrieve(api, agent["headers"], **body)
    assert resp.status_code == 401 and resp.json()["code"] == "API_KEY_REVOKED"

    soon = await issue_key(
        api, client_id, expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat()
    )
    async with create_session_factory(engine)() as session:
        key = await session.get(ApiKey, soon["id"])
        assert key is not None
        key.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    resp = await retrieve(api, key_headers(soon["secret"]), **body)
    assert resp.status_code == 401 and resp.json()["code"] == "API_KEY_EXPIRED"

    past = await api.post(
        f"{ADMIN}/clients/{client_id}/keys",
        json={"name": "old", "expires_at": "2020-01-01T00:00:00Z"},
        headers=ALICE,
    )
    assert past.status_code == 422


async def test_disabled_and_deleted_client(api: httpx.AsyncClient, agent: dict[str, Any]) -> None:
    client_id = agent["client"]["id"]
    assert (await retrieve(api, agent["headers"], query="年假")).status_code == 200
    resp = await api.put(f"{ADMIN}/clients/{client_id}", json={"status": "disabled"}, headers=ALICE)
    assert resp.status_code == 200, resp.text
    resp = await retrieve(api, agent["headers"], query="年假")
    assert resp.status_code == 403 and resp.json()["code"] == "API_CLIENT_DISABLED"
    await api.put(f"{ADMIN}/clients/{client_id}", json={"status": "active"}, headers=ALICE)
    assert (await retrieve(api, agent["headers"], query="年假")).status_code == 200
    assert (await api.delete(f"{ADMIN}/clients/{client_id}", headers=ALICE)).status_code == 204
    resp = await retrieve(api, agent["headers"], query="年假")
    assert resp.status_code == 401


# ---- authorization bounds ----------------------------------------------------------------


async def test_identity_acl_hides_restricted_kb_even_when_granted(
    api: httpx.AsyncClient, agent: dict[str, Any], corpus: dict[str, Any]
) -> None:
    secret_doc = corpus["secret"]["id"]
    for query in ["FX-9001 工艺参数", "机密配方", f"kb:{corpus['secret_kb']['name']} 配方"]:
        resp = await retrieve(api, agent["headers"], query=query, top_k=20)
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert all(i["document_id"] != secret_doc for i in items), query
        assert all("FX-9001" not in i["content"] for i in items), query
    # Explicitly asking for the granted-but-unreadable KB returns nothing, not its content.
    resp = await retrieve(api, agent["headers"], query="配方", kb_ids=[corpus["secret_kb"]["id"]])
    assert resp.status_code == 200 and resp.json()["items"] == []

    public = await retrieve(api, agent["headers"], query="年假天数", top_k=5)
    assert public.status_code == 200
    assert {i["kb_id"] for i in public.json()["items"]} == {corpus["public_kb"]["id"]}

    who = (await api.get(f"{OPEN}/whoami", headers=agent["headers"])).json()
    assert [kb["id"] for kb in who["kbs"]] == [corpus["public_kb"]["id"]]


async def test_role_binding_does_not_escalate(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    opts = await options(api)
    client = await create_client(
        api,
        name="伪管理员",
        kb_ids=[corpus["public_kb"]["id"], corpus["secret_kb"]["id"]],
        principals=[{"type": "role", "id": named(opts["roles"], "知识库管理员")}],
        scopes=["retrieve"],
    )
    headers = key_headers((await issue_key(api, client["id"]))["secret"])
    resp = await retrieve(api, headers, query="FX-9001 机密配方", top_k=20)
    assert resp.status_code == 200
    assert all(i["document_id"] != corpus["secret"]["id"] for i in resp.json()["items"])
    # The agent identity can't use the user-facing API at all.
    assert (await api.get("/api/v1/admin/users", headers=headers)).status_code == 401


async def test_ungranted_kb_is_unreachable(
    api: httpx.AsyncClient,
    agent: dict[str, Any],
    pipeline: IngestPipeline,
    indexing: IndexingRuntime,
) -> None:
    finance = await create_kb(api, "财务库", visibility="org")
    await ingest(api, pipeline, finance["id"], "finance.md", FINANCE_MD)
    assert set(await drain(indexing)) == {"done"}
    # Carol (sales) can read it herself — the grant, not the ACL, is what stops the agent.
    resp = await api.get("/api/v1/search", params={"q": "FIN-7788"}, headers=CAROL)
    assert resp.status_code == 200 and resp.json()["items"]

    resp = await retrieve(api, agent["headers"], query="付款审批", kb_ids=[finance["id"]])
    assert resp.status_code == 403 and resp.json()["code"] == "KB_NOT_GRANTED"
    for query in ["FIN-7788 付款审批", "kb:财务库 付款审批", "kb:财务库 FIN-7788"]:
        resp = await retrieve(api, agent["headers"], query=query, top_k=20)
        assert resp.status_code == 200, resp.text
        assert all(i["kb_id"] != finance["id"] for i in resp.json()["items"]), query


async def test_scope_denied(api: httpx.AsyncClient, corpus: dict[str, Any]) -> None:
    opts = await options(api)
    client = await create_client(
        api,
        name="只读",
        kb_ids=[corpus["public_kb"]["id"]],
        principals=[{"type": "group", "id": named(opts["groups"], "sales")}],
        scopes=["retrieve"],
    )
    headers = key_headers((await issue_key(api, client["id"]))["secret"])
    resp = await api.post(f"{OPEN}/chat", json={"question": "年假"}, headers=headers)
    assert resp.status_code == 403 and resp.json()["code"] == "SCOPE_DENIED"
    resp = await api.post(f"{OPEN}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                          headers=headers)  # fmt: skip
    assert resp.status_code == 403 and resp.json()["code"] == "SCOPE_DENIED"


# ---- limits ------------------------------------------------------------------------------


async def test_rate_limit_quota_and_ip_allowlist(
    api: httpx.AsyncClient, corpus: dict[str, Any], engine: AsyncEngine
) -> None:
    opts = await options(api)
    base = {
        "kb_ids": [corpus["public_kb"]["id"]],
        "principals": [{"type": "group", "id": named(opts["groups"], "sales")}],
        "scopes": ["retrieve"],
    }
    limited = await create_client(api, name="限流", rate_limit_per_minute=2, **base)
    headers = key_headers((await issue_key(api, limited["id"]))["secret"])
    codes = [(await retrieve(api, headers, query="年假")).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and codes[2:] == [429, 429]

    quota = await create_client(api, name="配额", daily_quota=1, **base)
    headers = key_headers((await issue_key(api, quota["id"]))["secret"])
    assert (await retrieve(api, headers, query="年假")).status_code == 200
    resp = await retrieve(api, headers, query="年假")
    assert resp.status_code == 429 and resp.json()["code"] == "QUOTA_EXCEEDED"

    fenced = await create_client(api, name="IP", ip_allowlist=["10.0.0.0/8"], **base)
    headers = key_headers((await issue_key(api, fenced["id"]))["secret"])
    for extra in [{}, {"X-Forwarded-For": "10.1.2.3"}, {"X-Real-IP": "10.1.2.3"}]:
        resp = await retrieve(api, {**headers, **extra}, query="年假")
        assert resp.status_code == 403 and resp.json()["code"] == "IP_NOT_ALLOWED", extra

    entries = await logs(engine)
    assert {e.error_code for e in entries} >= {"RATE_LIMITED", "QUOTA_EXCEEDED", "IP_NOT_ALLOWED"}


async def test_xff_honoured_only_from_trusted_proxy(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opts = await options(api)
    client = await create_client(
        api,
        name="经网关",
        kb_ids=[corpus["public_kb"]["id"]],
        principals=[{"type": "group", "id": named(opts["groups"], "sales")}],
        scopes=["retrieve"],
        ip_allowlist=["10.0.0.0/8"],
    )
    headers = key_headers((await issue_key(api, client["id"]))["secret"])
    monkeypatch.setattr(settings, "open_api_trusted_proxies", ["127.0.0.1/32"])
    ok = await retrieve(api, {**headers, "X-Forwarded-For": "10.1.2.3"}, query="年假")
    assert ok.status_code == 200, ok.text
    # Client-supplied hops before the real one don't help.
    resp = await retrieve(api, {**headers, "X-Forwarded-For": "10.1.2.3, 8.8.8.8"}, query="年假")
    assert resp.status_code == 403


async def test_rate_limit_holds_across_minute_boundary(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ApiClient(id="c1", org_id="o", rate_limit_per_minute=3, daily_quota=0)
    cache = MemoryCache()
    clock = {"now": 60 * 1000 + 58.0}
    monkeypatch.setattr(open_auth.time, "time", lambda: clock["now"])
    outcomes = []
    for t in [58.0, 58.5, 59.0, 60.2, 60.4, 60.6]:
        clock["now"] = 60 * 1000 + t
        try:
            await open_auth.apply_limits(client, cache, settings)
            outcomes.append("ok")
        except RateLimitedError:
            outcomes.append("429")
    assert outcomes == ["ok", "ok", "ok", "429", "429", "429"]
    clock["now"] = 60 * 1003 + 1.0
    await open_auth.apply_limits(client, cache, settings)


# ---- chat --------------------------------------------------------------------------------


async def test_chat_is_bounded_and_streams_steps(
    api: httpx.AsyncClient,
    agent: dict[str, Any],
    corpus: dict[str, Any],
    chat: ScriptedChat,
    answerable: Settings,
) -> None:
    chat.answer = "入职满一年享有 5 天年假[1]。"
    resp = await api.post(f"{OPEN}/chat", json={"question": "年假几天？"}, headers=agent["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == chat.answer and body["grounding"] == "grounded"
    assert {c["document_id"] for c in body["citations"]} <= {
        corpus["leave"]["id"],
        corpus["expense"]["id"],
    }
    assert [s["step"] for s in body["steps"]] == ["rewrite", "retrieve", "evidence", "generate"]
    assert all(s["status"] == "done" for s in body["steps"])

    chat.answer = "机密内容[1]"
    resp = await api.post(
        f"{OPEN}/chat", json={"question": "FX-9001 的工艺参数是多少？"}, headers=agent["headers"]
    )
    assert resp.status_code == 200
    # The question names the secret; the secret's content must never reach the model.
    assert all("42 针" not in "\n".join(m.content for m in s) for s in chat.streams)
    assert all(c["document_id"] != corpus["secret"]["id"] for c in resp.json()["citations"])

    # Someone else's conversation can't be continued.
    conv = (await api.post("/api/v1/chat/conversations", json={}, headers=CAROL)).json()
    resp = await api.post(
        f"{OPEN}/chat",
        json={"question": "继续", "conversation_id": conv["id"]},
        headers=agent["headers"],
    )
    assert resp.status_code == 404

    chat.answer = "需提前 3 个工作日申请[1]。"
    resp = await api.post(
        f"{OPEN}/chat",
        json={"question": "年假怎么申请？", "stream": True},
        headers=agent["headers"],
    )
    assert resp.status_code == 200
    types = [t for t, _ in parse_sse(resp.text)]
    assert types[0] == "meta" and types[-1] == "done" and "step" in types and "token" in types


# ---- MCP ---------------------------------------------------------------------------------


async def mcp(api: httpx.AsyncClient, headers: dict[str, str], payload: Any) -> httpx.Response:
    return await api.post(f"{OPEN}/mcp", json=payload, headers=headers)


async def test_mcp_protocol_and_tools(
    api: httpx.AsyncClient, agent: dict[str, Any], corpus: dict[str, Any]
) -> None:
    h = agent["headers"]
    init = await mcp(api, h, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18"}})  # fmt: skip
    assert init.status_code == 200 and init.json()["result"]["protocolVersion"] == "2025-06-18"
    note = await mcp(api, h, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202

    tools = (await mcp(api, h, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})).json()
    assert {t["name"] for t in tools["result"]["tools"]} == {
        "list_knowledge_bases",
        "search_knowledge",
        "ask_knowledge",
    }
    params = {"name": "search_knowledge", "arguments": {"query": "FX-9001 机密配方", "top_k": 20}}
    found = await mcp(api, h, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": params})
    result = found.json()["result"]
    assert result["isError"] is False
    assert all(
        i["document_id"] != corpus["secret"]["id"] for i in result["structuredContent"]["items"]
    )
    denied = await mcp(api, h, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "search_knowledge", "arguments": {"query": "x", "kb_ids": ["nope"]}}})  # fmt: skip
    assert denied.json()["result"]["isError"] is True
    assert denied.json()["result"]["structuredContent"]["code"] == "KB_NOT_GRANTED"


async def test_mcp_malformed_requests(api: httpx.AsyncClient, agent: dict[str, Any]) -> None:
    h = agent["headers"]
    raw = await api.post(
        f"{OPEN}/mcp", content=b"{not json", headers={**h, "Content-Type": "application/json"}
    )
    assert raw.status_code == 400 and raw.json()["error"]["code"] == -32700
    cases: list[tuple[Any, int]] = [
        ({"id": 1, "method": "ping"}, -32600),
        ([], -32600),
        ("hello", -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, -32601),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []}, -32602),
        ({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rm -rf"}}, -32602),
        (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "search_knowledge", "arguments": "x"},
            },
            -32602,
        ),
    ]
    for payload, code in cases:
        resp = await mcp(api, h, payload)
        assert resp.status_code == 200, (payload, resp.text)
        assert resp.json()["error"]["code"] == code, payload
    bad_args = await mcp(api, h, {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
        "name": "search_knowledge", "arguments": {"top_k": 9999}}})  # fmt: skip
    assert bad_args.json()["result"]["isError"] is True
    batch = await mcp(api, h, [{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                               {"jsonrpc": "2.0", "method": "notifications/x"}])  # fmt: skip
    assert [r["id"] for r in batch.json()] == [1]
    assert (await api.get(f"{OPEN}/mcp", headers=h)).status_code == 405


# ---- logging & preview -------------------------------------------------------------------


async def test_calls_logged_and_preview(
    api: httpx.AsyncClient, agent: dict[str, Any], corpus: dict[str, Any], engine: AsyncEngine
) -> None:
    client_id = agent["client"]["id"]
    await retrieve(api, agent["headers"], query="年假天数")
    await retrieve(api, agent["headers"], query="x", kb_ids=["nope"])
    page = (await api.get(f"{ADMIN}/clients/{client_id}/logs", headers=ALICE)).json()
    assert page["total"] == 2
    assert sorted(i["status_code"] for i in page["items"]) == [200, 403]
    usage = (await api.get(f"{ADMIN}/clients/{client_id}/usage?days=7", headers=ALICE)).json()
    assert usage["total_calls"] == 2 and usage["total_errors"] == 1

    preview = await api.post(
        f"{ADMIN}/clients/{client_id}/preview", json={"query": "FX-9001 机密配方"}, headers=ALICE
    )
    assert preview.status_code == 200, preview.text
    assert all(i["document_id"] != corpus["secret"]["id"] for i in preview.json()["items"])
    assert (
        await api.post(f"{ADMIN}/clients/{client_id}/preview", json={"query": "x"}, headers=CAROL)
    ).status_code == 403
