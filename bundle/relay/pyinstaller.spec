# PyInstaller spec for OpenClawRelay.app.
#
# Invoked by bundle/relay/build.sh:
#     uv run --no-sync pyinstaller bundle/relay/pyinstaller.spec --clean --noconfirm
#
# Produces dist/OpenClawRelay.app — a Cocoa-style .app bundle whose
# Contents/MacOS/OpenClawRelay binary is a frozen Python interpreter
# launching relay.launcher:main(). The .app's Info.plist is generated
# from bundle/relay/Info.plist.template by build.sh after PyInstaller
# finishes (we override BUNDLE.info_plist below to keep PyInstaller's
# defaults from clobbering it).
#
# Boundary note: we explicitly DO NOT pull `bridge` or `brains_shared`
# into the bundle — the relay is its own package boundary. Only the
# relay's own modules + httpx (its single declared dep) need to ship.

# ruff: noqa  -- this is a PyInstaller config, not normal Python source

import os
from pathlib import Path

# bundle/relay/pyinstaller.spec lives two levels under the repo root.
SPEC_DIR = Path(SPEC).resolve().parent  # type: ignore[name-defined]
REPO_ROOT = SPEC_DIR.parent.parent
RELAY_SRC = REPO_ROOT / "relays" / "imessage" / "src"

block_cipher = None


a = Analysis(
    [str(RELAY_SRC / "relay" / "launcher.py")],
    pathex=[str(RELAY_SRC)],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyInstaller's static analyser walks imports from launcher.py and
        # picks up relay.{main,bridge_client,chatdb,config,osascript,keychain_reader}
        # automatically. Listed here as a belt-and-braces guard against
        # PyInstaller missing one of them under exotic import shapes.
        "relay",
        "relay.bridge_client",
        "relay.chatdb",
        "relay.config",
        "relay.keychain_reader",
        "relay.launcher",
        "relay.main",
        "relay.osascript",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Belt-and-braces: forbid any cross-package leakage.
        "bridge",
        "brains_shared",
        "clu",
        "tron",
        "flynn",
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
    name="OpenClawRelay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # LSUIElement-style background app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",     # M-series only; bridge spec is locked to a single Mac Mini M4
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
    name="OpenClawRelay",
)

# Wrap into a .app. Info.plist is replaced wholesale by build.sh after
# PyInstaller writes its default — we keep PyInstaller's stub minimal so
# the post-build plutil overwrite is idempotent.
app = BUNDLE(
    coll,
    name="OpenClawRelay.app",
    icon=None,
    bundle_identifier="com.giuseppelopesme.openclaw.relay.clu",
    version="0.1.0",
    info_plist={
        # Minimal stub — bundle/relay/build.sh overwrites this file with
        # the contents of bundle/relay/Info.plist.template after PyInstaller
        # finishes. The values here exist only so PyInstaller's BUNDLE step
        # doesn't fail validation.
        "CFBundleName": "OpenClawRelay",
        "CFBundleDisplayName": "OpenClaw Relay",
        "CFBundleIdentifier": "com.giuseppelopesme.openclaw.relay.clu",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "14.0",
    },
)
