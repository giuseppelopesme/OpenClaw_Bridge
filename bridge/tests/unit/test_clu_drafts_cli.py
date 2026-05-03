"""End-to-end tests for scripts/clu-drafts.py against an in-process bridge.

Strategy:
- Use the existing test bridge (the `client` fixture) for HTTP routing.
- Patch ``brains_shared.client.BridgeClient`` so the CLI sends through
  the FastAPI TestClient's transport instead of opening a real socket.
- Run the CLI's ``main()`` directly; capture stdout/stderr.

We import the CLI by file path because ``scripts/clu-drafts.py`` has a
hyphen in the filename (Python module names can't have hyphens).
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import httpx
import pytest
from _support import TokenFixture
from fastapi.testclient import TestClient

# Load scripts/clu-drafts.py as a module (hyphen → underscore alias).
_CLI_PATH = Path(__file__).resolve().parents[3] / "scripts" / "clu-drafts.py"
_spec = importlib.util.spec_from_file_location("clu_drafts_cli", _CLI_PATH)
assert _spec is not None and _spec.loader is not None
clu_drafts_cli = importlib.util.module_from_spec(_spec)
sys.modules["clu_drafts_cli"] = clu_drafts_cli
_spec.loader.exec_module(clu_drafts_cli)


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> TestClient:
    """Wire the CLI's BridgeClient to the FastAPI TestClient's transport."""
    monkeypatch.setenv("CLI_TOKEN", "dev-token-agent-approve")
    monkeypatch.setenv("BRIDGE_URL", "http://bridge.test")

    # Build an httpx.AsyncClient whose transport routes to the in-process app.
    transport = httpx.ASGITransport(app=client.app)

    real_bridge_client = clu_drafts_cli.BridgeClient

    class _PatchedBridgeClient(real_bridge_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # Replace the underlying httpx.AsyncClient with one routed
            # at the in-process FastAPI app.
            self._httpx = httpx.AsyncClient(  # noqa: SLF001
                base_url=kwargs["base_url"],
                timeout=2.0,
                transport=transport,
                headers={"Authorization": f"Bearer {kwargs['token']}"},
            )
            inner = self.get_inner()
            inner.set_async_httpx_client(self._httpx)  # noqa: SLF001

    monkeypatch.setattr(clu_drafts_cli, "BridgeClient", _PatchedBridgeClient)
    return client


def _run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = clu_drafts_cli.main(list(argv))
    return rc, out.getvalue(), err.getvalue()


def _create_via_bridge(client: TestClient, body: str = "demo body") -> str:
    """Create a draft via POST /v1/agent/drafts using the agent-write token."""
    resp = client.post(
        "/v1/agent/drafts",
        json={
            "agent": "clu",
            "channel": "imessage",
            "to_handle": "+39 333 1234567",
            "body": body,
        },
        headers={"Authorization": "Bearer dev-token-agent-write"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["draft_id"])


# -- list -----------------------------------------------------------------


def test_list_returns_zero_with_message_when_no_drafts(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _ = cli_env
    rc, stdout, _ = _run_cli("list")
    assert rc == 0
    assert "no drafts" in stdout


def test_list_shows_pending_draft(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env, body="please review")
    rc, stdout, _ = _run_cli("list")
    assert rc == 0
    assert "pending" in stdout
    assert draft_id in stdout
    assert "please review" in stdout


# -- show -----------------------------------------------------------------


def test_show_prints_full_body(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env, body="full body content here")
    rc, stdout, _ = _run_cli("show", draft_id)
    assert rc == 0
    assert "full body content here" in stdout
    assert draft_id in stdout


def test_show_unknown_id_exits_1(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _ = cli_env
    rc, _, stderr = _run_cli("show", "nope-nope-nope")
    assert rc == 1
    assert "ERROR" in stderr


# -- approve --------------------------------------------------------------


def test_approve_flips_status_and_enqueues(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env, body="ready to ship")
    rc, stdout, _ = _run_cli("approve", draft_id, "--by", "giuseppe")
    assert rc == 0
    assert "approved" in stdout
    # Confirm via show that status is now approved.
    rc2, show_out, _ = _run_cli("show", draft_id)
    assert rc2 == 0
    assert "approved" in show_out
    assert "approved_by" in show_out


def test_approve_terminal_state_returns_1(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env)
    # Reject first.
    _run_cli("reject", draft_id, "--reason", "spam")
    # Now try to approve — must 1.
    rc, _, stderr = _run_cli("approve", draft_id)
    assert rc == 1
    assert "ERROR" in stderr


# -- reject ---------------------------------------------------------------


def test_reject_with_reason(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env)
    rc, stdout, _ = _run_cli("reject", draft_id, "--reason", "not relevant")
    assert rc == 0
    assert "rejected" in stdout
    rc2, show_out, _ = _run_cli("show", draft_id)
    assert "rejected" in show_out
    assert "not relevant" in show_out


# -- retry ----------------------------------------------------------------


def test_retry_only_works_on_send_failed(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env)
    # Pending → retry should refuse.
    rc, _, stderr = _run_cli("retry", draft_id)
    assert rc == 1
    assert "send_failed" in stderr or "cannot retry" in stderr.lower()


def test_retry_reapproves_send_failed_draft(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    draft_id = _create_via_bridge(cli_env)
    # Approve, then simulate relay failure.
    approved = cli_env.patch(
        f"/v1/agent/drafts/{draft_id}",
        json={"status": "approved"},
        headers={"Authorization": "Bearer dev-token-agent-approve"},
    ).json()
    cli_env.post(
        "/v1/imessage/sent",
        json={
            "agent": "clu",
            "message_id": approved["dispatch_message_id"],
            "to": approved["to_handle"],
            "body": approved["body"],
            "status": "failed",
            "error_code": "buddy_not_found",
            "error_message": "not on iMessage",
        },
        headers={"Authorization": "Bearer dev-token-imessage-relay"},
    )
    rc, stdout, _ = _run_cli("retry", draft_id)
    assert rc == 0
    assert "retry queued" in stdout


# -- edit -----------------------------------------------------------------


def test_edit_with_editor_substitution(
    cli_env: TestClient,
    tokens: list[TokenFixture],  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Substitute a tiny shell that rewrites the editor file in place."""
    draft_id = _create_via_bridge(cli_env, body="original")
    # Stand in for $EDITOR: a one-liner that overwrites the file's content.
    fake_editor_path = Path(os.environ.get("TMPDIR", "/tmp")) / "fake_editor.sh"  # noqa: S108
    fake_editor_path.write_text(
        "#!/bin/sh\nprintf 'edited body here' > \"$1\"\n",
        encoding="utf-8",
    )
    fake_editor_path.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(fake_editor_path))

    rc, stdout, _ = _run_cli("edit", draft_id)
    assert rc == 0
    assert "updated body" in stdout
    rc2, show_out, _ = _run_cli("show", draft_id)
    assert "edited body here" in show_out


# -- env handling ---------------------------------------------------------


def test_missing_cli_token_exits_2(
    cli_env: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tokens: list[TokenFixture],  # noqa: ARG001
) -> None:
    _ = cli_env
    monkeypatch.delenv("CLI_TOKEN", raising=False)
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err), pytest.raises(SystemExit) as exc:
        clu_drafts_cli.main(["list"])
    assert exc.value.code == 2
    assert "CLI_TOKEN" in err.getvalue()
