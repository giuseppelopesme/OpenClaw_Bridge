"""Error envelope and exception handlers.

Every non-2xx response from the bridge ships the envelope defined in
`docs/api-contract.md`:

    {"error": {"code": "...", "message": "...", "details": {}, "request_id": "..."}}

Concrete subclasses cover every code listed in the spec. Handlers are
registered via `install(app)` from `main.create_app`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("bridge.errors")


class BridgeError(Exception):
    """Base class for all errors that should render as the API envelope."""

    code: str = "internal_error"
    # Integer literals match `docs/api-contract.md` exactly and avoid coupling
    # to starlette/FastAPI status names (e.g. 422 was renamed in RFC 9110).
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        # Optional response headers (e.g. Retry-After on RateLimited).
        # Stamped onto the JSONResponse in the handler.
        self.headers: dict[str, str] = headers or {}


class BadRequest(BridgeError):
    code = "bad_request"
    http_status = 400


class Unauthorized(BridgeError):
    code = "unauthorized"
    http_status = 401


class ForbiddenScope(BridgeError):
    code = "forbidden_scope"
    http_status = 403


class NotFound(BridgeError):
    code = "not_found"
    http_status = 404


class Conflict(BridgeError):
    code = "conflict"
    http_status = 409


class IdempotencyReplay(BridgeError):
    code = "idempotency_replay"
    http_status = 409


class ValidationFailed(BridgeError):
    code = "validation_failed"
    http_status = 422


class RateLimited(BridgeError):
    code = "rate_limited"
    http_status = 429


class DependencyUnavailable(BridgeError):
    code = "dependency_unavailable"
    http_status = 502


class InternalError(BridgeError):
    code = "internal_error"
    http_status = 500


def envelope(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        },
    }


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else ""


# Map raw HTTP status codes (e.g. from FastAPI's built-in 404 / 405 handling)
# to the spec's envelope code + default human message.
_HTTP_CODE_MAP: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Malformed request."),
    401: ("unauthorized", "Authentication required."),
    403: ("forbidden_scope", "Token lacks required scope."),
    404: ("not_found", "Resource not found."),
    405: ("bad_request", "Method not allowed for this resource."),
    409: ("conflict", "State precondition failed."),
    422: ("validation_failed", "Request body failed validation."),
    429: ("rate_limited", "Rate limit exceeded."),
    500: ("internal_error", "Internal server error."),
    502: ("dependency_unavailable", "Downstream dependency unavailable."),
}


_DEFAULT_HTTP_MAPPING: tuple[str, str] = ("internal_error", "Internal server error.")


def _map_http_exception(exc: StarletteHTTPException) -> tuple[str, str]:
    code, default_msg = _HTTP_CODE_MAP.get(exc.status_code, _DEFAULT_HTTP_MAPPING)
    # Keep the default canonical message for 404/405 to avoid leaking framework text.
    if isinstance(exc.detail, str) and exc.detail and exc.status_code not in (404, 405):
        return code, exc.detail
    return code, default_msg


async def bridge_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, BridgeError)
    return JSONResponse(
        status_code=exc.http_status,
        content=envelope(exc.code, exc.message, _request_id(request), exc.details),
        headers=exc.headers or None,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _map_http_exception(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(code, message, _request_id(request)),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content=envelope(
            "validation_failed",
            "Request body failed validation.",
            _request_id(request),
            details={"errors": exc.errors()},
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        extra={
            "request_id": _request_id(request),
            "exc_type": type(exc).__name__,
        },
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content=envelope("internal_error", "Internal server error.", _request_id(request)),
    )


def install(app: FastAPI) -> None:
    """Register every envelope-producing exception handler on the app.

    The catch-all `Exception` is *not* registered here: starlette routes that
    handler to its outermost `ServerErrorMiddleware`, which writes through the
    original `send` and bypasses our `RequestIDMiddleware` header stamping. We
    instead catch unhandled exceptions inside `RequestIDMiddleware` itself,
    which guarantees `X-Request-ID` survives onto the 500 response.
    """
    app.add_exception_handler(BridgeError, bridge_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
