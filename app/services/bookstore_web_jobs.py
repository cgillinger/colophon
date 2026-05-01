import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path


from app.paths import (
    JOB_DIR,
    JOB_COMMAND_PATH as COMMAND_PATH,
    JOB_LOG_PATH as LOG_PATH,
    JOB_PID_PATH as PID_PATH,
    PROJECT_ROOT,
)

logger = logging.getLogger(__name__)


def ensure_dirs():
    JOB_DIR.mkdir(parents=True, exist_ok=True)


def read_pid():
    if not PID_PATH.exists():
        return None

    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def is_zombie_process(pid):
    stat_path = Path(f"/proc/{pid}/stat")

    if not stat_path.exists():
        return False

    try:
        stat_text = stat_path.read_text(encoding="utf-8", errors="ignore")
        parts = stat_text.split()

        if len(parts) >= 3 and parts[2] == "Z":
            return True
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    return False


def is_pid_running(pid):
    if not pid:
        return False

    if is_zombie_process(pid):
        return False

    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def cleanup_stale_job():
    pid = read_pid()

    if pid and is_pid_running(pid):
        return

    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)


def is_job_running():
    cleanup_stale_job()
    return is_pid_running(read_pid())


def read_log():
    ensure_dirs()

    if not LOG_PATH.exists():
        return ""

    try:
        return LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_command():
    if not COMMAND_PATH.exists():
        return ""

    try:
        return COMMAND_PATH.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def clear_job_lock():
    try:
        PID_PATH.unlink(missing_ok=True)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        COMMAND_PATH.unlink(missing_ok=True)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    return {
        "ok": True,
        "message": "Jobblåset är rensat.",
    }


def start_job(args, extra_env=None):
    ensure_dirs()
    cleanup_stale_job()

    if is_job_running():
        return {
            "ok": False,
            "message": "Ett jobb kör redan. Stoppa det först eller rensa jobblåset.",
        }

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    command_text = " ".join(args)

    LOG_PATH.write_text(
        f"[START] {timestamp}\n[KOMMANDO] {command_text}\n\n",
        encoding="utf-8",
    )

    COMMAND_PATH.write_text(command_text, encoding="utf-8")

    log_file = open(LOG_PATH, "a", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if extra_env:
        env.update(extra_env)

    process = subprocess.Popen(
        args,
        cwd=str(PROJECT_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
        env=env,
    )

    PID_PATH.write_text(str(process.pid), encoding="utf-8")

    return {
        "ok": True,
        "message": f"Startade jobb med PID {process.pid}.",
    }


def stop_job():
    pid = read_pid()

    if not pid or not is_pid_running(pid):
        clear_job_lock()
        return {
            "ok": False,
            "message": "Inget aktivt jobb att stoppa.",
        }

    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception as error:
            return {
                "ok": False,
                "message": f"Kunde inte stoppa jobbet: {error}",
            }

    clear_job_lock()

    return {
        "ok": True,
        "message": "Jobbet stoppades.",
    }


def list_downloads(store="adlibris"):
    path = PROJECT_ROOT / "downloads" / "bookstores" / store

    if not path.exists():
        return []

    files = []

    for item in sorted(path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not item.is_file():
            continue

        stat = item.stat()

        files.append(
            {
                "name": item.name,
                "path": str(item),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )

    return files[:100]


def worker_command(*extra):
    return [
        sys.executable,
        str(PROJECT_ROOT / "tools" / "bookstore_web_worker.py"),
        *extra,
    ]
