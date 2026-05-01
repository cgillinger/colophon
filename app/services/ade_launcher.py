import os
import shlex
import shutil
import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)



def _cmd_text(parts):
    return " ".join(shlex.quote(str(part)) for part in parts)


def _wine_binaries():
    found = []
    for name in ["wine", "wine64"]:
        path = shutil.which(name)
        if path and path not in found:
            found.append(path)
    return found


def _prefix_candidates():
    home = Path.home()
    candidates = [
        home / ".wine-ade",
        home / ".wine",
        home / ".local" / "share" / "wineprefixes" / "ade",
        home / ".local" / "share" / "wineprefixes" / "AdobeDigitalEditions",
        home / ".local" / "share" / "wineprefixes" / "adobe-digital-editions",
    ]

    if os.environ.get("WINEPREFIX"):
        candidates.insert(0, Path(os.environ["WINEPREFIX"]).expanduser())

    out = []
    seen = set()

    for path in candidates:
        try:
            path = Path(path).expanduser()
        except Exception:
            continue

        key = str(path)
        if key in seen:
            continue
        seen.add(key)

        if path.exists() and path.is_dir():
            out.append(path)

    return out


def _find_ade_exe():
    exe_names = [
        "DigitalEditions.exe",
        "Adobe Digital Editions.exe",
    ]

    for prefix in _prefix_candidates():
        drive_c = prefix / "drive_c"
        if not drive_c.exists():
            continue

        likely_dirs = [
            drive_c / "Program Files" / "Adobe" / "Adobe Digital Editions 4.5",
            drive_c / "Program Files (x86)" / "Adobe" / "Adobe Digital Editions 4.5",
            drive_c / "Program Files" / "Adobe" / "Adobe Digital Editions",
            drive_c / "Program Files (x86)" / "Adobe" / "Adobe Digital Editions",
        ]

        for folder in likely_dirs:
            for exe_name in exe_names:
                candidate = folder / exe_name
                if candidate.exists() and candidate.is_file():
                    return candidate, prefix

        for pattern in ["**/DigitalEditions.exe", "**/Adobe Digital Editions.exe"]:
            try:
                for candidate in drive_c.glob(pattern):
                    if candidate.exists() and candidate.is_file():
                        return candidate, prefix
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

    return None, None


def get_ade_launch_status():
    wine_binaries = _wine_binaries()
    exe_path, prefix = _find_ade_exe()

    if wine_binaries and exe_path and prefix:
        command = [wine_binaries[0], str(exe_path)]
        return {
            "installed": True,
            "method": "wine",
            "wine_binary": wine_binaries[0],
            "wine_prefix": str(prefix),
            "exe_path": str(exe_path),
            "command": command,
            "command_text": _cmd_text(command),
        }

    return {
        "installed": False,
        "method": "saknas",
        "wine_binaries": wine_binaries,
        "checked_prefixes": [str(p) for p in _prefix_candidates()],
    }


def start_ade_only():
    status = get_ade_launch_status()

    if not status["installed"]:
        return {
            "ok": False,
            "message": "Adobe Digital Editions hittades inte i Wine.",
            "status": status,
        }

    env = os.environ.copy()
    env["WINEDEBUG"] = "-all"
    env["WINEPREFIX"] = status["wine_prefix"]

    subprocess.Popen(
        status["command"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

    return {
        "ok": True,
        "message": "Adobe Digital Editions startades i Wine.",
        "status": status,
    }
