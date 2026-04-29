"""HTTP middleware: request-id propagation, access logging, and 500-envelope.

Implemented as plain ASGI middlewares (not `BaseHTTPMiddleware` subclasses) so
they observe response messages directly. This matters for the error envelope:
when a route handler raises, FastAPI/starlette routes catch-all `Exception`
handlers to its outer `ServerErrorMiddleware`, which writes through the
original `send` and bypasses our header-stamping wrapper. To keep
`X-Request-ID` on every response — including unhandled-exception 500s — the
outermost middleware here both stamps headers and turns any unhandled
exception into a spec-conformant envelope itself.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bridge import __version__

access_logger = logging.getLogger("bridge.access")
error_logger = logging.getLogger("bridge.errors")

_REQUEST_ID_HEADER: Final[bytes] = b"x-request-id"
_BRIDGE_VERSION_HEADER: Final[bytes] = b"x-bridge-version"


def _read_header(scope: Scope, name: bytes) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for header_name, header_value in headers:
        if header_name == name:
            return header_value.decode("latin-1")
    return None


class RequestIDMiddleware:
    """Stamp `X-Request-ID` and `X-Bridge-Version` on every response.

    Generates a UUID4 if no `X-Request-ID` header is supplied, echoes it back,
    and writes it to `scope["state"]["request_id"]` so handlers can attach it
    to error envelopes via `Request.state.request_id`.

    Also catches unhandled exceptions from inner ASGI layers and emits a
    spec-conformant 500 envelope. We do this here, at the outermost user
    middleware, so the response carries our headers — starlette's built-in
    `ServerErrorMiddleware` would write past our `send` wrapper.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = _read_header(scope, _REQUEST_ID_HEADER) or str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = rid

        version_bytes = __version__.encode("latin-1")
        rid_bytes = rid.encode("latin-1")

        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers: list[tuple[bytes, bytes]] = [
                    (n, v)
                    for n, v in message.get("headers", [])
                    if n not in (_REQUEST_ID_HEADER, _BRIDGE_VERSION_HEADER)
                ]
                headers.append((_REQUEST_ID_HEADER, rid_bytes))
                headers.append((_BRIDGE_VERSION_HEADER, version_bytes))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            if response_started:
                # Headers already sent; the connection must be torn down.
                # Re-raise so the ASGI server can do that.
                error_logger.error(
                    "unhandled_after_response_started",
                    extra={"request_id": rid, "exc_type": type(exc).__name__},
                    exc_info=exc,
                )
                raise
            error_logger.error(
                "unhandled_exception",
                extra={"request_id": rid, "exc_type": type(exc).__name__},
                exc_info=exc,
            )
            body = json.dumps(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Internal server error.",
                        "details": {},
                        "request_id": rid,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1")),
                        (_REQUEST_ID_HEADER, rid_bytes),
                        (_BRIDGE_VERSION_HEADER, version_bytes),
                    ],
                },
            )
            await send({"type": "http.response.body", "body": body})


class AccessLogMiddleware:
    """One JSON log line per HTTP request — structured per `Telemetry Plan`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_observed(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_observed)
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            state = scope.get("state", {})
            access_logger.info(
                "request",
                extra={
                    "request_id": state.get("request_id", ""),
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                    "actor": state.get("actor"),
                },
            )
