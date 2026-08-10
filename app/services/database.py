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
        # Device-facing identity, deliberately independent of the primary key.
        # A row's id is an autoincrement that a delete + re-add changes, and the
        # Kobo treats a changed id as a different book — losing the reading
        # position and stranding the old entitlement on the device. book_uid
        # survives that. See backfill_book_uids() for why existing rows keep
        # their current UUID.
        "book_uid": "ALTER TABLE library_items ADD COLUMN book_uid VARCHAR(64)",
        "genres": "ALTER TABLE library_items ADD COLUMN genres TEXT",
        "published_date": "ALTER TABLE library_items ADD COLUMN published_date VARCHAR(20)",
        "file_modified_by_colophon": "ALTER TABLE library_items ADD COLUMN file_modified_by_colophon DATETIME",
        "upstream_synced_at": "ALTER TABLE library_items ADD COLUMN upstream_synced_at DATETIME",
        # Author-folder moves (DESIGN-author-folders.md): last pushed
        # relative path + old upstream path awaiting orphan cleanup.
        "upstream_rel_path": "ALTER TABLE library_items ADD COLUMN upstream_rel_path VARCHAR(2000)",
        "pending_upstream_cleanup": "ALTER TABLE library_items ADD COLUMN pending_upstream_cleanup VARCHAR(2000)",
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
        # Open merge proposal (DESIGN-robust-author-links.md): the entry
        # this book's linked entry probably duplicates. Settled by merge/
        # confirm/combobox pick.
        "suggested_author_id": (
            "ALTER TABLE library_items ADD COLUMN suggested_author_id "
            "INTEGER REFERENCES authors(id)"
        ),
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
    backfill_book_uids()
    sanitize_html_descriptions()
    backfill_language_detection()
    normalize_series_index_values()
    backfill_author_status_confirmed()
    backfill_relink_limbo_books()
    backfill_gc_orphan_tentative_authors()


def backfill_relink_limbo_books():
    """v2 invariant repair (DESIGN-robust-author-links.md): books left
    unlinked with a non-empty author string — the old 'review' limbo —
    re-enter the pending pass, which now always ends in a link (worst
    case a literal tentative entry + a merge proposal). Idempotent: the
    filter matches nothing once every stringed book is linked."""
    try:
        rows = db.session.execute(text(
            "SELECT id FROM library_items "
            "WHERE author IS NOT NULL AND author != '' AND author_id IS NULL"
        )).fetchall()
        if not rows:
            return
        db.session.execute(text(
            "UPDATE library_items SET author_status = NULL, "
            "suggested_author_id = NULL "
            "WHERE id IN (%s)" % ",".join(str(r[0]) for r in rows)
        ))
        from app.services.author_resolver import resolve_pending_authors
        counts = resolve_pending_authors(db.session)
        db.session.commit()
        logging.getLogger(__name__).info(
            "Relinked %d limbo books: %s", len(rows), counts
        )
    except Exception:
        db.session.rollback()


def backfill_gc_orphan_tentative_authors():
    """Remove auto-created (tentative) registry entries that no book
    links to and no proposal references — leftovers from the pre-v2 link
    severing. Logged before removal (design decision: log, then delete).
    Confirmed entries are never touched."""
    try:
        rows = db.session.execute(text(
            "SELECT id, canonical_name FROM authors WHERE source = 'tentative' "
            "AND id NOT IN (SELECT author_id FROM library_items "
            "               WHERE author_id IS NOT NULL) "
            "AND id NOT IN (SELECT suggested_author_id FROM library_items "
            "               WHERE suggested_author_id IS NOT NULL)"
        )).fetchall()
        if not rows:
            return
        logger = logging.getLogger(__name__)
        for author_id, name in rows:
            logger.info("GC orphan tentative author %s: %r", author_id, name)
        ids = ",".join(str(r[0]) for r in rows)
        db.session.execute(text(
            "DELETE FROM author_aliases WHERE author_id IN (%s)" % ids
        ))
        db.session.execute(text("DELETE FROM authors WHERE id IN (%s)" % ids))
        db.session.commit()
    except Exception:
        db.session.rollback()


def backfill_author_status_confirmed():
    """author_status 'new' marks the book that created a tentative registry
    entry — it's 'waiting' only until that entry is confirmed. Confirms used
    to leave the flag set, so the review banner never shrank; clear it for
    books whose author has since been confirmed/authority-linked."""
    try:
        result = db.session.execute(text(
            "UPDATE library_items SET author_status = 'linked' "
            "WHERE author_status = 'new' AND author_id IN "
            "(SELECT id FROM authors WHERE source != 'tentative')"
        ))
        if result.rowcount:
            db.session.commit()
        else:
            db.session.rollback()
    except Exception:
        db.session.rollback()


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


def backfill_book_uids():
    """Give every existing row the uid that reproduces its current Kobo UUID.

    The device identity used to be ``uuid5(NS, f"book-{item.id}")``. Seeding
    ``book_uid = "book-<id>"`` and hashing *that* keeps every already-synced
    book's UUID byte-identical across the upgrade — no re-downloads, no
    stranded entitlements, no lost reading positions. New rows get a random
    uid instead, so from here on identity no longer rides on the primary key.

    Idempotent — only touches NULLs.
    """
    result = db.session.execute(text(
        "UPDATE library_items SET book_uid = 'book-' || id WHERE book_uid IS NULL"
    ))
    if result.rowcount:
        db.session.commit()
        logger.info("Backfilled book_uid for %d rows", result.rowcount)
    else:
        db.session.rollback()

    try:
        db.session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_library_items_book_uid "
            "ON library_items (book_uid)"
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning("Could not create the book_uid index: %s", exc)


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


def ensure_multi_author_tables():
    """Multi-author support (v1.36.0): ordered book↔author links + split
    rules. db.create_all() handles fresh databases; this migrates existing
    ones and backfills one position-0 link per already-linked book so the
    registry views can count/filter through book_authors alone."""
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS book_authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES library_items(id),
            author_id INTEGER NOT NULL REFERENCES authors(id),
            position INTEGER NOT NULL DEFAULT 0,
            UNIQUE (item_id, position),
            UNIQUE (item_id, author_id)
        )
    """))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_book_authors_item_id "
        "ON book_authors (item_id)"
    ))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_book_authors_author_id "
        "ON book_authors (author_id)"
    ))
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS author_split_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_key VARCHAR(500) NOT NULL UNIQUE,
            author_ids TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    db.session.commit()

    # v1.37.0: "no, this is one person" dismissal of the looks-multi
    # badge. Same duplicate-column tolerance as ensure_database_columns
    # (two Gunicorn workers race this on boot).
    try:
        db.session.execute(text(
            "ALTER TABLE authors ADD COLUMN split_dismissed "
            "BOOLEAN NOT NULL DEFAULT 0"
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if "duplicate column name" not in str(exc).lower():
            raise

    # Backfill: mirror every existing single link as a position-0 row.
    # Idempotent — the NOT IN filter matches nothing on later boots. Books
    # whose fused string should split stay single-linked until their next
    # resolve (re-scan) or a manual split; nothing is guessed here.
    try:
        result = db.session.execute(text(
            "INSERT INTO book_authors (item_id, author_id, position) "
            "SELECT id, author_id, 0 FROM library_items "
            "WHERE author_id IS NOT NULL "
            "AND id NOT IN (SELECT item_id FROM book_authors)"
        ))
        if result.rowcount:
            db.session.commit()
            logger.info(
                "Backfilled book_authors for %d items", result.rowcount
            )
        else:
            db.session.rollback()
    except Exception as exc:
        db.session.rollback()
        if "unique" not in str(exc).lower():
            raise


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


def ensure_device_transfers_table():
    """The USB channel ledger (see services/device_transfers.py).

    Additive and idempotent, like every other ensure_* here: two Gunicorn
    workers boot concurrently and both run it.
    """
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS device_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
            device_id INTEGER REFERENCES kobo_devices(id) ON DELETE CASCADE,
            device_serial VARCHAR(64),
            device_label VARCHAR(200),
            method VARCHAR(16) NOT NULL DEFAULT 'usb',
            transferred_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    for sql in (
        "CREATE INDEX IF NOT EXISTS ix_device_transfers_item_id "
        "ON device_transfers (item_id)",
        "CREATE INDEX IF NOT EXISTS ix_device_transfers_device_id "
        "ON device_transfers (device_id)",
        "CREATE INDEX IF NOT EXISTS ix_device_transfers_device_serial "
        "ON device_transfers (device_serial)",
    ):
        db.session.execute(text(sql))
    db.session.commit()

    # Serial number on the device row — the fallback identity for a Kobo that
    # was never paired wirelessly. Tolerate the duplicate-column race the same
    # way ensure_database_columns does.
    try:
        db.session.execute(text(
            "ALTER TABLE kobo_devices ADD COLUMN device_serial VARCHAR(64)"
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if "duplicate column name" not in str(exc).lower():
            raise


def ensure_kobo_book_states_table():
    """The ledger of what each device has actually been told about.

    The delta sync (services/kobo_sync.py) asks this table — not the sync
    token's `since` — what to say about a book: no row => NewEntitlement,
    content newer than what we shipped => ChangedEntitlement, only reading
    state newer => ChangedReadingState. A device that lost its token
    therefore triggers no download storm; it gets only what it lacks.
    """
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS kobo_book_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER NOT NULL,
            library_item_id INTEGER NOT NULL,
            last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            revision_id VARCHAR(64),
            sent_updated_at DATETIME,
            sent_content_at DATETIME,
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

    # Upgrades: the table predates the two columns above.
    for sql in (
        "ALTER TABLE kobo_book_states ADD COLUMN sent_updated_at DATETIME",
        "ALTER TABLE kobo_book_states ADD COLUMN sent_content_at DATETIME",
    ):
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            if "duplicate column name" not in str(exc).lower():
                raise

    backfill_kobo_sent_timestamps()


def backfill_kobo_sent_timestamps():
    """Seed sent_* from last_synced_at for rows that predate the columns.

    This one matters. Unlike Bookstation, which built its ledger from
    nothing, Colophon has had a populated kobo_book_states all along. The
    classifier treats a NULL reference as "yes, newer" — so leaving these
    NULL would ship the ENTIRE library as ChangedEntitlement on the first
    sync after upgrade, which is precisely the download storm the delta sync
    exists to prevent.

    last_synced_at is the semantically right seed: the device was told about
    the book at that moment, so anything changed since then legitimately
    re-ships, and nothing else does.
    """
    result = db.session.execute(text(
        "UPDATE kobo_book_states "
        "   SET sent_updated_at = last_synced_at, "
        "       sent_content_at = last_synced_at "
        " WHERE sent_updated_at IS NULL OR sent_content_at IS NULL"
    ))
    if result.rowcount:
        db.session.commit()
        logger.info(
            "Backfilled Kobo ledger timestamps for %d row(s)", result.rowcount
        )
    else:
        db.session.rollback()


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
