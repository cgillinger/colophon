# Colophon – e-book metadata manager
"""Language check: read what the book actually says, compare, report.

This is the read-only half of the language scenario. It opens each EPUB,
detects the language from two samples taken from inside the book (see
`language_detect.detect_language_confident`), and reports only the books
worth a human's attention: the ones with no stored language, and the ones
where the stored value disagrees with the text.

Nothing here writes. Applying a finding is a separate, explicit step —
`apply_language_changes` — driven by what the user ticked.
"""
import logging
import os

from app.models import LibraryItem, db
from app.services.language_detect import detect_language_confident

logger = logging.getLogger(__name__)

# ebook-meta cannot write these, and we cannot read text out of them either.
READABLE_EXTENSIONS = {".epub", ".kepub"}

# Stored values that mean "nobody has said" rather than a real language.
_EMPTY_LANGUAGE_VALUES = {"", "und", "unknown", "unk", "xx"}


def _stored_language(item):
    return (item.language or "").strip().lower()


def is_missing_language(item):
    return _stored_language(item) in _EMPTY_LANGUAGE_VALUES


def _same_language(stored, detected):
    """Compare loosely: 'en-GB' and 'en' are the same answer."""
    if not stored or not detected:
        return False
    return stored.replace("_", "-").split("-")[0] == detected.split("-")[0]


def candidate_items(item_ids=None):
    """Books this check can say anything about, in a stable order."""
    q = LibraryItem.query
    if item_ids:
        q = q.filter(LibraryItem.id.in_(list(item_ids)))
    return q.order_by(LibraryItem.id.asc()).all()


def check_language(item):
    """Inspect one book.

    Returns one of:
      None                      — nothing to report (stored value is right)
      {"status": "unreadable"}  — not an EPUB, or no usable text
      {"status": "missing"|"differs", ...}  — a finding for the review list
    """
    if (item.extension or "").lower() not in READABLE_EXTENSIONS:
        return {"status": "unreadable", "reason": "format"}

    path = item.file_path
    if not path or not os.path.exists(path):
        return {"status": "unreadable", "reason": "not_found"}

    detected = detect_language_confident(path)
    if not detected:
        return {"status": "unreadable", "reason": "no_text"}

    stored = _stored_language(item)
    if is_missing_language(item):
        status = "missing"
    elif _same_language(stored, detected["code"]):
        return None
    else:
        status = "differs"

    return {
        "status": status,
        "item_id": item.id,
        "title": item.title or item.file_name or "",
        "author": item.author or "",
        "stored": stored,
        "detected": detected["code"],
        "prob": round(detected["prob"], 3),
        # Both probes landed on the same language. When they didn't, the
        # book is the kind that deserves a human look, not a default tick.
        "agree": detected["agree"],
    }


def iter_language_findings(item_ids=None, on_progress=None, should_abort=None):
    """Walk the library and yield findings as they are discovered.

    `on_progress(done, total)` is called after each book so an SSE route can
    stream a progress bar. `should_abort()` lets the caller stop early.

    Read-only: this function never touches the database.
    """
    items = candidate_items(item_ids)
    total = len(items)
    unreadable = 0
    checked = 0

    for index, item in enumerate(items, start=1):
        if should_abort and should_abort():
            break
        try:
            finding = check_language(item)
        except Exception:
            logger.debug("language check failed for item %s", item.id, exc_info=True)
            finding = {"status": "unreadable", "reason": "error"}

        if finding and finding.get("status") == "unreadable":
            unreadable += 1
        elif finding:
            yield finding
            checked += 1
        else:
            checked += 1

        if on_progress:
            on_progress(index, total)

    # The caller needs the tally even when nothing was found, so hand it back
    # as a final summary object rather than a return value a generator hides.
    yield {
        "status": "summary",
        "total": total,
        "checked": checked,
        "unreadable": unreadable,
    }


def apply_language_changes(changes, write_files=False, cover_dir=None):
    """Write the ticked languages. DB always; files only when asked.

    `changes` is [{"item_id": int, "code": str}].

    The file write goes through apply_metadata_to_item with
    selected_fields={"language"} — nothing else may ride along. When
    write_files is False this touches the DB only, which deliberately does
    NOT stamp content_updated_at, so a Kobo does not re-download the book
    over a metadata correction it cannot see.
    """
    from app.services.metadata_writer import apply_metadata_to_item

    updated = 0
    files_written = 0
    errors = []

    for change in changes or []:
        item = db.session.get(LibraryItem, change.get("item_id"))
        code = (change.get("code") or "").strip()
        if item is None or not code:
            errors.append({"item_id": change.get("item_id"), "error": "not_found"})
            continue

        try:
            result = apply_metadata_to_item(
                item=item,
                result={"language": code},
                cover_dir=cover_dir,
                overwrite=True,
                write_to_file=write_files,
                selected_fields={"language"},
            )
        except Exception as exc:
            logger.exception("language apply failed for item %s", item.id)
            errors.append({"item_id": item.id, "error": str(exc)})
            continue

        updated += 1
        if write_files:
            if result.get("file_updated"):
                files_written += 1
            elif result.get("file_write_error"):
                errors.append({
                    "item_id": item.id,
                    "error": result.get("file_write_error"),
                })

    db.session.commit()
    return {
        "ok": True,
        "updated": updated,
        "files_written": files_written,
        "errors": errors,
    }
