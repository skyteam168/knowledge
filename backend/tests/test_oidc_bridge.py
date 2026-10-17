import base64
import functools
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api import oidc_bridge as oidc_api
from app.core.cache import MemoryCache
from app.core.config import Settings, get_settings
from app.core.crypto import encrypt_json
from app.core.db import create_session_factory
from app.core.resources import AppResources
from app.core.storage import MemoryStorage
from app.llm import LLMGateway
from app.main import create_app
from app.models import AuditLog, DirectorySource, User, UserIdentity
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.queue import RecordingTaskQueue
from app.services.oidc_bridge.service import OidcBridgeService
from app.services.org_bootstrap import create_organization
from tests.conftest import TEST_IDENTITIES, FakeTokenVerifier, auth

BROKER = "http://localhost:8080/realms/ekb/broker/{}/endpoint"
CLIENT = {"client_id": "keycloak", "client_secret": "change-me-oidc-bridge-secret"}


@dataclass
class Upstream:
    """Fake WeCom, DingTalk and Keycloak admin APIs."""

    wecom_codes: dict[str, dict[str, Any]] = field(default_factory=dict)
    dingtalk_codes: dict[str, str] = field(default_factory=dict)
    dingtalk_userids: dict[str, str] = field(default_factory=dict)
    kc_users: dict[str, dict[str, Any]] = field(default_factory=dict)
    kc_passwords: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.calls.append(f"{request.method} {host}{path}")
        if host == "qyapi.weixin.qq.com":
            if path == "/cgi-bin/gettoken":
                assert request.url.params["corpsecret"] == "agent-secret"
                return httpx.Response(200, json={"errcode": 0, "access_token": "wx-token"})
            if path == "/cgi-bin/auth/getuserinfo":
                info = self.wecom_codes.get(request.url.params["code"])
                if info is None:
                    return httpx.Response(200, json={"errcode": 40029, "errmsg": "invalid code"})
                return httpx.Response(200, json={"errcode": 0, **info})
        if host == "api.dingtalk.com":
            if path == "/v1.0/oauth2/userAccessToken":
                body = json.loads(request.content)
                assert body["clientSecret"] == "ding-secret"
                if body["code"] not in self.dingtalk_codes:
                    return httpx.Response(400, json={"code": "invalidAuthCode"})
                return httpx.Response(200, json={"accessToken": f"user:{body['code']}"})
            if path == "/v1.0/contact/users/me":
                code = request.headers["x-acs-dingtalk-access-token"].split(":", 1)[1]
                return httpx.Response(200, json={"unionId": self.dingtalk_codes[code]})
            if path == "/v1.0/oauth2/accessToken":
                return httpx.Response(200, json={"accessToken": "app-token"})
        if host == "oapi.dingtalk.com" and path == "/topapi/user/getbyunionid":
            union = json.loads(request.content)["unionid"]
            userid = self.dingtalk_userids.get(union)
            if userid is None:
                return httpx.Response(200, json={"errcode": 60121, "errmsg": "not found"})
            return httpx.Response(200, json={"errcode": 0, "result": {"userid": userid}})
        if host == "localhost" and request.url.port == 8080:
            return self.keycloak(request)
        raise AssertionError(f"unexpected upstream call {request.method} {request.url}")

    def keycloak(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/realms/ekb/protocol/openid-connect/token":
            form = parse_qs(request.content.decode())
            if form["client_secret"] != ["kc-admin-secret"]:
                return httpx.Response(401, json={"error": "unauthorized_client"})
            return httpx.Response(200, json={"access_token": "kc-admin-token"})
        assert request.headers["authorization"] == "Bearer kc-admin-token"
        prefix = "/admin/realms/ekb/users"
        if path == prefix and request.method == "GET":
            name = request.url.params["username"]
            return httpx.Response(
                200, json=[u for u in self.kc_users.values() if u["username"] == name]
            )
        if path == prefix and request.method == "POST":
            body = json.loads(request.content)
            if body.get("email") and any(
                u.get("email") == body["email"] for u in self.kc_users.values()
            ):
                return httpx.Response(409, json={"errorMessage": "User exists with same email"})
            uid = f"kc-{len(self.kc_users) + 1}"
            self.kc_users[uid] = {"id": uid, **body}
            return httpx.Response(201, headers={"Location": f"http://kc{prefix}/{uid}"})
        uid = path.removeprefix(prefix + "/").split("/")[0]
        if path.endswith("/reset-password"):
            self.kc_passwords[uid] = json.loads(request.content)
            return httpx.Response(204)
        if request.method == "GET":
            user = self.kc_users.get(uid)
            return httpx.Response(200, json=user) if user else httpx.Response(404)
        if request.method == "PUT":
            self.kc_users[uid] = json.loads(request.content)
            return httpx.Response(204)
        raise AssertionError(f"unexpected keycloak call {request.method} {path}")


@dataclass
class Env:
    api: httpx.AsyncClient
    upstream: Upstream
    settings: Settings
    ids: dict[str, str]


async def _seed(engine: AsyncEngine, settings: Settings) -> dict[str, str]:
    async with create_session_factory(engine)() as s:
        org = await create_organization(s, code="org-demo", name="Demo")
        ids: dict[str, str] = {"org": org.id}
        for username, active, provider, external, union in (
            ("zhangsan", True, "wecom", "zhangsan", None),
            ("lisi", False, "wecom", "lisi", None),
            ("zhaoliu", True, "dingtalk", "ding-u1", "union-1"),
            ("qianqi", True, "dingtalk", "ding-u2", None),
        ):
            user = User(
                org_id=org.id,
                username=username,
                display_name=username.title(),
                email=f"{username}@example.com" if username == "zhangsan" else None,
                is_active=active,
                source=provider,
            )
            s.add(user)
            await s.flush()
            ids[username] = user.id
            s.add(
                UserIdentity(
                    org_id=org.id,
                    user_id=user.id,
                    provider=provider,
                    external_id=external,
                    union_id=union,
                )
            )
        for type_, config in (
            (
                "wecom",
                {
                    "corp_id": "ww-corp",
                    "contacts_secret": "contacts-secret",
                    "agent_id": "1000002",
                    "agent_secret": "agent-secret",
                },
            ),
            ("dingtalk", {"app_key": "ding-key", "app_secret": "ding-secret"}),
        ):
            s.add(
                DirectorySource(
                    org_id=org.id,
                    type=type_,
                    name=type_,
                    is_primary=type_ == "wecom",
                    config_encrypted=encrypt_json(settings.directory_secret_key, config),
                )
            )
        await s.commit()
    return ids


@pytest.fixture
async def env(
    settings: Settings,
    engine: AsyncEngine,
    memory_cache: MemoryCache,
    storage: MemoryStorage,
    task_queue: RecordingTaskQueue,
    llm_gateway: LLMGateway,
    indexing: IndexingRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Env]:
    upstream = Upstream()
    transport = httpx.MockTransport(upstream)
    custom = settings.model_copy(update={"keycloak_admin_client_secret": "kc-admin-secret"})
    resources = AppResources(
        engine=engine,
        session_factory=create_session_factory(engine),
        cache=memory_cache,
        http=httpx.AsyncClient(transport=transport),
        token_verifier=FakeTokenVerifier(dict(TEST_IDENTITIES)),
        storage=storage,
        task_queue=task_queue,
        llm=llm_gateway,
        indexing=indexing,
    )
    monkeypatch.setattr(
        oidc_api, "OidcBridgeService", functools.partial(OidcBridgeService, transport=transport)
    )
    application = create_app(custom, resources_factory=lambda _: resources)
    application.state.resources = resources
    application.dependency_overrides[get_settings] = lambda: custom
    ids = await _seed(engine, custom)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://localhost:3000"
    ) as c:
        yield Env(c, upstream, custom, ids)
    await resources.http.aclose()


async def _authorize(env: Env, provider: str = "wecom", **overrides: str) -> httpx.Response:
    params = {
        "client_id": "keycloak",
        "redirect_uri": BROKER.format(provider),
        "response_type": "code",
        "state": "kc-state",
        "nonce": "kc-nonce",
        "scope": "openid",
        **overrides,
    }
    return await env.api.get(f"/oidc/{provider}/authorize", params=params)


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _login_code(env: Env, provider: str, upstream_code: str) -> str:
    start = await _authorize(env, provider)
    assert start.status_code == 302, start.text
    state = _query(start.headers["location"])["state"]
    params = {"state": state, ("authCode" if provider == "dingtalk" else "code"): upstream_code}
    back = await env.api.get(f"/oidc/{provider}/callback", params=params)
    assert back.status_code == 302, back.text
    assert back.headers["location"].startswith(BROKER.format(provider) + "?")
    target = _query(back.headers["location"])
    assert target["state"] == "kc-state"
    return target["code"]


async def _token(env: Env, code: str, provider: str = "wecom", **extra: str) -> httpx.Response:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": BROKER.format(provider),
        **CLIENT,
        **extra,
    }
    return await env.api.post(f"/oidc/{provider}/token", data=data)


async def test_discovery_and_jwks(env: Env) -> None:
    conf = (await env.api.get("/oidc/wecom/.well-known/openid-configuration")).json()
    assert conf["issuer"] == "http://localhost:3000/oidc/wecom"
    assert conf["authorization_endpoint"].endswith("/oidc/wecom/authorize")
    assert conf["id_token_signing_alg_values_supported"] == ["RS256"]
    keys = (await env.api.get("/oidc/wecom/jwks")).json()["keys"]
    assert keys[0]["kty"] == "RSA" and keys[0]["alg"] == "RS256" and "d" not in keys[0]
    unknown = await env.api.get("/oidc/feishu/.well-known/openid-configuration")
    assert unknown.status_code == 404


async def test_wecom_full_flow_issues_verifiable_id_token(env: Env) -> None:
    env.upstream.wecom_codes["wx-code"] = {"userid": "zhangsan"}
    start = await _authorize(env)
    location = start.headers["location"]
    assert location.startswith("https://login.work.weixin.qq.com/wwlogin/sso/login?")
    q = _query(location)
    assert q["appid"] == "ww-corp" and q["agentid"] == "1000002" and q["login_type"] == "CorpApp"
    assert q["redirect_uri"] == "http://localhost:3000/oidc/wecom/callback"
    assert q["state"] != "kc-state", "Keycloak's state never leaves for the upstream"
    assert "ekb_oidc_wecom" in start.headers["set-cookie"]
    assert "httponly" in start.headers["set-cookie"].lower()

    back = await env.api.get(
        "/oidc/wecom/callback", params={"code": "wx-code", "state": q["state"]}
    )
    code = _query(back.headers["location"])["code"]
    resp = await _token(env, code)
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["token_type"] == "Bearer"

    jwk = jwt.PyJWKSet.from_dict((await env.api.get("/oidc/wecom/jwks")).json()).keys[0]
    claims = jwt.decode(
        body["id_token"],
        jwk.key,
        algorithms=["RS256"],
        audience="keycloak",
        issuer="http://localhost:3000/oidc/wecom",
    )
    assert claims["sub"] == env.ids["zhangsan"]
    assert claims["preferred_username"] == "zhangsan"
    assert claims["org_id"] == "org-demo" and claims["nonce"] == "kc-nonce"
    assert claims["email"] == "zhangsan@example.com"
    assert jwt.get_unverified_header(body["id_token"])["kid"] == jwk.key_id

    info = await env.api.get(
        "/oidc/wecom/userinfo", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert info.json()["preferred_username"] == "zhangsan"
    forged = await env.api.get(
        "/oidc/wecom/userinfo", headers={"Authorization": f"Bearer {body['id_token']}"}
    )
    assert forged.status_code == 401, "an id_token (aud=keycloak) is not an access token"


async def test_authorization_code_is_single_use(env: Env) -> None:
    env.upstream.wecom_codes["wx-code"] = {"userid": "zhangsan"}
    code = await _login_code(env, "wecom", "wx-code")
    assert (await _token(env, code)).status_code == 200
    replay = await _token(env, code)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"


async def test_token_endpoint_checks_client_and_redirect_uri(env: Env) -> None:
    env.upstream.wecom_codes["wx-code"] = {"userid": "zhangsan"}

    code = await _login_code(env, "wecom", "wx-code")
    bad_secret = await _token(env, code, client_secret="guess")
    assert bad_secret.status_code == 401 and bad_secret.json()["error"] == "invalid_client"
    assert "www-authenticate" in bad_secret.headers
    # A failed client authentication does not burn the code.
    assert (await _token(env, code)).status_code == 200

    code = await _login_code(env, "wecom", "wx-code")
    mismatch = await _token(env, code, redirect_uri="https://evil.example.com/cb")
    assert mismatch.status_code == 400 and mismatch.json()["error"] == "invalid_grant"
    assert (await _token(env, code)).status_code == 400, "code consumed by the failed attempt"

    code = await _login_code(env, "wecom", "wx-code")
    other_provider = await _token(env, code, provider="dingtalk")
    assert other_provider.json()["error"] == "invalid_grant"

    code = await _login_code(env, "wecom", "wx-code")
    basic = base64.b64encode(b"keycloak:change-me-oidc-bridge-secret").decode()
    via_basic = await env.api.post(
        "/oidc/wecom/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": BROKER.format("wecom"),
        },
        headers={"Authorization": f"Basic {basic}"},
    )
    assert via_basic.status_code == 200

    grant = await _token(env, "x", grant_type="password")
    assert grant.json()["error"] == "unsupported_grant_type"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"redirect_uri": "https://evil.example.com/cb"}, "OIDC_BRIDGE_REDIRECT_URI"),
        ({"redirect_uri": BROKER.format("dingtalk")}, "OIDC_BRIDGE_REDIRECT_URI"),
        ({"client_id": "someone-else"}, "OIDC_BRIDGE_CLIENT"),
        ({"response_type": "token"}, "OIDC_BRIDGE_RESPONSE_TYPE"),
        ({"state": ""}, "OIDC_BRIDGE_STATE"),
    ],
)
async def test_authorize_rejects_bad_requests(
    env: Env, overrides: dict[str, str], code: str
) -> None:
    resp = await _authorize(env, **overrides)
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("text/html")
    assert code in resp.text and "返回登录" in resp.text
    assert "set-cookie" not in resp.headers


async def test_callback_state_tampering(env: Env) -> None:
    env.upstream.wecom_codes["wx-code"] = {"userid": "zhangsan"}
    start = await _authorize(env)
    state = _query(start.headers["location"])["state"]

    tampered = await env.api.get(
        "/oidc/wecom/callback", params={"code": "wx-code", "state": state + "x"}
    )
    assert tampered.status_code == 400 and "OIDC_BRIDGE_STATE" in tampered.text

    # Another browser (no cookie) replaying a valid state.
    async with httpx.AsyncClient(
        transport=env.api._transport, base_url="http://localhost:3000"
    ) as stranger:
        stolen = await stranger.get(
            "/oidc/wecom/callback", params={"code": "wx-code", "state": state}
        )
    assert stolen.status_code == 400 and "OIDC_BRIDGE_STATE" in stolen.text

    # Forged cookie + state that the bridge never issued.
    env.api.cookies.set("ekb_oidc_wecom", "forged", path="/oidc/wecom")
    forged = await env.api.get(
        "/oidc/wecom/callback", params={"code": "wx-code", "state": "forged"}
    )
    assert forged.status_code == 400 and "OIDC_BRIDGE_STATE" in forged.text
    assert not any("getuserinfo" in c for c in env.upstream.calls), "upstream never called"


async def test_callback_state_is_single_use(env: Env) -> None:
    env.upstream.wecom_codes["wx-code"] = {"userid": "zhangsan"}
    start = await _authorize(env)
    state = _query(start.headers["location"])["state"]
    cookie = start.cookies["ekb_oidc_wecom"]
    first = await env.api.get("/oidc/wecom/callback", params={"code": "wx-code", "state": state})
    assert first.status_code == 302
    env.api.cookies.set("ekb_oidc_wecom", cookie, path="/oidc/wecom")
    second = await env.api.get("/oidc/wecom/callback", params={"code": "wx-code", "state": state})
    assert second.status_code == 400 and "OIDC_BRIDGE_STATE" in second.text


@pytest.mark.parametrize(
    ("info", "error"),
    [
        ({"userid": "stranger"}, "OIDC_BRIDGE_UNMATCHED"),
        ({"userid": "lisi"}, "OIDC_BRIDGE_USER_DISABLED"),
        ({"openid": "external-openid"}, "OIDC_BRIDGE_NOT_MEMBER"),
    ],
)
async def test_unsynced_disabled_and_external_users_are_rejected(
    env: Env, info: dict[str, str], error: str
) -> None:
    env.upstream.wecom_codes["wx-code"] = info
    start = await _authorize(env)
    state = _query(start.headers["location"])["state"]
    resp = await env.api.get("/oidc/wecom/callback", params={"code": "wx-code", "state": state})
    assert resp.status_code == 400 and error in resp.text
    assert "idp=none" in resp.text, "error page offers the normal login page"


async def test_upstream_errors_and_cancelled_login(env: Env) -> None:
    start = await _authorize(env)
    state = _query(start.headers["location"])["state"]
    resp = await env.api.get("/oidc/wecom/callback", params={"code": "bad", "state": state})
    assert resp.status_code == 400 and "OIDC_BRIDGE_UPSTREAM" in resp.text

    start = await _authorize(env)
    state = _query(start.headers["location"])["state"]
    resp = await env.api.get("/oidc/wecom/callback", params={"state": state})
    assert "OIDC_BRIDGE_DENIED" in resp.text


async def test_wecom_client_uses_silent_oauth(env: Env) -> None:
    resp = await env.api.get(
        "/oidc/wecom/authorize",
        params={
            "client_id": "keycloak",
            "redirect_uri": BROKER.format("wecom"),
            "response_type": "code",
            "state": "s",
        },
        headers={"User-Agent": "Mozilla/5.0 wxwork/4.1.30 MicroMessenger/7.0.1"},
    )
    location = resp.headers["location"]
    assert location.startswith("https://open.weixin.qq.com/connect/oauth2/authorize?")
    assert location.endswith("#wechat_redirect") and "scope=snsapi_base" in location


async def test_dingtalk_flow_by_unionid_and_userid_fallback(env: Env) -> None:
    env.upstream.dingtalk_codes.update({"c1": "union-1", "c2": "union-2"})
    env.upstream.dingtalk_userids["union-2"] = "ding-u2"

    start = await _authorize(env, "dingtalk")
    q = _query(start.headers["location"])
    assert start.headers["location"].startswith("https://login.dingtalk.com/oauth2/auth?")
    assert q["client_id"] == "ding-key" and q["scope"] == "openid"

    code = await _login_code(env, "dingtalk", "c1")
    claims = jwt.decode(
        (await _token(env, code, "dingtalk")).json()["id_token"],
        options={"verify_signature": False},
    )
    assert claims["preferred_username"] == "zhaoliu", "matched by stored unionid"
    assert not any("getbyunionid" in c for c in env.upstream.calls)

    code = await _login_code(env, "dingtalk", "c2")
    claims = jwt.decode(
        (await _token(env, code, "dingtalk")).json()["id_token"],
        options={"verify_signature": False},
    )
    assert claims["preferred_username"] == "qianqi", "unionid -> userid fallback"


async def test_not_configured_provider(env: Env, engine: AsyncEngine) -> None:
    async with create_session_factory(engine)() as s:
        for source in (await s.execute(select(DirectorySource))).scalars():
            source.enabled = False
        await s.commit()
    resp = await _authorize(env)
    assert resp.status_code == 400 and "OIDC_BRIDGE_NOT_CONFIGURED" in resp.text


async def test_production_requires_configured_signing_key(env: Env) -> None:
    prod_like = env.settings.model_copy(update={"app_env": "prod"})
    service = OidcBridgeService(None, prod_like, MemoryCache())  # type: ignore[arg-type]
    with pytest.raises(Exception, match="signing key"):
        await service.jwks()


# ---- password login fallback ------------------------------------------------------------


async def test_open_password_login_creates_keycloak_account(env: Env, engine: AsyncEngine) -> None:
    alice = auth("alice-token")
    await env.api.get("/api/v1/auth/me", headers=alice)
    resp = await env.api.post(
        f"/api/v1/admin/users/{env.ids['zhangsan']}/password-login", headers=alice
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == "zhangsan" and body["created"] is True
    password = body["temporary_password"]
    assert len(password) == 12
    assert any(c.isupper() for c in password) and any(c.islower() for c in password)
    assert any(c.isdigit() for c in password)

    account = next(iter(env.upstream.kc_users.values()))
    assert account["username"] == "zhangsan" and account["attributes"] == {"org_id": ["org-demo"]}
    assert env.upstream.kc_passwords[account["id"]] == {
        "type": "password",
        "value": password,
        "temporary": True,
    }

    again = (
        await env.api.post(
            f"/api/v1/admin/users/{env.ids['zhangsan']}/password-login", headers=alice
        )
    ).json()
    assert again["created"] is False and again["temporary_password"] != password

    async with create_session_factory(engine)() as s:
        logs = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "user.password_login")))
            .scalars()
            .all()
        )
    assert len(logs) == 2
    assert all(password not in json.dumps(log.after) for log in logs)

    disabled = await env.api.post(
        f"/api/v1/admin/users/{env.ids['lisi']}/password-login", headers=alice
    )
    assert disabled.status_code == 422
    denied = await env.api.post(
        f"/api/v1/admin/users/{env.ids['zhangsan']}/password-login", headers=auth("carol-token")
    )
    assert denied.status_code == 403


async def test_password_login_reports_email_taken_by_other_account(env: Env) -> None:
    env.upstream.kc_users["kc-admin"] = {
        "id": "kc-admin",
        "username": "admin",
        "email": "zhangsan@example.com",
        "enabled": True,
        "attributes": {"org_id": ["org-demo"]},
    }
    alice = auth("alice-token")
    await env.api.get("/api/v1/auth/me", headers=alice)
    resp = await env.api.post(
        f"/api/v1/admin/users/{env.ids['zhangsan']}/password-login", headers=alice
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "KEYCLOAK_CONFLICT" and "邮箱" in body["message"]
    assert env.upstream.kc_passwords == {}


async def test_password_login_refuses_account_of_another_org(env: Env) -> None:
    env.upstream.kc_users["kc-x"] = {
        "id": "kc-x",
        "username": "zhaoliu",
        "enabled": True,
        "attributes": {"org_id": ["org-other"]},
    }
    alice = auth("alice-token")
    await env.api.get("/api/v1/auth/me", headers=alice)
    resp = await env.api.post(
        f"/api/v1/admin/users/{env.ids['zhaoliu']}/password-login", headers=alice
    )
    assert resp.status_code == 409 and resp.json()["code"] == "KEYCLOAK_ORG_MISMATCH"
    assert env.upstream.kc_passwords == {}
