"""Onboarding tour progress: per user, upserted, resettable, never visible to others."""

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_session_factory
from app.models import AuditLog, UserGuideProgress
from tests.conftest import auth

ALICE, CAROL, DAVE = auth("alice-token"), auth("carol-token"), auth("other-org-token")
URL = "/api/v1/me/guides"


async def test_progress_is_saved_per_user_and_upserted(
    api: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    assert (await api.get(URL, headers=CAROL)).json() == []

    done = await api.put(f"{URL}/layout", headers=CAROL, json={"version": 1})
    assert done.status_code == 200, done.text
    assert done.json()["guide_key"] == "layout" and done.json()["status"] == "completed"
    skipped = await api.put(
        f"{URL}/assistant", headers=CAROL, json={"version": 2, "status": "skipped"}
    )
    assert skipped.json()["status"] == "skipped"
    again = await api.put(f"{URL}/layout", headers=CAROL, json={"version": 3})
    assert again.json()["version"] == 3

    listed = (await api.get(URL, headers=CAROL)).json()
    assert [(g["guide_key"], g["version"], g["status"]) for g in listed] == [
        ("assistant", 2, "skipped"),
        ("layout", 3, "completed"),
    ]
    assert (await api.get(URL, headers=ALICE)).json() == []
    assert (await api.get(URL, headers=DAVE)).json() == []

    async with create_session_factory(engine)() as session:
        rows = (await session.execute(select(func.count()).select_from(UserGuideProgress))).one()
        assert rows[0] == 2
        audits = await session.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.action.like("guide%"))
        )
        assert audits.one()[0] == 0


async def test_reset_only_clears_the_caller(api: httpx.AsyncClient) -> None:
    await api.put(f"{URL}/layout", headers=CAROL, json={"version": 1})
    await api.put(f"{URL}/layout", headers=ALICE, json={"version": 1})

    reset = await api.delete(URL, headers=CAROL)
    assert reset.status_code == 204
    assert (await api.get(URL, headers=CAROL)).json() == []
    assert [g["guide_key"] for g in (await api.get(URL, headers=ALICE)).json()] == ["layout"]


async def test_invalid_input_is_rejected(api: httpx.AsyncClient) -> None:
    for key in ("Layout", "has space", "x" * 65, "-lead"):
        resp = await api.put(f"{URL}/{key}", headers=CAROL, json={"version": 1})
        assert resp.status_code in (404, 422), (key, resp.status_code)
    assert (await api.put(f"{URL}/layout", headers=CAROL, json={"version": 0})).status_code == 422
    bad_status = await api.put(f"{URL}/layout", headers=CAROL, json={"version": 1, "status": "x"})
    assert bad_status.status_code == 422
    assert (await api.get(URL)).status_code == 401
