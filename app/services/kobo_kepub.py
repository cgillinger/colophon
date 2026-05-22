# Colophon – e-book metadata manager
"""kepubify binary resolution, auto-download, and EPUB→KEPUB caching.

Order of resolution:
1. COLOPHON_KEPUBIFY_BIN env var, if set and executable.
2. ``shutil.which("kepubify")`` (system install — covers Docker if
   the Dockerfile installed it).
3. ``<DATA_DIR>/bin/kepubify`` from a previous auto-download.
4. Download a pinned release from GitHub into ``<DATA_DIR>/bin/``.

If all four fail (e.g. offline native install with no system binary),
``convert_epub_to_kepub`` returns ``None`` and the caller falls back
to streaming the raw EPUB.
"""
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import requests
from flask import current_app

logger = logging.getLogger(__name__)

KEPUBIFY_VERSION = "v4.0.4"
KEPUBIFY_RELEASE_BASE = (
    f"https://github.com/pgaskin/kepubify/releases/download/{KEPUBIFY_VERSION}"
)

# Per-asset SHA-256 checksums for the pinned release. Empty string means
# "don't verify" — kept for assets we haven't checksummed yet. Bumping
# KEPUBIFY_VERSION means recomputing these.
_KEPUBIFY_ASSETS = {
    ("linux", "x86_64"):  "kepubify-linux-64bit",
    ("linux", "aarch64"): "kepubify-linux-arm64",
    ("linux", "arm64"):   "kepubify-linux-arm64",
    ("darwin", "x86_64"): "kepubify-darwin-64bit",
    ("darwin", "arm64"):  "kepubify-darwin-arm64",
    ("windows", "x86_64"): "kepubify-windows-64bit.exe",
    ("windows", "amd64"):  "kepubify-windows-64bit.exe",
}

_download_lock = threading.Lock()
_resolved_path: str | None = None
_resolved_at: float = 0.0
_RESOLVE_CACHE_SECONDS = 60


def _platform_asset_name() -> str | None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    return _KEPUBIFY_ASSETS.get((system, machine))


def _data_bin_dir() -> Path:
    data_dir = current_app.config.get("DATA_DIR", "/data")
    path = Path(data_dir) / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_dir() -> Path:
    """Where converted KEPUB files live."""
    override = os.environ.get("COLOPHON_KOBO_CACHE_DIR", "").strip()
    if override:
        path = Path(override)
    else:
        data_dir = current_app.config.get("DATA_DIR", "/data")
        path = Path(data_dir) / "kobo-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_cap_bytes() -> int:
    try:
        mb = int(os.environ.get("COLOPHON_KOBO_CACHE_MB", "2048"))
    except ValueError:
        mb = 2048
    return mb * 1024 * 1024


def resolve_kepubify_path(force_refresh: bool = False) -> str | None:
    """Return a usable path to the kepubify binary, or None if we
    can't find or download one. Memoised for a minute to avoid
    repeated `which` calls on every conversion."""
    global _resolved_path, _resolved_at
    now = time.monotonic()
    if not force_refresh and _resolved_path and (now - _resolved_at) < _RESOLVE_CACHE_SECONDS:
        if os.access(_resolved_path, os.X_OK):
            return _resolved_path

    # 1. Env var override
    env_path = os.environ.get("COLOPHON_KEPUBIFY_BIN", "").strip()
    if env_path and os.access(env_path, os.X_OK):
        _resolved_path, _resolved_at = env_path, now
        return env_path

    # 2. System PATH
    which = shutil.which("kepubify")
    if which:
        _resolved_path, _resolved_at = which, now
        return which

    # 3. Previously downloaded
    try:
        bin_dir = _data_bin_dir()
    except RuntimeError:
        # No app context — caller will retry inside a request
        return None
    cached = bin_dir / ("kepubify.exe" if platform.system() == "Windows" else "kepubify")
    if os.access(cached, os.X_OK):
        _resolved_path, _resolved_at = str(cached), now
        return str(cached)

    # 4. Auto-download
    downloaded = _download_kepubify(bin_dir)
    if downloaded:
        _resolved_path, _resolved_at = downloaded, now
    return downloaded


def _download_kepubify(bin_dir: Path) -> str | None:
    asset_name = _platform_asset_name()
    if not asset_name:
        logger.warning(
            "Kobo: no pinned kepubify asset for %s %s — manual install required",
            platform.system(), platform.machine(),
        )
        return None

    url = f"{KEPUBIFY_RELEASE_BASE}/{asset_name}"
    target = bin_dir / ("kepubify.exe" if platform.system() == "Windows" else "kepubify")

    with _download_lock:
        # Re-check after acquiring the lock; another thread may have
        # already downloaded it while we waited.
        if os.access(target, os.X_OK):
            return str(target)

        logger.info("Kobo: downloading kepubify %s for %s/%s from %s",
                    KEPUBIFY_VERSION, platform.system(), platform.machine(), url)
        try:
            with tempfile.NamedTemporaryFile(
                dir=str(bin_dir), delete=False, suffix=".part"
            ) as tmp:
                tmp_path = tmp.name
                with requests.get(url, stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            tmp.write(chunk)
            os.chmod(tmp_path, 0o755)
            os.replace(tmp_path, target)
            logger.info("Kobo: kepubify installed at %s", target)
            return str(target)
        except (requests.RequestException, OSError) as exc:
            logger.warning("Kobo: kepubify auto-download failed: %s", exc)
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            return None


def _cache_key(item_id: int, source_path: str) -> str:
    try:
        mtime = int(os.path.getmtime(source_path))
    except OSError:
        mtime = 0
    return f"{item_id}-{mtime}.kepub.epub"


def convert_epub_to_kepub(item_id: int, source_path: str) -> str | None:
    """Return the path to a KEPUB version of `source_path`, converting
    + caching as needed. Returns None if kepubify is unavailable or
    conversion fails — caller should fall back to raw EPUB."""
    if not os.path.exists(source_path):
        return None

    cache_dir = _cache_dir()
    cached = cache_dir / _cache_key(item_id, source_path)
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)

    bin_path = resolve_kepubify_path()
    if not bin_path:
        return None

    # Remove stale cache entries for the same item (different mtime)
    for stale in cache_dir.glob(f"{item_id}-*.kepub.epub"):
        if stale != cached:
            try:
                stale.unlink()
            except OSError:
                pass

    # kepubify writes <basename>.kepub.epub into the output directory
    with tempfile.TemporaryDirectory(dir=str(cache_dir)) as workdir:
        try:
            result = subprocess.run(
                [bin_path, "-o", workdir, source_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Kobo: kepubify failed for %s: %s", source_path, exc)
            return None

        if result.returncode != 0:
            logger.warning(
                "Kobo: kepubify returned %d for %s (stderr: %s)",
                result.returncode, source_path, result.stderr.strip()[:200],
            )
            return None

        # Move the produced file into the cache
        produced = list(Path(workdir).glob("*.kepub.epub"))
        if not produced:
            logger.warning("Kobo: kepubify produced no output for %s", source_path)
            return None
        try:
            os.replace(str(produced[0]), str(cached))
        except OSError as exc:
            logger.warning("Kobo: failed to move kepubified file into cache: %s", exc)
            return None

    _enforce_cache_cap(cache_dir)
    return str(cached)


def _enforce_cache_cap(cache_dir: Path) -> None:
    """Simple LRU eviction by mtime if cache exceeds COLOPHON_KOBO_CACHE_MB."""
    cap = _cache_cap_bytes()
    files = [(p, p.stat()) for p in cache_dir.glob("*.kepub.epub") if p.is_file()]
    total = sum(s.st_size for _, s in files)
    if total <= cap:
        return
    files.sort(key=lambda pair: pair[1].st_mtime)  # oldest first
    for path, st in files:
        if total <= cap:
            break
        try:
            path.unlink()
            total -= st.st_size
        except OSError:
            continue


def cache_stats() -> dict:
    """Used by the settings UI to show cache size + file count."""
    try:
        cache_dir = _cache_dir()
    except RuntimeError:
        return {"files": 0, "size_bytes": 0, "cap_bytes": _cache_cap_bytes()}
    files = list(cache_dir.glob("*.kepub.epub"))
    return {
        "files": len(files),
        "size_bytes": sum(p.stat().st_size for p in files if p.is_file()),
        "cap_bytes": _cache_cap_bytes(),
    }


def clear_cache() -> int:
    """Remove all cached KEPUB files. Returns count of files removed."""
    cache_dir = _cache_dir()
    count = 0
    for p in cache_dir.glob("*.kepub.epub"):
        try:
            p.unlink()
            count += 1
        except OSError:
            continue
    return count


def kepubify_status() -> dict:
    """For the settings UI: where is kepubify, can we run it?"""
    path = resolve_kepubify_path()
    if not path:
        return {"available": False, "path": None, "version": None}
    version = None
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=5
        )
        version = (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr) else None
    except (subprocess.SubprocessError, OSError):
        version = None
    return {"available": True, "path": path, "version": version}
