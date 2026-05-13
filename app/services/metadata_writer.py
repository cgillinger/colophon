# Colophon – e-book metadata manager
import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.services.metadata_sources import download_cover_to_file

logger = logging.getLogger(__name__)


_TEXT_FIELDS = (
    "title",
    "author",
    "series",
    "series_index",
    "isbn",
    "publisher",
    "language",
    "description",
    "genres",
    "published_date",
)

_FILE_WRITABLE_EXTS = {".epub", ".mobi", ".azw3", ".kepub"}

# Human-readable English labels for file_write_error codes (used by routes).
# Routes wrap these with gettext when rendering.
FILE_WRITE_ERROR_MESSAGES = {
    "not_installed":      "ebook-meta is missing on the server",
    "unsupported_format": "the format does not support file writing",
    "file_not_found":     "the ebook file was not found on disk",
    "no_path":            "file path missing",
    "command_failed":     "the ebook-meta command failed",
    "timeout":            "ebook-meta took too long",
    "no_fields":          "no fields to write",
}


def _stringify(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def apply_metadata_to_item(
    item,
    result,
    cover_dir,
    overwrite=False,
    write_to_file=True,
    selected_fields=None,
    smart_replace_fields=None,
):
    """Apply a metadata result-dict to both the database and the ebook file.

    selected_fields=None means: apply every field that has a value, subject to
    the overwrite flag. The language field is *never* written in this implicit
    mode — it must be selected explicitly via selected_fields.

    selected_fields=set(...) means: write only those exact fields.

    Returns:
        db_updated        int   — number of DB text fields written
        file_updated      bool  — True if ebook file was written successfully
        file_write_error  str | None — error code when file_updated is False and
                                       write_to_file was True; see
                                       FILE_WRITE_ERROR_MESSAGES for labels
        cover_saved       bool  — True if cover was saved to the covers dir
        cover_attempted   bool  — True if a cover URL or local path was present
        fields_added      list[str] — fields that were empty and got filled
        fields_replaced   list[str] — fields that had a value and were overwritten
        fields_skipped    list[str] — fields with a fetched value that we did not
                                      write because the existing value was kept
    """
    is_explicit = selected_fields is not None
    selected = selected_fields or set()
    smart_replace = smart_replace_fields or set()

    def _should_write(field):
        if is_explicit:
            return field in selected
        if field == "language":
            return False
        value = _stringify(result.get(field))
        if not value:
            return False
        current = _stringify(getattr(item, field, None))
        if overwrite or not current:
            return True
        if field in smart_replace:
            from app.services.quality import evaluate_quality

            author = _stringify(getattr(item, "author", "")) if field == "publisher" else ""
            is_better, _ = evaluate_quality(field, current, value, author=author)
            return is_better
        return False

    db_updated = 0
    written_text: dict[str, str] = {}
    fields_added: list[str] = []
    fields_replaced: list[str] = []
    fields_skipped: list[str] = []

    from app.services.metadata_sources import clean_text

    for field in _TEXT_FIELDS:
        value = _stringify(result.get(field))
        if not value:
            continue
        if field == "description":
            value = clean_text(value)
            if not value:
                continue

        current = _stringify(getattr(item, field, None))

        if _should_write(field):
            if current:
                fields_replaced.append(field)
            else:
                fields_added.append(field)
            setattr(item, field, value)
            db_updated += 1
            written_text[field] = value
        else:
            # Had a fetched value but did not write: existing kept.
            # Skip the language policy-skip in implicit mode (never tracked).
            if current and not (not is_explicit and field == "language"):
                fields_skipped.append(field)

    cover_url = _stringify(result.get("cover_url"))
    cover_local_path = _stringify(result.get("cover_path"))
    had_cover_before = bool(getattr(item, "cover_path", ""))

    if is_explicit:
        apply_cover = "cover" in selected
    else:
        apply_cover = bool(cover_url) and (overwrite or not item.cover_path)

    cover_saved = False
    cover_dest_for_file = None

    if apply_cover:
        if cover_local_path and os.path.exists(cover_local_path):
            os.makedirs(cover_dir, exist_ok=True)
            ext = os.path.splitext(cover_local_path)[1] or ".jpg"
            dest = os.path.join(cover_dir, f"cover_{item.id}{ext}")
            shutil.copy2(cover_local_path, dest)
            item.cover_path = dest
            item.cover_locked = True
            cover_saved = True
            cover_dest_for_file = dest
        elif cover_url:
            new_path = download_cover_to_file(
                cover_url=cover_url,
                cover_dir=cover_dir,
                item_id=item.id,
            )
            if new_path:
                item.cover_path = new_path
                if is_explicit:
                    item.cover_locked = True
                cover_saved = True
                cover_dest_for_file = new_path

    if cover_saved:
        if had_cover_before:
            fields_replaced.append("cover")
        else:
            fields_added.append("cover")
    elif (cover_url or cover_local_path) and not apply_cover and had_cover_before:
        fields_skipped.append("cover")

    item.manual_metadata = True

    if "title" in written_text or "author" in written_text:
        from app.services.grouping import compute_group_key
        item.group_key = compute_group_key(item.title or "", item.author or "")

    file_updated = False
    file_write_error = None
    if write_to_file:
        logger.info(
            "apply_metadata_to_item: item_id=%s written_text_keys=%s "
            "write_to_file=True is_explicit=%s overwrite=%s",
            getattr(item, "id", None),
            sorted(written_text.keys()),
            is_explicit,
            overwrite,
        )
        write_result = write_metadata_to_file(
            item=item,
            written_text=written_text,
            cover_path=cover_dest_for_file,
        )
        file_updated = write_result["ok"]
        if file_updated:
            from datetime import datetime
            item.file_modified_by_colophon = datetime.utcnow()
        if not file_updated:
            file_write_error = write_result["error"]
            logger.info(
                "apply_metadata_to_item: file write failed item_id=%s error=%s",
                getattr(item, "id", None), file_write_error,
            )
    else:
        logger.info(
            "apply_metadata_to_item: item_id=%s written_text_keys=%s "
            "write_to_file=False",
            getattr(item, "id", None),
            sorted(written_text.keys()),
        )

    # Refresh the completeness score so the DB reflects the post-write state.
    try:
        from app.services.metadata_pipeline import completeness_score
        item.completeness_score = completeness_score(item)
    except Exception:
        logger.debug("completeness_score update failed", exc_info=True)

    return {
        "db_updated": db_updated,
        "file_updated": file_updated,
        "file_write_error": file_write_error,
        "cover_saved": cover_saved,
        "cover_attempted": bool(cover_url) or bool(cover_local_path),
        "fields_added": fields_added,
        "fields_replaced": fields_replaced,
        "fields_skipped": fields_skipped,
    }


def write_metadata_to_file(item, written_text, cover_path):
    """Write metadata fields and/or cover to the ebook file via ebook-meta.

    Returns a dict:
        ok     bool        — True if ebook-meta ran and exited 0
        error  str | None  — error code when ok is False; see
                             FILE_WRITE_ERROR_MESSAGES for human-readable labels
                             Possible values:
                               "no_path"            — item has no file_path
                               "file_not_found"     — file does not exist on disk
                               "unsupported_format" — extension not in writable set
                               "not_installed"      — ebook-meta binary not found
                               "no_fields"          — nothing to write
                               "command_failed"     — non-zero exit or exception
                               "timeout"            — subprocess timed out
    """
    file_path_value = getattr(item, "file_path", "") or ""
    if not file_path_value:
        return {"ok": False, "error": "no_path"}

    file_path = Path(file_path_value)
    if not file_path.exists():
        return {"ok": False, "error": "file_not_found"}
    if file_path.suffix.lower() not in _FILE_WRITABLE_EXTS:
        return {"ok": False, "error": "unsupported_format"}
    if not shutil.which("ebook-meta"):
        return {"ok": False, "error": "not_installed"}

    args = ["ebook-meta", str(file_path)]
    if "title" in written_text:
        args += ["--title", written_text["title"]]
    if "author" in written_text:
        args += ["--authors", written_text["author"]]
    if "description" in written_text:
        args += ["--comments", written_text["description"]]
    if "publisher" in written_text:
        args += ["--publisher", written_text["publisher"]]
    if "isbn" in written_text:
        args += ["--identifier", f"isbn:{written_text['isbn']}"]
    if "language" in written_text:
        args += ["--language", written_text["language"]]
    # ebook-meta crashes on `--series ""` / `--index ""` (the latter raises
    # "could not convert string to float"). Drop empty values, and only pass
    # --index when numeric.
    series_val = (written_text.get("series") or "").strip()
    if series_val:
        args += ["--series", series_val]
    index_val = (written_text.get("series_index") or "").strip()
    if index_val:
        try:
            float(index_val)
            args += ["--index", index_val]
        except ValueError:
            logger.info(
                "Skipping --index for %s: non-numeric value %r",
                file_path, index_val,
            )
    if "published_date" in written_text:
        args += ["--date", written_text["published_date"]]
    if cover_path and os.path.exists(cover_path):
        args += ["--cover", cover_path]

    if len(args) <= 2:
        return {"ok": False, "error": "no_fields"}

    written_fields = sorted(written_text.keys())
    logger.info(
        "write_metadata_to_file: path=%s fields=%s has_cover=%s",
        file_path, written_fields, bool(cover_path and os.path.exists(cover_path)),
    )

    try:
        run_result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ebook-meta timeout for %s", file_path)
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        logger.warning("ebook-meta misslyckades: %s", exc)
        return {"ok": False, "error": "command_failed"}

    if run_result.returncode != 0:
        logger.warning(
            "ebook-meta returnerade kod %s for %s: stderr=%s",
            run_result.returncode,
            file_path,
            (run_result.stderr or run_result.stdout or "").strip(),
        )
        return {"ok": False, "error": "command_failed"}

    logger.info(
        "write_metadata_to_file: ok path=%s wrote=%s",
        file_path, written_fields,
    )
    return {"ok": True, "error": None}


_SYNCABLE_FIELDS = (
    "title", "author", "description", "series", "series_index",
    "isbn", "publisher", "language", "genres", "published_date",
)


def sync_group_metadata(group_items, cover_dir=None):
    """Cross-populate empty fields within a format group.

    For each syncable field, find the best non-empty value across all members
    and copy it into members that lack it.  Cover paths are synced separately
    (the source file must actually exist on disk).

    Only fills *empty* fields — never overwrites existing values.

    Returns a dict:
        fields_synced  int        — total field writes across all members
        details        list[dict] — per-member summary (item_id, format, fields_synced)
    """
    if len(group_items) < 2:
        return {"fields_synced": 0, "details": []}

    # Build a "best value" dict: prefer the longest non-empty value per field.
    best: dict[str, str] = {}
    for field in _SYNCABLE_FIELDS:
        for item in group_items:
            val = (getattr(item, field, None) or "").strip()
            if val and len(val) > len(best.get(field, "")):
                best[field] = val

    # Best cover: first member with a cover_path that exists on disk.
    best_cover = None
    for item in group_items:
        if item.cover_path and os.path.exists(item.cover_path):
            best_cover = item.cover_path
            break

    total_synced = 0
    details = []

    for item in group_items:
        member_synced = []

        for field in _SYNCABLE_FIELDS:
            current = (getattr(item, field, None) or "").strip()
            if not current and best.get(field):
                setattr(item, field, best[field])
                member_synced.append(field)

        if best_cover and not item.cover_path:
            item.cover_path = best_cover
            member_synced.append("cover")

        total_synced += len(member_synced)
        if member_synced:
            details.append({
                "item_id": item.id,
                "format": (item.extension or "").lstrip(".").upper(),
                "fields_synced": member_synced,
            })

    return {"fields_synced": total_synced, "details": details}


def item_has_good_metadata(item):
    return bool(item.author and item.description and item.cover_path)
