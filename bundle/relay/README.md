# `bundle/relay/` — OpenClawRelay.app build artefacts

PyInstaller spec, plist templates, entitlements, and build/test scripts
for **OpenClawRelay.app** — the Developer-ID-signed, notarized .app
bundle that runs the iMessage relay process. Replaces the
`scripts/run-relay.sh` + `ops/launchd/com.giuseppelopesme.openclaw.relay.clu.plist`
topology that shipped in Session 7.

Why a `.app` exists at all: macOS Sequoia denies AppleEvents
(osascript → Messages.app) from unsigned/ad-hoc-signed binaries. The
`.app`'s code-signed identity is what lets the operator click "Allow"
on the "OpenClawRelay wants to control Messages.app" prompt and have
the grant stick. See "Strategic shift" in
`01 - Projects/OpenClaw/Bridge/Claude Code Handoff.md`.

## Files

| File | Role |
| --- | --- |
| `pyinstaller.spec` | PyInstaller build definition. Pulls `relays/imessage/src/relay/launcher.py` as the entry point; bundles only the relay package + httpx (the relay's only declared dep). |
| `Info.plist.template` | Real `Info.plist`. Injected into the .app by `build.sh` after PyInstaller's BUNDLE step. `__VERSION__` is replaced with the package version from `relays/imessage/pyproject.toml`. |
| `entitlements.plist` | Code-signing entitlements. See "Entitlements rationale" below. Comments are kept out of the XML body — `codesign`'s AMFI parser rejects multi-line inline comments even when `plutil -lint` accepts them. |
| `launchagent.plist.template` | LaunchAgent that starts the .app at user login. Bundled at `Contents/Library/LaunchAgents/com.giuseppelopesme.openclaw.relay.clu.plist` inside the .app; the install step copies it into `~/Library/LaunchAgents/` and substitutes `__APP_PATH__` + `__LOG_DIR__`. |
| `build.sh` | Build → codesign → notarize → staple. Idempotent. Reads `TEAM_ID`, `DEV_ID_IDENTITY`, `NOTARY_PROFILE` from env. |
| `test_bundle.sh` | Post-build smoke test. Verifies bundle structure, Info.plist values, hardened-runtime signing, entitlements, Gatekeeper acceptance, stapled ticket. |
| `dist/` | Build output. Not checked in. `OpenClawRelay.app` and `OpenClawRelay.zip` (notarization payload) live here. |
| `build/` | PyInstaller intermediates. Not checked in. |

## Entitlements rationale

Each entry in `entitlements.plist` is a deliberate trade-off. Future
contributors should not add or remove keys without re-doing the
analysis below.

- **`com.apple.security.automation.apple-events = true`** — ESSENTIAL.
  This is the entitlement whose absence caused `errAEEventNotPermitted`
  on 2026-05-04 and triggered the entire move to Developer-ID signing.
  Without it the relay cannot drive `osascript` → Messages.app.
- **`com.apple.security.app-sandbox = false`** — ESSENTIAL (in negative
  form). The App Store sandbox forbids reading `chat.db`
  (FDA-protected) and forbids AppleEvents to apps the user hasn't
  pre-declared. The whole Apple Developer Program / direct-distribution
  path exists for this reason — see "Strategic shift" in
  `01 - Projects/OpenClaw/Bridge/Claude Code Handoff.md`. Do not enable
  app-sandbox without re-doing that analysis.
- **`com.apple.security.cs.allow-jit = true`** — TRADEOFF for
  PyInstaller's frozen interpreter. The bootloader maps pages of
  bundled bytecode as RWX briefly during startup. Hardened runtime
  (which `codesign --options runtime` enables, and notarization
  requires) forbids this without `cs.allow-jit`. The alternative is
  `cs.allow-unsigned-executable-memory`, which is strictly weaker —
  JIT-allow is the documented PyInstaller path. Symptom without it:
  bundle launches, hardened runtime kills it instantly with
  `EXC_BAD_ACCESS (SIGKILL)`, Console reports
  `killed: 9 — code signing violation`.
- **`com.apple.security.cs.disable-library-validation = true`** —
  TRADEOFF for PyInstaller's bundled C extensions. Python 3.13 ships
  C extensions (`_ssl`, `_hashlib`, ...) signed by python.org's
  certificate, not ours. Hardened runtime would refuse to load them
  under our identity without this. We bundle a known-good Python and
  the surface is small; the tradeoff is acceptable. Symptom without
  it: at first launch, dyld errors of the form `library not loaded` /
  `code signature in foo.so not valid`.

## Bundling tool — choice and rationale

**PyInstaller**, not Briefcase or py2app.

PyInstaller is the well-trodden path for freezing Python services into
macOS .app bundles: documented hardened-runtime story, `--target-arch
arm64` flag for our M-series-only runtime, integrates cleanly with
Apple's `codesign` + `notarytool` workflow. Briefcase (BeeWare) is more
opinionated about app structure, generates extra Toga UI scaffolding the
relay does not need, and would have required teaching it about
LaunchAgents. py2app is a third option but its notarization story is
less well-trodden and it's been less actively maintained.

If a future session needs to swap in Briefcase (e.g. for the bridge .app
which may want a real status-bar UI), the per-bundle build setup is
already isolated under `bundle/<component>/` — no shared scaffolding
to disentangle.

## Build flow

```
$ export TEAM_ID=283UY8S778
$ export DEV_ID_IDENTITY="Developer ID Application: Giuseppe Lopes (283UY8S778)"
$ export NOTARY_PROFILE=openclaw-notary
$ bundle/relay/build.sh         # ~3 minutes (notarization is the long pole)
$ bundle/relay/test_bundle.sh   # ~5 seconds; fails fast if anything is off
```

After both pass: `bundle/relay/dist/OpenClawRelay.app` is ready to ship.
The operator-side install lives in `scripts/setup-clu-account.sh`.

## Caveats / open issues

- **Per-agent variants.** This bundle is hardcoded to agent `clu`
  (CFBundleIdentifier ends in `.relay.clu`, the bundled LaunchAgent
  label is `com.giuseppelopesme.openclaw.relay.clu`). When TRON and
  FLYNN land, the natural shape is to parameterise the spec so a
  single build script produces three .apps (`bundle/relay/build.sh
  --agent tron`, etc.). Out of scope for Session 10a — first pattern
  needs to ship and prove out before generalising.
- **No CI yet.** `build.sh` requires the operator's signing identity
  and notarytool credentials, which are not (and should not be) in
  CI's hands. When CI does happen, the build artefact will need to be
  produced on a self-hosted runner or via a managed Apple-signing
  service.
- **Auto-update.** Not part of this session. A Sparkle integration is
  the obvious future work, but the current install flow is `git pull
  && ./bundle/relay/build.sh && cp -r dist/OpenClawRelay.app …` which
  is acceptable for personal infra.
