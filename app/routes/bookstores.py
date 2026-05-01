import os
import sys
import subprocess
import time
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.paths import PROJECT_ROOT
from app.services.drm_skip_registry import read_skipped_drm
from app.services.drm_platform import get_bookstores_drm_context, open_latest_acsm_folder
from app.services.ade_launcher import get_ade_launch_status, start_ade_only
from app.services.bookstore_web_jobs import (
    clear_job_lock,
    is_job_running,
    list_downloads,
    read_command,
    read_log,
    start_job,
    stop_job,
    worker_command,
)
bookstores_bp = Blueprint("bookstores", __name__)


STORE_JOB_DIR = Path("/tmp/bookstation_store_jobs")


def _store_job_paths(store):
    STORE_JOB_DIR.mkdir(parents=True, exist_ok=True)
    safe_store = "".join(ch for ch in store if ch.isalnum() or ch in ("-", "_")).lower()
    return {
        "log": STORE_JOB_DIR / f"{safe_store}.log",
        "pid": STORE_JOB_DIR / f"{safe_store}.pid",
    }


def _is_pid_running(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _parse_store_progress(log_text, pid_running):
    percent = 0
    current = "Startar..."
    titles = []

    lines = [line.strip() for line in log_text.splitlines() if line.strip()]

    if lines:
        current = lines[-1]

    for line in lines:
        if "[ÖPPNAR]" in line:
            percent = max(percent, 5)

        if "Hittade " in line and "möjliga" in line:
            percent = max(percent, 15)

        if "Öppnar meny" in line:
            percent = max(percent, 35)

        if "Klickar" in line or "Exportera" in line:
            percent = max(percent, 55)

        if "Downloaded:" in line or "Nedladdade" in line or "[HOPPAR ÖVER]" in line:
            percent = max(percent, 75)
            titles.append(line)

        if "[KLART]" in line or "KLART" in line:
            percent = 100

    if not pid_running and lines:
        percent = max(percent, 100)

    useful_titles = []
    for line in titles[-30:]:
        cleaned = line
        cleaned = cleaned.replace("[HOPPAR ÖVER] Redan hämtad:", "Redan hämtad:")
        cleaned = cleaned.replace("[", "").replace("]", "")
        useful_titles.append(cleaned)

    return {
        "percent": percent,
        "running": pid_running,
        "current": current,
        "titles": useful_titles,
        "log_tail": lines[-80:],
    }


@bookstores_bp.route("/bookstores", methods=["GET"])
def bookstores_page():
    stores = ["adlibris", "bokus", "bokon", "kobo", "google"]

    return render_template(
        "bookstores.html",
        running=is_job_running(),
        log_text=read_log(),
        command_text=read_command(),
        downloads_by_store={store: list_downloads(store) for store in stores},
        skipped_drm=read_skipped_drm(limit=200),
    )


@bookstores_bp.route("/bookstores/login", methods=["POST"])
def bookstores_login():
    store = request.form.get("store", "adlibris").strip()
    url = request.form.get("url", "").strip()

    args = worker_command("login", "--store", store)

    if url:
        args.extend(["--url", url])

    result = start_job(args)

    if not result["ok"]:
        flash(result["message"], "error")
        return redirect(url_for("bookstores.bookstores_page"))

    flash(result["message"], "success")
    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/adlibris-download", methods=["POST"])
def bookstores_adlibris_download():
    url = request.form.get("url", "").strip()
    max_downloads = request.form.get("max_downloads", "999").strip()
    dry_run = request.form.get("dry_run") == "1"
    headless = request.form.get("headless") == "1"

    args = worker_command("download-adlibris")

    if url:
        args.extend(["--url", url])

    args.extend(["--max-downloads", max_downloads or "999"])

    if dry_run:
        args.append("--dry-run")

    if headless:
        args.append("--headless")

    result = start_job(args)

    if result["ok"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/stop", methods=["POST"])
def bookstores_stop():
    result = stop_job()

    if result["ok"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/watch", methods=["POST"])
def bookstores_watch():
    store = request.form.get("store", "adlibris").strip()
    url = request.form.get("url", "").strip()

    args = worker_command("watch", "--store", store)

    if url:
        args.extend(["--url", url])

    result = start_job(args)

    if result["ok"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/generic-download", methods=["POST"])
def bookstores_generic_download():
    store = request.form.get("store", "bokus").strip()
    url = request.form.get("url", "").strip()
    max_downloads = request.form.get("max_downloads", "3").strip()
    dry_run = request.form.get("dry_run") == "1"
    headless = request.form.get("headless") == "1"

    args = worker_command("generic-download", "--store", store)

    if url:
        args.extend(["--url", url])

    args.extend(["--max-downloads", max_downloads or "3"])

    if dry_run:
        args.append("--dry-run")

    if headless:
        args.append("--headless")

    result = start_job(args)

    if result["ok"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/open-latest-acsm-folder", methods=["POST"])
def bookstores_open_latest_acsm_folder():
    result = open_latest_acsm_folder()

    if result["ok"]:
        flash("Öppnade mappen med senaste ACSM-filen.", "success")
    else:
        flash(result["message"], "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/clear-lock", methods=["POST"])
def bookstores_clear_lock():
    result = clear_job_lock()

    if result["ok"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/bookstores/start-ade", methods=["POST"])
def bookstores_start_ade():
    result = start_ade_only()

    if result["ok"]:
        flash("Adobe Digital Editions startades. Lägg nu till boken manuellt i ADE.", "success")
    else:
        flash("Adobe Digital Editions kunde inte startas. Kontrollera Wine/ADE-installationen.", "error")

    return redirect(url_for("bookstores.bookstores_page"))


@bookstores_bp.route("/my-stores")
def my_stores_page():
    stores = [
        {"key": "kobo", "name": "Kobo", "url": "https://www.kobo.com/se/sv", "icon": "📘"},
        {"key": "bokus", "name": "Bokus", "url": "https://www.bokus.com", "icon": "📚"},
        {"key": "google", "name": "Google Play Böcker", "url": "https://play.google.com/books", "icon": "▶️"},
        {"key": "bokon", "name": "Bokon", "url": "https://www.bokon.se", "icon": "📖"},
        {"key": "adlibris", "name": "Adlibris", "url": "https://www.adlibris.com/se", "icon": "🛒"},
    ]

    return render_template("my_stores.html", stores=stores)


@bookstores_bp.route("/my-stores/download", methods=["POST"])
def my_stores_start_download():
    store = request.form.get("store", "bokus").strip().lower()
    max_downloads = request.form.get("max_downloads", "10").strip()

    allowed = {"adlibris", "bokus", "bokon", "kobo", "google"}

    if store not in allowed:
        flash("Okänd butik.", "error")
        return redirect(url_for("bookstores.my_stores_page"))

    paths = _store_job_paths(store)

    if paths["pid"].exists():
        old_pid = paths["pid"].read_text(encoding="utf-8").strip()
        if old_pid and _is_pid_running(old_pid):
            return redirect(url_for("bookstores.my_stores_progress_page", store=store))

    worker = PROJECT_ROOT / "tools" / "bookstore_web_worker.py"

    if not worker.exists():
        flash("bookstore_web_worker.py hittades inte.", "error")
        return redirect(url_for("bookstores.my_stores_page"))

    dry_run = request.form.get("dry_run") == "1"
    headless = request.form.get("headless") == "1"

    log_file = paths["log"]
    log_file.write_text(
        f"[START] {time.strftime('%Y-%m-%d %H:%M:%S')}\nButik: {store}\nDry-run: {dry_run}\nHeadless: {headless}\n\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    command = [
        sys.executable,
        str(worker),
        "generic-download",
        "--store",
        store,
        "--max-downloads",
        max_downloads,
    ]

    if dry_run:
        command.append("--dry-run")

    if headless:
        command.append("--headless")

    with log_file.open("a", encoding="utf-8") as out:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=out,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )

    paths["pid"].write_text(str(process.pid), encoding="utf-8")

    return redirect(url_for("bookstores.my_stores_progress_page", store=store))


@bookstores_bp.route("/my-stores/progress/<store>")
def my_stores_progress_page(store):
    return render_template("my_stores_progress.html", store=store)


@bookstores_bp.route("/my-stores/progress/<store>/status")
def my_stores_progress_status(store):
    paths = _store_job_paths(store)

    log_text = ""
    if paths["log"].exists():
        log_text = paths["log"].read_text(encoding="utf-8", errors="ignore")

    pid_running = False
    if paths["pid"].exists():
        pid = paths["pid"].read_text(encoding="utf-8").strip()
        pid_running = bool(pid and _is_pid_running(pid))

    data = _parse_store_progress(log_text, pid_running)

    return jsonify(data)
