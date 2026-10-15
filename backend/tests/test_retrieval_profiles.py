from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_session_factory
from app.models import AuditLog
from tests.conftest import auth

ALICE, CAROL = auth("alice-token"), auth("carol-token")
BASE = "/api/v1/admin/retrieval/profiles"


async def create(api: httpx.AsyncClient, name: str, config: dict[str, Any]) -> dict[str, Any]:
    resp = await api.post(BASE, json={"name": name, "config": config}, headers=ALICE)
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def active_name(api: httpx.AsyncClient) -> str:
    profiles = (await api.get(BASE, headers=ALICE)).json()
    return str(next(p["name"] for p in profiles if p["is_active"]))


async def test_profile_lifecycle(api: httpx.AsyncClient, engine: AsyncEngine) -> None:
    profiles = (await api.get(BASE, headers=ALICE)).json()
    assert [p["name"] for p in profiles] == ["builtin"]
    assert profiles[0]["builtin"] and profiles[0]["is_active"] and profiles[0]["id"] is None
    defaults = (await api.get(f"{BASE}/defaults", headers=ALICE)).json()
    assert defaults["fusion"]["k"] == 60 and defaults["dense"]["top_k"] == 40
    assert defaults["rerank"]["top_n"] == 40 and defaults["top_k"] == 10

    bm25 = await create(
        api, "bm25-heavy", {"fusion": {"k": 30, "weights": {"dense": 0.5, "sparse": 2.0}}}
    )
    assert bm25["config"]["fusion"]["weights"] == {"dense": 0.5, "sparse": 2.0}
    assert bm25["config"]["sparse"]["field_boosts"] == {
        "title": 3.0,
        "heading_path": 2.0,
        "content": 1.0,
    }
    assert bm25["is_active"] is False

    activated = await api.post(f"{BASE}/{bm25['id']}/activate", headers=ALICE)
    assert activated.status_code == 200 and activated.json()["is_active"] is True
    assert await active_name(api) == "bm25-heavy"

    other = await create(api, "no-rerank", {"rerank": {"enabled": False}})
    await api.post(f"{BASE}/{other['id']}/activate", headers=ALICE)
    assert await active_name(api) == "no-rerank"  # exactly one active per org

    updated = await api.put(
        f"{BASE}/{bm25['id']}", json={"config": {"top_k": 5}, "description": "x"}, headers=ALICE
    )
    assert updated.status_code == 200
    assert updated.json()["config"]["top_k"] == 5 and updated.json()["description"] == "x"

    assert (await api.delete(f"{BASE}/{other['id']}", headers=ALICE)).status_code == 409
    await api.post(f"{BASE}/builtin/activate", headers=ALICE)
    assert await active_name(api) == "builtin"
    assert (await api.delete(f"{BASE}/{other['id']}", headers=ALICE)).status_code == 204
    assert (await api.delete(f"{BASE}/{other['id']}", headers=ALICE)).status_code == 404

    async with create_session_factory(engine)() as session:
        actions = (
            await session.execute(
                select(AuditLog.action).where(AuditLog.resource_type == "retrieval_profile")
            )
        ).scalars()
        assert {
            "retrieval_profile.create",
            "retrieval_profile.update",
            "retrieval_profile.activate",
            "retrieval_profile.delete",
        } <= set(actions)


async def test_profile_validation(api: httpx.AsyncClient) -> None:
    await create(api, "a", {})
    assert (await api.post(BASE, json={"name": "a"}, headers=ALICE)).status_code == 409
    assert (await api.post(BASE, json={"name": "builtin"}, headers=ALICE)).status_code == 409
    for bad in (
        {"dense": {"enabled": False}, "sparse": {"enabled": False}},
        {"fusion": {"k": 0}},
        {"fusion": {"weights": {"dense": -1}}},
        {"sparse": {"field_boosts": {"body": 1}}},
        {"rerank": {"top_n": 0}},
        {"nope": True},
    ):
        resp = await api.post(BASE, json={"name": "bad", "config": bad}, headers=ALICE)
        assert resp.status_code == 422, bad
    assert (await api.post(f"{BASE}/missing/activate", headers=ALICE)).status_code == 404


async def test_profiles_require_admin_permission(api: httpx.AsyncClient) -> None:
    assert (await api.get(BASE, headers=CAROL)).status_code == 403
    assert (await api.post(BASE, json={"name": "x"}, headers=CAROL)).status_code == 403


async def test_search_uses_active_profile_or_admin_override(api: httpx.AsyncClient) -> None:
    profile = await create(api, "sparse-only", {"dense": {"enabled": False}})
    await api.post(f"{BASE}/{profile['id']}/activate", headers=ALICE)
    body = (await api.get("/api/v1/search", params={"q": "制度"}, headers=CAROL)).json()
    assert body["profile"] == {"id": profile["id"], "name": "sparse-only"}

    override = await api.get(
        "/api/v1/search",
        params={"q": "制度", "profile_id": "builtin", "debug": True},
        headers=ALICE,
    )
    assert override.status_code == 200
    assert override.json()["profile"]["name"] == "builtin"
    assert override.json()["debug"]["config"]["dense"]["enabled"] is True
