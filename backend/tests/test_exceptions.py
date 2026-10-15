from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import NotFoundError


def _register_routes(app: FastAPI) -> None:
    @app.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFoundError("doc missing", detail={"id": 1})

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    @app.get("/_test/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}


def test_app_error_format(app: FastAPI, client: TestClient) -> None:
    _register_routes(app)
    resp = client.get("/_test/not-found", headers={"X-Trace-ID": "t-1"})
    assert resp.status_code == 404
    assert resp.json() == {
        "code": "NOT_FOUND",
        "message": "doc missing",
        "detail": {"id": 1},
        "trace_id": "t-1",
    }


def test_unknown_route_format(client: TestClient) -> None:
    resp = client.get("/no-such-route")
    body = resp.json()
    assert resp.status_code == 404
    assert body["code"] == "NOT_FOUND"
    assert body["trace_id"] == resp.headers["X-Trace-ID"]


def test_validation_error_format(app: FastAPI, client: TestClient) -> None:
    _register_routes(app)
    resp = client.get("/_test/items/abc")
    body = resp.json()
    assert resp.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["detail"], list)


def test_unhandled_error_format(app: FastAPI, client: TestClient) -> None:
    _register_routes(app)
    resp = client.get("/_test/boom", headers={"X-Trace-ID": "t-500"})
    assert resp.status_code == 500
    assert resp.json() == {
        "code": "INTERNAL_ERROR",
        "message": "Internal server error",
        "detail": None,
        "trace_id": "t-500",
    }
    assert resp.headers["X-Trace-ID"] == "t-500"
