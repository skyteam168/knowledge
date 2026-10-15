import httpx

from tests.conftest import auth

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")


async def test_requires_token(api: httpx.AsyncClient) -> None:
    resp = await api.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"
    bad = await api.get("/api/v1/auth/me", headers=auth("nope"))
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_TOKEN"


async def test_me_reflects_roles_and_permissions(api: httpx.AsyncClient) -> None:
    alice = (await api.get("/api/v1/auth/me", headers=ALICE)).json()
    assert alice["permissions"] == ["*"]
    assert alice["is_platform_admin"] is True
    assert alice["org"]["code"] == "org-demo"
    assert [g["name"] for g in alice["groups"]] == ["engineering"]

    bob = (await api.get("/api/v1/auth/me", headers=BOB)).json()
    assert "kb:create" in bob["permissions"]
    assert not any(p.startswith("admin:") for p in bob["permissions"])
    assert bob["is_platform_admin"] is False

    carol = (await api.get("/api/v1/auth/me", headers=CAROL)).json()
    assert carol["permissions"] == ["chat:use", "kb:read", "search:use"]
    assert carol["org"]["id"] == alice["org"]["id"]


async def test_forbidden_without_permission(api: httpx.AsyncClient) -> None:
    await api.get("/api/v1/auth/me", headers=ALICE)
    for path in ("/api/v1/admin/users", "/api/v1/admin/audit-logs", "/api/v1/admin/roles"):
        resp = await api.get(path, headers=CAROL)
        assert resp.status_code == 403, path
        assert resp.json()["code"] == "PERMISSION_DENIED"
    resp = await api.post("/api/v1/admin/departments", json={"name": "x"}, headers=BOB)
    assert resp.status_code == 403
    assert (await api.get("/api/v1/platform/organizations", headers=BOB)).status_code == 403
    assert (await api.get("/api/v1/platform/organizations", headers=ALICE)).status_code == 200


async def test_department_crud_is_audited(api: httpx.AsyncClient) -> None:
    root = (
        await api.post("/api/v1/admin/departments", json={"name": "总部"}, headers=ALICE)
    ).json()
    child = (
        await api.post(
            "/api/v1/admin/departments",
            json={"name": "研发", "parent_id": root["id"]},
            headers=ALICE,
        )
    ).json()
    resp = await api.put(
        f"/api/v1/admin/departments/{child['id']}", json={"name": "研发中心"}, headers=ALICE
    )
    assert resp.status_code == 200

    tree = (await api.get("/api/v1/admin/departments/tree", headers=ALICE)).json()
    assert tree[0]["name"] == "总部" and tree[0]["children"][0]["name"] == "研发中心"

    conflict = await api.delete(f"/api/v1/admin/departments/{root['id']}", headers=ALICE)
    assert conflict.status_code == 409

    logs = (
        await api.get(
            "/api/v1/admin/audit-logs",
            params={"resource_type": "department"},
            headers={**ALICE, "X-Trace-ID": "q-1"},
        )
    ).json()
    actions = [i["action"] for i in logs["items"]]
    assert actions.count("department.create") == 2 and "department.update" in actions
    update = next(i for i in logs["items"] if i["action"] == "department.update")
    assert update["diff"] == {"name": {"before": "研发", "after": "研发中心"}}
    assert update["actor_name"] == "alice" and update["trace_id"]
    assert logs["total"] == len(logs["items"])

    failed = (
        await api.get("/api/v1/admin/audit-logs", params={"action": "http."}, headers=ALICE)
    ).json()
    assert any(i["method"] == "DELETE" and i["status_code"] == 409 for i in failed["items"]), (
        "failed write recorded by middleware"
    )


async def test_role_permission_change_takes_effect_immediately(api: httpx.AsyncClient) -> None:
    await api.get("/api/v1/auth/me", headers=CAROL)
    assert (await api.get("/api/v1/admin/audit-logs", headers=CAROL)).status_code == 403

    roles = (await api.get("/api/v1/admin/roles", headers=ALICE)).json()
    viewer = next(r for r in roles if r["code"] == "kb_viewer")
    # Administration permissions are refused on a default role.
    await api.put(f"/api/v1/admin/roles/{viewer['id']}", json={"is_default": False}, headers=ALICE)
    resp = await api.put(
        f"/api/v1/admin/roles/{viewer['id']}/permissions",
        json={"permissions": [*viewer["permissions"], "admin:audit"]},
        headers=ALICE,
    )
    assert resp.status_code == 200

    assert (await api.get("/api/v1/admin/audit-logs", headers=CAROL)).status_code == 200


async def test_assign_local_role_and_group(api: httpx.AsyncClient) -> None:
    carol_id = (await api.get("/api/v1/auth/me", headers=CAROL)).json()["id"]
    roles = (await api.get("/api/v1/admin/roles", headers=ALICE)).json()
    editor = next(r for r in roles if r["code"] == "kb_editor")
    group = (await api.post("/api/v1/admin/groups", json={"name": "项目组"}, headers=ALICE)).json()

    detail = (
        await api.put(
            f"/api/v1/admin/users/{carol_id}/roles", json={"ids": [editor["id"]]}, headers=ALICE
        )
    ).json()
    assert {r["code"] for r in detail["roles"]} == {"kb_viewer", "kb_editor"}
    members = (
        await api.put(
            f"/api/v1/admin/groups/{group['id']}/members", json={"ids": [carol_id]}, headers=ALICE
        )
    ).json()
    assert [m["username"] for m in members] == ["carol"]

    me = (await api.get("/api/v1/auth/me", headers=CAROL)).json()
    assert "kb:create" in me["permissions"]
    assert {g["name"] for g in me["groups"]} == {"sales", "项目组"}


async def test_users_are_isolated_per_org(api: httpx.AsyncClient) -> None:
    await api.get("/api/v1/auth/me", headers=CAROL)
    other = auth("other-org-token")
    users = (await api.get("/api/v1/admin/users", headers=other)).json()
    assert [u["username"] for u in users["items"]] == ["dave"]
    carol_id = (await api.get("/api/v1/auth/me", headers=CAROL)).json()["id"]
    assert (await api.get(f"/api/v1/admin/users/{carol_id}", headers=other)).status_code == 404


async def test_disabled_user_gets_403(api: httpx.AsyncClient) -> None:
    carol_id = (await api.get("/api/v1/auth/me", headers=CAROL)).json()["id"]
    resp = await api.delete(f"/api/v1/admin/users/{carol_id}", headers=ALICE)
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    blocked = await api.get("/api/v1/auth/me", headers=CAROL)
    assert blocked.status_code == 403 and blocked.json()["code"] == "USER_DISABLED"
