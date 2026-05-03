"""Sync HTTP client wrapping the bridge's iMessage endpoints.

The relay loop is sync; we use ``httpx.Client`` rather than the async
flavour to keep the dispatch surface obvious. Three calls cover the
relay's needs:

- ``post_inbound`` — forward a chat.db observation
- ``get_outbox``  — long-poll for queued outbound jobs
- ``post_sent``   — confirm dispatch outcome (success or failure)

Bearer auth is set once on the underlying client. ``X-Request-ID`` is
generated client-side per call so the bridge can correlate access-log
lines back to the originating relay action.

Retry policy: bounded exponential on 5xx and connect errors. We do
*not* retry on 4xx — those are caller errors and retrying won't help.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Final, Literal, cast

import httpx

logger = logging.getLogger("relay.bridge_client")

_MAX_ATTEMPTS: Final[int] = 3
_BACKOFF_BASE_S: Final[float] = 0.25
_DEFAULT_HTTP_TIMEOUT_S: Final[float] = 5.0


class BridgeClientError(Exception):
    """Raised when a bridge call fails after retries."""

    def __init__(self, *, status: int | None, message: str, body: str = "") -> None:
        super().__init__(f"bridge call failed (status={status}): {message}")
        self.status = status
        self.message = message
        self.body = body


class BridgeClient:
    """Bound to one bridge URL + bearer token."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        http_timeout_s: float = _DEFAULT_HTTP_TIMEOUT_S,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=http_timeout_s,
            headers={"Authorization": f"Bearer {token}"},
        )

    # -- lifecycle --

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BridgeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    # -- calls --

    def post_inbound(
        self,
        *,
        agent: str,
        sender: str,
        body: str,
        received_at: str,
        chat_guid: str,
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            "/v1/imessage/inbound",
            json={
                "agent": agent,
                "from": sender,
                "body": body,
                "received_at": received_at,
                "chat_guid": chat_guid,
            },
        )

    def get_outbox(
        self,
        *,
        agent: str,
        timeout_s: int = 25,
    ) -> dict[str, Any] | None:
        # Outbox uses the bridge's BLPOP timeout; client-side timeout must
        # exceed it or we'll cut connections short of completion.
        client_timeout = float(timeout_s) + 5.0
        result = self._call(
            "GET",
            f"/v1/imessage/outbox?agent={agent}&timeout_s={timeout_s}",
            allow_204=True,
            override_timeout=client_timeout,
        )
        if result is None:
            return None
        return result

    def post_sent(
        self,
        *,
        agent: str,
        message_id: str,
        to: str,
        body: str,
        status: Literal["success", "failed"],
        sent_at: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent": agent,
            "message_id": message_id,
            "to": to,
            "body": body,
            "status": status,
        }
        if sent_at is not None:
            payload["sent_at"] = sent_at
        if error_code is not None:
            payload["error_code"] = error_code
        if error_message is not None:
            payload["error_message"] = error_message
        return self._call("POST", "/v1/imessage/sent", json=payload)

    # -- internals --

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        allow_204: bool = False,
        override_timeout: float | None = None,
    ) -> dict[str, Any] | None:
        last_status: int | None = None
        last_body: str = ""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            request_id = str(uuid.uuid4())
            try:
                resp = self._client.request(
                    method,
                    path,
                    json=json,
                    headers={"X-Request-ID": request_id},
                    timeout=override_timeout if override_timeout is not None else None,
                )
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as exc:
                logger.warning(
                    "bridge_call_transport_error",
                    extra={
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                last_status = None
                last_body = str(exc)
                self._sleep_backoff(attempt)
                continue
            if allow_204 and resp.status_code == 204:
                return None
            if 200 <= resp.status_code < 300:
                return cast("dict[str, Any]", resp.json())
            if resp.status_code >= 500:
                last_status = resp.status_code
                last_body = resp.text
                logger.warning(
                    "bridge_call_5xx",
                    extra={
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "status": resp.status_code,
                    },
                )
                self._sleep_backoff(attempt)
                continue
            # 4xx — caller error, no retry.
            raise BridgeClientError(
                status=resp.status_code,
                message=f"{method} {path} returned {resp.status_code}",
                body=resp.text,
            )
        raise BridgeClientError(
            status=last_status,
            message=f"{method} {path} failed after {_MAX_ATTEMPTS} attempts",
            body=last_body,
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(_BACKOFF_BASE_S * (2 ** (attempt - 1)))
