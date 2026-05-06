#!/usr/bin/env bash
# Build .icns icon bundles + menu bar template assets from SVG sources.
#
# Usage:  scripts/build-icons.sh
#
# Inputs:
#   assets/icons/sources/Bridge.svg          (1024x1024 squircle, cyan)
#   assets/icons/sources/Relay.svg           (1024x1024 squircle, amber)
#   assets/icons/sources/MenubarTemplate.svg (22x22 monochrome, transparent bg)
#
# Outputs:
#   assets/icons/build/Bridge.icns
#   assets/icons/build/Relay.icns
#   assets/icons/build/RelayMenubarTemplate/RelayTemplate.png       (22pt @1x)
#   assets/icons/build/RelayMenubarTemplate/RelayTemplate@2x.png    (44pt @2x)
#   assets/icons/build/RelayMenubarTemplate/RelayTemplate@3x.png    (66pt @3x)
#   assets/icons/build/RelayMenubarTemplate/RelayTemplate.pdf       (vector)
#
# Liquid Glass note: .icns is the legacy fallback. For true Tahoe Liquid
# Glass icons, open the same SVG sources in Icon Composer
# (Xcode > Open Developer Tool > Icon Composer) and export `.icon`.
# `.icns` works fine for launchd Login Items + Finder; `.icon` adds the
# dynamic light/dark/tinted/clear modes.
#
# Requires: rsvg-convert (brew install librsvg), iconutil (Xcode CLT).

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
src="$repo_root/assets/icons/sources"
out="$repo_root/assets/icons/build"

if ! command -v rsvg-convert >/dev/null 2>&1; then
    echo "ERROR: rsvg-convert not found. Run: brew install librsvg" >&2
    exit 1
fi
if ! command -v iconutil >/dev/null 2>&1; then
    echo "ERROR: iconutil not found. Install Xcode Command Line Tools." >&2
    exit 1
fi

mkdir -p "$out"

# .icns built from a .iconset directory containing the canonical Apple
# size matrix (16, 32, 128, 256, 512 each at @1x and @2x → 1024 max).
build_icns() {
    local name="$1"
    local svg="$src/${name}.svg"
    if [[ ! -f "$svg" ]]; then
        echo "ERROR: missing source $svg" >&2
        return 1
    fi
    local iconset="$out/${name}.iconset"
    rm -rf "$iconset" "$out/${name}.icns"
    mkdir -p "$iconset"

    rasterize() {
        local px="$1" file="$2"
        rsvg-convert -w "$px" -h "$px" -a "$svg" -o "$iconset/$file"
    }

    rasterize 16   icon_16x16.png
    rasterize 32   icon_16x16@2x.png
    rasterize 32   icon_32x32.png
    rasterize 64   icon_32x32@2x.png
    rasterize 128  icon_128x128.png
    rasterize 256  icon_128x128@2x.png
    rasterize 256  icon_256x256.png
    rasterize 512  icon_256x256@2x.png
    rasterize 512  icon_512x512.png
    rasterize 1024 icon_512x512@2x.png

    iconutil --convert icns --output "$out/${name}.icns" "$iconset"
    rm -rf "$iconset"
    echo "  built $out/${name}.icns"
}

build_menubar_template() {
    local svg="$src/MenubarTemplate.svg"
    local mb_out="$out/RelayMenubarTemplate"
    rm -rf "$mb_out"
    mkdir -p "$mb_out"
    # Menu bar item is 22pt tall on macOS. Render at @1x/@2x/@3x.
    rsvg-convert -w 22 -h 22 -a "$svg" -o "$mb_out/RelayTemplate.png"
    rsvg-convert -w 44 -h 44 -a "$svg" -o "$mb_out/RelayTemplate@2x.png"
    rsvg-convert -w 66 -h 66 -a "$svg" -o "$mb_out/RelayTemplate@3x.png"
    rsvg-convert -f pdf -a "$svg" -o "$mb_out/RelayTemplate.pdf"
    echo "  built $mb_out/ (PNG @1x/2x/3x + vector PDF)"
}

echo "Building app icons..."
build_icns Bridge
build_icns Relay
echo "Building relay menu bar template..."
build_menubar_template

echo
echo "Done. Outputs in $out/"
