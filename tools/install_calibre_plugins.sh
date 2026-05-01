#!/usr/bin/env bash
# Install third-party Calibre metadata plugins at Docker build time.
# Sources: https://github.com/kiwidude68/calibre_plugins
set -euo pipefail

PLUGINS=(
    "https://github.com/kiwidude68/calibre_plugins/releases/download/goodreads-1.8.4/goodreads-1.8.4.zip"
    "https://github.com/kiwidude68/calibre_plugins/releases/download/fantastic_fiction-1.7.5/fantastic_fiction-1.7.5.zip"
    "https://github.com/kiwidude68/calibre_plugins/releases/download/fictiondb-1.4.3/fictiondb-1.4.3.zip"
)

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export QT_QPA_PLATFORM=offscreen
export CALIBRE_NO_NATIVE_FILEDIALOGS=1

for URL in "${PLUGINS[@]}"; do
    FILENAME=$(basename "$URL")
    echo "Downloading $FILENAME..."
    curl -fsSL -o "$TMP/$FILENAME" "$URL"
    echo "Installing $FILENAME..."
    calibre-customize --add-plugin="$TMP/$FILENAME"
    echo "Done: $FILENAME"
done

echo "All Calibre plugins installed."
