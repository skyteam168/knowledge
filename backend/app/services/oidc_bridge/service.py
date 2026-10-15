"""OIDC provider facade over WeCom / DingTalk login, consumed by Keycloak as a generic OIDC IdP.

authorize -> upstream QR / in-app OAuth -> callback (map to a synced local user through
user_identities) -> one-time code -> token (RS256 id_token). The bridge never creates
users: only people already synced from the directory can sign in.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import KeyValueCache
from app.core.config import Settings
from app.core.crypto import decrypt_json
from app.core.exceptions import AppError
from app.models import DirectorySource, Organization, User, UserIdentity
from app.services.directory.connectors.base import ConnectorError
from app.services.directory.service import login_configured
from app.services.oidc_bridge.keys import SigningKey, load_signing_key
from app.services.oidc_bridge.providers import LOGIN_PROVIDERS, LoginProvider

logger = logging.getLogger(__name__)

STATE_PREFIX = "oidc:bridge:state:"
CODE_PREFIX = "oidc:bridge:code:"
PROVIDER_LABEL = {"wecom": "企业微信", "dingtalk": "钉钉"}


class BridgeError(AppError):
    """Shown to the end user as an HTML page (authorize / callback)."""

    status_code = 400
    code = "OIDC_BRIDGE_ERROR"
    message = "登录失败"


class OAuthError(Exception):
    """RFC 6749 error for the back-channel endpoints (token / userinfo)."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True)
class AuthorizeResult:
    redirect_url: str
    state_key: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class OidcBridgeService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        cache: KeyValueCache,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cache = cache
        self.transport = transport

    # ---- URLs -------------------------------------------------------------------------

    def issuer(self, provider: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/oidc/{provider}"

    def callback_url(self, provider: str) -> str:
        return f"{self.issuer(provider)}/callback"

    def broker_redirect_uri(self, provider: str) -> str:
        s = self.settings
        realm = f"{s.keycloak_public_url.rstrip('/')}/realms/{s.keycloak_realm}"
        return f"{realm}/broker/{provider}/endpoint"

    def discovery(self, provider: str) -> dict[str, Any]:
        self._check_provider(provider)
        issuer = self.issuer(provider)
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "userinfo_endpoint": f"{issuer}/userinfo",
            "jwks_uri": f"{issuer}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "email"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "grant_types_supported": ["authorization_code"],
            "claims_supported": ["sub", "preferred_username", "name", "email", "org_id"],
        }

    async def jwks(self) -> dict[str, Any]:
        key = await load_signing_key(self.settings, self.cache)
        return {"keys": [key.jwk()]}

    # ---- front channel ----------------------------------------------------------------

    def _check_provider(self, provider: str) -> None:
        if not self.settings.oidc_bridge_enabled:
            raise BridgeError("扫码登录未启用", code="OIDC_BRIDGE_DISABLED", status_code=404)
        if provider not in LOGIN_PROVIDERS:
            raise BridgeError("不支持的登录方式", code="OIDC_BRIDGE_PROVIDER", status_code=404)

    async def _login_sources(self, provider: str) -> list[tuple[DirectorySource, dict[str, Any]]]:
        rows = await self.session.execute(
            select(DirectorySource)
            .where(DirectorySource.type == provider, DirectorySource.enabled.is_(True))
            .order_by(DirectorySource.created_at)
        )
        result = []
        for source in rows.scalars():
            config = decrypt_json(self.settings.directory_secret_key, source.config_encrypted)
            if login_configured(provider, config):
                result.append((source, config))
        return result

    async def _source(
        self, provider: str, source_id: str | None
    ) -> tuple[DirectorySource, dict[str, Any]]:
        sources = await self._login_sources(provider)
        if source_id:
            sources = [s for s in sources if s[0].id == source_id]
        label = PROVIDER_LABEL[provider]
        if not sources:
            raise BridgeError(
                f"{label}登录尚未配置，请联系管理员在「组织同步」中填写扫码登录参数",
                code="OIDC_BRIDGE_NOT_CONFIGURED",
            )
        if len(sources) > 1:
            raise BridgeError(
                f"存在多个{label}登录数据源，"
                "请在 Keycloak 身份提供方的授权地址上加 ?source=<数据源ID>",
                code="OIDC_BRIDGE_AMBIGUOUS",
            )
        return sources[0]

    async def authorize(
        self,
        provider: str,
        *,
        client_id: str | None,
        redirect_uri: str | None,
        response_type: str | None,
        state: str | None,
        nonce: str | None,
        source_id: str | None,
        user_agent: str,
    ) -> AuthorizeResult:
        self._check_provider(provider)
        if not client_id or not hmac.compare_digest(client_id, self.settings.oidc_bridge_client_id):
            raise BridgeError("client_id 不正确", code="OIDC_BRIDGE_CLIENT")
        if redirect_uri != self.broker_redirect_uri(provider):
            raise BridgeError("redirect_uri 不在允许范围内", code="OIDC_BRIDGE_REDIRECT_URI")
        if response_type != "code":
            raise BridgeError("仅支持 response_type=code", code="OIDC_BRIDGE_RESPONSE_TYPE")
        if not state:
            raise BridgeError("缺少 state 参数", code="OIDC_BRIDGE_STATE")
        source, config = await self._source(provider, source_id)
        state_key = secrets.token_urlsafe(24)
        await self.cache.set(
            STATE_PREFIX + _digest(state_key),
            json.dumps(
                {
                    "provider": provider,
                    "source_id": source.id,
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "nonce": nonce,
                }
            ),
            self.settings.oidc_bridge_state_ttl_seconds,
        )
        login = LOGIN_PROVIDERS[provider](config)
        return AuthorizeResult(
            login.login_url(self.callback_url(provider), state_key, user_agent), state_key
        )

    async def callback(
        self, provider: str, params: dict[str, str], cookie_state: str | None
    ) -> str:
        """Returns the URL to send the browser back to (Keycloak's broker endpoint)."""
        self._check_provider(provider)
        state_key = params.get("state") or ""
        if not state_key or not cookie_state or not hmac.compare_digest(state_key, cookie_state):
            raise BridgeError("登录会话已失效，请返回重新登录", code="OIDC_BRIDGE_STATE")
        raw = await self.cache.pop(STATE_PREFIX + _digest(state_key))
        if raw is None:
            raise BridgeError("登录会话已过期，请返回重新登录", code="OIDC_BRIDGE_STATE")
        pending: dict[str, Any] = json.loads(raw)
        if pending["provider"] != provider:
            raise BridgeError("登录会话不匹配，请返回重新登录", code="OIDC_BRIDGE_STATE")

        login_cls = LOGIN_PROVIDERS[provider]
        code = login_cls.callback_code(params)
        if not code:
            raise BridgeError("已取消授权或未获得授权码", code="OIDC_BRIDGE_DENIED")
        source, config = await self._source(provider, pending["source_id"])
        login = login_cls(config)
        user, org = await self._resolve_user(provider, source, login, code)

        one_time = secrets.token_urlsafe(32)
        await self.cache.set(
            CODE_PREFIX + _digest(one_time),
            json.dumps(
                {
                    "provider": provider,
                    "client_id": pending["client_id"],
                    "redirect_uri": pending["redirect_uri"],
                    "nonce": pending.get("nonce"),
                    "sub": user.id,
                    "preferred_username": user.username,
                    "name": user.display_name or user.username,
                    "email": user.email,
                    "org_id": org.code,
                }
            ),
            self.settings.oidc_bridge_code_ttl_seconds,
        )
        logger.info(
            "oidc_bridge_login",
            extra={"provider": provider, "org_id": org.id, "user_id": user.id},
        )
        query = urlencode({"code": one_time, "state": pending["state"]})
        return f"{pending['redirect_uri']}?{query}"

    async def _resolve_user(
        self, provider: str, source: DirectorySource, login: LoginProvider, code: str
    ) -> tuple[User, Organization]:
        label = PROVIDER_LABEL[provider]
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.directory_http_timeout_seconds, transport=self.transport
            ) as http:
                upstream = await login.resolve(http, code)
                identity = None
                if upstream.external_id:
                    identity = await self._identity(source.org_id, provider, upstream.external_id)
                elif upstream.union_id:
                    identity = await self._identity_by_union(
                        source.org_id, provider, upstream.union_id
                    )
                    if identity is None:
                        userid = await login.userid_by_unionid(http, upstream.union_id)
                        if userid:
                            identity = await self._identity(source.org_id, provider, userid)
        except ConnectorError as exc:
            logger.warning("oidc_bridge_upstream_error", extra={"provider": provider})
            raise BridgeError(
                f"{label}身份校验失败：{exc.message}", code="OIDC_BRIDGE_UPSTREAM"
            ) from exc
        if upstream.external_id is None and upstream.union_id is None:
            raise BridgeError(f"当前账号不是本企业的{label}成员", code="OIDC_BRIDGE_NOT_MEMBER")
        if identity is None:
            raise BridgeError(
                f"你的{label}账号尚未同步到知识库平台，请联系管理员执行组织同步",
                code="OIDC_BRIDGE_UNMATCHED",
            )
        user = await self.session.get(User, identity.user_id)
        org = await self.session.get(Organization, source.org_id)
        if user is None or org is None:
            raise BridgeError("账号不存在，请联系管理员", code="OIDC_BRIDGE_UNMATCHED")
        if not user.is_active or org.status != "active":
            raise BridgeError("账号已停用，请联系管理员", code="OIDC_BRIDGE_USER_DISABLED")
        return user, org

    async def _identity(self, org_id: str, provider: str, external_id: str) -> UserIdentity | None:
        return (
            await self.session.execute(
                select(UserIdentity).where(
                    UserIdentity.org_id == org_id,
                    UserIdentity.provider == provider,
                    UserIdentity.external_id == external_id,
                )
            )
        ).scalar_one_or_none()

    async def _identity_by_union(
        self, org_id: str, provider: str, union_id: str
    ) -> UserIdentity | None:
        return (
            await self.session.execute(
                select(UserIdentity)
                .where(
                    UserIdentity.org_id == org_id,
                    UserIdentity.provider == provider,
                    UserIdentity.union_id == union_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    # ---- back channel -----------------------------------------------------------------

    def _check_client(self, client_id: str | None, client_secret: str | None) -> None:
        s = self.settings
        ok = (
            client_id is not None
            and client_secret is not None
            and hmac.compare_digest(client_id, s.oidc_bridge_client_id)
            and hmac.compare_digest(client_secret, s.oidc_bridge_client_secret)
        )
        if not ok:
            raise OAuthError("invalid_client", "client authentication failed", 401)

    async def token(
        self,
        provider: str,
        *,
        grant_type: str | None,
        code: str | None,
        redirect_uri: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> dict[str, Any]:
        if not self.settings.oidc_bridge_enabled or provider not in LOGIN_PROVIDERS:
            raise OAuthError("invalid_request", "unknown provider", 404)
        self._check_client(client_id, client_secret)
        if grant_type != "authorization_code":
            raise OAuthError("unsupported_grant_type", "only authorization_code is supported")
        if not code:
            raise OAuthError("invalid_request", "code is required")
        raw = await self.cache.pop(CODE_PREFIX + _digest(code))
        if raw is None:
            raise OAuthError("invalid_grant", "code is invalid, expired or already used")
        grant: dict[str, Any] = json.loads(raw)
        if grant["provider"] != provider or grant["client_id"] != client_id:
            raise OAuthError("invalid_grant", "code was issued to another client")
        if redirect_uri != grant["redirect_uri"]:
            raise OAuthError("invalid_grant", "redirect_uri mismatch")

        key = await load_signing_key(self.settings, self.cache)
        now = int(time.time())
        ttl = self.settings.oidc_bridge_token_ttl_seconds
        profile = {
            k: grant[k] for k in ("preferred_username", "name", "email", "org_id") if grant.get(k)
        }
        id_claims: dict[str, Any] = {
            "iss": self.issuer(provider),
            "sub": grant["sub"],
            "aud": client_id,
            "iat": now,
            "exp": now + ttl,
            **profile,
        }
        if grant.get("nonce"):
            id_claims["nonce"] = grant["nonce"]
        access_claims = {
            "iss": self.issuer(provider),
            "sub": grant["sub"],
            "aud": f"{self.issuer(provider)}/userinfo",
            "iat": now,
            "exp": now + ttl,
            "scope": "openid profile email",
            **profile,
        }
        return {
            "access_token": self._sign(key, access_claims),
            "token_type": "Bearer",
            "expires_in": ttl,
            "id_token": self._sign(key, id_claims),
            "scope": "openid profile email",
        }

    @staticmethod
    def _sign(key: SigningKey, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid})

    async def userinfo(self, provider: str, access_token: str | None) -> dict[str, Any]:
        if not access_token:
            raise OAuthError("invalid_token", "missing access token", 401)
        key = await load_signing_key(self.settings, self.cache)
        try:
            claims = jwt.decode(
                access_token,
                key.private_key.public_key(),
                algorithms=["RS256"],
                audience=f"{self.issuer(provider)}/userinfo",
                issuer=self.issuer(provider),
            )
        except jwt.PyJWTError as exc:
            raise OAuthError("invalid_token", "access token is invalid", 401) from exc
        return {
            k: claims[k]
            for k in ("sub", "preferred_username", "name", "email", "org_id")
            if k in claims
        }
