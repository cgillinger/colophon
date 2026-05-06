import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_IMAGE

from app.models import LibraryItem, db
from app.services.grouping import compute_group_key

logger = logging.getLogger(__name__)


EBOOK_EXTENSIONS = {".epub", ".mobi", ".azw3", ".kepub", ".pdf", ".cbz", ".cbr"}


# ---------------------------------------------------------------------------
# Internal text helpers
# ---------------------------------------------------------------------------

def _clean_title_from_filename(stem: str) -> str:
    title = stem.replace("_", " ").replace(".", " ").replace("-", " ")
    return " ".join(title.split()).strip()


def _clean_metadata_text(value):
    if not value:
        return None
    value = str(value)
    soup = BeautifulSoup(value, "html.parser")
    value = soup.get_text(" ", strip=True)
    value = " ".join(value.split()).strip()
    return value or None


def _first_metadata_value(book, namespace, key):
    values = book.get_metadata(namespace, key)
    if not values:
        return None
    return _clean_metadata_text(values[0][0])


def _save_epub_cover(book, file_path, cover_dir):
    cover_item = None
    try:
        cover_meta = book.get_metadata("OPF", "cover")
        if cover_meta:
            cover_id = cover_meta[0][1].get("content")
            if cover_id:
                cover_item = book.get_item_with_id(cover_id)
    except Exception:
        pass
    if not cover_item:
        try:
            cover_item = book.get_item_with_id("cover")
        except Exception:
            pass
    if not cover_item:
        try:
            for item in book.get_items_of_type(ITEM_IMAGE):
                name = item.get_name().lower()
                if "cover" in name:
                    cover_item = item
                    break
        except Exception:
            pass
    if not cover_item:
        return None
    try:
        cover_data = cover_item.get_content()
        if not cover_data:
            return None
        ext = Path(cover_item.get_name()).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        digest = hashlib.sha1(str(file_path).encode()).hexdigest()
        Path(cover_dir).mkdir(parents=True, exist_ok=True)
        cover_path = Path(cover_dir) / (digest + ext)
        cover_path.write_bytes(cover_data)
        return str(cover_path.resolve())
    except Exception:
        return None


def _assess_quality(meta: dict) -> str:
    has_title = bool(meta.get("title"))
    has_author = bool(meta.get("author"))
    has_rich = bool(meta.get("description") or meta.get("isbn") or meta.get("publisher"))
    if has_title and has_author and has_rich:
        return "good"
    if has_title and (has_author or has_rich):
        return "partial"
    return "minimal"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_ebook_files(root_path) -> list:
    """Return a list of all ebook files under root_path.

    Collecting up-front (not a generator) is required so callers know the
    total count for progress reporting before iteration starts.
    """
    root = Path(root_path)
    if not root.exists():
        return []
    files = []
    for file_path in root.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in EBOOK_EXTENSIONS:
            files.append(file_path)
    return files


def extract_local_metadata(file_path, cover_dir=None) -> dict:
    """Read metadata from a single ebook file and return a normalized dict.

    Return shape:
        title, author, description, isbn, publisher, language,
        series, series_index, cover_path,
        source ("ebooklib" | "ebook-meta" | "filename"),
        quality ("good" | "partial" | "minimal"),
        warnings (list[str])
    """
    file_path = Path(file_path)
    extension = file_path.suffix.lower()
    warnings = []

    base: dict = {
        "title": "", "author": "", "description": "",
        "isbn": "", "publisher": "", "language": "",
        "series": "", "series_index": "", "cover_path": None,
        "source": "filename", "quality": "minimal", "warnings": warnings,
    }

    try:
        if extension == ".epub":
            meta = _extract_epub_metadata(file_path, cover_dir, warnings)
        elif extension in {".mobi", ".azw3", ".kepub"}:
            meta = _extract_ebook_meta_metadata(file_path, warnings)
        else:
            meta = {}
    except Exception as exc:
        logger.warning("Kunde inte läsa metadata från %s: %s", file_path, exc)
        warnings.append(f"Metadataläsning misslyckades: {exc}")
        meta = {}

    base.update({k: v for k, v in meta.items() if v not in (None, "")})

    if not base["title"]:
        base["title"] = _clean_title_from_filename(file_path.stem)
        if base["source"] != "filename":
            warnings.append("Titel saknas i filenens metadata – använder filnamn.")
        base["source"] = "filename"

    base["quality"] = _assess_quality(base)
    return base


def _extract_epub_metadata(file_path, cover_dir, warnings: list) -> dict:
    book = epub.read_epub(str(file_path))
    title = _first_metadata_value(book, "DC", "title")
    author = _first_metadata_value(book, "DC", "creator")
    description = _first_metadata_value(book, "DC", "description")
    isbn_raw = _first_metadata_value(book, "DC", "identifier")
    publisher = _first_metadata_value(book, "DC", "publisher")
    language = _first_metadata_value(book, "DC", "language")

    cover_path = None
    if cover_dir:
        cover_path = _save_epub_cover(book, file_path, cover_dir)

    # Normalize ISBN — strip non-digits (ebooklib often returns "urn:isbn:…")
    isbn = ""
    if isbn_raw:
        import re
        digits = re.sub(r"[^0-9Xx]", "", isbn_raw)
        if len(digits) in (10, 13):
            isbn = digits

    return {
        "title": title or "",
        "author": author or "",
        "description": description or "",
        "isbn": isbn,
        "publisher": publisher or "",
        "language": language or "",
        "series": "",
        "series_index": "",
        "cover_path": cover_path,
        "source": "ebooklib",
    }


def _extract_ebook_meta_metadata(file_path, warnings: list) -> dict:
    try:
        from app.services.metadata_calibre import read_all_ebook_meta_fields
        fields = read_all_ebook_meta_fields(file_path)
    except Exception as exc:
        warnings.append(f"ebook-meta misslyckades: {exc}")
        return {"source": "filename"}

    if not fields:
        warnings.append("ebook-meta returnerade inga fält.")
        return {"source": "filename"}

    return {
        "title": fields.get("title") or "",
        "author": fields.get("author(s)") or "",
        "description": fields.get("comments") or "",
        "isbn": "",
        "publisher": fields.get("publisher") or "",
        "language": fields.get("languages") or "",
        "series": "",
        "series_index": "",
        "cover_path": None,
        "source": "ebook-meta",
    }


def upsert_library_item(file_path, metadata: dict, existing=None, db_session=None) -> LibraryItem:
    """Create or update a LibraryItem from a normalized metadata dict.

    Respects manual_metadata (never overwrites text fields when True) and
    cover_locked (never overwrites cover_path when True).

    Sets file_mtime and metadata_read_at on the item.
    """
    session = db_session if db_session is not None else db.session
    file_path = Path(file_path)
    absolute_path = str(file_path.resolve())
    extension = file_path.suffix.lower()
    now = datetime.utcnow()

    try:
        size_bytes = os.path.getsize(absolute_path)
        file_mtime = file_path.stat().st_mtime
    except OSError:
        size_bytes = 0
        file_mtime = None

    if existing:
        existing.file_name = file_path.name
        existing.extension = extension
        existing.size_bytes = size_bytes
        existing.file_mtime = file_mtime
        existing.metadata_read_at = now
        existing.scanned_at = now

        if not existing.manual_metadata:
            old_title = existing.title
            old_author = existing.author
            if metadata.get("title"):
                existing.title = metadata["title"]
            if metadata.get("author"):
                existing.author = metadata["author"]
            if metadata.get("description"):
                existing.description = metadata["description"]
            if metadata.get("publisher"):
                existing.publisher = metadata["publisher"]
            if metadata.get("language"):
                existing.language = metadata["language"]
            if metadata.get("isbn"):
                existing.isbn = metadata["isbn"]
            if metadata.get("series"):
                existing.series = metadata["series"]
            if metadata.get("series_index"):
                existing.series_index = metadata["series_index"]
            if metadata.get("cover_path") and not existing.cover_locked:
                existing.cover_path = metadata["cover_path"]

            if existing.title != old_title or existing.author != old_author or not existing.group_key:
                existing.group_key = compute_group_key(existing.title or "", existing.author or "")
        elif not existing.group_key:
            existing.group_key = compute_group_key(existing.title or "", existing.author or "")

        return existing

    item_title = metadata.get("title") or _clean_title_from_filename(file_path.stem)
    item_author = metadata.get("author") or None

    item = LibraryItem(
        title=item_title,
        author=item_author,
        description=metadata.get("description") or None,
        publisher=metadata.get("publisher") or None,
        language=metadata.get("language") or None,
        isbn=metadata.get("isbn") or None,
        series=metadata.get("series") or None,
        series_index=metadata.get("series_index") or None,
        cover_path=metadata.get("cover_path"),
        file_path=absolute_path,
        file_name=file_path.name,
        extension=extension,
        size_bytes=size_bytes,
        file_mtime=file_mtime,
        metadata_read_at=now,
        manual_metadata=False,
        pipeline_status="scanned",
        scanned_at=now,
        group_key=compute_group_key(item_title or "", item_author or ""),
    )
    session.add(item)
    return item


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

def scan_directory(root_path, db_session=None, on_progress=None, cover_dir=None) -> dict:
    session = db_session if db_session is not None else db.session
    root = Path(root_path)

    result = {"added": 0, "updated": 0, "skipped": 0, "removed": 0}

    if not root.exists():
        return result

    # Remove DB items whose files no longer exist
    for existing_item in LibraryItem.query.all():
        if not existing_item.file_path or not Path(existing_item.file_path).exists():
            session.delete(existing_item)
            result["removed"] += 1
    session.commit()

    # Build one in-memory index instead of querying per file
    existing_by_path = {item.file_path: item for item in LibraryItem.query.all()}

    files = discover_ebook_files(root)
    total = len(files)

    for idx, file_path in enumerate(files, 1):
        absolute_path = str(file_path.resolve())
        existing = existing_by_path.get(absolute_path)

        try:
            current_size = os.path.getsize(absolute_path)
            current_mtime = file_path.stat().st_mtime
        except OSError:
            current_size = 0
            current_mtime = None

        # Skip heavy extraction when file is unchanged and metadata is already present
        if (
            existing is not None
            and existing.file_mtime is not None
            and current_mtime is not None
            and abs(existing.file_mtime - current_mtime) < 0.01
            and existing.size_bytes == current_size
        ):
            result["skipped"] += 1
            if on_progress:
                on_progress({
                    "type": "progress",
                    "stage": "local_metadata",
                    "current": idx,
                    "total": total,
                    "file": file_path.name,
                    "status": "skipped",
                    "source": None,
                    **result,
                })
            continue

        try:
            meta = extract_local_metadata(file_path, cover_dir=cover_dir)
        except Exception:
            logger.warning("Kunde inte läsa metadata från %s, använder filnamn", file_path)
            meta = {
                "title": _clean_title_from_filename(file_path.stem),
                "source": "filename", "quality": "minimal", "warnings": [],
            }

        upsert_library_item(file_path, meta, existing=existing, db_session=session)

        if existing:
            result["updated"] += 1
        else:
            result["added"] += 1

        if on_progress:
            on_progress({
                "type": "progress",
                "stage": "local_metadata",
                "current": idx,
                "total": total,
                "file": file_path.name,
                "status": "read_metadata",
                "source": meta.get("source"),
                **result,
            })

    session.commit()
    return result


def scan_library(library_dir, cover_dir=None) -> dict:
    summary = scan_directory(library_dir, cover_dir=cover_dir)
    summary.setdefault("skipped", 0)
    summary.setdefault("missing_folder", not Path(library_dir).exists())
    return summary
