# Colophon – e-book metadata manager
import logging
import os

from sqlalchemy import text

from app.models import db

logger = logging.getLogger(__name__)


def ensure_database_columns():
    rows = db.session.execute(text("PRAGMA table_info(library_items)")).fetchall()
    existing_columns = {row[1] for row in rows}

    columns_to_add = {
        "description": "ALTER TABLE library_items ADD COLUMN description TEXT",
        "cover_path": "ALTER TABLE library_items ADD COLUMN cover_path VARCHAR(2000)",
        "series": "ALTER TABLE library_items ADD COLUMN series VARCHAR(500)",
        "series_index": "ALTER TABLE library_items ADD COLUMN series_index VARCHAR(100)",
        "isbn": "ALTER TABLE library_items ADD COLUMN isbn VARCHAR(100)",
        "publisher": "ALTER TABLE library_items ADD COLUMN publisher VARCHAR(500)",
        "language": "ALTER TABLE library_items ADD COLUMN language VARCHAR(100)",
        "manual_metadata": "ALTER TABLE library_items ADD COLUMN manual_metadata BOOLEAN DEFAULT 0",
        "pipeline_status": "ALTER TABLE library_items ADD COLUMN pipeline_status VARCHAR(50) DEFAULT 'scanned'",
        "scanned_at": "ALTER TABLE library_items ADD COLUMN scanned_at DATETIME",
        "enriched_at": "ALTER TABLE library_items ADD COLUMN enriched_at DATETIME",
        "polished_at": "ALTER TABLE library_items ADD COLUMN polished_at DATETIME",
        "file_mtime": "ALTER TABLE library_items ADD COLUMN file_mtime REAL",
        "metadata_read_at": "ALTER TABLE library_items ADD COLUMN metadata_read_at DATETIME",
        "group_key": "ALTER TABLE library_items ADD COLUMN group_key VARCHAR(64)",
        "genres": "ALTER TABLE library_items ADD COLUMN genres TEXT",
        "published_date": "ALTER TABLE library_items ADD COLUMN published_date VARCHAR(20)",
        "file_modified_by_colophon": "ALTER TABLE library_items ADD COLUMN file_modified_by_colophon DATETIME",
        "upstream_synced_at": "ALTER TABLE library_items ADD COLUMN upstream_synced_at DATETIME",
        "completeness_score": "ALTER TABLE library_items ADD COLUMN completeness_score INTEGER",
    }

    changed = False
    group_key_added = False

    for column_name, sql in columns_to_add.items():
        if column_name not in existing_columns:
            db.session.execute(text(sql))
            changed = True
            if column_name == "group_key":
                group_key_added = True

    if changed:
        db.session.commit()

    try:
        db.session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_library_items_group_key "
            "ON library_items (group_key)"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    backfill_group_keys(force=group_key_added)
    sanitize_html_descriptions()
    backfill_language_detection()
    normalize_series_index_values()


def sanitize_html_descriptions():
    """Strip HTML tags from existing descriptions."""
    from app.services.metadata_sources import clean_text

    rows = db.session.execute(
        text(
            "SELECT id, description FROM library_items "
            "WHERE description IS NOT NULL AND description LIKE '%<%'"
        )
    ).fetchall()

    if not rows:
        return

    changed = 0
    for item_id, description in rows:
        cleaned = clean_text(description)
        if cleaned != description:
            db.session.execute(
                text("UPDATE library_items SET description = :desc WHERE id = :id"),
                {"desc": cleaned, "id": item_id},
            )
            changed += 1

    if changed:
        db.session.commit()


def backfill_group_keys(force=False):
    """Compute group_key for items that don't have one set yet."""
    from app.services.grouping import compute_group_key

    rows = db.session.execute(text(
        "SELECT id, title, author FROM library_items "
        "WHERE group_key IS NULL OR group_key = ''"
    )).fetchall()

    if not rows:
        return

    for item_id, title, author in rows:
        key = compute_group_key(title or "", author or "")
        if key:
            db.session.execute(
                text("UPDATE library_items SET group_key = :key WHERE id = :id"),
                {"key": key, "id": item_id},
            )

    db.session.commit()


def backfill_language_detection():
    """Detect language for existing EPUB/KEPUB items that lack one.

    Idempotent — only runs against rows where language is NULL or empty,
    so it's a no-op once every item has a language set.
    """
    rows = db.session.execute(text(
        "SELECT id, file_path FROM library_items "
        "WHERE (language IS NULL OR language = '') "
        "AND lower(extension) IN ('.epub', '.kepub', 'epub', 'kepub')"
    )).fetchall()

    if not rows:
        return

    from app.services.language_detect import (
        detect_language_from_text,
        extract_text_sample_from_epub,
    )

    updated = 0
    for item_id, file_path in rows:
        if not file_path or not os.path.exists(file_path):
            continue
        sample = extract_text_sample_from_epub(file_path)
        detected = detect_language_from_text(sample)
        if not detected:
            continue
        db.session.execute(
            text("UPDATE library_items SET language = :lang WHERE id = :id"),
            {"lang": detected, "id": item_id},
        )
        updated += 1

    if updated:
        db.session.commit()
        logger.info("Backfilled language for %d items", updated)


def normalize_series_index_values():
    """One-time cleanup: strip trailing ".0" from series_index values like "1.0" → "1"."""
    result = db.session.execute(text(
        "UPDATE library_items "
        "SET series_index = CAST(CAST(series_index AS REAL) AS INTEGER) "
        "WHERE series_index LIKE '%.0' "
        "AND CAST(CAST(series_index AS REAL) AS INTEGER) = CAST(series_index AS REAL)"
    ))
    if result.rowcount:
        db.session.commit()
        logger.info("Normalized series_index for %d rows", result.rowcount)
    else:
        db.session.rollback()


def ensure_app_settings_table():
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT
        )
    """))
    db.session.commit()


def ensure_kobo_devices_table():
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS kobo_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(200) NOT NULL,
            api_key_hash VARCHAR(64) NOT NULL UNIQUE,
            api_key_prefix VARCHAR(16) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen_at DATETIME,
            last_sync_at DATETIME,
            sync_count INTEGER DEFAULT 0,
            revoked BOOLEAN DEFAULT 0
        )
    """))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_kobo_devices_api_key_hash "
        "ON kobo_devices (api_key_hash)"
    ))
    db.session.commit()


def ensure_kobo_book_states_table():
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS kobo_book_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            library_item_id INTEGER NOT NULL,
            last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            revision_id VARCHAR(64),
            status VARCHAR(50),
            current_bookmark TEXT,
            statistics TEXT,
            state_modified_at DATETIME,
            UNIQUE (device_id, library_item_id)
        )
    """))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_kobo_book_states_device_id "
        "ON kobo_book_states (device_id)"
    ))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_kobo_book_states_library_item_id "
        "ON kobo_book_states (library_item_id)"
    ))
    db.session.commit()


def ensure_ai_usage_log_table():
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS ai_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider VARCHAR(50),
            model VARCHAR(100),
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            book_id INTEGER,
            book_title VARCHAR(500),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.session.commit()
