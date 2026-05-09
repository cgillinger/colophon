import os

from sqlalchemy import text

from app.models import db


_LEGACY_ENV_FALLBACK = {
    "AI_API_KEY": "COLOPHON_MISTRAL_API_KEY",
    "AI_MODEL": "COLOPHON_MISTRAL_MODEL",
}


def get_setting(key, default=None):
    """Read a setting. DB value wins, then COLOPHON_<KEY> env, then legacy env."""
    try:
        row = db.session.execute(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": key},
        ).fetchone()
        if row is not None and row[0] not in (None, ""):
            return row[0]
    except Exception:
        pass

    env_val = os.environ.get(f"COLOPHON_{key}", "").strip()
    if env_val:
        return env_val

    legacy_env = _LEGACY_ENV_FALLBACK.get(key)
    if legacy_env:
        legacy_val = os.environ.get(legacy_env, "").strip()
        if legacy_val:
            return legacy_val

    return default


def set_setting(key, value):
    """Write a setting to db. Empty string/None deletes the row (= fall back to env)."""
    if value in (None, ""):
        db.session.execute(
            text("DELETE FROM app_settings WHERE key = :key"),
            {"key": key},
        )
    else:
        db.session.execute(
            text("INSERT OR REPLACE INTO app_settings (key, value) VALUES (:key, :value)"),
            {"key": key, "value": value},
        )
    db.session.commit()


def get_upstream_dir():
    """Return upstream dir path: env var wins, then db setting, then None."""
    env_val = os.environ.get("COLOPHON_UPSTREAM_DIR", "").strip()
    if env_val:
        return env_val
    db_val = get_setting("upstream_dir", "")
    return db_val.strip() if db_val else None
