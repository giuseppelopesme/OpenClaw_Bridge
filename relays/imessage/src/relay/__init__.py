"""OpenClaw iMessage relay.

Runs as a single macOS user (`clu`, `tron`, or `flynn`) — one process per
user. Polls ``~/Library/Messages/chat.db`` for new messages, posts them
to the bridge as ``imessage.received.{agent}`` events, and dispatches
queued outbound jobs the bridge hands back via long-poll.

The relay is intentionally thin: it never imports from ``bridge/`` or
``brains/``. All cross-component communication goes through the bridge's
HTTP API on loopback. See ``docs/repo-layout.md`` § Package boundaries.
"""

__version__ = "0.1.0"
