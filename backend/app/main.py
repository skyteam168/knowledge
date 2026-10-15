import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, metrics, oidc_bridge
from app.api.audit_middleware import AuditMiddleware
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.metrics import HttpMetricsMiddleware
from app.core.middleware import TRACE_HEADER, TraceIdMiddleware
from app.core.resources import AppResources
from app.core.telemetry import instrument_app, shutdown_tracing
from app.services.models import import_env_config

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    resources_factory: Callable[[Settings], AppResources] = AppResources.create,
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.resources = resources_factory(settings)
        if settings.llm_config_import_on_startup:
            try:
                await import_env_config(app.state.resources.session_factory, settings)
            except Exception:
                logger.exception("llm_config_import_failed")
        logger.info("startup", extra={"env": settings.app_env})
        try:
            yield
        finally:
            await app.state.resources.close()
            shutdown_tracing()
            logger.info("shutdown")

    public_docs = settings.app_env != "prod"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if public_docs else None,
        redoc_url="/redoc" if public_docs else None,
        openapi_url="/openapi.json" if public_docs else None,
    )

    # Middleware order (outermost first): Metrics -> TraceId -> CORS -> Audit -> routes
    app.add_middleware(AuditMiddleware, path_prefix=settings.api_prefix)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[TRACE_HEADER],
    )
    app.add_middleware(TraceIdMiddleware)
    if settings.metrics_enabled:
        app.add_middleware(HttpMetricsMiddleware)
    register_exception_handlers(app)

    app.include_router(health.router)
    if settings.metrics_enabled:
        app.include_router(metrics.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(oidc_bridge.router)
    instrument_app(app, settings)
    return app


app = create_app()
