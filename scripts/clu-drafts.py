#!/usr/bin/env python3
"""CLI for the agent-draft approval flow (P1a).

Subcommands:

    clu-drafts.py list   [--all] [--agent clu]
    clu-drafts.py show   <draft_id>
    clu-drafts.py approve <draft_id> [--by NAME]
    clu-drafts.py reject  <draft_id> [--reason TEXT]
    clu-drafts.py retry   <draft_id>
    clu-drafts.py edit    <draft_id>      (opens $EDITOR)

Env:

    BRIDGE_URL   default http://127.0.0.1:8788
    CLI_TOKEN    bearer with `agent:drafts:read` + `agent:drafts:approve`
                 (mint via scripts/mint-token.py --actor cli.giuseppelopes
                  --scopes agent:drafts:read,agent:drafts:approve)

Output:

    Plain text, stdlib only — no `rich`. ANSI colour codes are only
    emitted when stdout is a TTY (operator's terminal); otherwise raw,
    pipe-friendly. Exit code 0 on success; 1 on any caller / bridge error.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

# The CLI is invoked via `uv run --no-sync python scripts/clu-drafts.py`,
# so brains_shared lives on PYTHONPATH already (per scripts/run-bridge.sh
# convention). When run from a fresh interpreter we still need to push
# the workspace src dirs onto sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in ("brains/shared/src", "bridge/src"):
    _full = _REPO_ROOT / _src
    if str(_full) not in sys.path:
        sys.path.insert(0, str(_full))

from brains_shared import (  # noqa: E402
    AgentError,
    BridgeClient,
    Draft,
    create_draft,  # re-exported for completeness, not used here
    get_draft,
    list_drafts,
    update_draft,
)

_ = create_draft  # silence unused-import; the CLI doesn't create, only reads/updates

DEFAULT_BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8788")


# -- ANSI colour helpers --------------------------------------------------


def _isatty() -> bool:
    return sys.stdout.isatty()


def _colorise(text: str, code: str) -> str:
    if not _isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(s: str) -> str:
    return _colorise(s, "1")


def _green(s: str) -> str:
    return _colorise(s, "32")


def _yellow(s: str) -> str:
    return _colorise(s, "33")


def _red(s: str) -> str:
    return _colorise(s, "31")


def _dim(s: str) -> str:
    return _colorise(s, "2")


_STATUS_COLOR: dict[str, Callable[[str], str]] = {
    "pending": _yellow,
    "approved": _green,
    "sent": _green,
    "rejected": _dim,
    "send_failed": _red,
}


def _fmt_status(status: str) -> str:
    fn = _STATUS_COLOR.get(status, lambda s: s)
    return fn(status)


def _short(s: str | None, n: int = 80) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


# -- bridge client wrapper -----------------------------------------------


def _token() -> str:
    token = os.environ.get("CLI_TOKEN", "").strip()
    if not token:
        sys.stderr.write(
            "ERROR: CLI_TOKEN not set. Mint with:\n"
            "  scripts/mint-token.py --actor cli.giuseppelopes "
            "--scopes agent:drafts:read,agent:drafts:approve\n"
            "Then export CLI_TOKEN=<the printed plaintext>.\n",
        )
        sys.exit(2)
    return token


async def _with_client(work: Callable[[BridgeClient], Awaitable[int]]) -> int:
    base = os.environ.get("BRIDGE_URL", DEFAULT_BRIDGE_URL)
    async with BridgeClient(base_url=base, token=_token()) as client:
        return await work(client)


# -- subcommand: list -----------------------------------------------------


async def cmd_list(args: argparse.Namespace) -> int:
    async def _run(client: BridgeClient) -> int:
        try:
            status = None if args.all else "pending"
            drafts = await list_drafts(
                client,
                agent=args.agent,
                status=status,
                limit=args.limit,
            )
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        if not drafts:
            scope = f"status={status or 'any'}"
            if args.agent:
                scope += f", agent={args.agent}"
            print(_dim(f"(no drafts: {scope})"))
            return 0
        # Header
        print(
            _bold(f"{'STATUS':<11}  {'AGENT':<6}  {'CREATED':<25}  {'TO':<22}  {'PREVIEW'}"),
        )
        for d in drafts:
            print(
                f"{_fmt_status(d.status):<11}  "
                f"{d.agent:<6}  "
                f"{d.created_at:<25}  "
                f"{_short(d.to_handle, 22):<22}  "
                f"{_short(d.preview, 60)}",
            )
            print(_dim(f"  id: {d.draft_id}"))
        return 0

    return await _with_client(_run)


# -- subcommand: show -----------------------------------------------------


async def cmd_show(args: argparse.Namespace) -> int:
    async def _run(client: BridgeClient) -> int:
        try:
            d = await get_draft(client, args.draft_id)
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        _print_full(d)
        return 0

    return await _with_client(_run)


def _print_full(d: Draft) -> None:
    print(_bold("draft_id      "), d.draft_id)
    print(_bold("agent          "), d.agent)
    print(_bold("channel        "), d.channel)
    print(_bold("to             "), d.to_handle)
    print(_bold("status         "), _fmt_status(d.status))
    print(_bold("created_at     "), d.created_at)
    print(_bold("last_modified  "), d.last_modified_at)
    if d.in_reply_to_event_id:
        print(_bold("in_reply_to    "), d.in_reply_to_event_id)
    if d.approved_at:
        print(_bold("approved_at    "), d.approved_at)
    if d.approved_by:
        print(_bold("approved_by    "), d.approved_by)
    if d.reject_reason:
        print(_bold("reject_reason  "), d.reject_reason)
    if d.dispatch_message_id:
        print(_bold("dispatch_msg   "), d.dispatch_message_id)
    if d.sent_at:
        print(_bold("sent_at        "), d.sent_at)
    if d.last_send_error_code:
        print(
            _bold("send_error     "),
            _red(f"{d.last_send_error_code}: {d.last_send_error_message}"),
        )
    print()
    print(_bold("body:"))
    print(d.body)


# -- subcommand: approve / reject / retry --------------------------------


async def cmd_approve(args: argparse.Namespace) -> int:
    async def _run(client: BridgeClient) -> int:
        try:
            d = await update_draft(
                client,
                args.draft_id,
                status="approved",
                approved_by=args.by,
            )
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        print(_green(f"approved {d.draft_id}"))
        if d.dispatch_message_id:
            print(_dim(f"  dispatch queued as message_id={d.dispatch_message_id}"))
        return 0

    return await _with_client(_run)


async def cmd_reject(args: argparse.Namespace) -> int:
    async def _run(client: BridgeClient) -> int:
        try:
            d = await update_draft(
                client,
                args.draft_id,
                status="rejected",
                reject_reason=args.reason,
            )
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        print(_dim(f"rejected {d.draft_id}: {d.reject_reason or '(no reason given)'}"))
        return 0

    return await _with_client(_run)


async def cmd_retry(args: argparse.Namespace) -> int:
    async def _run(client: BridgeClient) -> int:
        try:
            current = await get_draft(client, args.draft_id)
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        if current.status not in ("send_failed", "approved"):
            sys.stderr.write(
                f"ERROR: cannot retry from status {current.status!r}; "
                "retry only applies to send_failed (or already-approved) drafts.\n",
            )
            return 1
        try:
            d = await update_draft(client, args.draft_id, status="approved")
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        print(_green(f"retry queued for {d.draft_id}"))
        return 0

    return await _with_client(_run)


# -- subcommand: edit -----------------------------------------------------


async def cmd_edit(args: argparse.Namespace) -> int:
    async def _run(client: BridgeClient) -> int:
        try:
            d = await get_draft(client, args.draft_id)
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        if d.status in ("sent", "rejected"):
            sys.stderr.write(
                f"ERROR: cannot edit a {d.status} draft.\n",
            )
            return 1
        new_body = _open_editor(d.body)
        if new_body is None:
            print(_dim("edit cancelled (no changes saved)"))
            return 0
        if new_body == d.body:
            print(_dim("body unchanged"))
            return 0
        try:
            updated = await update_draft(client, args.draft_id, body=new_body)
        except AgentError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 1
        print(_green(f"updated body for {updated.draft_id}"))
        if args.then_approve:
            try:
                approved = await update_draft(
                    client,
                    args.draft_id,
                    status="approved",
                    approved_by=args.by,
                )
            except AgentError as exc:
                sys.stderr.write(f"ERROR (approve after edit): {exc}\n")
                return 1
            print(_green(f"approved {approved.draft_id}"))
        return 0

    return await _with_client(_run)


def _open_editor(initial: str) -> str | None:
    """Open $EDITOR (or vi) on `initial`, return the new content or None
    if the operator didn't change anything (bailing out is also an option;
    we treat unchanged-after-save as a no-op)."""
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as fh:
        fh.write(initial)
        path = fh.name
    try:
        # Spawn editor; inherit stdio so the operator can interact with it.
        rc = subprocess.run([editor, path], check=False).returncode  # noqa: S603 — editor is operator-trusted
        if rc != 0:
            return None
        edited = Path(path).read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
    # Strip a single trailing newline editors love to add.
    if edited.endswith("\n") and not initial.endswith("\n"):
        edited = edited[:-1]
    return edited


# -- argparse plumbing ---------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clu-drafts",
        description="CLI for the bridge's agent-draft approval flow (P1a).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list drafts (pending by default)")
    p_list.add_argument(
        "--all",
        action="store_true",
        help="include non-pending statuses",
    )
    p_list.add_argument(
        "--agent",
        choices=("clu", "tron", "flynn"),
        default=None,
        help="filter by agent",
    )
    p_list.add_argument(
        "--limit",
        type=int,
        default=50,
        help="max rows (1..200)",
    )
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show full body + metadata")
    p_show.add_argument("draft_id")
    p_show.set_defaults(func=cmd_show)

    p_approve = sub.add_parser("approve", help="approve a draft (triggers dispatch)")
    p_approve.add_argument("draft_id")
    p_approve.add_argument(
        "--by",
        default=os.environ.get("USER", "operator"),
        help="approved_by attribution (defaults to $USER)",
    )
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="reject a draft (terminal, no dispatch)")
    p_reject.add_argument("draft_id")
    p_reject.add_argument("--reason", default=None, help="optional reject reason")
    p_reject.set_defaults(func=cmd_reject)

    p_retry = sub.add_parser("retry", help="retry a send_failed draft")
    p_retry.add_argument("draft_id")
    p_retry.set_defaults(func=cmd_retry)

    p_edit = sub.add_parser("edit", help="open $EDITOR on the draft body")
    p_edit.add_argument("draft_id")
    p_edit.add_argument(
        "--then-approve",
        action="store_true",
        help="after a successful edit, immediately approve the draft",
    )
    p_edit.add_argument(
        "--by",
        default=os.environ.get("USER", "operator"),
        help="approved_by attribution if --then-approve is set",
    )
    p_edit.set_defaults(func=cmd_edit)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    coro = args.func(args)
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
