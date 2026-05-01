import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_IMAGE

from app.models import LibraryItem, db

logger = logging.getLogger(__name__)


EBOOK_EXTENSIONS = {".epub", ".mobi", ".azw3", ".kepub", ".pdf", ".cbz", ".cbr"}


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


def _get_epub_metadata(file_path, cover_dir):
    title = author = description = cover_path = isbn = publisher = language = None
    try:
        book = epub.read_epub(str(file_path))
        title = _first_metadata_value(book, "DC", "title")
        author = _first_metadata_value(book, "DC", "creator")
        description = _first_metadata_value(book, "DC", "description")
        isbn = _first_metadata_value(book, "DC", "identifier")
        publisher = _first_metadata_value(book, "DC", "publisher")
        language = _first_metadata_value(book, "DC", "language")
        if cover_dir:
            cover_path = _save_epub_cover(book, file_path, cover_dir)
    except Exception:
        pass
    return title, author, description, cover_path, isbn, publisher, language


def scan_directory(root_path, db_session=None, on_progress=None, cover_dir=None) -> dict:
    session = db_session if db_session is not None else db.session
    root = Path(root_path)

    result = {"added": 0, "updated": 0, "removed": 0}

    if not root.exists():
        return result

    for existing in LibraryItem.query.all():
        if not existing.file_path or not Path(existing.file_path).exists():
            session.delete(existing)
            result["removed"] += 1
    session.commit()

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        extension = file_path.suffix.lower()
        if extension not in EBOOK_EXTENSIONS:
            continue

        absolute_path = str(file_path.resolve())

        try:
            if extension == ".epub":
                title, author, description, epub_cover, isbn, publisher, language = _get_epub_metadata(file_path, cover_dir)
                if not title:
                    title = _clean_title_from_filename(file_path.stem)
                meta = {
                    "title": title,
                    "author": author,
                    "description": description,
                    "cover_path": epub_cover,
                    "isbn": isbn,
                    "publisher": publisher,
                    "language": language,
                }
            else:
                meta = {"title": _clean_title_from_filename(file_path.stem)}
        except Exception:
            logger.warning("Kunde inte läsa metadata från %s, använder filnamn", file_path)
            meta = {"title": _clean_title_from_filename(file_path.stem)}

        size_bytes = os.path.getsize(absolute_path)
        now = datetime.utcnow()

        existing = LibraryItem.query.filter_by(file_path=absolute_path).first()

        if existing:
            existing.file_name = file_path.name
            existing.extension = extension
            existing.size_bytes = size_bytes
            if not existing.manual_metadata:
                if meta.get("title"):
                    existing.title = meta["title"]
                if meta.get("author"):
                    existing.author = meta["author"]
                if meta.get("description"):
                    existing.description = meta["description"]
                if meta.get("publisher"):
                    existing.publisher = meta["publisher"]
                if meta.get("language"):
                    existing.language = meta["language"]
                if meta.get("isbn"):
                    existing.isbn = meta["isbn"]
                if meta.get("cover_path") and not existing.cover_locked:
                    existing.cover_path = meta["cover_path"]
            result["updated"] += 1
        else:
            item = LibraryItem(
                title=meta.get("title") or _clean_title_from_filename(file_path.stem),
                author=meta.get("author"),
                description=meta.get("description"),
                publisher=meta.get("publisher"),
                language=meta.get("language"),
                isbn=meta.get("isbn"),
                cover_path=meta.get("cover_path"),
                file_path=absolute_path,
                file_name=file_path.name,
                extension=extension,
                size_bytes=size_bytes,
                manual_metadata=False,
                pipeline_status="scanned",
                scanned_at=now,
            )
            session.add(item)
            result["added"] += 1

        if on_progress:
            on_progress({
                "type": "progress",
                "file": file_path.name,
                "added": result["added"],
                "updated": result["updated"],
                "removed": result["removed"],
            })

    session.commit()
    return result


def scan_library(library_dir, cover_dir=None) -> dict:
    summary = scan_directory(library_dir, cover_dir=cover_dir)
    summary.setdefault("skipped", 0)
    summary.setdefault("missing_folder", not Path(library_dir).exists())
    return summary
