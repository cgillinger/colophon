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
)

_FILE_WRITABLE_EXTS = {".epub", ".mobi", ".azw3", ".kepub"}

# Human-readable Swedish labels for file_write_error codes (used by routes)
FILE_WRITE_ERROR_MESSAGES = {
    "not_installed":      "ebook-meta saknas på servern",
    "unsupported_format": "formatet stöder inte filskrivning",
    "file_not_found":     "e-boksfilen hittades inte på disk",
    "no_path":            "filsökväg saknas",
    "command_failed":     "ebook-meta-kommandot misslyckades",
    "timeout":            "ebook-meta tog för lång tid",
    "no_fields":          "inga fält att skriva",
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
    """
    is_explicit = selected_fields is not None
    selected = selected_fields or set()

    def _should_write(field):
        if is_explicit:
            return field in selected
        if field == "language":
            return False
        value = _stringify(result.get(field))
        if not value:
            return False
        current = getattr(item, field, None)
        return overwrite or not current

    db_updated = 0
    written_text: dict[str, str] = {}

    for field in _TEXT_FIELDS:
        if not _should_write(field):
            continue
        value = _stringify(result.get(field))
        if not value:
            continue
        setattr(item, field, value)
        db_updated += 1
        written_text[field] = value

    cover_url = _stringify(result.get("cover_url"))
    cover_local_path = _stringify(result.get("cover_path"))

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

    item.manual_metadata = True

    if "title" in written_text or "author" in written_text:
        from app.services.grouping import compute_group_key
        item.group_key = compute_group_key(item.title or "", item.author or "")

    file_updated = False
    file_write_error = None
    if write_to_file:
        write_result = write_metadata_to_file(
            item=item,
            written_text=written_text,
            cover_path=cover_dest_for_file,
        )
        file_updated = write_result["ok"]
        if not file_updated:
            file_write_error = write_result["error"]

    return {
        "db_updated": db_updated,
        "file_updated": file_updated,
        "file_write_error": file_write_error,
        "cover_saved": cover_saved,
        "cover_attempted": bool(cover_url) or bool(cover_local_path),
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
    if "series" in written_text:
        args += ["--series", written_text["series"]]
    if "series_index" in written_text:
        args += ["--index", written_text["series_index"]]
    if cover_path and os.path.exists(cover_path):
        args += ["--cover", cover_path]

    if len(args) <= 2:
        return {"ok": False, "error": "no_fields"}

    try:
        run_result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ebook-meta timeout för %s", file_path)
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        logger.warning("ebook-meta misslyckades: %s", exc)
        return {"ok": False, "error": "command_failed"}

    if run_result.returncode != 0:
        logger.warning(
            "ebook-meta returnerade kod %s: %s",
            run_result.returncode,
            (run_result.stderr or run_result.stdout or "").strip(),
        )
        return {"ok": False, "error": "command_failed"}

    return {"ok": True, "error": None}


def item_has_good_metadata(item):
    return bool(item.author and item.description and item.cover_path)
