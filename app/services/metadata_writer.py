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

    file_updated = False
    if write_to_file:
        file_updated = _write_to_ebook_file(
            item=item,
            written_text=written_text,
            cover_path=cover_dest_for_file,
        )

    return {
        "db_updated": db_updated,
        "file_updated": file_updated,
        "cover_saved": cover_saved,
        "cover_attempted": bool(cover_url) or bool(cover_local_path),
    }


def _write_to_ebook_file(item, written_text, cover_path):
    file_path_value = getattr(item, "file_path", "") or ""
    if not file_path_value:
        return False
    file_path = Path(file_path_value)
    if not file_path.exists():
        return False
    if file_path.suffix.lower() not in _FILE_WRITABLE_EXTS:
        return False
    if not shutil.which("ebook-meta"):
        return False

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
        return False

    try:
        run_result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        logger.warning("ebook-meta misslyckades: %s", exc)
        return False

    if run_result.returncode != 0:
        logger.warning(
            "ebook-meta returnerade kod %s: %s",
            run_result.returncode,
            (run_result.stderr or run_result.stdout or "").strip(),
        )
        return False

    return True


def item_has_good_metadata(item):
    return bool(item.author and item.description and item.cover_path)
