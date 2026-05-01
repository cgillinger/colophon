import logging
import os
from calendar import monthrange
from datetime import date

from flask import Blueprint, flash, redirect, render_template, url_for
from sqlalchemy import text

from app.models import db
from app.services.ai_metadata import test_ai_connection

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__)

_DEFAULT_MODEL = "mistral-small-latest"


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
    api_key = os.environ.get("BOOKSTATION_MISTRAL_API_KEY", "").strip()
    model = os.environ.get("BOOKSTATION_MISTRAL_MODEL", "").strip() or _DEFAULT_MODEL
    configured = bool(api_key)

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

    return render_template(
        "settings_ai.html",
        configured=configured,
        model=model,
        stats=stats,
    )


@settings_bp.route("/settings/ai/test", methods=["POST"])
def ai_test_connection():
    result = test_ai_connection()

    if result["ok"]:
        model_count = len(result.get("models", []))
        flash(f"Anslutningen fungerar. {model_count} modeller tillgängliga.", "success")
    else:
        error = result["error"]
        if error == "no_key":
            flash("Ingen API-nyckel konfigurerad (BOOKSTATION_MISTRAL_API_KEY).", "error")
        elif error == "auth":
            flash("Ogiltig API-nyckel. Kontrollera BOOKSTATION_MISTRAL_API_KEY.", "error")
        elif error == "timeout":
            flash("Anslutningen tog för lång tid. Kontrollera nätverket.", "error")
        elif error == "rate_limit":
            flash("Gränsen för Mistral-anrop verkar vara nådd. Försök igen senare.", "error")
        else:
            flash(f"Anslutningstest misslyckades ({error}).", "error")

    return redirect(url_for("settings.ai_settings"))
