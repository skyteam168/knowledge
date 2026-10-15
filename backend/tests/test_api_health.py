from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_health_service
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


def test_trace_id_is_propagated(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Trace-ID": "abc-123"})
    assert resp.headers["X-Trace-ID"] == "abc-123"


def test_invalid_trace_id_is_replaced(client: TestClient) -> None:
    resp = client.get("/health", headers={"X-Trace-ID": "bad id with spaces"})
    assert resp.headers["X-Trace-ID"] != "bad id with spaces"
