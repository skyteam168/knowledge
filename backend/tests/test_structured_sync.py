"""B8: CSV / REST connectors upsert into equip_* mirror tables."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.models import StructuredSource, StructuredSourceType
from app.repositories.structured_repo import StructuredRepository
from app.services.structured.sync import StructuredSyncExecutor, due_structured_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structured"


def _settings() -> Settings:
    return Settings()


async def _make_csv_source(session: AsyncSession, org_id: str) -> StructuredSource:
    source = StructuredSource(
        org_id=org_id,
        name="MES CSV 连接器",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={
            "connector": "csv",
            "sync_interval_minutes": 60,
            "csv": {
                "devices": str(FIXTURES / "devices.csv"),
                "work_orders": str(FIXTURES / "work_orders.csv"),
                "spare_parts": str(FIXTURES / "spare_parts.csv"),
            },
        },
    )
    session.add(source)
    await session.flush()
    return source


async def test_csv_sync_upserts_equipment(session: AsyncSession) -> None:
    org_id = "org-sync-csv"
    source = await _make_csv_source(session, org_id)
    await session.commit()

    executor = StructuredSyncExecutor(session, _settings())
    first = await executor.sync_source(org_id, source.id, triggered_by="test")
    await session.commit()

    assert first["status"] == "ok"
    assert first["connector"] == "csv"
    assert first["stats"]["devices"]["created"] == 2
    assert first["stats"]["work_orders"]["created"] == 2
    assert first["stats"]["spare_parts"]["created"] == 2

    repo = StructuredRepository(session)
    device = await repo.get_device_by_external(org_id, "EQ-CSV-01", source_id=source.id)
    assert device is not None
    assert device.name == "CSV导入飞织机"
    assert device.location == "织造车间B"

    # Idempotent second run → unchanged
    second = await executor.sync_source(org_id, source.id)
    await session.commit()
    assert second["stats"]["devices"]["created"] == 0
    assert second["stats"]["devices"]["unchanged"] == 2

    await session.refresh(source)
    assert source.meta.get("last_sync_status") == "ok"
    assert source.meta.get("last_sync_stats")


async def test_csv_dry_run_does_not_write(session: AsyncSession) -> None:
    org_id = "org-sync-dry"
    source = await _make_csv_source(session, org_id)
    await session.commit()

    result = await StructuredSyncExecutor(session, _settings()).sync_source(
        org_id, source.id, dry_run=True
    )
    assert result["dry_run"] is True
    assert result["stats"]["devices"]["created"] == 2

    repo = StructuredRepository(session)
    assert await repo.get_device_by_external(org_id, "EQ-CSV-01", source_id=source.id) is None


async def test_sync_requires_connector_meta(session: AsyncSession) -> None:
    org_id = "org-sync-manual"
    source = StructuredSource(
        org_id=org_id,
        name="手工源",
        type=StructuredSourceType.MANUAL.value,
        enabled=True,
        meta={},
    )
    session.add(source)
    await session.flush()

    with pytest.raises(ValidationAppError):
        await StructuredSyncExecutor(session, _settings()).sync_source(org_id, source.id)


async def test_rest_sync_with_mock_transport(session: AsyncSession) -> None:
    org_id = "org-sync-rest"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/devices"):
            return httpx.Response(
                200,
                json=[
                    {
                        "external_id": "EQ-REST-01",
                        "name": "REST飞织机",
                        "status": "active",
                        "location": "A区",
                    }
                ],
            )
        if path.endswith("/work-orders"):
            return httpx.Response(
                200,
                json={"items": [{"external_id": "WO-REST-1", "title": "REST工单", "status": "open"}]},
            )
        if path.endswith("/spare-parts"):
            return httpx.Response(
                200,
                json=[{"code": "SP-REST-1", "name": "REST备件", "qty_on_hand": 3}],
            )
        return httpx.Response(404, json={"error": "missing"})

    transport = httpx.MockTransport(handler)
    source = StructuredSource(
        org_id=org_id,
        name="MES REST",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={
            "connector": "rest",
            "sync_interval_minutes": 0,
            "rest": {
                "base_url": "https://mes.test/api/",
                "paths": {
                    "devices": "/devices",
                    "work_orders": "/work-orders",
                    "spare_parts": "/spare-parts",
                },
            },
        },
    )
    session.add(source)
    await session.flush()

    result = await StructuredSyncExecutor(
        session, _settings(), transport=transport
    ).sync_source(org_id, source.id)
    await session.commit()

    assert result["connector"] == "rest"
    assert result["stats"]["devices"]["created"] == 1
    assert result["stats"]["work_orders"]["created"] == 1
    assert result["stats"]["spare_parts"]["created"] == 1

    repo = StructuredRepository(session)
    device = await repo.get_device_by_external(org_id, "EQ-REST-01", source_id=source.id)
    assert device is not None
    assert device.name == "REST飞织机"


async def test_due_structured_sources(session: AsyncSession) -> None:
    org_id = "org-sync-due"
    due_source = await _make_csv_source(session, org_id)
    due_source.name = "due-source"
    skipped = StructuredSource(
        org_id=org_id,
        name="manual-skip",
        type=StructuredSourceType.MANUAL.value,
        enabled=True,
        meta={"connector": "csv", "sync_interval_minutes": 0, "csv": {"devices": "x"}},
    )
    session.add(skipped)
    await session.flush()

    due = await due_structured_sources(session)
    ids = {s.id for s in due}
    assert due_source.id in ids
    assert skipped.id not in ids
