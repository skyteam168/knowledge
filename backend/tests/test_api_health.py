import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_health_service
from app.core.config import Settings
from app.services.health_service import DependencyCheck, HealthService


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("refused")


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.headers["X-Trace-ID"]


def test_ready_all_up(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        [DependencyCheck("postgres", _ok), DependencyCheck("redis", _ok)], 1.0
    )
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert set(body["checks"]) == {"postgres", "redis"}


def test_ready_required_down_returns_503(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        [DependencyCheck("postgres", _fail)], 1.0
    )
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["postgres"]["status"] == "down"


def test_ready_hides_details_without_metrics_token(
    app: FastAPI, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_token", "s3cret")
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        [DependencyCheck("postgres", _ok), DependencyCheck("rerank", _fail, required=False)], 1.0
    )
    public = client.get("/ready").json()
    assert public["status"] == "degraded"
    assert public["checks"]["rerank"] == {"status": "down", "required": False}

    wrong = client.get("/ready", headers={"Authorization": "Bearer nope"}).json()
    assert "error" not in wrong["checks"]["rerank"]

    full = client.get("/ready", headers={"Authorization": "Bearer s3cret"}).json()
    assert full["checks"]["rerank"]["error"] == "ConnectionError: refused"
    assert "latency_ms" in full["checks"]["postgres"]


def test_trace_id_is_propagated(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Trace-ID": "abc-123"})
    assert resp.headers["X-Trace-ID"] == "abc-123"


def test_invalid_trace_id_is_replaced(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Trace-ID": "bad id with spaces"})
    assert resp.headers["X-Trace-ID"] != "bad id with spaces"
