# Colophon – e-book metadata manager
import logging
import os

from sqlalchemy import text

from app.models import db

logger = logging.getLogger(__name__)


def ensure_database_columns():
    # On a brand-new database the table doesn't exist yet — db.create_all()
    # (called right after this in create_app) builds it complete from the model.
    # The per-column ALTERs below are migration-only, for upgrading an existing
    # library, so skip them entirely when the table is absent; a missing-table
    # ALTER would otherwise raise and abort first boot of a fresh instance.
    table_exists = db.session.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_items'"
    )).fetchone()
    if not table_exists:
        return

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
        # Phase 3 — Kobo reading state sync. Defaults match the model so
        # books with no progress on Kobo aren't accidentally promoted.
        "read_status": (
            "ALTER TABLE library_items ADD COLUMN read_status "
            "VARCHAR(20) NOT NULL DEFAULT 'ReadyToRead'"
        ),
        "read_progress": "ALTER TABLE library_items ADD COLUMN read_progress REAL",
        "read_location": "ALTER TABLE library_items ADD COLUMN read_location TEXT",
        "read_location_json": "ALTER TABLE library_items ADD COLUMN read_location_json TEXT",
        "read_last_modified": "ALTER TABLE library_items ADD COLUMN read_last_modified DATETIME",
        "read_started_at": "ALTER TABLE library_items ADD COLUMN read_started_at DATETIME",
        "read_finished_at": "ALTER TABLE library_items ADD COLUMN read_finished_at DATETIME",
        "forgot_dismissed_at": "ALTER TABLE library_items ADD COLUMN forgot_dismissed_at DATETIME",
        "user_rating": "ALTER TABLE library_items ADD COLUMN user_rating INTEGER",
        "times_started": (
            "ALTER TABLE library_items ADD COLUMN times_started "
            "INTEGER NOT NULL DEFAULT 0"
        ),
        # Drives the Kobo sync delta — advances only on content/file
        # changes, never on reading progress. See models.py.
        "content_updated_at": "ALTER TABLE library_items ADD COLUMN content_updated_at DATETIME",
        # Author authority control — FK into authors. The authors table
        # exists before this runs (db.create_all / ensure_author_tables).
        "author_id": "ALTER TABLE library_items ADD COLUMN author_id INTEGER REFERENCES authors(id)",
        # Resolution outcome: linked/new/review/missing. NULL = pending —
        # exactly right for existing rows after upgrade: the next scan's
        # pending pass resolves the whole library in one batch.
        "author_status": "ALTER TABLE library_items ADD COLUMN author_status VARCHAR(16)",
    }

    changed = False
    group_key_added = False

    # Commit each ALTER on its own and tolerate "duplicate column name". The two
    # Gunicorn sync workers boot concurrently and both run this; without per-
    # column commits a lost race aborts the whole batch, and without swallowing
    # the duplicate error the losing worker crashes (code 3) and takes the
    # master down with it. Idempotent here = clean first boot.
    for column_name, sql in columns_to_add.items():
        if column_name not in existing_columns:
            try:
                db.session.execute(text(sql))
                db.session.commit()
                changed = True
                if column_name == "group_key":
                    group_key_added = True
            except Exception as exc:
                db.session.rollback()
                if "duplicate column name" not in str(exc).lower():
                    raise

    try:
        db.session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_library_items_group_key "
            "ON library_items (group_key)"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Index on the author_id FK column added above. Created here rather than in
    # ensure_author_tables() because the column only exists after the ALTER.
    try:
        db.session.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_library_items_author_id "
            "ON library_items (author_id)"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    backfill_group_keys(force=group_key_added)
    backfill_content_updated_at()
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


def backfill_content_updated_at():
    """Seed content_updated_at = updated_at for rows that predate the column.

    Existing books were last synced under the old logic, where the device's
    sync token `since` >= the book's updated_at. Setting content_updated_at to
    updated_at keeps content_updated_at <= since for those books, so the first
    sync after upgrade does NOT re-ship them as ChangedEntitlement (which would
    trigger a one-time mass re-download). Idempotent — only touches NULLs.
    """
    result = db.session.execute(text(
        "UPDATE library_items SET content_updated_at = updated_at "
        "WHERE content_updated_at IS NULL"
    ))
    if result.rowcount:
        db.session.commit()
        logger.info("Backfilled content_updated_at for %d rows", result.rowcount)
    else:
        db.session.rollback()


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


def ensure_author_tables():
    """Author authority control (docs/author-authority-design.md):
    canonical authors + variant aliases. db.create_all() creates these on
    fresh databases; this keeps already-migrated databases in step and adds
    the indexes ALTER TABLE can't."""
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name VARCHAR(500) NOT NULL,
            sort_name VARCHAR(500),
            wikidata_qid VARCHAR(32),
            libris_id VARCHAR(64),
            viaf_id VARCHAR(64),
            source VARCHAR(20) NOT NULL DEFAULT 'tentative',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS author_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_key VARCHAR(500) NOT NULL UNIQUE,
            author_id INTEGER NOT NULL REFERENCES authors(id)
        )
    """))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_author_aliases_author_id "
        "ON author_aliases (author_id)"
    ))
    # The ix_library_items_author_id index lives in ensure_database_columns(),
    # not here: it needs the library_items.author_id column, which that function
    # adds. This function must run first (the author_id ALTER references
    # authors(id)), so the column doesn't exist yet at this point.
    db.session.commit()


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
