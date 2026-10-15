import asyncio
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from app.core.config import Settings
from app.core.resources import AppResources
from app.services.health_service import DependencyCheck, HealthService, build_dependency_checks


def _model_checks(status_by_host: dict[str, int]) -> dict[str, DependencyCheck]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_by_host[request.url.host])

    settings = Settings(
        embedding_base_url="http://embed/v1",
        rerank_base_url="http://rerank/v1",
        chat_base_url="http://chat/v1",
    )
    res = SimpleNamespace(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    checks = build_dependency_checks(settings, cast(AppResources, res))
    return {c.name: c for c in checks if c.name in ("embedding", "rerank", "chat")}


@pytest.mark.parametrize("code", [200, 404, 405])
async def test_model_reachable_even_without_model_listing(code: int) -> None:
    checks = _model_checks({"embed": 200, "rerank": code, "chat": 200})
    result = await HealthService(list(checks.values()), 1.0).readiness()
    assert result.checks["rerank"].status == "up"
    assert result.status == "ready"


@pytest.mark.parametrize(("code", "fragment"), [(401, "authentication"), (503, "503")])
async def test_model_auth_or_server_errors_are_down(code: int, fragment: str) -> None:
    checks = _model_checks({"embed": 200, "rerank": 200, "chat": code})
    result = await HealthService(list(checks.values()), 1.0).readiness()
    assert result.checks["chat"].status == "down"
    assert fragment in (result.checks["chat"].error or "")
    assert result.status == "degraded"


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("refused")


async def _slow() -> None:
    await asyncio.sleep(1)


async def test_all_up_is_ready() -> None:
    svc = HealthService([DependencyCheck("a", _ok), DependencyCheck("b", _ok)], 1.0)
    result = await svc.readiness()
    assert result.status == "ready"
    assert all(c.status == "up" for c in result.checks.values())


async def test_required_down_is_not_ready() -> None:
    svc = HealthService([DependencyCheck("db", _fail), DependencyCheck("x", _ok)], 1.0)
    result = await svc.readiness()
    assert result.status == "not_ready"
    assert result.checks["db"].status == "down"
    assert result.checks["db"].error == "ConnectionError: refused"


async def test_optional_down_is_degraded() -> None:
    svc = HealthService(
        [DependencyCheck("db", _ok), DependencyCheck("llm", _fail, required=False)], 1.0
    )
    result = await svc.readiness()
    assert result.status == "degraded"
    assert result.checks["llm"].required is False


async def test_timeout_marks_down() -> None:
    svc = HealthService([DependencyCheck("slow", _slow)], 0.05)
    result = await svc.readiness()
    assert result.checks["slow"].status == "down"
    assert result.checks["slow"].error is not None
    assert "timeout" in result.checks["slow"].error
