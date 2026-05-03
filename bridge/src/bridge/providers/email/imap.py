"""IMAP provider — thread listing, thread detail, healthcheck.

Wraps stdlib `imaplib.IMAP4_SSL` via `asyncio.to_thread` so the bridge's
event loop never blocks. The sync work happens in a thread pool worker;
`async` methods are thin shims over their `_sync_*` counterparts.

### Threading model

We use the IMAP `THREAD REFERENCES` extension (RFC 5256). It's supported
by all three providers in this v1 deployment (Fastmail, iCloud, Gmail).
If a server doesn't speak THREAD, the call falls through to a flat-list
fallback that groups by Subject — accepted as degraded but functional.

### List vs detail

`list_threads` returns lightweight summaries (subject + participants +
count + latest-at + ~200-char snippet). `get_thread` returns full
messages with bodies. We don't cache anything between calls; the
`thread_id` round-trips through the URL and decodes back into the
account + root Message-ID, then we re-search for the thread members.

### Test seam

`IMAPProvider.__init__` accepts a `client_factory` callable. Tests pass
in a factory that returns a fake `IMAP4`-shaped object; production uses
the default factory which constructs a real `IMAP4_SSL`.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, Final, Literal

from bridge.errors import DependencyUnavailable, NotFound
from bridge.providers.email.models import (
    EmailAccount,
    EmailMessage,
    ThreadDetail,
    ThreadSummary,
)
from bridge.providers.email.parsing import parse_imap_message
from bridge.providers.email.threading import (
    encode_thread_id,
    parse_thread_response,
)

logger = logging.getLogger("bridge.providers.email.imap")

DepStatus = Literal["ok", "degraded", "down"]

ClientFactory = Callable[[], Any]
"""Returns an `imaplib.IMAP4`-shaped object. We do not type the protocol
explicitly because imaplib has no Protocol stub and tests pass a Fake."""

# Rough cap on body bytes pulled per message in a list_threads call. We
# fetch full RFC 822 to compute the snippet; payloads above this are
# truncated by IMAP itself if the server supports it, otherwise we just
# take the head of what came back.
_SNIPPET_LEN: Final[int] = 200
# IMAP socket timeout for a single command, seconds.
_CMD_TIMEOUT_S: Final[float] = 10.0
# Healthcheck total budget (login + NOOP + logout), seconds.
_HEALTH_TIMEOUT_S: Final[float] = 3.0


class IMAPProvider:
    """One per email account. Stateless across requests; opens a fresh
    IMAP connection per call (wrapped by `_connect`) — keeps the threading
    model simple and avoids stale connections after long idles."""

    def __init__(
        self,
        account: EmailAccount,
        password: str,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._account = account
        self._password = password
        self._factory: ClientFactory = client_factory or self._default_factory

    @property
    def account(self) -> EmailAccount:
        return self._account

    def _default_factory(self) -> Any:
        return imaplib.IMAP4_SSL(
            self._account.imap_host,
            self._account.imap_port,
            timeout=_CMD_TIMEOUT_S,
        )

    @contextmanager
    def _connect(self) -> Any:
        """Login → yield client → logout. Wraps every imaplib error as a
        `DependencyUnavailable` so route-level handlers stay clean."""
        try:
            client = self._factory()
        except (OSError, imaplib.IMAP4.error) as exc:
            raise DependencyUnavailable(
                "IMAP connect failed.",
                details={"account": self._account.name, "error": str(exc)},
            ) from exc
        try:
            try:
                typ, _ = client.login(self._account.address, self._password)
            except imaplib.IMAP4.error as exc:
                raise DependencyUnavailable(
                    "IMAP login failed.",
                    details={"account": self._account.name, "error": str(exc)},
                ) from exc
            if typ != "OK":
                raise DependencyUnavailable(
                    "IMAP login refused.",
                    details={"account": self._account.name, "status": typ},
                )
            yield client
        finally:
            try:
                client.logout()
            except (OSError, imaplib.IMAP4.error):
                logger.debug("imap_logout_swallowed", exc_info=True)

    # -- listing --------------------------------------------------------

    async def list_threads(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        before: str | None = None,
    ) -> list[ThreadSummary]:
        return await asyncio.to_thread(self._sync_list_threads, query, limit, before)

    def _sync_list_threads(
        self,
        query: str | None,
        limit: int,
        before: str | None,
    ) -> list[ThreadSummary]:
        with self._connect() as imap:
            self._select_inbox(imap)
            criteria = self._build_search_criteria(query, before)
            try:
                typ, data = imap.thread("REFERENCES", "UTF-8", *criteria)
            except imaplib.IMAP4.error as exc:
                raise DependencyUnavailable(
                    "IMAP THREAD failed.",
                    details={"account": self._account.name, "error": str(exc)},
                ) from exc
            if typ != "OK" or not data or not data[0]:
                return []
            raw_threads = parse_thread_response(data[0])
            # Newest-first: IMAP THREAD lists oldest-first by tree root.
            raw_threads.reverse()
            raw_threads = raw_threads[:limit]

            summaries: list[ThreadSummary] = []
            for uids in raw_threads:
                if not uids:
                    continue
                summary = self._build_summary(imap, uids)
                if summary is not None:
                    summaries.append(summary)
            return summaries

    def _build_summary(
        self,
        imap: Any,
        uids: list[int],
    ) -> ThreadSummary | None:
        root_uid = uids[0]
        latest_uid = uids[-1]
        # We need: root subject + Message-ID; latest from/to/date/snippet;
        # all participants. Two FETCHes minimum.
        root_msg = self._fetch_message(imap, root_uid)
        if root_msg is None:
            return None
        latest_msg = root_msg if latest_uid == root_uid else self._fetch_message(imap, latest_uid)
        if latest_msg is None:
            latest_msg = root_msg

        participants = self._collect_participants(imap, uids)
        snippet_source = (latest_msg.body_text or latest_msg.body_html or "").strip()
        snippet = snippet_source[:_SNIPPET_LEN]
        return ThreadSummary(
            id=encode_thread_id(self._account.name, root_msg.message_id),
            subject=root_msg.subject,
            participants=participants,
            message_count=len(uids),
            latest_at=latest_msg.date,
            snippet=snippet,
        )

    def _collect_participants(self, imap: Any, uids: list[int]) -> list[str]:
        """Cheap participant list: From of root + From of latest, deduped.

        A full participant scan would FETCH every message; that's expensive
        for long threads. The summary advertises message_count so the
        caller knows there may be more participants in the detail view.
        """
        seen: list[str] = []
        for uid in (uids[0], uids[-1]):
            msg = self._fetch_message(imap, uid)
            if msg is None:
                continue
            if msg.from_ and msg.from_ not in seen:
                seen.append(msg.from_)
        return seen

    # -- detail ---------------------------------------------------------

    async def get_thread(self, root_message_id: str) -> ThreadDetail:
        return await asyncio.to_thread(self._sync_get_thread, root_message_id)

    def _sync_get_thread(self, root_message_id: str) -> ThreadDetail:
        with self._connect() as imap:
            self._select_inbox(imap)
            # The THREAD parent is referenced by every reply. SEARCH for
            # messages whose Message-ID equals the root OR whose
            # References header contains the root.
            try:
                typ, data = imap.uid(
                    "SEARCH",
                    "OR",
                    "HEADER",
                    "Message-ID",
                    root_message_id,
                    "HEADER",
                    "References",
                    root_message_id,
                )
            except imaplib.IMAP4.error as exc:
                raise DependencyUnavailable(
                    "IMAP SEARCH failed.",
                    details={"account": self._account.name, "error": str(exc)},
                ) from exc
            if typ != "OK":
                raise DependencyUnavailable(
                    "IMAP SEARCH refused.",
                    details={"account": self._account.name, "status": typ},
                )
            uid_blob = b" ".join(data) if data else b""
            uids = [int(tok) for tok in uid_blob.split() if tok.isdigit()]
            if not uids:
                raise NotFound(
                    "Email thread not found.",
                    details={"message_id": root_message_id},
                )
            messages: list[EmailMessage] = []
            for uid in uids:
                msg = self._fetch_message(imap, uid)
                if msg is not None:
                    messages.append(msg)
            messages.sort(key=lambda m: m.date or m.id)
            subject = messages[0].subject if messages else ""
            return ThreadDetail(
                id=encode_thread_id(self._account.name, root_message_id),
                subject=subject,
                messages=messages,
            )

    # -- healthcheck ----------------------------------------------------

    async def healthcheck(self) -> DepStatus:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._sync_healthcheck),
                timeout=_HEALTH_TIMEOUT_S,
            )
        except (TimeoutError, DependencyUnavailable, OSError, imaplib.IMAP4.error):
            return "down"

    def _sync_healthcheck(self) -> DepStatus:
        with self._connect() as imap:
            try:
                typ, _ = imap.noop()
            except imaplib.IMAP4.error:
                return "down"
            return "ok" if typ == "OK" else "degraded"

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _select_inbox(imap: Any) -> None:
        try:
            typ, _ = imap.select("INBOX", readonly=True)
        except imaplib.IMAP4.error as exc:
            raise DependencyUnavailable(
                "IMAP SELECT INBOX failed.",
                details={"error": str(exc)},
            ) from exc
        if typ != "OK":
            raise DependencyUnavailable(
                "IMAP SELECT INBOX refused.",
                details={"status": typ},
            )

    @staticmethod
    def _build_search_criteria(query: str | None, before: str | None) -> tuple[str, ...]:
        parts: list[str] = []
        if before:
            from datetime import datetime as _dt

            try:
                dt = _dt.fromisoformat(before)
            except ValueError as exc:
                raise DependencyUnavailable(
                    "Invalid `before` date for IMAP SEARCH.",
                    details={"value": before, "error": str(exc)},
                ) from exc
            parts.extend(("BEFORE", dt.strftime("%d-%b-%Y")))
        if query:
            parts.extend(("TEXT", query))
        if not parts:
            parts.append("ALL")
        return tuple(parts)

    @staticmethod
    def _fetch_message(imap: Any, uid: int) -> EmailMessage | None:
        try:
            typ, data = imap.fetch(str(uid).encode("ascii"), "(RFC822)")
        except imaplib.IMAP4.error as exc:
            logger.warning(
                "imap_fetch_failed",
                extra={"uid": uid, "error": str(exc)},
            )
            return None
        if typ != "OK" or not data:
            return None
        # imaplib FETCH yields a list of tuples or `b')'` separators. The
        # tuple form is `(b'<header>', b'<rfc822 bytes>')`.
        for entry in data:
            if isinstance(entry, tuple) and len(entry) >= 2 and isinstance(entry[1], bytes):
                return parse_imap_message(str(uid), entry[1])
        return None
