#!/bin/bash
# Install kepubify (Kobo EPUB→KEPUB converter) for the Kobo sync feature.
# Pinned version is mirrored in app/services/kobo_kepub.py — keep in sync.
#
# Native installs don't need this script; the Python wrapper auto-downloads
# the same binary on first use. The script exists so Docker builds get
# the binary baked in (no first-request delay, works offline).
set -euo pipefail

VERSION="${KEPUBIFY_VERSION:-v4.0.4}"
ARCH="$(uname -m)"

case "$ARCH" in
    x86_64|amd64) ASSET="kepubify-linux-64bit" ;;
    aarch64|arm64) ASSET="kepubify-linux-arm64" ;;
    *)
        echo "kepubify: no pinned asset for arch=$ARCH — skipping (Python will auto-download at runtime)"
        exit 0
        ;;
esac

URL="https://github.com/pgaskin/kepubify/releases/download/${VERSION}/${ASSET}"
DEST="/usr/local/bin/kepubify"

echo "kepubify: downloading $VERSION ($ASSET) from $URL"
curl -fsSL -o "$DEST" "$URL"
chmod +x "$DEST"

echo "kepubify: installed at $DEST"
"$DEST" --version || true
