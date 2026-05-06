# OpenClaw — Icon Assets

Liquid Glass Tahoe-style app icons + relay menu bar template.

## Layout

```
assets/icons/
├── sources/                    # SVG masters (edit here)
│   ├── Bridge.svg              # Bridge.app — cyan, hub-and-spire
│   ├── Relay.svg               # Relay.app — amber, pulse antenna
│   └── MenubarTemplate.svg     # Relay menu bar — monochrome template
├── sketches/                   # Concept exploration (kept for reference)
│   └── index.html              # Side-by-side preview of all 9 concepts
└── build/                      # Generated — do not edit
    ├── Bridge.icns
    ├── Relay.icns
    └── RelayMenubarTemplate/
        ├── RelayTemplate.png       # 22pt @1x
        ├── RelayTemplate@2x.png    # 44pt @2x
        ├── RelayTemplate@3x.png    # 66pt @3x
        └── RelayTemplate.pdf       # vector
```

## Build

```bash
scripts/build-icons.sh
```

Requires: `librsvg` (`brew install librsvg`) and `iconutil` (Xcode CLT).

## Liquid Glass — true `.icon` files

`.icns` is the legacy fallback. macOS 26 Tahoe supports the new `.icon`
format with dynamic light / dark / tinted / clear modes via Icon Composer
(bundled with Xcode 26).

To produce real Liquid Glass icons:

1. Open **Icon Composer** — `/Applications/Xcode.app/Contents/Applications/Icon Composer.app`
2. **File → New** → macOS → 1024×1024
3. Drag `assets/icons/sources/Bridge.svg` (or `Relay.svg`) into the canvas
4. Split into layers (background, glass body, glyph, highlight) — Icon Composer auto-detects most of this; manually re-stack as needed
5. Adjust the per-layer **Material** to `Glass` for the body, `Glow` for the central node, `Solid` for the squircle background
6. **File → Export** → `.icon`
7. Save as `assets/icons/build/Bridge.icon` / `Relay.icon`

The `.icon` bundle replaces the `.icns` for true Tahoe rendering. Both
formats can coexist in `Resources/`; macOS prefers `.icon` when present.

## Menu bar template

`MenubarTemplate.svg` is monochrome black on transparent background. The
file name suffix `Template` (case-sensitive) is what tells `NSStatusItem`
to invert the asset for dark-mode menu bars and tint it for the active
accent — do not change the suffix.

## Concept selections

Made from the 9 sketches in `sketches/index.html`:

| App                 | Concept                | Color                 |
|---------------------|------------------------|-----------------------|
| Bridge.app          | B3 — Hub Spire         | cyan `#5BC0EB`        |
| Relay.app           | R2 — Pulse Antenna     | amber `#F5A524`       |
| Relay menu bar      | M1 — Antenna + Arcs    | template (monochrome) |
