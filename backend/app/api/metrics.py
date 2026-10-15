import hmac

from fastapi import APIRouter, Request, Response

from app.api.deps import ResourcesDep, SettingsDep
from app.core.exceptions import UnauthorizedError
from app.core.metrics import render
from app.services.monitoring import BacklogCollector

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request, settings: SettingsDep, resources: ResourcesDep) -> Response:
    if settings.metrics_token:
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {settings.metrics_token}".encode()):
            raise UnauthorizedError("Invalid metrics token")
    collector: BacklogCollector | None = getattr(request.app.state, "backlog_collector", None)
    if collector is None:
        collector = BacklogCollector(
            resources.session_factory, resources.cache, settings.metrics_gauge_cache_seconds
        )
        request.app.state.backlog_collector = collector
    await collector.refresh()
    body, content_type = render()
    return Response(body, media_type=content_type)
