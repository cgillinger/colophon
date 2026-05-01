#!/usr/bin/env bash
set -euo pipefail

GITHUB_RELEASES_URL="https://api.github.com/repos/kiwidude68/calibre_plugins/releases?per_page=100"

if ! command -v calibre-customize &>/dev/null; then
    echo "Fel: calibre-customize hittades inte i PATH." >&2
    exit 1
fi

# Cache installed plugins to a temp file (avoids pipe/encoding issues)
_PLUGIN_CACHE=$(mktemp)
trap 'rm -f "$_PLUGIN_CACHE"' EXIT
calibre-customize --list-plugins > "$_PLUGIN_CACHE" 2>&1 || true

echo "Hämtar release-lista från GitHub API..."
RELEASES_JSON=$(curl -fsSL --retry 3 "$GITHUB_RELEASES_URL") || {
    echo "Fel: Kunde inte nå GitHub API ($GITHUB_RELEASES_URL)" >&2
    exit 1
}

if [ -z "$RELEASES_JSON" ] || [ "$RELEASES_JSON" = "[]" ]; then
    echo "Fel: GitHub API returnerade inga releaser." >&2
    exit 1
fi

_get_download_url() {
    local prefix="$1"
    if command -v jq &>/dev/null; then
        echo "$RELEASES_JSON" | jq -r --arg p "$prefix" '
            [ .[] | select(.tag_name | startswith($p)) ]
            | sort_by(.published_at)
            | last
            | .assets[]
            | select(.name | endswith(".zip"))
            | .browser_download_url
        ' | head -n1
    else
        echo "$RELEASES_JSON" | python3 - "$prefix" <<'PYEOF'
import json, sys
prefix = sys.argv[1]
data = json.loads(sys.stdin.read())
releases = [r for r in data if r.get("tag_name", "").startswith(prefix)]
if not releases:
    sys.exit(1)
releases.sort(key=lambda r: r.get("published_at", ""))
latest = releases[-1]
for asset in latest.get("assets", []):
    if asset.get("name", "").endswith(".zip"):
        print(asset["browser_download_url"])
        break
PYEOF
    fi
}

_already_installed() {
    grep -aqi "$1" "$_PLUGIN_CACHE"
}

_install_plugin() {
    local name="$1"
    local prefix="$2"
    local url tmpfile

    if _already_installed "$name"; then
        echo "$name är redan installerad, hoppar över."
        return 0
    fi

    echo "Letar upp senaste $name-release..."
    url=$(_get_download_url "$prefix") || true

    if [ -z "$url" ]; then
        echo "Fel: Hittade ingen release-asset för $name (prefix: $prefix)." >&2
        return 1
    fi

    echo "Laddar ner $name från $url..."
    tmpfile=$(mktemp --suffix=.zip)

    if ! curl -fsSL --retry 3 -o "$tmpfile" "$url"; then
        echo "Fel: Nedladdning av $name misslyckades." >&2
        rm -f "$tmpfile"
        return 1
    fi

    if ! file --mime-type "$tmpfile" | grep -q "application/zip"; then
        echo "Fel: Nedladdad fil för $name är inte en ZIP." >&2
        rm -f "$tmpfile"
        return 1
    fi

    echo "Installerar $name..."
    if ! calibre-customize --add-plugin="$tmpfile"; then
        echo "Fel: calibre-customize misslyckades för $name." >&2
        rm -f "$tmpfile"
        return 1
    fi

    rm -f "$tmpfile"
    echo "$name installerad."
    return 0
}

errors=0
_install_plugin "Goodreads"         "goodreads"         || { echo "Varning: Goodreads hoppas över.";         errors=$((errors + 1)); }
_install_plugin "Fantastic Fiction"  "fantastic_fiction"  || { echo "Varning: Fantastic Fiction hoppas över."; errors=$((errors + 1)); }
_install_plugin "FictionDb"         "fictiondb"         || { echo "Varning: FictionDb hoppas över.";         errors=$((errors + 1)); }

echo ""
echo "Verifierar installerade plugins..."
calibre-customize --list-plugins > "$_PLUGIN_CACHE" 2>&1 || true

verify_ok=true
for plugin_name in "Goodreads" "Fantastic Fiction" "FictionDB"; do
    if grep -aqi "$plugin_name" "$_PLUGIN_CACHE"; then
        echo "  ✓ $plugin_name"
    else
        echo "  ✗ $plugin_name — SAKNAS"
        verify_ok=false
    fi
done

echo ""
if [ "$errors" -gt 0 ] || [ "$verify_ok" = false ]; then
    echo "Klar med problem. Se varningar ovan."
    exit 1
else
    echo "Klar. Starta om Calibre om det körs för att ladda om plugins."
fi
