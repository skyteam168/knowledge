from typing import Any

import httpx
import pytest

from tests.conftest import TEST_IDENTITIES, auth, make_claims
from tests.test_directory_api import ROSTER, _excel_source, _upload, _xlsx

ALICE, CAROL = auth("alice-token"), auth("carol-token")
ROLES = "/api/v1/admin/roles"


async def _roles(api: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    return {r["code"]: r for r in (await api.get(ROLES, headers=ALICE)).json()}


async def _user_roles(api: httpx.AsyncClient, username: str) -> set[str]:
    users = (await api.get("/api/v1/admin/users", params={"size": 100}, headers=ALICE)).json()
    user = next(u for u in users["items"] if u["username"] == username)
    detail = (await api.get(f"/api/v1/admin/users/{user['id']}", headers=ALICE)).json()
    return {r["code"] for r in detail["roles"]}


async def _dept_id(api: httpx.AsyncClient, path_name: str) -> str:
    def walk(nodes: list[dict[str, Any]]) -> str | None:
        for n in nodes:
            if n["path_name"] == path_name:
                return str(n["id"])
            found = walk(n.get("children") or [])
            if found:
                return found
        return None

    tree = (await api.get("/api/v1/directory/departments", headers=ALICE)).json()
    found = walk(tree)
    assert found, path_name
    return found


async def _bulk(api: httpx.AsyncClient, role_id: str, **body: Any) -> httpx.Response:
    return await api.post(f"{ROLES}/{role_id}/bulk", json=body, headers=ALICE)


async def test_synced_users_get_default_roles(api: httpx.AsyncClient) -> None:
    source = await _excel_source(api)
    roles = await _roles(api)
    assert roles["kb_viewer"]["is_default"] is True
    assert roles["kb_admin"]["is_default"] is False

    # A superuser role can never become a default role.
    resp = await api.put(
        f"{ROLES}/{roles['kb_admin']['id']}", json={"is_default": True}, headers=ALICE
    )
    assert resp.status_code == 422 and resp.json()["code"] == "ROLE_PRIVILEGED"
    # Nor can a default role gain administration permissions.
    resp = await api.put(
        f"{ROLES}/{roles['kb_viewer']['id']}/permissions",
        json={"permissions": ["kb:read", "admin:user"]},
        headers=ALICE,
    )
    assert resp.status_code == 422 and resp.json()["code"] == "ROLE_PRIVILEGED"

    resp = await api.put(
        f"{ROLES}/{roles['kb_editor']['id']}", json={"is_default": True}, headers=ALICE
    )
    assert resp.status_code == 200 and resp.json()["is_default"] is True

    await _upload(api, source["id"], _xlsx(ROSTER), "apply")
    assert await _user_roles(api, "zhangsan") == {"kb_viewer", "kb_editor"}
    assert await _user_roles(api, "lisi") == {"kb_viewer", "kb_editor"}


@pytest.fixture
def erin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token without roles; registered before the `api` fixture copies the identities."""
    monkeypatch.setitem(TEST_IDENTITIES, "erin-token", make_claims("sub-erin", "erin"))


async def test_first_login_gets_default_roles(erin: None, api: httpx.AsyncClient) -> None:
    await api.get("/api/v1/auth/me", headers=ALICE)
    # No roles in the token (e.g. an AD account): the default roles apply.
    erin = (await api.get("/api/v1/auth/me", headers=auth("erin-token"))).json()
    assert "chat:use" in erin["permissions"]
    assert await _user_roles(api, "erin") == {"kb_viewer"}
    # Roles mapped from the token take precedence.
    await api.get("/api/v1/auth/me", headers=auth("bob-token"))
    assert await _user_roles(api, "bob") == {"kb_editor"}


async def test_bulk_grant_and_revoke_by_department_and_group(api: httpx.AsyncClient) -> None:
    source = await _excel_source(api)
    roles = await _roles(api)
    editor = roles["kb_editor"]["id"]
    await _upload(api, source["id"], _xlsx(ROSTER), "apply")
    vietnam = await _dept_id(api, "集团 / 越南Flyknit")
    group_root = await _dept_id(api, "集团")

    # Dry run: counts only, nothing written. zhangsan is in two sub-departments: counted once.
    dry = await _bulk(api, editor, action="grant", department_ids=[vietnam], dry_run=True)
    assert dry.status_code == 200, dry.text
    assert dry.json() == {"matched": 1, "changed": 1, "unchanged": 0, "skipped": 0, "dry_run": True}
    assert "kb_editor" not in await _user_roles(api, "zhangsan")

    done = (await _bulk(api, editor, action="grant", department_ids=[vietnam])).json()
    assert done["changed"] == 1 and done["dry_run"] is False
    assert "kb_editor" in await _user_roles(api, "zhangsan")
    assert "kb_editor" not in await _user_roles(api, "lisi")
    again = (await _bulk(api, editor, action="grant", department_ids=[vietnam])).json()
    assert (again["changed"], again["unchanged"]) == (0, 1)

    # By job-title group.
    groups = (await api.get("/api/v1/admin/groups", params={"size": 100}, headers=ALICE)).json()
    legal = next(g for g in groups["items"] if g["name"] == "职务/法务专员")
    by_group = (await _bulk(api, editor, action="grant", group_ids=[legal["id"]])).json()
    assert (by_group["matched"], by_group["changed"]) == (1, 1)
    assert "kb_editor" in await _user_roles(api, "lisi")

    # Revoke from the whole group (root department and its sub-tree).
    revoked = (await _bulk(api, editor, action="revoke", department_ids=[group_root])).json()
    assert (revoked["matched"], revoked["changed"], revoked["skipped"]) == (2, 2, 0)
    assert await _user_roles(api, "zhangsan") == {"kb_viewer"}

    logs = (
        await api.get(
            "/api/v1/admin/audit-logs", params={"action": "role.bulk_grant"}, headers=ALICE
        )
    ).json()
    assert logs["total"] >= 2


async def test_bulk_assign_guards(api: httpx.AsyncClient) -> None:
    source = await _excel_source(api)
    roles = await _roles(api)
    await _upload(api, source["id"], _xlsx(ROSTER), "apply")
    root = await _dept_id(api, "集团")

    resp = await _bulk(api, roles["kb_admin"]["id"], action="grant", department_ids=[root])
    assert resp.status_code == 422 and resp.json()["code"] == "ROLE_PRIVILEGED"
    resp = await _bulk(api, roles["kb_editor"]["id"], action="grant")
    assert resp.status_code == 422
    resp = await _bulk(api, roles["kb_editor"]["id"], action="grant", department_ids=["nope"])
    assert resp.status_code == 404
    resp = await api.post(
        f"{ROLES}/{roles['kb_editor']['id']}/bulk",
        json={"action": "grant", "department_ids": [root]},
        headers=CAROL,
    )
    assert resp.status_code == 403

    # Disabled users are skipped unless asked for.
    await _upload(api, source["id"], _xlsx(ROSTER[:2]), "apply")  # lisi disabled
    only_active = (
        await _bulk(
            api, roles["kb_editor"]["id"], action="grant", department_ids=[root], dry_run=True
        )
    ).json()
    with_inactive = (
        await _bulk(
            api,
            roles["kb_editor"]["id"],
            action="grant",
            department_ids=[root],
            include_inactive=True,
            dry_run=True,
        )
    ).json()
    assert (only_active["matched"], with_inactive["matched"]) == (1, 2)
