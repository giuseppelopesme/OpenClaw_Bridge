"""External-system providers (Apple, email, vault, LLM, …).

The bridge is the only component that talks to these. Each module here owns
one external concern and exposes a small, typed interface that routes use.
"""
