import io
from typing import Any

import httpx
from openpyxl import Workbook

from app.services.ingest.queue import RecordingTaskQueue
from tests.conftest import auth

ALICE, CAROL = auth("alice-token"), auth("carol-token")
BASE = "/api/v1/admin/directory"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["部门路径", "账号", "工号", "姓名", "邮箱", "手机", "职务", "是否主部门", "在职"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROSTER = [
    ["集团/越南Flyknit/织造车间", "zhangsan", "VN0001", "张三", "", "", "班组长", "是", "是"],
    ["集团/越南Flyknit/品质部", "zhangsan", "VN0001", "张三", "", "", "班组长", "否", "是"],
    ["集团/总部/法务部", "lisi", "HQ0002", "李四", "", "13800000000", "法务专员", "是", "是"],
]


async def _upload(
    api: httpx.AsyncClient, source_id: str, content: bytes, mode: str, force: bool = False
) -> httpx.Response:
    return await api.post(
        f"{BASE}/sources/{source_id}/upload",
        files={"file": ("roster.xlsx", content, XLSX)},
        data={"mode": mode, "force": str(force).lower()},
        headers=ALICE,
    )


async def _excel_source(api: httpx.AsyncClient) -> dict[str, Any]:
    await api.get("/api/v1/auth/me", headers=ALICE)
    resp = await api.post(
        f"{BASE}/sources",
        json={"type": "excel", "name": "花名册", "is_primary": True},
        headers=ALICE,
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def test_requires_admin_directory_permission(api: httpx.AsyncClient) -> None:
    await api.get("/api/v1/auth/me", headers=ALICE)
    for method, path in (("GET", "/sources"), ("GET", "/runs"), ("GET", "/excel-template")):
        resp = await api.request(method, BASE + path, headers=CAROL)
        assert resp.status_code == 403, path


async def test_excel_preview_then_apply(api: httpx.AsyncClient) -> None:
    source = await _excel_source(api)
    template = await api.get(f"{BASE}/excel-template", headers=ALICE)
    assert template.status_code == 200 and template.headers["content-type"] == XLSX

    preview = await _upload(api, source["id"], _xlsx(ROSTER), "preview")
    assert preview.status_code == 200, preview.text
    run = preview.json()
    assert run["mode"] == "preview" and run["status"] == "succeeded"
    assert run["stats"]["stats"]["departments"]["created"] == 6
    assert run["stats"]["stats"]["users"]["created"] == 2
    users = (await api.get("/api/v1/admin/users", headers=ALICE)).json()
    assert "zhangsan" not in {u["username"] for u in users["items"]}, "preview writes nothing"

    applied = (await _upload(api, source["id"], _xlsx(ROSTER), "apply")).json()
    assert applied["status"] == "succeeded"
    users = (await api.get("/api/v1/admin/users", params={"size": 100}, headers=ALICE)).json()
    zhang = next(u for u in users["items"] if u["username"] == "zhangsan")
    assert zhang["source"] == "excel" and zhang["job_title"] == "班组长"
    assert [(d["path_name"], d["is_primary"]) for d in zhang["departments"]] == [
        ("集团 / 越南Flyknit / 织造车间", True),
        ("集团 / 越南Flyknit / 品质部", False),
    ]

    runs = (await api.get(f"{BASE}/runs", headers=ALICE)).json()
    assert runs["total"] == 2
    detail = (await api.get(f"{BASE}/runs/{applied['id']}", headers=ALICE)).json()
    assert {c["name"] for c in detail["changes"]["users"]} == {"张三", "李四"}
    listed = (await api.get(f"{BASE}/sources", headers=ALICE)).json()
    assert listed[0]["last_status"] == "succeeded" and listed[0]["last_run_id"] == applied["id"]

    # Same file again: nothing to change.
    again = (await _upload(api, source["id"], _xlsx(ROSTER), "apply")).json()
    assert again["stats"]["stats"]["users"]["created"] == 0
    assert again["stats"]["stats"]["users"]["unchanged"] == 2

    # ACL picker shows full department paths.
    options = (
        await api.get(
            "/api/v1/directory/principals",
            params={"type": "dept", "keyword": "品质"},
            headers=ALICE,
        )
    ).json()
    assert any(o["description"] == "集团 / 越南Flyknit / 品质部" for o in options), options
    tree = (await api.get("/api/v1/directory/departments", headers=ALICE)).json()

    def paths(nodes: list[dict[str, Any]]) -> set[str]:
        return {n["path_name"] for n in nodes} | {
            p for n in nodes for p in paths(n.get("children") or [])
        }

    assert "集团 / 总部 / 法务部" in paths(tree)


async def test_synced_fields_are_read_only(api: httpx.AsyncClient) -> None:
    source = await _excel_source(api)
    await _upload(api, source["id"], _xlsx(ROSTER), "apply")
    users = (await api.get("/api/v1/admin/users", params={"size": 100}, headers=ALICE)).json()
    lisi = next(u for u in users["items"] if u["username"] == "lisi")

    blocked = await api.put(
        f"/api/v1/admin/users/{lisi['id']}", json={"display_name": "改名"}, headers=ALICE
    )
    assert blocked.status_code == 400 and blocked.json()["code"] == "DIRECTORY_MANAGED"
    allowed = await api.put(
        f"/api/v1/admin/users/{lisi['id']}", json={"is_active": False}, headers=ALICE
    )
    assert allowed.status_code == 200 and allowed.json()["is_active"] is False

    dept_id = lisi["departments"][0]["id"]
    rename = await api.put(
        f"/api/v1/admin/departments/{dept_id}", json={"name": "法务"}, headers=ALICE
    )
    assert rename.status_code == 400 and rename.json()["code"] == "DIRECTORY_MANAGED"
    delete = await api.delete(f"/api/v1/admin/departments/{dept_id}", headers=ALICE)
    assert delete.json()["code"] == "DIRECTORY_MANAGED"
    order = await api.put(
        f"/api/v1/admin/departments/{dept_id}", json={"sort_order": 5}, headers=ALICE
    )
    assert order.status_code == 200, "local-only fields stay editable"

    # Deleting the primary source releases its records back to local management.
    assert (await api.delete(f"{BASE}/sources/{source['id']}", headers=ALICE)).status_code == 204
    freed = await api.put(
        f"/api/v1/admin/users/{lisi['id']}", json={"display_name": "李四(本地)"}, headers=ALICE
    )
    assert freed.status_code == 200 and freed.json()["source"] == "local"


async def test_disable_guard_aborts_until_forced(api: httpx.AsyncClient) -> None:
    source = await _excel_source(api)
    roster = [
        [f"集团/车间{i % 3}", f"user{i:02d}", f"E{i:02d}", f"员工{i}", "", "", "", "是", "是"]
        for i in range(10)
    ]
    await _upload(api, source["id"], _xlsx(roster), "apply")

    aborted = (await _upload(api, source["id"], _xlsx(roster[:4]), "apply")).json()
    assert aborted["status"] == "aborted"
    assert "6/10" in aborted["error"]
    users = (await api.get("/api/v1/admin/users", params={"is_active": True}, headers=ALICE)).json()
    assert sum(u["username"].startswith("user") for u in users["items"]) == 10

    forced = (await _upload(api, source["id"], _xlsx(roster[:4]), "apply", force=True)).json()
    assert forced["status"] == "succeeded" and forced["forced"] is True
    assert forced["stats"]["stats"]["users"]["disabled"] == 6


async def test_api_source_secrets_and_async_sync(
    api: httpx.AsyncClient, task_queue: RecordingTaskQueue
) -> None:
    await api.get("/api/v1/auth/me", headers=ALICE)
    created = await api.post(
        f"{BASE}/sources",
        json={
            "type": "wecom",
            "name": "企业微信",
            "is_primary": True,
            "sync_interval_minutes": 60,
            "config": {
                "corp_id": "ww1",
                "contacts_secret": "contacts-s3cret",
                "agent_id": "1000002",
                "agent_secret": "agent-s3cret",
            },
        },
        headers=ALICE,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert "contacts_secret" not in source["config"] and "agent_secret" not in source["config"]
    assert sorted(source["secrets_set"]) == ["agent_secret", "contacts_secret"]
    assert source["login_supported"] and source["login_configured"]
    assert source["next_sync_at"] is not None
    assert "s3cret" not in created.text

    updated = await api.put(
        f"{BASE}/sources/{source['id']}",
        json={"config": {"corp_id": "ww2", "contacts_secret": "", "agent_id": "1000002"}},
        headers=ALICE,
    )
    assert updated.status_code == 200
    assert updated.json()["config"]["corp_id"] == "ww2"
    assert sorted(updated.json()["secrets_set"]) == ["agent_secret", "contacts_secret"]

    too_often = await api.put(
        f"{BASE}/sources/{source['id']}", json={"sync_interval_minutes": 5}, headers=ALICE
    )
    assert too_often.status_code == 422

    duplicate = await api.post(
        f"{BASE}/sources",
        json={"type": "wecom", "name": "again", "config": {"corp_id": "x", "contacts_secret": "y"}},
        headers=ALICE,
    )
    assert duplicate.status_code == 409

    invalid = await api.post(
        f"{BASE}/sources",
        json={"type": "dingtalk", "name": "钉钉", "config": {"app_key": "k"}},
        headers=ALICE,
    )
    assert invalid.status_code == 422

    started = await api.post(
        f"{BASE}/sources/{source['id']}/sync", json={"mode": "preview"}, headers=ALICE
    )
    assert started.status_code == 202 and started.json()["status"] == "running"
    assert task_queue.directory_runs == [started.json()["id"]]
    busy = await api.post(
        f"{BASE}/sources/{source['id']}/sync", json={"mode": "apply"}, headers=ALICE
    )
    assert busy.status_code == 409 and busy.json()["code"] == "SYNC_RUNNING"

    excel_upload = await api.post(
        f"{BASE}/sources/{source['id']}/upload",
        files={"file": ("x.xlsx", _xlsx(ROSTER), XLSX)},
        headers=ALICE,
    )
    assert excel_upload.status_code in (400, 409, 422)
