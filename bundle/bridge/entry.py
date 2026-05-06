"""Multi-mode entry point for the frozen OpenClawBridge.app binary.

PyInstaller produces a single signed binary at
``Contents/MacOS/OpenClawBridge``. That binary cannot accept ``-m`` —
PyInstaller bakes one entry-script callable at build time. To keep the
bundle to a single signed Mach-O (one TCC identity, one notarization
ticket, simpler entitlements story), this module dispatches on
``argv[1]``:

  * (no arg)   → supervisor mode (default; what launchd starts)
  * "bridge"   → bridge mode (FastAPI on 127.0.0.1:8788)
  * "brain"    → brain mode (agent process)

The supervisor's ``_build_default_children`` already knows it is frozen
and spawns the same ``sys.executable`` with ``"bridge"`` or ``"brain"``
as argv[1], so this dispatch matches what the supervisor sends.

In dev (``scripts/run-supervisor.sh``), this module is unused — the
supervisor uses ``[python, "-m", "bridge"]`` and
``[python, "-m", "agent"]`` because the venv's Python accepts ``-m``.

Boundary note: this file imports both ``bridge`` and ``agent`` packages.
That is intentional — the .app *is* the integration point between them,
and ``scripts/check-boundaries.sh`` only enforces boundaries inside the
``bridge/``, ``brains/``, and ``relays/`` source trees. ``bundle/`` is
build infrastructure and lives outside that scope.
"""

from __future__ import annotations

import sys


def _supervisor_main() -> int:
    from bridge.supervisor import main as supervisor_main

    return supervisor_main()


def _bridge_main() -> int:
    # Strip the mode arg so downstream sees argv[0]=binary, argv[1:]=user args.
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    from bridge.__main__ import main as bridge_main

    bridge_main()
    return 0


def _brain_main() -> int:
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    from agent.__main__ import main as brain_main

    return brain_main()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "supervisor"
    if mode == "supervisor":
        return _supervisor_main()
    if mode == "bridge":
        return _bridge_main()
    if mode == "brain":
        return _brain_main()
    sys.stderr.write(f"OpenClawBridge: unknown mode {mode!r}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
