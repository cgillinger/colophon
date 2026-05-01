import json
import os
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


ADOBE_DOWNLOAD_URL = "https://www.adobe.com/solutions/ebook/digital-editions/download.html"

from app.paths import (
    DOWNLOAD_ROOT,
    DRM_STATUS_DIR as STATUS_DIR,
    DRM_STATUS_FILE as STATUS_FILE,
    PROJECT_ROOT,
)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_status(data):
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload.setdefault("time", _now())
    payload.setdefault("adobe_download_url", ADOBE_DOWNLOAD_URL)
    STATUS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def read_drm_status():
    if not STATUS_FILE.exists():
        return {}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cmd_text(parts):
    return " ".join(shlex.quote(str(part)) for part in parts)


def _wine_binaries():
    binaries = []
    for name in ["wine", "wine64"]:
        path = shutil.which(name)
        if path and path not in binaries:
            binaries.append(path)
    return binaries


def _standard_prefix_candidates():
    home = Path.home()
    candidates = []

    if os.environ.get("WINEPREFIX"):
        candidates.append(Path(os.environ["WINEPREFIX"]).expanduser())

    candidates.extend(
        [
            home / ".wine",
            home / ".wine-ade",
            home / ".local" / "share" / "wineprefixes",
            home / ".local" / "share" / "bottles" / "bottles",
            home / ".var" / "app" / "com.usebottles.bottles" / "data" / "bottles" / "bottles",
            home / ".local" / "share" / "lutris",
            home / "Games",
        ]
    )

    seen = set()
    out = []

    for path in candidates:
        try:
            path = path.expanduser()
        except Exception:
            continue

        key = str(path)
        if key in seen:
            continue
        seen.add(key)

        if path.exists():
            out.append(path)

    return out


def _collect_possible_prefixes():
    seen = set()
    prefixes = []

    def add(path):
        try:
            path = Path(path).expanduser()
        except Exception:
            return

        key = str(path)
        if key in seen:
            return
        seen.add(key)

        if path.exists() and path.is_dir():
            prefixes.append(path)

    roots = _standard_prefix_candidates()

    for root in roots:
        add(root)

        if root.name == "wineprefixes":
            for child in root.iterdir():
                if child.is_dir():
                    add(child)

        if "bottles" in str(root).lower():
            for child in root.iterdir():
                if child.is_dir():
                    add(child)

        if root.name == "Games":
            for child in root.iterdir():
                if child.is_dir():
                    add(child)

    return prefixes


def _candidate_program_dirs(prefix):
    drive_c = prefix / "drive_c"
    if not drive_c.exists():
        return []

    dirs = [
        drive_c / "Program Files (x86)" / "Adobe" / "Adobe Digital Editions 4.5",
        drive_c / "Program Files" / "Adobe" / "Adobe Digital Editions 4.5",
        drive_c / "Program Files (x86)" / "Adobe" / "Adobe Digital Editions",
        drive_c / "Program Files" / "Adobe" / "Adobe Digital Editions",
        drive_c / "Program Files (x86)" / "Adobe Digital Editions",
        drive_c / "Program Files" / "Adobe Digital Editions",
    ]

    return [path for path in dirs if path.exists() and path.is_dir()]


def _discover_prefix_from_exe(exe_path):
    current = Path(exe_path).resolve()
    for parent in current.parents:
        if parent.name.lower() == "drive_c":
            return parent.parent
    return None


def _find_ade_exe_in_known_prefixes():
    exe_names = [
        "DigitalEditions.exe",
        "Adobe Digital Editions.exe",
    ]

    for prefix in _collect_possible_prefixes():
        for folder in _candidate_program_dirs(prefix):
            for exe_name in exe_names:
                candidate = folder / exe_name
                if candidate.exists() and candidate.is_file():
                    return candidate

        drive_c = prefix / "drive_c"
        if drive_c.exists():
            for pattern in ["**/DigitalEditions.exe", "**/Adobe Digital Editions.exe"]:
                try:
                    for candidate in drive_c.glob(pattern):
                        if candidate.exists() and candidate.is_file():
                            return candidate
                except Exception:
                    logger.debug("Tystat fel ignorerat", exc_info=True)

    return None


def _search_home_for_ade_exe():
    home = Path.home()
    exe_names_lower = {
        "digitaleditions.exe",
        "adobe digital editions.exe",
    }

    preferred_roots = _standard_prefix_candidates()
    search_roots = preferred_roots if preferred_roots else [home]

    seen = set()
    final_roots = []

    for root in search_roots:
        root = Path(root)
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        if root.exists():
            final_roots.append(root)

    skip_dir_names = {
        ".cache",
        ".cargo",
        ".npm",
        ".thumbnails",
        "Cache",
        "cache",
        "Trash",
        ".Trash-1000",
        "node_modules",
    }

    for root in final_roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dir_names]

            for filename in filenames:
                if filename.lower() in exe_names_lower:
                    candidate = Path(dirpath) / filename
                    if candidate.is_file():
                        return candidate

    return None


def _find_ade_exe():
    exe = _find_ade_exe_in_known_prefixes()
    if exe:
        return exe
    return _search_home_for_ade_exe()


def get_ade_status():
    env_cmd = os.environ.get("BOOKSTATION_ADE_CMD", "").strip()

    if env_cmd:
        parts = shlex.split(env_cmd)
        if parts:
            return {
                "installed": True,
                "method": "BOOKSTATION_ADE_CMD",
                "command": parts,
                "command_text": _cmd_text(parts),
                "checked_prefixes": [str(p) for p in _collect_possible_prefixes()],
                "checked_wine_binaries": _wine_binaries(),
            }

    for command_name in ["adobe-digital-editions", "digitaleditions", "ade"]:
        found = shutil.which(command_name)
        if found:
            return {
                "installed": True,
                "method": "linux-kommando",
                "command": [found],
                "command_text": _cmd_text([found]),
                "checked_prefixes": [str(p) for p in _collect_possible_prefixes()],
                "checked_wine_binaries": _wine_binaries(),
            }

    wine_binaries = _wine_binaries()
    exe = _find_ade_exe()

    if wine_binaries and exe:
        prefix = _discover_prefix_from_exe(exe)
        wine_binary = wine_binaries[0]
        command = [wine_binary, str(exe)]

        return {
            "installed": True,
            "method": "wine",
            "command": command,
            "command_text": _cmd_text(command),
            "exe_path": str(exe),
            "wine_binary": wine_binary,
            "wine_prefix": str(prefix) if prefix else "",
            "checked_prefixes": [str(p) for p in _collect_possible_prefixes()],
            "checked_wine_binaries": wine_binaries,
        }

    return {
        "installed": False,
        "method": "saknas",
        "command": [],
        "command_text": "",
        "checked_prefixes": [str(p) for p in _collect_possible_prefixes()],
        "checked_wine_binaries": wine_binaries,
    }


def list_pending_acsm_files():
    if not DOWNLOAD_ROOT.exists():
        return []

    files = []

    for path in DOWNLOAD_ROOT.rglob("*.acsm"):
        if not path.is_file():
            continue

        stat = path.stat()

        files.append(
            {
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "mtime": stat.st_mtime,
            }
        )

    files.sort(key=lambda row: row["mtime"], reverse=True)
    return files[:200]


def _possible_my_digital_editions_dirs():
    home = Path.home()
    dirs = [
        home / "Dokument" / "My Digital Editions",
        home / "Documents" / "My Digital Editions",
        home / "My Digital Editions",
    ]

    for prefix in _collect_possible_prefixes():
        users_dir = prefix / "drive_c" / "users"
        if not users_dir.exists():
            continue

        for user_dir in users_dir.iterdir():
            if not user_dir.is_dir():
                continue

            dirs.append(user_dir / "Documents" / "My Digital Editions")
            dirs.append(user_dir / "My Documents" / "My Digital Editions")
            dirs.append(user_dir / "Mina dokument" / "My Digital Editions")

    seen = set()
    out = []

    for path in dirs:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)

        if path.exists() and path.is_dir():
            out.append(path)

    return out


def _unique_path(path):
    if not path.exists():
        return path

    counter = 2
    while True:
        candidate = path.parent / f"{path.stem} ({counter}){path.suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _recent_ade_books(since=None, max_age=86400):
    now = time.time()
    found = []

    for folder in _possible_my_digital_editions_dirs():
        for path in folder.rglob("*"):
            if not path.is_file():
                continue

            if path.suffix.lower() not in {".epub", ".pdf"}:
                continue

            stat = path.stat()

            if since is not None and stat.st_mtime < since:
                continue

            if since is None and now - stat.st_mtime > max_age:
                continue

            if stat.st_size > 0:
                found.append(path)

    found.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return found


def copy_ade_books_to_library(library_dir, since=None):
    library = Path(library_dir)
    target_dir = library / "DRM importerade"
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = []

    for source in _recent_ade_books(since=since):
        target = _unique_path(target_dir / source.name)
        shutil.copy2(source, target)
        copied.append(
            {
                "source": str(source),
                "target": str(target),
            }
        )

    _write_status(
        {
            "state": "import_checked",
            "message": f"Importerade {len(copied)} fil(er) från Adobe Digital Editions.",
            "copied": copied,
            "library_dir": str(library),
            "ade_dirs": [str(p) for p in _possible_my_digital_editions_dirs()],
        }
    )

    return copied


def open_acsm_in_ade(acsm_path, library_dir=None, wait_seconds=0, log=print):
    acsm_path = Path(acsm_path).expanduser().resolve()

    if acsm_path.suffix.lower() != ".acsm":
        return {
            "handled": False,
            "state": "not_acsm",
        }

    status = get_ade_status()

    if not status["installed"]:
        _write_status(
            {
                "state": "ade_missing",
                "message": "Adobe Digital Editions hittades inte.",
                "acsm_path": str(acsm_path),
                "checked_prefixes": status.get("checked_prefixes", []),
                "checked_wine_binaries": status.get("checked_wine_binaries", []),
            }
        )

        log("[DRM] Adobe Digital Editions saknas. Öppna DRM/ADE-sidan i Bookstation.", flush=True)

        return {
            "handled": True,
            "state": "ade_missing",
        }

    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"

    wine_prefix = status.get("wine_prefix", "").strip()
    if wine_prefix:
        env["WINEPREFIX"] = wine_prefix

    if status.get("method") == "wine":
        wine_binary = status.get("wine_binary") or shutil.which("wine") or "wine"
        exe_path = status.get("exe_path", "")
        command = [wine_binary, exe_path]
        launch_mode = "wine-start-ade-only"
    else:
        command = list(status["command"])
        launch_mode = status.get("method", "okänd")

    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

    _write_status(
        {
            "state": "ade_started_manual_import_needed",
            "message": "Adobe Digital Editions startades. Öppna sedan ACSM-filen via Arkiv > Add to Library i ADE.",
            "acsm_path": str(acsm_path),
            "command": _cmd_text(command),
            "method": status.get("method", ""),
            "launch_mode": launch_mode,
            "wine_prefix": wine_prefix,
            "exe_path": status.get("exe_path", ""),
            "note": "Direkt extern öppning av ACSM i Wine är avstängd eftersom den kraschar i denna miljö.",
        }
    )

    log(f"[DRM] Startade ADE utan ACSM-argument: {acsm_path}", flush=True)

    return {
        "handled": True,
        "state": "ade_started_manual_import_needed",
    }


def handle_downloaded_file(path, log=print):
    library_dir = PROJECT_ROOT / "app" / "bibliotek"
    library_dir.mkdir(parents=True, exist_ok=True)
    return open_acsm_in_ade(path, library_dir=library_dir, log=log)


def process_pending_acsm_files(library_dir):
    pending = list_pending_acsm_files()

    if not pending:
        return []

    newest = pending[0]

    result = open_acsm_in_ade(
        newest["path"],
        library_dir=library_dir,
    )

    return [
        {
            "file": newest,
            "result": result,
        }
    ]
