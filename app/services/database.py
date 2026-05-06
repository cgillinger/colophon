from sqlalchemy import text

from app.models import db


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
