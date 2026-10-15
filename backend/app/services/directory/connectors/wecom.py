"""WeCom (企业微信) contacts: gettoken -> department/list -> user/list per department.

Needs the "通讯录同步" secret and the server's egress IP in the corp's trusted IP list
(errcode 60020 otherwise). Fields restricted by WeCom (mobile / email for newer apps) come
back empty and are kept locally (see reconciler.KEEP_IF_EMPTY).
"""

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.services.directory.connectors.base import ConnectorError, HttpConnector
from app.services.directory.snapshot import DeptRecord, Snapshot, UserRecord

TOKEN_EXPIRED = {40014, 42001}
ERROR_HINTS = {
    60020: "服务器出口 IP 不在企业可信 IP 列表中（应用管理 → 企业可信IP）",
    40001: "Secret 错误，或不是「通讯录同步」的 Secret",
    40013: "CorpID 错误",
    48009: "该接口需要使用「通讯录同步」Secret",
    60011: "Secret 对应的应用没有通讯录范围权限",
}
# 1 = active, 4 = not activated yet (still employed); 2 = disabled, 5 = left.
ACTIVE_STATUSES = {1, 4}


class WeComConfig(BaseModel):
    corp_id: str = Field(min_length=1, max_length=64)
    contacts_secret: str = Field(min_length=1, max_length=256)
    root_department_id: int = 1
    # WeCom has no built-in employee number: name of the custom attribute holding it.
    employee_no_attr: str | None = Field(default="工号", max_length=64)
    # QR-code login (self-built app): AgentId and its Secret.
    agent_id: str | None = Field(default=None, max_length=32)
    agent_secret: str | None = Field(default=None, max_length=256)
    api_base: str = "https://qyapi.weixin.qq.com"


def _ext_attr(user: dict[str, Any], name: str | None) -> str | None:
    if not name:
        return None
    for attr in (user.get("extattr") or {}).get("attrs") or []:
        if attr.get("name") == name:
            value = (attr.get("text") or {}).get("value") or attr.get("value")
            return str(value) if value else None
    return None


class WeComClient:
    """Shared by the connector (contacts secret) and the QR-code login (agent secret)."""

    def __init__(self, http: httpx.AsyncClient, api_base: str, corp_id: str, secret: str) -> None:
        self.http = http
        self.base = api_base.rstrip("/")
        self.corp_id = corp_id
        self.secret = secret
        self._token: str | None = None

    async def _token_value(self, refresh: bool = False) -> str:
        if self._token is None or refresh:
            resp = await self.http.get(
                f"{self.base}/cgi-bin/gettoken",
                params={"corpid": self.corp_id, "corpsecret": self.secret},
            )
            data = await HttpConnector.json(resp)
            self._check(data)
            self._token = str(data["access_token"])
        return self._token

    @staticmethod
    def _check(data: dict[str, Any]) -> None:
        code = int(data.get("errcode", 0) or 0)
        if code:
            raise ConnectorError(
                f"企业微信接口错误 {code}: {ERROR_HINTS.get(code, data.get('errmsg', ''))}",
                detail={"errcode": code, "errmsg": data.get("errmsg")},
            )

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        token = await self._token_value()
        for attempt in range(2):
            resp = await self.http.get(
                f"{self.base}{path}", params={"access_token": token, **params}
            )
            data = await HttpConnector.json(resp)
            if int(data.get("errcode", 0) or 0) in TOKEN_EXPIRED and attempt == 0:
                token = await self._token_value(refresh=True)
                continue
            self._check(data)
            return data
        raise ConnectorError("企业微信 access_token 刷新失败")


class WeComConnector(HttpConnector):
    config_model = WeComConfig
    secret_fields = ("contacts_secret", "agent_secret")

    async def fetch(self) -> Snapshot:
        cfg = WeComConfig.model_validate(self.raw_config)
        async with self.client() as http:
            api = WeComClient(http, cfg.api_base, cfg.corp_id, cfg.contacts_secret)
            data = await api.get("/cgi-bin/department/list", id=cfg.root_department_id)
            raw_depts = data.get("department") or []
            depts = [
                DeptRecord(
                    external_id=str(d["id"]),
                    name=str(d.get("name") or d["id"]),
                    parent_external_id=(
                        None
                        if int(d["id"]) == cfg.root_department_id
                        else str(d.get("parentid") or "") or None
                    ),
                    # WeCom: larger order first; locally smaller sort_order first.
                    order=-int(d.get("order") or 0),
                )
                for d in raw_depts
            ]
            semaphore = asyncio.Semaphore(8)

            async def users_of(dept_id: str) -> list[dict[str, Any]]:
                async with semaphore:
                    result = await api.get("/cgi-bin/user/list", department_id=dept_id)
                    return list(result.get("userlist") or [])

            pages = await asyncio.gather(*(users_of(d.external_id) for d in depts))
        users: dict[str, UserRecord] = {}
        for page in pages:
            for u in page:
                uid = str(u["userid"])
                if uid in users:
                    continue
                dept_ids = [str(x) for x in u.get("department") or []]
                users[uid] = UserRecord(
                    external_id=uid,
                    username=uid,
                    name=str(u.get("name") or uid),
                    email=u.get("biz_mail") or u.get("email") or None,
                    mobile=u.get("mobile") or None,
                    employee_no=_ext_attr(u, cfg.employee_no_attr),
                    title=u.get("position") or None,
                    dept_external_ids=dept_ids,
                    primary_dept=str(u["main_department"]) if u.get("main_department") else None,
                    active=int(u.get("status") or 1) in ACTIVE_STATUSES,
                )
        return Snapshot(departments=depts, users=list(users.values()))
