import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx
from sqlalchemy import text

from app.core.config import Settings
from app.core.resources import AppResources
from app.schemas.health import DependencyStatus, ReadinessResponse

CheckFn = Callable[[], Awaitable[None]]

# Rerank-only endpoints (e.g. DashScope) do not implement GET /models; a 404 / 405 still
# proves the service answers, and real failures surface as degraded retrieval traces.
MODEL_LISTING_UNSUPPORTED = (404, 405)


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    check: CheckFn
    required: bool = True


class HealthService:
    def __init__(self, checks: Sequence[DependencyCheck], timeout_seconds: float) -> None:
        self._checks = list(checks)
        self._timeout = timeout_seconds

    async def _run(self, dep: DependencyCheck) -> DependencyStatus:
        start = time.perf_counter()
        error: str | None = None
        try:
            await asyncio.wait_for(dep.check(), timeout=self._timeout)
        except TimeoutError:
            error = f"timeout after {self._timeout}s"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
        return DependencyStatus(
            status="down" if error else "up",
            required=dep.required,
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            error=error,
        )

    async def readiness(self) -> ReadinessResponse:
        results = await asyncio.gather(*(self._run(dep) for dep in self._checks))
        checks = {dep.name: res for dep, res in zip(self._checks, results, strict=True)}
        if any(r.status == "down" and r.required for r in checks.values()):
            status = "not_ready"
        elif any(r.status == "down" for r in checks.values()):
            status = "degraded"
        else:
            status = "ready"
        return ReadinessResponse(status=status, checks=checks)


async def _http_ok(client: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
    resp = await client.get(url, **kwargs)  # type: ignore[arg-type]
    resp.raise_for_status()
    return resp


def build_dependency_checks(settings: Settings, res: AppResources) -> list[DependencyCheck]:
    async def postgres() -> None:
        async with res.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis() -> None:
        await res.cache.ping()

    async def minio() -> None:
        await _http_ok(res.http, f"{settings.minio_endpoint}/minio/health/live")

    async def qdrant() -> None:
        headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else None
        await _http_ok(res.http, f"{settings.qdrant_url}/readyz", headers=headers)

    async def opensearch() -> None:
        auth = (
            (settings.opensearch_user, settings.opensearch_password)
            if settings.opensearch_user and settings.opensearch_password
            else None
        )
        resp = await _http_ok(res.http, f"{settings.opensearch_url}/_cluster/health", auth=auth)
        cluster_status = resp.json().get("status")
        if cluster_status not in ("green", "yellow"):
            raise RuntimeError(f"cluster status is {cluster_status}")

    async def keycloak() -> None:
        await _http_ok(res.http, settings.keycloak_issuer_discovery_url)

    def model_check(base_url: str) -> CheckFn:
        async def _check() -> None:
            headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
            resp = await res.http.get(f"{base_url.rstrip('/')}/models", headers=headers)
            if resp.status_code in MODEL_LISTING_UNSUPPORTED:
                return
            if resp.status_code in (401, 403):
                raise RuntimeError(f"authentication failed (HTTP {resp.status_code})")
            resp.raise_for_status()

        return _check

    return [
        DependencyCheck("postgres", postgres),
        DependencyCheck("redis", redis),
        DependencyCheck("minio", minio),
        DependencyCheck("qdrant", qdrant),
        DependencyCheck("opensearch", opensearch),
        DependencyCheck("keycloak", keycloak),
        DependencyCheck("embedding", model_check(settings.embedding_base_url), required=False),
        DependencyCheck("rerank", model_check(settings.rerank_base_url), required=False),
        DependencyCheck("chat", model_check(settings.chat_base_url), required=False),
    ]
