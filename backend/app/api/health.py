import hmac

from fastapi import APIRouter, Request, Response, status

from app.api.deps import HealthServiceDep, SettingsDep
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(app=settings.app_name, env=settings.app_env)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    response_model_exclude_none=True,
    responses={503: {"model": ReadinessResponse}},
)
async def ready(
    service: HealthServiceDep, settings: SettingsDep, request: Request, response: Response
) -> ReadinessResponse:
    result = await service.readiness()
    if result.status == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if settings.metrics_token:
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {settings.metrics_token}".encode()):
            return result.redacted()
    return result
