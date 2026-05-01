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
    }

    changed = False

    for column_name, sql in columns_to_add.items():
        if column_name not in existing_columns:
            db.session.execute(text(sql))
            changed = True

    if changed:
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
