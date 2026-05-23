# Colophon – e-book metadata manager
import logging
import os
from datetime import date
from pathlib import Path

import requests
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from sqlalchemy import text

from app.models import db
from app.services.ai_metadata import ai_is_configured, test_ai_connection
from app.services.app_settings import get_setting, get_upstream_dir, set_setting

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__)

_DEFAULT_AI_API_URL = "https://api.mistral.ai/v1/chat/completions"
_DEFAULT_MODEL = "mistral-small-latest"

# Free-text settings managed by the API page. Empty submit deletes the row
# (= falls back to env var or default).
_API_TEXT_KEYS = [
    "AI_API_URL",
    "AI_MODEL",
]

# API-key fields. Empty submit *keeps* the existing value to avoid wiping a
# stored key when the form re-renders with a masked placeholder. A separate
# "clear_<KEY>" form field deletes the row explicitly.
_API_KEY_KEYS = [
    "AI_API_KEY",
    "GOOGLE_BOOKS_KEY",
    "HARDCOVER_API_TOKEN",
]

_API_TOGGLE_KEYS = [
    "COVER_OPENLIBRARY_ENABLED",
    "COVER_GOOGLE_ZOOM_ENABLED",
    "COVER_WIKIDATA_ENABLED",
    "COVER_DDGS_ENABLED",
]


def _get_ai_stats():
    today = date.today()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")

    row_month = db.session.execute(text("""
        SELECT SUM(total_tokens), COUNT(*)
        FROM ai_usage_log
        WHERE created_at >= :month_start
    """), {"month_start": month_start}).fetchone()

    row_total = db.session.execute(text("""
        SELECT SUM(total_tokens), COUNT(*) FROM ai_usage_log
    """)).fetchone()

    recent = db.session.execute(text("""
        SELECT created_at, book_title, total_tokens
        FROM ai_usage_log
        ORDER BY created_at DESC
        LIMIT 10
    """)).fetchall()

    return {
        "month_tokens": row_month[0] or 0,
        "month_calls": row_month[1] or 0,
        "total_tokens": row_total[0] or 0,
        "total_calls": row_total[1] or 0,
        "recent": [
            {
                "date": str(r[0])[:10],
                "book_title": r[1] or "—",
                "tokens": r[2] or 0,
            }
            for r in recent
        ],
    }


@settings_bp.route("/settings/ai")
def ai_settings():
    configured = ai_is_configured()
    model = (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip()

    try:
        stats = _get_ai_stats()
    except Exception as exc:
        logger.warning("Could not fetch AI stats: %s", exc)
        stats = {
            "month_tokens": 0,
            "month_calls": 0,
            "total_tokens": 0,
            "total_calls": 0,
            "recent": [],
        }

    upstream_dir = get_upstream_dir()
    upstream_env_override = bool(os.environ.get("COLOPHON_UPSTREAM_DIR", "").strip())
    upstream_ok = bool(
        upstream_dir
        and os.path.isdir(upstream_dir)
        and any(os.scandir(upstream_dir))
    )
    if upstream_ok:
        upstream_file_count = sum(1 for _ in os.scandir(upstream_dir) if _.is_file())
    else:
        upstream_file_count = 0

    last_sync = None
    try:
        from app.models import LibraryItem
        from sqlalchemy import func
        row = db.session.query(func.max(LibraryItem.upstream_synced_at)).scalar()
        if row:
            last_sync = str(row)[:16].replace("T", " ")
    except Exception:
        pass

    return render_template(
        "settings_ai.html",
        configured=configured,
        model=model,
        stats=stats,
        upstream_dir=upstream_dir,
        upstream_env_override=upstream_env_override,
        upstream_ok=upstream_ok,
        upstream_file_count=upstream_file_count,
        last_sync=last_sync,
    )


@settings_bp.route("/settings/upstream", methods=["POST"])
def save_upstream():
    if os.environ.get("COLOPHON_UPSTREAM_DIR", "").strip():
        flash(_("The upstream library is configured via an environment variable."), "error")
        return redirect(url_for("settings.ai_settings"))

    if request.form.get("clear"):
        set_setting("upstream_dir", "")
        flash(_("Upstream library removed."), "success")
    else:
        path = request.form.get("upstream_dir", "").strip()
        if path and not os.path.isdir(path):
            flash(_('Path "%(path)s" was not found.', path=path), "error")
        else:
            set_setting("upstream_dir", path)
            if path:
                flash(_("Upstream library saved."), "success")
            else:
                flash(_("Upstream library removed."), "success")

    return redirect(url_for("settings.ai_settings"))


@settings_bp.route("/settings/ai/test", methods=["POST"])
def ai_test_connection():
    result = test_ai_connection()

    if result["ok"]:
        model = result.get("model") or "?"
        flash(_("AI connection works (model: %(model)s).", model=model), "success")
    else:
        error = result["error"]
        if error == "auth":
            flash(_("Invalid API key. Check AI_API_KEY."), "error")
        elif error == "timeout":
            flash(_("The AI connection took too long. Check the network."), "error")
        elif error == "rate_limit":
            flash(_("The AI rate limit appears to have been reached. Try again later."), "error")
        else:
            flash(_("AI connection test failed (%(error)s).", error=error), "error")

    return redirect(url_for("settings.ai_settings"))


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "•" * len(value)
    return "•" * 6 + value[-6:]


def _settings_view_context():
    """Collect the current values used to render settings_api.html."""
    ai_key = (get_setting("AI_API_KEY") or "").strip()
    google_books_key = (get_setting("GOOGLE_BOOKS_KEY") or "").strip()
    hardcover_token = (get_setting("HARDCOVER_API_TOKEN") or "").strip()

    library_container_path = os.environ.get("COLOPHON_LIBRARY_DIR", "/books")
    library_host_path = os.environ.get("COLOPHON_LIBRARY_HOST", "").strip() or None

    return {
        "ai_url": (get_setting("AI_API_URL") or _DEFAULT_AI_API_URL).strip(),
        "ai_url_default": _DEFAULT_AI_API_URL,
        "ai_key_masked": _mask_secret(ai_key),
        "ai_key_set": bool(ai_key),
        "ai_model": (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip(),
        "ai_model_default": _DEFAULT_MODEL,
        "google_books_key_masked": _mask_secret(google_books_key),
        "google_books_key_set": bool(google_books_key),
        "hardcover_token_masked": _mask_secret(hardcover_token),
        "hardcover_token_set": bool(hardcover_token),
        "openlibrary_enabled": (get_setting("COVER_OPENLIBRARY_ENABLED", "true") or "true").lower() == "true",
        "google_zoom_enabled": (get_setting("COVER_GOOGLE_ZOOM_ENABLED", "true") or "true").lower() == "true",
        "wikidata_enabled": (get_setting("COVER_WIKIDATA_ENABLED", "true") or "true").lower() == "true",
        "ddgs_enabled": (get_setting("COVER_DDGS_ENABLED", "true") or "true").lower() == "true",
        "library_container_path": library_container_path,
        "library_host_path": library_host_path,
    }


@settings_bp.route("/settings/api", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        for key in _API_TEXT_KEYS:
            val = request.form.get(key, "").strip()
            set_setting(key, val)

        for key in _API_KEY_KEYS:
            if request.form.get(f"clear_{key}"):
                set_setting(key, "")
                continue
            val = request.form.get(key, "").strip()
            if val:
                set_setting(key, val)
            # Empty submit = keep existing value (don't overwrite with "")

        for toggle in _API_TOGGLE_KEYS:
            set_setting(toggle, "true" if request.form.get(toggle) else "false")

        flash(_("API settings saved."), "success")
        return redirect(url_for("settings.api_settings"))

    return render_template("settings_api.html", **_settings_view_context())


@settings_bp.route("/settings/api/test", methods=["POST"])
def test_api_connections():
    """Test every configured API and return per-service status as JSON."""
    results = {}

    if ai_is_configured() or (get_setting("AI_API_URL") or "").strip():
        results["ai"] = test_ai_connection()

    hardcover_token = (get_setting("HARDCOVER_API_TOKEN") or "").strip()
    try:
        headers = {"Content-Type": "application/json"}
        if hardcover_token:
            headers["Authorization"] = f"Bearer {hardcover_token}"
        r = requests.post(
            "https://api.hardcover.app/v1/graphql",
            json={"query": "{ me { username } }"},
            headers=headers,
            timeout=5,
        )
        results["hardcover"] = {"ok": r.ok or r.status_code == 401}
    except requests.Timeout:
        results["hardcover"] = {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("Hardcover test error: %s", exc)
        results["hardcover"] = {"ok": False, "error": "request_failed"}

    google_key = (get_setting("GOOGLE_BOOKS_KEY") or "").strip()
    if google_key:
        try:
            resp = requests.get(
                "https://www.googleapis.com/books/v1/volumes",
                params={"q": "test", "maxResults": 1, "key": google_key},
                timeout=10,
            )
            if resp.status_code == 200:
                results["google_books"] = {"ok": True}
            elif resp.status_code in (401, 403):
                results["google_books"] = {"ok": False, "error": "auth"}
            elif resp.status_code == 429:
                results["google_books"] = {"ok": False, "error": "rate_limit"}
            else:
                results["google_books"] = {"ok": False, "error": f"http_{resp.status_code}"}
        except requests.Timeout:
            results["google_books"] = {"ok": False, "error": "timeout"}
        except requests.RequestException:
            results["google_books"] = {"ok": False, "error": "network"}

    if (get_setting("COVER_OPENLIBRARY_ENABLED", "true") or "true").lower() == "true":
        try:
            r = requests.head(
                "https://covers.openlibrary.org/b/isbn/0385472579-S.jpg",
                timeout=5,
                allow_redirects=True,
            )
            results["openlibrary"] = {"ok": r.ok}
        except requests.RequestException:
            results["openlibrary"] = {"ok": False, "error": "timeout"}

    return jsonify(results)


# ---------------------------------------------------------------------------
# Kobo sync settings
# ---------------------------------------------------------------------------

@settings_bp.route("/settings/kobo")
def kobo_settings():
    from app.services.kobo_auth import list_devices
    from app.services.kobo_kepub import cache_stats, kepubify_status

    devices = list_devices()
    new_token = request.args.get("new_token") or None
    new_name = request.args.get("new_name") or None
    return render_template(
        "settings_kobo.html",
        devices=devices,
        new_token=new_token,
        new_name=new_name,
        host_url=request.host_url.rstrip("/"),
        kepubify=kepubify_status(),
        cache=cache_stats(),
    )


@settings_bp.route("/settings/kobo/clear-cache", methods=["POST"])
def kobo_clear_cache():
    from app.services.kobo_kepub import clear_cache
    count = clear_cache()
    flash(_("Cleared %(n)d cached KEPUB files.", n=count), "success")
    return redirect(url_for("settings.kobo_settings"))


@settings_bp.route("/settings/kobo/create", methods=["POST"])
def kobo_create_device():
    from app.services.kobo_auth import create_device
    name = (request.form.get("name") or "").strip() or "Kobo device"
    device, token = create_device(name)
    return redirect(url_for(
        "settings.kobo_settings",
        new_token=token,
        new_name=device.name,
    ))


@settings_bp.route("/settings/kobo/revoke/<int:device_id>", methods=["POST"])
def kobo_revoke_device(device_id):
    from app.services.kobo_auth import revoke_device
    if revoke_device(device_id):
        flash(_("Device revoked."), "success")
    else:
        flash(_("Device not found."), "warning")
    return redirect(url_for("settings.kobo_settings"))


@settings_bp.route("/settings/kobo/patch-conf", methods=["POST"])
def kobo_patch_conf():
    """Accept a Kobo eReader.conf upload, rewrite the [OneStoreServices]
    section for the given device token, return the patched file as a
    download. The file is processed in memory and never persisted.

    Token comes in as a form field rather than from the URL because the
    page that hosts the form already has it visible to the user (the
    one-time banner after device creation), and we don't want to expose
    tokens in URLs / referer / browser history.
    """
    import io
    from flask import send_file
    from app.services.kobo_auth import find_device_by_token, is_valid_token_format
    from app.services.kobo_conf import (
        KoboConfError,
        MAX_CONF_BYTES,
        decode_conf,
        encode_conf,
        patch_conf_text,
    )

    token = (request.form.get("token") or "").strip()
    if not is_valid_token_format(token):
        flash(_("Invalid or missing device token."), "warning")
        return redirect(url_for("settings.kobo_settings"))

    device = find_device_by_token(token)
    if device is None:
        flash(_("Device not found — was it revoked?"), "warning")
        return redirect(url_for("settings.kobo_settings"))

    upload = request.files.get("conf")
    if upload is None or not upload.filename:
        flash(_("No file uploaded."), "warning")
        return redirect(url_for("settings.kobo_settings"))

    raw = upload.read(MAX_CONF_BYTES + 1)
    if not raw:
        flash(_("Uploaded file was empty."), "warning")
        return redirect(url_for("settings.kobo_settings"))
    if len(raw) > MAX_CONF_BYTES:
        flash(_("Uploaded file is too large to be a Kobo conf (max 200 KB)."), "warning")
        return redirect(url_for("settings.kobo_settings"))

    try:
        text_content, encoding = decode_conf(raw)
        new_endpoint = f"{request.host_url.rstrip('/')}/kobo/{token}"
        patched_text = patch_conf_text(text_content, new_endpoint)
    except KoboConfError as exc:
        flash(_("Could not patch the file: %(msg)s", msg=str(exc)), "warning")
        return redirect(url_for("settings.kobo_settings"))

    payload = encode_conf(patched_text, encoding)
    buf = io.BytesIO(payload)
    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="Kobo eReader.conf",
    )
