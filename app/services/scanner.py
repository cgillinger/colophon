import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app.models import LibraryItem, db
from app.services.metadata_calibre import _read_all_ebook_meta_fields

logger = logging.getLogger(__name__)


EBOOK_EXTENSIONS = {".epub", ".mobi", ".azw3", ".kepub", ".pdf", ".cbz", ".cbr"}


def _clean_title_from_filename(stem: str) -> str:
    title = stem.replace("_", " ").replace(".", " ").replace("-", " ")
    return " ".join(title.split()).strip()


def _read_embedded_metadata(file_path: Path) -> dict:
    if not shutil.which("ebook-meta"):
        return {}
    try:
        fields = _read_all_ebook_meta_fields(file_path)
    except (subprocess.SubprocessError, OSError):
        logger.debug("ebook-meta misslyckades för %s", file_path, exc_info=True)
        return {}
    return fields


def _metadata_from_file(file_path: Path) -> dict:
    fields = _read_embedded_metadata(file_path)
    return {
        "title": fields.get("title") or _clean_title_from_filename(file_path.stem),
        "author": fields.get("author(s)") or fields.get("authors") or None,
        "description": fields.get("comments") or None,
        "publisher": fields.get("publisher") or None,
        "language": fields.get("languages") or fields.get("language") or None,
        "isbn": (fields.get("identifiers") or "").split("isbn:")[-1].split(",")[0].strip() or None
            if fields.get("identifiers") and "isbn" in fields.get("identifiers", "").lower() else None,
    }


def scan_directory(root_path, db_session=None) -> dict:
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
        meta = _metadata_from_file(file_path)
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
            result["updated"] += 1
        else:
            item = LibraryItem(
                title=meta.get("title") or _clean_title_from_filename(file_path.stem),
                author=meta.get("author"),
                description=meta.get("description"),
                publisher=meta.get("publisher"),
                language=meta.get("language"),
                isbn=meta.get("isbn"),
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

    session.commit()
    return result


# Backwards-compatible wrapper for existing callers.
def scan_library(library_dir, cover_dir=None) -> dict:
    summary = scan_directory(library_dir)
    summary.setdefault("skipped", 0)
    summary.setdefault("missing_folder", not Path(library_dir).exists())
    return summary
