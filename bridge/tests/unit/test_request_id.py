"""X-Request-ID middleware: echo when supplied, generate when missing."""

from __future__ import annotations

import re
import uuid

from fastapi.testclient import TestClient

# UUID4 string: xxxxxxxx-xxxx-4xxx-Yxxx-xxxxxxxxxxxx with Y in {8,9,a,b}.
_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def test_request_id_generated_when_missing(client: TestClient) -> None:
    resp = client.get("/v1/health")
    rid = resp.headers["X-Request-ID"]
    assert _UUID4.match(rid), f"expected UUID4, got {rid!r}"


def test_request_id_echoed_when_supplied(client: TestClient) -> None:
    supplied = str(uuid.uuid4())
    resp = client.get("/v1/health", headers={"X-Request-ID": supplied})
    assert resp.headers["X-Request-ID"] == supplied


def test_request_id_present_on_error_responses(client: TestClient) -> None:
    # Hitting an unknown route must still produce a request id and the envelope.
    supplied = str(uuid.uuid4())
    resp = client.get("/v1/does-not-exist", headers={"X-Request-ID": supplied})
    assert resp.status_code == 404
    assert resp.headers["X-Request-ID"] == supplied
    body = resp.json()
    assert body["error"]["request_id"] == supplied
