# Colophon – e-book metadata manager
"""Read a mounted Kobo: which devices are connected, and what they have read.

Two hard-won rules from the Bookstation implementation this is ported from,
both of which look like paranoia until they bite:

1. **Never read ``KoboReader.sqlite`` in place.** Opening it with
   ``immutable=1`` tells SQLite to ignore the journal, so a device that was
   unplugged mid-write leaves a hot WAL and the main file reads as *malformed*
   — a healthy database reported as corrupt. Copy the database **and its
   ``-wal``/``-shm``/``-journal`` sidecars** to a private writable directory
   and read the copy, where SQLite can replay the journal normally.

2. **Genuinely corrupt databases exist.** Not just a hot WAL — actual broken
   pages. Rather than give up on the whole file, re-read in rowid ranges and
   then row by row within a failing range, so the rows on healthy pages
   survive. Pure Python: sqlite3's ``.recover`` is absent from some builds
   (Ubuntu's), and unlike ``.dump`` this salvages rows *after* the first bad
   page too.

Unlike the reference implementation, this also imports the **reading position**
and not merely a percentage. The device stores ``ChapterIDBookmarked`` as
``OEBPS/chapter026.xhtml#kobo.8.1`` — which is exactly Colophon's own
``Source`` + ``Value`` pair — so a Kobo that has been offline for a month can
hand over its precise position the moment it is plugged in.
"""
import logging
import os
import shutil
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

DB_RELPATH = os.path.join(".kobo", "KoboReader.sqlite")

# A directory is a Kobo if it carries the firmware's own fingerprints.
_SIGNATURE_PATHS = (
    os.path.join(".kobo", "version"),
    os.path.join(".kobo", "KoboReader.sqlite"),
)

# ReadStatus in KoboReader.sqlite -> Colophon's monotonic status.
_STATUS_BY_RANK = {0: "ReadyToRead", 1: "Reading", 2: "Finished"}

_STATE_QUERY = """
    SELECT ContentID, Title, Attribution, ReadStatus, ___PercentRead,
           ChapterIDBookmarked, DateLastRead
    FROM content
    WHERE ContentType = 6
      AND BookID IS NULL
      AND (___PercentRead > 0 OR ReadStatus > 0)
"""

_SALVAGE_CHUNK = 512


def find_kobo_db(mount_path) -> str | None:
    candidate = os.path.join(mount_path, DB_RELPATH)
    return candidate if os.path.isfile(candidate) else None


def looks_like_kobo(mount_path) -> bool:
    return all(os.path.exists(os.path.join(mount_path, p)) for p in _SIGNATURE_PATHS)


def connected_mounts() -> list[str]:
    """Mount points that look like a Kobo, read from ``/proc/mounts``.

    Synchronous and cheap — no background thread, so nothing can pin a Gunicorn
    worker. Volume labels are deliberately ignored: they are user-editable and
    unreliable, so identity comes from the device's own files instead.
    """
    mounts = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return mounts

    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        # /proc/mounts octal-escapes spaces and friends.
        target = parts[1].encode("utf-8", "surrogateescape").decode("unicode_escape")
        if target in mounts:
            continue
        try:
            if looks_like_kobo(target):
                mounts.append(target)
        except OSError:
            continue
    return mounts


def _query(db_file: str) -> list:
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(_STATE_QUERY).fetchall()
    finally:
        conn.close()


def _salvage(db_file: str) -> list:
    """Recover what can be read from a database with broken pages."""
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    ranged = _STATE_QUERY + " AND rowid BETWEEN :lo AND :hi"
    try:
        try:
            max_rowid = conn.execute("SELECT max(rowid) FROM content").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                "the database is too damaged to salvage — even the table's "
                "extent cannot be read"
            ) from exc
        if not max_rowid:
            return []

        rows = []
        for lo in range(1, max_rowid + 1, _SALVAGE_CHUNK):
            hi = min(lo + _SALVAGE_CHUNK - 1, max_rowid)
            try:
                rows.extend(conn.execute(ranged, {"lo": lo, "hi": hi}).fetchall())
            except sqlite3.DatabaseError:
                for rowid in range(lo, hi + 1):
                    try:
                        rows.extend(
                            conn.execute(ranged, {"lo": rowid, "hi": rowid}).fetchall()
                        )
                    except sqlite3.DatabaseError:
                        continue
        return rows
    finally:
        conn.close()


def _split_bookmark(raw):
    """``OEBPS/ch26.xhtml#kobo.8.1`` -> ``("OEBPS/ch26.xhtml", "kobo.8.1")``.

    The device's own bookmark format is already Colophon's ``Source``/``Value``
    pair, so this is a split rather than a translation.

    But a device can be holding a bookmark we gave it *wrongly*: before v1.28.2
    Colophon fabricated ``Source = book_uuid``, and a real device still carries
    such rows years later. Importing one would put the old bug straight back
    into the database, so the Source has to look like a content document — a
    final segment with a file extension. A bare UUID has none.
    """
    if not raw or "#" not in str(raw):
        return None, None
    source, _, value = str(raw).partition("#")
    source = source.strip()
    value = value.strip()
    if not source or not value.startswith("kobo."):
        return None, None
    if "." not in source.rsplit("/", 1)[-1]:
        logger.debug(
            "Kobo USB: ignoring bookmark whose Source is not a document: %r", source
        )
        return None, None
    return source, value


def read_device_state(mount_path) -> tuple[list[dict], bool]:
    """``(entries, recovered)`` — what the device has read.

    ``recovered`` is True when the database was corrupt and only partially
    salvaged, so callers can say so rather than presenting the result as
    complete.
    """
    db_path = find_kobo_db(mount_path)
    if not db_path:
        return [], False

    recovered = False
    with tempfile.TemporaryDirectory(prefix="colophon-koboreader-") as tmp_dir:
        db_copy = os.path.join(tmp_dir, "KoboReader.sqlite")
        shutil.copy2(db_path, db_copy)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = db_path + suffix
            if os.path.isfile(sidecar):
                shutil.copy2(sidecar, db_copy + suffix)

        try:
            rows = _query(db_copy)
        except sqlite3.DatabaseError as exc:
            logger.warning(
                "Kobo USB: database is corrupt (%s) — salvaging row by row", exc
            )
            rows = _salvage(db_copy)
            recovered = True
            logger.info("Kobo USB: salvaged %d row(s) from a corrupt database", len(rows))

    entries = []
    for row in rows:
        content_id = row["ContentID"] or ""
        source, value = _split_bookmark(row["ChapterIDBookmarked"])
        entries.append({
            "content_id": content_id,
            "title": row["Title"] or "",
            "author": row["Attribution"] or "",
            "status": _STATUS_BY_RANK.get(row["ReadStatus"] or 0, "ReadyToRead"),
            # Colophon stores 0–100, and so does the device. No rescaling.
            "percent": float(row["___PercentRead"] or 0),
            "location_source": source,
            "location_value": value,
            "date_last_read": row["DateLastRead"] or None,
        })
    return entries, recovered


def _item_for_entry(entry):
    """Match one device row to a library book.

    Cloud books carry the UUID Colophon minted, which is exact. Sideloaded
    books carry a file path instead, so fall back to the filename and then to
    a normalised title — the device knows nothing about our ids.
    """
    from app.models import LibraryItem
    from app.routes.kobo import _find_item_by_uuid
    from app.services.grouping import compute_group_key

    content_id = entry.get("content_id") or ""
    if content_id and "/" not in content_id:
        item = _find_item_by_uuid(content_id)
        if item is not None:
            return item

    filename = content_id.rsplit("/", 1)[-1] if "/" in content_id else ""
    if filename:
        # The device holds .kepub.epub where the library has .epub.
        for suffix in (".kepub.epub", ".kepub"):
            if filename.endswith(suffix):
                filename = filename[: -len(suffix)] + ".epub"
                break
        item = LibraryItem.query.filter_by(file_name=filename).first()
        if item is not None:
            return item

    title = (entry.get("title") or "").strip()
    if title:
        matches = LibraryItem.query.filter_by(
            group_key=compute_group_key(title)
        ).all()
        if len(matches) == 1:
            return matches[0]
    return None


def import_device_state(mount_path, dry_run=False) -> dict:
    """Pull reading state off a mounted Kobo into the library.

    Goes through ``apply_reading_state`` rather than writing columns directly,
    so a USB import obeys exactly the same monotonic / furthest-read rules as a
    wireless sync — and so it can never bump ``content_updated_at`` and make
    every imported book re-download.
    """
    from app.models import db
    from app.services.reading_state import apply_reading_state

    entries, recovered = read_device_state(mount_path)
    receipt = {
        "read": len(entries), "applied": 0, "skipped": 0, "unmatched": [],
        "recovered_from_corruption": recovered, "dry_run": bool(dry_run),
    }

    for entry in entries:
        item = _item_for_entry(entry)
        if item is None:
            receipt["unmatched"].append(entry.get("title") or entry.get("content_id"))
            continue

        location = None
        if entry["location_source"] and entry["location_value"]:
            location = {
                "Source": entry["location_source"],
                "Type": "KoboSpan",
                "Value": entry["location_value"],
            }

        if dry_run:
            receipt["applied"] += 1
            continue

        if apply_reading_state(
            item,
            entry["status"],
            progress=entry["percent"],
            location=location,
            modified_at=_parse_device_time(entry["date_last_read"]),
        ):
            receipt["applied"] += 1
        else:
            receipt["skipped"] += 1

    if not dry_run and receipt["applied"]:
        db.session.commit()
    else:
        db.session.rollback()

    logger.info(
        "Kobo USB import: read=%d applied=%d skipped=%d unmatched=%d recovered=%s",
        receipt["read"], receipt["applied"], receipt["skipped"],
        len(receipt["unmatched"]), recovered,
    )
    return receipt


def _parse_device_time(raw):
    """``2026-08-08T22:26:31Z`` -> naive UTC datetime, or ``None``."""
    if not raw:
        return None
    from datetime import datetime

    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
    return parsed
