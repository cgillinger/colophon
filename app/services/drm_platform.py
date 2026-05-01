import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.paths import DOWNLOAD_ROOT


def platform_key():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def platform_label():
    mapping = {
        "windows": "Windows",
        "mac": "Mac",
        "linux": "Linux",
        "other": "okänt system",
    }
    return mapping.get(platform_key(), "okänt system")


def is_auto_ade_platform():
    return platform_key() in {"windows", "mac"}


def list_pending_acsm_files():
    files = []

    if not DOWNLOAD_ROOT.exists():
        return files

    for path in DOWNLOAD_ROOT.rglob("*.acsm"):
        if not path.is_file():
            continue

        stat = path.stat()

        files.append(
            {
                "name": path.name,
                "path": str(path),
                "folder": str(path.parent),
                "store": path.parent.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "mtime": stat.st_mtime,
            }
        )

    files.sort(key=lambda row: row["mtime"], reverse=True)
    return files[:200]


def latest_acsm_file():
    files = list_pending_acsm_files()
    if not files:
        return None
    return files[0]


def open_latest_acsm_folder():
    latest = latest_acsm_file()

    if latest:
        folder = Path(latest["folder"])
    else:
        folder = DOWNLOAD_ROOT

    folder.mkdir(parents=True, exist_ok=True)

    try:
        system = platform_key()

        if system == "windows":
            os.startfile(str(folder))
        elif system == "mac":
            subprocess.Popen(
                ["open", str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return {
                    "ok": False,
                    "message": "Kunde inte hitta xdg-open.",
                    "folder": str(folder),
                }

            subprocess.Popen(
                [opener, str(folder)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        return {
            "ok": True,
            "message": f"Öppnade mappen: {folder}",
            "folder": str(folder),
        }
    except Exception as error:
        return {
            "ok": False,
            "message": f"Kunde inte öppna mappen: {error}",
            "folder": str(folder),
        }


def open_acsm_with_system_default(path, log=print):
    acsm_path = Path(path).expanduser().resolve()

    if acsm_path.suffix.lower() != ".acsm":
        return {
            "handled": False,
            "state": "not_acsm",
        }

    system = platform_key()

    if system == "windows":
        os.startfile(str(acsm_path))
        log(f"[DRM] Windows: öppnade ACSM automatiskt: {acsm_path}", flush=True)
        return {
            "handled": True,
            "state": "opened_windows",
            "path": str(acsm_path),
        }

    if system == "mac":
        subprocess.Popen(
            ["open", str(acsm_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        log(f"[DRM] Mac: öppnade ACSM automatiskt: {acsm_path}", flush=True)
        return {
            "handled": True,
            "state": "opened_mac",
            "path": str(acsm_path),
        }

    log(f"[DRM] Linux/manuellt läge: ACSM sparad utan automatisk öppning: {acsm_path}", flush=True)
    return {
        "handled": True,
        "state": "manual_linux",
        "path": str(acsm_path),
    }


def maybe_handle_downloaded_file(path, log=print):
    if is_auto_ade_platform():
        return open_acsm_with_system_default(path, log=log)

    return open_acsm_with_system_default(path, log=log)


def get_bookstores_drm_context():
    auto_mode = is_auto_ade_platform()
    system_label = platform_label()

    return {
        "pending_acsm_files": list_pending_acsm_files(),
        "drm_platform": platform_key(),
        "drm_platform_label": system_label,
        "drm_auto_supported": auto_mode,
        "ade_status": {
            "installed": auto_mode,
            "method": "automatiskt läge" if auto_mode else "manuellt läge på Linux",
        },
    }
