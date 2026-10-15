import asyncio

from app.services.health_service import DependencyCheck, HealthService


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
