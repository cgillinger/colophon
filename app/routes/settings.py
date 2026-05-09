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
        logger.warning("Kunde inte hämta AI-statistik: %s", exc)
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
        flash("Huvudbiblioteket konfigureras via miljövariabel.", "error")
        return redirect(url_for("settings.ai_settings"))

    if request.form.get("clear"):
        set_setting("upstream_dir", "")
        flash(_("Upstream library removed."), "success")
    else:
        path = request.form.get("upstream_dir", "").strip()
        if path and not os.path.isdir(path):
            flash(f'Sökvägen "{path}" hittades inte.', "error")
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
        flash(f"AI-anslutningen fungerar (modell: {model}).", "success")
    else:
        error = result["error"]
        if error == "auth":
            flash("Ogiltig API-nyckel. Kontrollera AI_API_KEY.", "error")
        elif error == "timeout":
            flash("AI-anslutningen tog för lång tid. Kontrollera nätverket.", "error")
        elif error == "rate_limit":
            flash("Gränsen för AI-anrop verkar vara nådd. Försök igen senare.", "error")
        else:
            flash(f"AI-anslutningstest misslyckades ({error}).", "error")

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
    hardcover_token = (get_setting("HARDCOVER_API_TOKEN") or "").strip()

    return {
        "ai_url": (get_setting("AI_API_URL") or _DEFAULT_AI_API_URL).strip(),
        "ai_url_default": _DEFAULT_AI_API_URL,
        "ai_key_masked": _mask_secret(ai_key),
        "ai_key_set": bool(ai_key),
        "ai_model": (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip(),
        "ai_model_default": _DEFAULT_MODEL,
        "hardcover_token_masked": _mask_secret(hardcover_token),
        "hardcover_token_set": bool(hardcover_token),
        "openlibrary_enabled": (get_setting("COVER_OPENLIBRARY_ENABLED", "true") or "true").lower() == "true",
        "google_zoom_enabled": (get_setting("COVER_GOOGLE_ZOOM_ENABLED", "true") or "true").lower() == "true",
        "wikidata_enabled": (get_setting("COVER_WIKIDATA_ENABLED", "true") or "true").lower() == "true",
        "ddgs_enabled": (get_setting("COVER_DDGS_ENABLED", "true") or "true").lower() == "true",
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
