# PyInstaller spec for OpenClawBridge.app.
#
# Invoked by bundle/bridge/build.sh:
#     uv run --no-sync pyinstaller bundle/bridge/pyinstaller.spec --clean --noconfirm
#
# Produces dist/OpenClawBridge.app — a Cocoa-style .app bundle whose
# Contents/MacOS/OpenClawBridge binary is a frozen Python interpreter
# launching bundle/bridge/entry.py:main(). The entry script dispatches
# on argv[1] to one of three modes (supervisor / bridge / brain), so a
# single signed binary covers all three roles. See bundle/bridge/entry.py.
#
# Three packages must ship inside the bundle:
#
#   1. bridge          — FastAPI app, Keychain wrapper, providers, routes.
#   2. brains_shared   — typed SDK the brain uses (incl. the generated
#                        attrs models).
#   3. agent           — the brain process (default agent identity).
#
# We deliberately exclude `relay` (its own .app) and dev-only deps
# (pytest, etc.). bundle/bridge/Info.plist.template is the real
# Info.plist; build.sh overwrites PyInstaller's stub after the BUNDLE
# step finishes.

# ruff: noqa  -- this is a PyInstaller config, not normal Python source

from pathlib import Path

# bundle/bridge/pyinstaller.spec lives two levels under the repo root.
SPEC_DIR = Path(SPEC).resolve().parent  # type: ignore[name-defined]
REPO_ROOT = SPEC_DIR.parent.parent
BRIDGE_SRC = REPO_ROOT / "bridge" / "src"
BRAIN_SHARED_SRC = REPO_ROOT / "brains" / "shared" / "src"
AGENT_SRC = REPO_ROOT / "brains" / "agent" / "src"

block_cipher = None


a = Analysis(
    [str(SPEC_DIR / "entry.py")],
    pathex=[
        str(BRIDGE_SRC),
        str(BRAIN_SHARED_SRC),
        str(AGENT_SRC),
    ],
    binaries=[],
    datas=[
        # Migrations live alongside the bridge code as `.sql` files. The
        # migration runner reads them at startup; PyInstaller does not
        # ship `.sql` files automatically. Path is relative to BRIDGE_SRC.
        (str(BRIDGE_SRC / "bridge" / "migrations" / "*.sql"), "bridge/migrations"),
    ],
    hiddenimports=[
        # Belt-and-braces — PyInstaller's static analyser walks imports
        # from entry.py, but a few are dynamic (route registration via
        # __init__.py imports, providers loaded by name) and benefit from
        # being listed explicitly. If a route file is missing from the
        # bundle, FastAPI startup fails with a clear ImportError.
        "bridge",
        "bridge.__main__",
        "bridge.auth",
        "bridge.config",
        "bridge.errors",
        "bridge.idempotency",
        "bridge.keychain",
        "bridge.logging_setup",
        "bridge.main",
        "bridge.middleware",
        "bridge.ratelimit",
        "bridge.supervisor",
        "bridge.telemetry",
        "bridge.eventbus",
        "bridge.eventbus.publisher",
        "bridge.eventbus.subscriber",
        "bridge.providers",
        "bridge.providers.vault",
        "bridge.providers.apple",
        "bridge.providers.apple.calendar",
        "bridge.providers.apple.contacts",
        "bridge.providers.apple.reminders",
        "bridge.providers.email",
        "bridge.providers.email.imap",
        "bridge.providers.email.smtp",
        "bridge.providers.llm",
        "bridge.providers.llm.base",
        "bridge.providers.llm.openrouter",
        "bridge.providers.llm.router",
        "bridge.routes",
        "bridge.routes.auth",
        "bridge.routes.calendar",
        "bridge.routes.contacts",
        "bridge.routes.email",
        "bridge.routes.events",
        "bridge.routes.health",
        "bridge.routes.imessage",
        "bridge.routes.llm",
        "bridge.routes.reminders",
        "bridge.routes.vault",
        "brains_shared",
        "brains_shared.client",
        "brains_shared.eventbus",
        "brains_shared.events",
        "brains_shared.llm",
        "brains_shared.obsidian",
        "agent",
        "agent.__main__",
        "agent.config",
        "agent.context",
        "agent.main",
        "agent.state",
        "agent.handlers",
        "agent.handlers.imessage_received",
        # uvicorn loads its loop and protocol implementations by string —
        # PyInstaller misses these without an explicit hint.
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Belt-and-braces: forbid any cross-package leakage from the
        # other side of the repo.
        "relay",
        # Test-only deps that can sneak in via dev installs.
        "pytest",
        "fakeredis",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenClawBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # LSUIElement-style background app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",     # M-series only; locked to a single Mac Mini M4
    codesign_identity=None,  # build.sh signs the whole .app post-pack
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OpenClawBridge",
)

# Wrap into a .app. Info.plist is replaced wholesale by build.sh after
# PyInstaller writes its default — we keep PyInstaller's stub minimal so
# the post-build plutil overwrite is idempotent.
app = BUNDLE(
    coll,
    name="OpenClawBridge.app",
    icon=None,
    bundle_identifier="me.lopes.openclaw.bridge",
    version="0.1.0",
    info_plist={
        # Minimal stub — bundle/bridge/build.sh overwrites this file with
        # the contents of bundle/bridge/Info.plist.template after PyInstaller
        # finishes. The values here exist only so PyInstaller's BUNDLE step
        # does not fail validation.
        "CFBundleName": "OpenClawBridge",
        "CFBundleDisplayName": "MacOS Bridge for OpenClaw",
        "CFBundleIdentifier": "me.lopes.openclaw.bridge",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "14.0",
    },
)
