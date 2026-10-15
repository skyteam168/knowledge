import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.middleware import TRACE_HEADER
from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base business error. Subclass and override defaults for specific error types."""

    status_code: int = 400
    code: str = "BAD_REQUEST"
    message: str = "Bad request"
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.detail = detail
        self.headers = headers
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "Resource not found"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "Permission denied"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "Resource conflict"


class ValidationAppError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "Validation failed"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"
    message = "Authentication required"


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    detail: Any = None,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    trace_id = _trace_id(request)
    body = ErrorResponse(code=code, message=message, detail=detail, trace_id=trace_id)
    headers = dict(extra_headers or {})
    if trace_id:
        headers[TRACE_HEADER] = trace_id
    return JSONResponse(
        status_code=status_code, content=jsonable_encoder(body), headers=headers or None
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _error_response(request, exc.status_code, exc.code, exc.message, exc.detail, exc.headers)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    try:
        phrase = HTTPStatus(exc.status_code).phrase
    except ValueError:
        phrase = "Error"
    code = phrase.upper().replace(" ", "_").replace("-", "_")
    message = exc.detail if isinstance(exc.detail, str) else phrase
    return _error_response(request, exc.status_code, code, message)


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Validator errors carry the raised exception object in ctx, which is not JSON-serializable.
    errors = [
        {**err, "ctx": {k: str(v) for k, v in err["ctx"].items()}} if "ctx" in err else err
        for err in exc.errors()
    ]
    return _error_response(request, 422, "VALIDATION_ERROR", "Request validation failed", errors)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", extra={"trace_id": _trace_id(request)})
    return _error_response(request, 500, "INTERNAL_ERROR", "Internal server error")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
