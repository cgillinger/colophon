import os

from sqlalchemy import text

from app.models import db


def get_setting(key, default=None):
    """Read a setting from db. Returns default if not found."""
    try:
        row = db.session.execute(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": key},
        ).fetchone()
        if row is not None:
            return row[0]
    except Exception:
        pass
    return default


def set_setting(key, value):
    """Write a setting to db."""
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
