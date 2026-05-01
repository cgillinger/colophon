import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app.paths import DOWNLOAD_ROOT


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
