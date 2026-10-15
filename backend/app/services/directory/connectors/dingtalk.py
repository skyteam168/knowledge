"""DingTalk (钉钉) contacts: v1.0 accessToken -> department/listsub (recursive) -> user/list.

The internal app needs the contacts read permissions (通讯录部门信息读权限 / 成员信息读权限,
plus 手机号 / 邮箱 / 工号 fields if those should be synced).
"""

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.services.directory.connectors.base import ConnectorError, HttpConnector
from app.services.directory.snapshot import DeptRecord, Snapshot, UserRecord

TOKEN_EXPIRED = {88, 40014, 42001}
ERROR_HINTS = {
    60011: "应用没有通讯录权限（开发者后台 → 权限管理）",
    60020: "服务器 IP 不在应用的白名单中",
    40089: "AppKey / AppSecret 不正确",
}
PAGE_SIZE = 100


class DingTalkConfig(BaseModel):
    app_key: str = Field(min_length=1, max_length=128)
    app_secret: str = Field(min_length=1, max_length=256)
    root_dept_id: int = 1
    api_base: str = "https://api.dingtalk.com"
    oapi_base: str = "https://oapi.dingtalk.com"


class DingTalkClient:
    def __init__(self, http: httpx.AsyncClient, cfg: DingTalkConfig) -> None:
        self.http = http
        self.cfg = cfg
        self._token: str | None = None

    async def token(self, refresh: bool = False) -> str:
        if self._token is None or refresh:
            resp = await self.http.post(
                f"{self.cfg.api_base.rstrip('/')}/v1.0/oauth2/accessToken",
                json={"appKey": self.cfg.app_key, "appSecret": self.cfg.app_secret},
            )
            if resp.status_code >= 400:
                body = resp.text[:500]
                raise ConnectorError(
                    f"钉钉获取 accessToken 失败（HTTP {resp.status_code}），"
                    "请检查 AppKey / AppSecret",
                    detail={"body": body},
                )
            data = await HttpConnector.json(resp)
            if not data.get("accessToken"):
                raise ConnectorError("钉钉获取 accessToken 失败", detail=data)
            self._token = str(data["accessToken"])
        return self._token

    @staticmethod
    def _check(data: dict[str, Any]) -> None:
        code = int(data.get("errcode", 0) or 0)
        if code:
            raise ConnectorError(
                f"钉钉接口错误 {code}: {ERROR_HINTS.get(code, data.get('errmsg', ''))}",
                detail={"errcode": code, "errmsg": data.get("errmsg")},
            )

    async def topapi(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = await self.token()
        for attempt in range(2):
            resp = await self.http.post(
                f"{self.cfg.oapi_base.rstrip('/')}{path}",
                params={"access_token": token},
                json=body,
            )
            data = await HttpConnector.json(resp)
            if int(data.get("errcode", 0) or 0) in TOKEN_EXPIRED and attempt == 0:
                token = await self.token(refresh=True)
                continue
            self._check(data)
            return data
        raise ConnectorError("钉钉 access_token 刷新失败")


class DingTalkConnector(HttpConnector):
    config_model = DingTalkConfig
    secret_fields = ("app_secret",)

    async def fetch(self) -> Snapshot:
        cfg = DingTalkConfig.model_validate(self.raw_config)
        semaphore = asyncio.Semaphore(8)
        async with self.client() as http:
            api = DingTalkClient(http, cfg)
            root = await api.topapi("/topapi/v2/department/get", {"dept_id": cfg.root_dept_id})
            root_info = root.get("result") or {}
            depts = [
                DeptRecord(
                    external_id=str(cfg.root_dept_id),
                    name=str(root_info.get("name") or cfg.root_dept_id),
                )
            ]

            async def children(dept_id: str) -> list[dict[str, Any]]:
                async with semaphore:
                    data = await api.topapi("/topapi/v2/department/listsub", {"dept_id": dept_id})
                    return list(data.get("result") or [])

            level = [str(cfg.root_dept_id)]
            seen = set(level)
            while level:
                results = await asyncio.gather(*(children(d) for d in level))
                level = []
                for items in results:
                    for d in items:
                        did = str(d["dept_id"])
                        if did in seen:
                            continue
                        seen.add(did)
                        level.append(did)
                        depts.append(
                            DeptRecord(
                                external_id=did,
                                name=str(d.get("name") or did),
                                parent_external_id=str(d.get("parent_id") or "") or None,
                                order=int(d.get("order") or 0),
                            )
                        )

            async def users_of(dept_id: str) -> list[dict[str, Any]]:
                result: list[dict[str, Any]] = []
                cursor = 0
                async with semaphore:
                    while True:
                        data = await api.topapi(
                            "/topapi/v2/user/list",
                            {"dept_id": int(dept_id), "cursor": cursor, "size": PAGE_SIZE},
                        )
                        page = data.get("result") or {}
                        result.extend(page.get("list") or [])
                        if not page.get("has_more"):
                            return result
                        cursor = int(page.get("next_cursor") or 0)

            pages = await asyncio.gather(*(users_of(d.external_id) for d in depts))
        users: dict[str, UserRecord] = {}
        for page in pages:
            for u in page:
                uid = str(u["userid"])
                if uid in users:
                    continue
                users[uid] = UserRecord(
                    external_id=uid,
                    username=str(u.get("job_number") or uid),
                    name=str(u.get("name") or uid),
                    email=u.get("org_email") or u.get("email") or None,
                    mobile=u.get("mobile") or None,
                    employee_no=u.get("job_number") or None,
                    title=u.get("title") or None,
                    dept_external_ids=[str(x) for x in u.get("dept_id_list") or []],
                    union_id=u.get("unionid") or None,
                    # Users returned by user/list are on the roster (left = removed upstream).
                    active=True,
                )
        return Snapshot(departments=depts, users=list(users.values()))
