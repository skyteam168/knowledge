import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from openpyxl import Workbook

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.services.directory.connectors.base import ConnectorError
from app.services.directory.connectors.dingtalk import DingTalkConnector
from app.services.directory.connectors.excel import build_template, parse_workbook
from app.services.directory.connectors.weaver import WeaverConfig, WeaverConnector
from app.services.directory.connectors.wecom import WeComConnector

WECOM_CONFIG = {"corp_id": "ww-corp", "contacts_secret": "s3cret", "employee_no_attr": "工号"}
DINGTALK_CONFIG = {"app_key": "ding-key", "app_secret": "ding-secret"}


def _json(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


# ---- WeCom ------------------------------------------------------------------------------


class FakeWeCom:
    def __init__(self, token_error: int | None = None) -> None:
        self.tokens = 0
        self.token_error = token_error
        self.expired_once = False
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        self.calls.append(path)
        if path == "/cgi-bin/gettoken":
            assert params["corpid"] == "ww-corp" and params["corpsecret"] == "s3cret"
            if self.token_error:
                return _json({"errcode": self.token_error, "errmsg": "denied"})
            self.tokens += 1
            return _json({"errcode": 0, "access_token": f"t{self.tokens}", "expires_in": 7200})
        if path == "/cgi-bin/department/list":
            if params["access_token"] == "t1" and not self.expired_once:
                self.expired_once = True
                return _json({"errcode": 42001, "errmsg": "access_token expired"})
            return _json(
                {
                    "errcode": 0,
                    "department": [
                        {"id": 1, "name": "集团", "parentid": 0, "order": 100},
                        {"id": 2, "name": "越南Flyknit", "parentid": 1, "order": 90},
                        {"id": 3, "name": "织造车间", "parentid": 2, "order": 80},
                    ],
                }
            )
        if path == "/cgi-bin/user/list":
            dept = params["department_id"]
            users = {
                "1": [],
                "2": [
                    {
                        "userid": "zhangsan",
                        "name": "张三",
                        "department": [2, 3],
                        "main_department": 3,
                        "position": "班组长",
                        "status": 1,
                        "extattr": {"attrs": [{"name": "工号", "text": {"value": "VN0001"}}]},
                    }
                ],
                "3": [
                    {"userid": "zhangsan", "name": "张三", "department": [2, 3], "status": 1},
                    {"userid": "lisi", "name": "李四", "department": [3], "status": 5},
                    {"userid": "wangwu", "name": "王五", "department": [3], "status": 4},
                ],
            }[dept]
            return _json({"errcode": 0, "userlist": users})
        raise AssertionError(f"unexpected call {path}")


async def test_wecom_fetch_refreshes_token_and_maps_fields(settings: Settings) -> None:
    fake = FakeWeCom()
    snap = await WeComConnector(WECOM_CONFIG, settings, transport=httpx.MockTransport(fake)).fetch()

    assert fake.tokens == 2, "expired token (42001) must be refreshed once"
    depts = {d.external_id: d for d in snap.departments}
    assert depts["1"].parent_external_id is None
    assert depts["3"].parent_external_id == "2"
    assert depts["1"].order < depts["3"].order, "WeCom: larger order sorts first"

    users = {u.external_id: u for u in snap.users}
    assert set(users) == {"zhangsan", "lisi", "wangwu"}, "duplicates across departments merged"
    zhang = users["zhangsan"]
    assert zhang.dept_external_ids == ["2", "3"] and zhang.primary_dept == "3"
    assert zhang.employee_no == "VN0001" and zhang.title == "班组长" and zhang.active
    assert users["lisi"].active is False, "status 5 = left"
    assert users["wangwu"].active is True, "status 4 = not activated yet, still employed"


async def test_wecom_error_codes_have_actionable_hints(settings: Settings) -> None:
    connector = WeComConnector(
        WECOM_CONFIG, settings, transport=httpx.MockTransport(FakeWeCom(token_error=60020))
    )
    with pytest.raises(ConnectorError) as exc:
        await connector.fetch()
    assert "可信 IP" in exc.value.message and exc.value.detail["errcode"] == 60020

    result = await WeComConnector(
        WECOM_CONFIG, settings, transport=httpx.MockTransport(FakeWeCom())
    ).test()
    assert result == {"departments": 3, "users": 3, "active_users": 2, "warnings": []}


# ---- DingTalk ---------------------------------------------------------------------------


class FakeDingTalk:
    def __init__(self) -> None:
        self.tokens = 0
        self.expired_once = False
        self.pages: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1.0/oauth2/accessToken":
            body = json.loads(request.content)
            if body["appSecret"] != "ding-secret":
                return httpx.Response(400, json={"code": "invalidClientSecret"})
            self.tokens += 1
            return _json({"accessToken": f"a{self.tokens}", "expireIn": 7200})
        body = json.loads(request.content)
        token = request.url.params["access_token"]
        if path == "/topapi/v2/department/get":
            return _json({"errcode": 0, "result": {"dept_id": 1, "name": "集团"}})
        if path == "/topapi/v2/department/listsub":
            if token == "a1" and not self.expired_once:
                self.expired_once = True
                return _json({"errcode": 88, "errmsg": "token expired"})
            children = {
                1: [{"dept_id": 2, "name": "华东工厂", "parent_id": 1}],
                2: [{"dept_id": 3, "name": "品质部", "parent_id": 2}],
                3: [],
            }[int(body["dept_id"])]
            return _json({"errcode": 0, "result": children})
        if path == "/topapi/v2/user/list":
            dept, cursor = int(body["dept_id"]), int(body["cursor"])
            assert body["size"] == 100
            if dept == 3 and cursor == 0:
                self.pages.append(cursor)
                return _json(
                    {
                        "errcode": 0,
                        "result": {
                            "has_more": True,
                            "next_cursor": 1,
                            "list": [
                                {
                                    "userid": "u1",
                                    "unionid": "union-1",
                                    "name": "赵六",
                                    "job_number": "D001",
                                    "title": "质检员",
                                    "dept_id_list": [3, 2],
                                }
                            ],
                        },
                    }
                )
            if dept == 3 and cursor == 1:
                self.pages.append(cursor)
                return _json(
                    {
                        "errcode": 0,
                        "result": {
                            "has_more": False,
                            "list": [{"userid": "u2", "name": "钱七", "dept_id_list": [3]}],
                        },
                    }
                )
            return _json({"errcode": 0, "result": {"has_more": False, "list": []}})
        raise AssertionError(f"unexpected call {path}")


async def test_dingtalk_fetch_recurses_paginates_and_refreshes(settings: Settings) -> None:
    fake = FakeDingTalk()
    snap = await DingTalkConnector(
        DINGTALK_CONFIG, settings, transport=httpx.MockTransport(fake)
    ).fetch()

    assert fake.tokens == 2, "errcode 88 must refresh the token once"
    assert fake.pages == [0, 1], "cursor pagination followed until has_more=false"
    depts = {d.external_id: d for d in snap.departments}
    assert depts["1"].name == "集团" and depts["3"].parent_external_id == "2"
    users = {u.external_id: u for u in snap.users}
    assert users["u1"].username == "D001", "job number preferred as account"
    assert users["u1"].union_id == "union-1" and users["u1"].title == "质检员"
    assert users["u1"].dept_external_ids == ["3", "2"]
    assert users["u2"].username == "u2", "falls back to userid"


async def test_dingtalk_bad_secret(settings: Settings) -> None:
    connector = DingTalkConnector(
        {**DINGTALK_CONFIG, "app_secret": "wrong"},
        settings,
        transport=httpx.MockTransport(FakeDingTalk()),
    )
    with pytest.raises(ConnectorError) as exc:
        await connector.fetch()
    assert "AppKey / AppSecret" in exc.value.message


# ---- Weaver e-cology 9 ------------------------------------------------------------------

WEAVER_SCHEMA = """
CREATE TABLE HrmSubCompany (id INTEGER, subcompanyname TEXT, supsubcomid INTEGER,
    showorder REAL, canceled TEXT);
CREATE TABLE HrmDepartment (id INTEGER, departmentname TEXT, supdepid INTEGER,
    subcompanyid1 INTEGER, showorder REAL, canceled TEXT);
CREATE TABLE HrmJobTitles (id INTEGER, jobtitlename TEXT);
CREATE TABLE HrmResource (id INTEGER, loginid TEXT, workcode TEXT, lastname TEXT,
    email TEXT, mobile TEXT, departmentid INTEGER, status INTEGER, accounttype INTEGER,
    belongto INTEGER, jobtitle INTEGER);
INSERT INTO HrmSubCompany VALUES (1, '集团', 0, 1, NULL), (2, '越南Flyknit', 1, 2, '0'),
    (3, '旧分部', 1, 3, '1');
INSERT INTO HrmDepartment VALUES (10, '织造车间', 0, 2, 1, NULL), (11, '织造一组', 10, 2, 1, NULL),
    (12, '品质部', 0, 2, 2, NULL), (20, '法务部', 0, 1, 1, NULL), (21, '已封存部门', 0, 1, 9, '1');
INSERT INTO HrmJobTitles VALUES (1, '班组长'), (2, '法务专员');
INSERT INTO HrmResource VALUES
    (100, 'zhangsan', 'VN0001', '张三', 'zs@example.com', '', 11, 1, 0, NULL, 1),
    (101, '', '', '张三', '', '', 12, 1, 1, 100, 1),
    (102, 'lisi', 'HQ0002', '李四', '', '13800000000', 20, 5, 0, NULL, 2),
    (103, '', 'HQ0003', '王五', '', '', 20, 0, 0, NULL, NULL),
    (104, 'sysadmin', '', '系统管理员', '', '', NULL, 1, 0, NULL, NULL);
"""

WEAVER_CONFIG = {
    "db_type": "sqlserver",
    "host": "oa-db",
    "database": "ecology",
    "username": "readonly",
    "password": "pw",
}


@pytest.fixture
def weaver_db(tmp_path: Path) -> Path:
    path = tmp_path / "ecology.db"
    conn = sqlite3.connect(path)
    conn.executescript(WEAVER_SCHEMA)
    conn.commit()
    conn.close()
    return path


async def test_weaver_default_sql_builds_tree_secondary_accounts_and_status(
    settings: Settings, weaver_db: Path
) -> None:
    seen: list[WeaverConfig] = []

    def connect(cfg: WeaverConfig, timeout: int) -> sqlite3.Connection:
        seen.append(cfg)
        return sqlite3.connect(weaver_db)

    snap = await WeaverConnector(WEAVER_CONFIG, settings, connect=connect).fetch()
    assert seen[0].db_type == "sqlserver"

    depts = {d.external_id: d for d in snap.departments}
    assert depts["sub:1"].parent_external_id is None
    assert depts["sub:2"].parent_external_id == "sub:1"
    assert depts["sub:3"].active is False, "canceled=1 subcompany archived"
    assert depts["dept:10"].parent_external_id == "sub:2", "top department under its subcompany"
    assert depts["dept:11"].parent_external_id == "dept:10"
    assert depts["dept:21"].active is False

    users = {u.external_id: u for u in snap.users}
    assert "101" not in users, "secondary account folded into the main account"
    zhang = users["100"]
    assert zhang.username == "zhangsan" and zhang.employee_no == "VN0001"
    assert zhang.dept_external_ids == ["dept:11", "dept:12"] and zhang.primary_dept == "dept:11"
    assert zhang.title == "班组长" and zhang.active
    assert users["102"].active is False, "status 5 = dismissed"
    assert users["103"].username == "HQ0003", "no loginid: work code as account"
    assert users["103"].active is True, "status 0 = probation"

    normalized = snap.normalized()
    paths = {d.external_id for d in normalized.departments}
    assert {"sub:1", "sub:2", "dept:10", "dept:11", "dept:12", "dept:20"} <= paths


async def test_weaver_without_subcompanies_and_sql_override(
    settings: Settings, weaver_db: Path
) -> None:
    config = {
        **WEAVER_CONFIG,
        "include_subcompanies": False,
        "sql_users": (
            "SELECT id, loginid, workcode, lastname AS name, email, mobile, departmentid, "
            "status, accounttype, belongto, NULL AS title FROM HrmResource WHERE id <> 104"
        ),
    }
    snap = await WeaverConnector(
        config, settings, connect=lambda cfg, t: sqlite3.connect(weaver_db)
    ).fetch()
    assert not any(d.external_id.startswith("sub:") for d in snap.departments)
    assert {d.external_id: d for d in snap.departments}["dept:10"].parent_external_id is None
    assert "104" not in {u.external_id for u in snap.users}


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM HrmResource",
        "SELECT 1; DROP TABLE HrmResource",
        "UPDATE HrmResource SET status = 5",
        "EXEC sp_who",
    ],
)
def test_weaver_sql_override_must_be_read_only(sql: str) -> None:
    with pytest.raises(ValueError):
        WeaverConfig.model_validate({**WEAVER_CONFIG, "sql_users": sql})


async def test_weaver_connection_and_query_errors(settings: Settings, weaver_db: Path) -> None:
    def refuse(cfg: WeaverConfig, timeout: int) -> sqlite3.Connection:
        raise OSError("connection refused")

    with pytest.raises(ConnectorError, match="无法连接泛微数据库"):
        await WeaverConnector(WEAVER_CONFIG, settings, connect=refuse).fetch()

    broken = {**WEAVER_CONFIG, "sql_departments": "SELECT id FROM NoSuchTable"}
    with pytest.raises(ConnectorError, match="sql_departments"):
        await WeaverConnector(
            broken, settings, connect=lambda cfg, t: sqlite3.connect(weaver_db)
        ).fetch()


# ---- Excel ------------------------------------------------------------------------------


def test_excel_template_round_trip() -> None:
    snap = parse_workbook(build_template())
    depts = {d.external_id: d for d in snap.departments}
    assert depts["集团/越南Flyknit/织造车间"].parent_external_id == "集团/越南Flyknit"
    assert depts["集团"].parent_external_id is None
    users = {u.username: u for u in snap.users}
    zhang = users["zhangsan"]
    assert zhang.dept_external_ids == ["集团/越南Flyknit/织造车间", "集团/越南Flyknit/品质部"]
    assert zhang.primary_dept == "集团/越南Flyknit/织造车间"
    assert zhang.employee_no == "VN0001" and zhang.title == "班组长"
    assert users["lisi"].mobile == "13800000000"


def _workbook(rows: list[list[Any]]) -> bytes:
    import io

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_validation_errors() -> None:
    with pytest.raises(ValidationAppError) as missing:
        parse_workbook(_workbook([["账号", "姓名"], ["a", "A"]]))
    assert missing.value.detail == {"missing": ["部门路径"]}

    with pytest.raises(ValidationAppError) as bad_row:
        parse_workbook(_workbook([["部门路径", "账号", "姓名"], ["集团/A", "", "无账号"]]))
    assert "第 2 行" in bad_row.value.detail["errors"][0]

    with pytest.raises(ValidationAppError):
        parse_workbook(b"not an xlsx")

    snap = parse_workbook(
        _workbook(
            [
                ["部门路径", "账号", "姓名", "在职", "工号"],
                ["集团\\B ", "u1", "甲", "否", 1001.0],
                [None, None, None, None, None],
            ]
        )
    )
    assert snap.users[0].active is False and snap.users[0].employee_no == "1001"
    assert [d.external_id for d in snap.departments] == ["集团", "集团/B"]
