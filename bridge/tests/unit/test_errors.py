"""Error envelope shape and exception-handler wiring.

Unit-level: every BridgeError subclass renders the spec envelope with the right
code/status. Integration-level: 401, 404, and 500 paths flow through the
handlers and produce the same envelope at the HTTP boundary.
"""

from __future__ import annotations

import pytest
from bridge.config import Settings
from bridge.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge import errors


@pytest.mark.parametrize(
    ("cls", "expected_code", "expected_status"),
    [
        (errors.BadRequest, "bad_request", 400),
        (errors.Unauthorized, "unauthorized", 401),
        (errors.ForbiddenScope, "forbidden_scope", 403),
        (errors.NotFound, "not_found", 404),
        (errors.Conflict, "conflict", 409),
        (errors.IdempotencyReplay, "idempotency_replay", 409),
        (errors.ValidationFailed, "validation_failed", 422),
        (errors.RateLimited, "rate_limited", 429),
        (errors.DependencyUnavailable, "dependency_unavailable", 502),
        (errors.InternalError, "internal_error", 500),
    ],
)
def test_every_documented_code_has_a_subclass(
    cls: type[errors.BridgeError],
    expected_code: str,
    expected_status: int,
) -> None:
    err = cls("msg", details={"k": "v"})
    assert err.code == expected_code
    assert err.http_status == expected_status
    assert err.message == "msg"
    assert err.details == {"k": "v"}


def test_envelope_shape() -> None:
    body = errors.envelope(
        code="bad_request",
        message="nope",
        request_id="abc",
        details={"field": "x"},
    )
    assert body == {
        "error": {
            "code": "bad_request",
            "message": "nope",
            "details": {"field": "x"},
            "request_id": "abc",
        },
    }


def test_404_uses_envelope(client: TestClient) -> None:
    resp = client.get("/v1/no-such-thing")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Resource not found."
    assert body["error"]["details"] == {}
    assert body["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_method_not_allowed_uses_envelope(client: TestClient) -> None:
    resp = client.post("/v1/health")
    assert resp.status_code == 405
    body = resp.json()
    # Spec maps 405 to bad_request — unusual outside HTTP, but the API only
    # documents the codes in `_HTTP_CODE_MAP`. Downstream callers should treat
    # 405 the same as 400.
    assert body["error"]["code"] == "bad_request"


def test_500_path_renders_envelope(settings: Settings) -> None:
    """A handler that raises an unexpected exception still ships the envelope."""
    app: FastAPI = create_app(settings)

    @app.get("/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/_test/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Internal server error."
    assert body["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_bridge_error_subclass_renders_envelope(settings: Settings) -> None:
    """An endpoint that raises a documented BridgeError gets the right shape."""
    app: FastAPI = create_app(settings)

    @app.get("/_test/conflict")
    async def _c() -> None:
        raise errors.Conflict("file already exists", details={"path": "x.md"})

    with TestClient(app) as client:
        resp = client.get("/_test/conflict")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "conflict"
    assert body["error"]["message"] == "file already exists"
    assert body["error"]["details"] == {"path": "x.md"}
