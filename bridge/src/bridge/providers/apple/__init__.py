"""Apple-host providers (Calendar, Reminders, Contacts).

The bridge talks to macOS user data through `osascript`. Each module here
owns one resource (calendar / reminders / contacts) and exposes a typed
interface that routes can consume.

A single shared async helper, `runner.run_osascript`, is the only seam that
calls into the host. Tests monkeypatch it; the integration tests opt in via
the `macos_apple` pytest marker.
"""
