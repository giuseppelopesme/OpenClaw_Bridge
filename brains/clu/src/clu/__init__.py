"""CLU brain.

Subscribes to ``imessage.received.clu`` and runs a triage + draft loop:

1. Decode the envelope.
2. If we've already processed ``event_id``, skip (dedup via SQLite).
3. Triage call: ask the LLM to classify (draft vs ignore).
4. On draft: ask the LLM for a reply body, persist as a pending draft,
   publish ``agent.clu.draft.pending``.
5. Always publish ``agent.clu.task.completed`` (success or error).

The brain is the first consumer of ``brains_shared``. Boundaries:
``clu`` only imports ``brains_shared`` — never ``bridge`` or
``relays`` directly.
"""

__version__ = "0.1.0"
