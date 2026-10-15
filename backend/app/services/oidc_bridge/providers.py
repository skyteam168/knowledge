"""Upstream QR-code / in-app OAuth for WeCom and DingTalk (both non-standard OAuth2)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.services.directory.connectors.base import ConnectorError, HttpConnector
from app.services.directory.connectors.dingtalk import DingTalkClient, DingTalkConfig
from app.services.directory.connectors.wecom import WeComClient, WeComConfig


@dataclass(frozen=True)
class UpstreamIdentity:
    external_id: str | None
    union_id: str | None = None


class LoginProvider(ABC):
    def __init__(self, config: dict[str, Any]) -> None:
        self.raw_config = config

    @abstractmethod
    def login_url(self, redirect_uri: str, state: str, user_agent: str) -> str: ...

    @staticmethod
    @abstractmethod
    def callback_code(params: dict[str, str]) -> str | None: ...

    @abstractmethod
    async def resolve(self, http: httpx.AsyncClient, code: str) -> UpstreamIdentity: ...

    async def userid_by_unionid(self, http: httpx.AsyncClient, union_id: str) -> str | None:
        return None


class WeComLogin(LoginProvider):
    QR_URL = "https://login.work.weixin.qq.com/wwlogin/sso/login"
    IN_APP_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.cfg = WeComConfig.model_validate(config)

    def login_url(self, redirect_uri: str, state: str, user_agent: str) -> str:
        if "wxwork" in user_agent.lower():
            # Opened inside the WeCom client: silent OAuth, no QR code.
            query = urlencode(
                {
                    "appid": self.cfg.corp_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "snsapi_base",
                    "state": state,
                    "agentid": self.cfg.agent_id or "",
                }
            )
            return f"{self.IN_APP_URL}?{query}#wechat_redirect"
        query = urlencode(
            {
                "login_type": "CorpApp",
                "appid": self.cfg.corp_id,
                "agentid": self.cfg.agent_id or "",
                "redirect_uri": redirect_uri,
                "state": state,
            }
        )
        return f"{self.QR_URL}?{query}"

    @staticmethod
    def callback_code(params: dict[str, str]) -> str | None:
        return params.get("code")

    async def resolve(self, http: httpx.AsyncClient, code: str) -> UpstreamIdentity:
        api = WeComClient(http, self.cfg.api_base, self.cfg.corp_id, self.cfg.agent_secret or "")
        data = await api.get("/cgi-bin/auth/getuserinfo", code=code)
        # Non-members only get an openid.
        userid = data.get("userid") or data.get("UserId")
        return UpstreamIdentity(external_id=str(userid) if userid else None)


class DingTalkLogin(LoginProvider):
    AUTH_URL = "https://login.dingtalk.com/oauth2/auth"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.cfg = DingTalkConfig.model_validate(config)

    def login_url(self, redirect_uri: str, state: str, user_agent: str) -> str:
        query = urlencode(
            {
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "client_id": self.cfg.app_key,
                "scope": "openid",
                "state": state,
                "prompt": "consent",
            }
        )
        return f"{self.AUTH_URL}?{query}"

    @staticmethod
    def callback_code(params: dict[str, str]) -> str | None:
        return params.get("authCode") or params.get("code")

    async def resolve(self, http: httpx.AsyncClient, code: str) -> UpstreamIdentity:
        base = self.cfg.api_base.rstrip("/")
        resp = await http.post(
            f"{base}/v1.0/oauth2/userAccessToken",
            json={
                "clientId": self.cfg.app_key,
                "clientSecret": self.cfg.app_secret,
                "code": code,
                "grantType": "authorization_code",
            },
        )
        token = (await HttpConnector.json(resp)).get("accessToken")
        if not token:
            raise ConnectorError("钉钉获取用户 accessToken 失败")
        resp = await http.get(
            f"{base}/v1.0/contact/users/me", headers={"x-acs-dingtalk-access-token": str(token)}
        )
        me = await HttpConnector.json(resp)
        union_id = me.get("unionId")
        return UpstreamIdentity(external_id=None, union_id=str(union_id) if union_id else None)

    async def userid_by_unionid(self, http: httpx.AsyncClient, union_id: str) -> str | None:
        data = await DingTalkClient(http, self.cfg).topapi(
            "/topapi/user/getbyunionid", {"unionid": union_id}
        )
        userid = (data.get("result") or {}).get("userid")
        return str(userid) if userid else None


LOGIN_PROVIDERS: dict[str, type[LoginProvider]] = {
    "wecom": WeComLogin,
    "dingtalk": DingTalkLogin,
}
