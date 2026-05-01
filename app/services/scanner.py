import hashlib
import os
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub
from ebooklib import ITEM_IMAGE

from app.models import db, LibraryItem
import logging

logger = logging.getLogger(__name__)



EBOOK_EXTENSIONS = {
    ".epub",
    ".pdf",
    ".txt",
    ".cbz",
    ".cbr",
}


def clean_title(filename_stem):
    title = filename_stem.replace("_", " ")
    title = title.replace(".", " ")
    title = title.replace("-", " ")
    title = " ".join(title.split())
    return title.strip()


def clean_metadata_text(value):
    if not value:
        return None

    value = str(value)

    soup = BeautifulSoup(value, "html.parser")
    value = soup.get_text(" ", strip=True)

    value = " ".join(value.split()).strip()

    if not value:
        return None

    return value


def first_metadata_value(book, namespace, key):
    values = book.get_metadata(namespace, key)

    if not values:
        return None

    value = values[0][0]

    return clean_metadata_text(value)


def save_epub_cover(book, file_path, cover_dir):
    cover_item = None

    try:
        cover_meta = book.get_metadata("OPF", "cover")

        if cover_meta:
            cover_id = cover_meta[0][1].get("content")
            if cover_id:
                cover_item = book.get_item_with_id(cover_id)
    except Exception:
        cover_item = None

    if cover_item is None:
        try:
            cover_item = book.get_item_with_id("cover")
        except Exception:
            cover_item = None

    if cover_item is None:
        try:
            for item in book.get_items_of_type(ITEM_IMAGE):
                name = item.get_name().lower()

                if "cover" in name or "omslag" in name:
                    cover_item = item
                    break
        except Exception:
            cover_item = None

    if cover_item is None:
        return None

    try:
        cover_data = cover_item.get_content()

        if not cover_data:
            return None

        cover_name = cover_item.get_name().lower()
        extension = Path(cover_name).suffix

        if extension not in [".jpg", ".jpeg", ".png", ".webp"]:
            extension = ".jpg"

        digest = hashlib.sha1(str(file_path).encode("utf-8")).hexdigest()
        cover_filename = digest + extension

        cover_dir_path = Path(cover_dir)
        cover_dir_path.mkdir(parents=True, exist_ok=True)

        cover_path = cover_dir_path / cover_filename

        with open(cover_path, "wb") as cover_file:
            cover_file.write(cover_data)

        return str(cover_path.resolve())

    except Exception:
        return None


def get_epub_metadata(file_path, cover_dir):
    title = None
    author = None
    description = None
    cover_path = None
    isbn = None
    publisher = None
    language = None

    try:
        book = epub.read_epub(str(file_path))

        title = first_metadata_value(book, "DC", "title")
        author = first_metadata_value(book, "DC", "creator")
        description = first_metadata_value(book, "DC", "description")
        isbn = first_metadata_value(book, "DC", "identifier")
        publisher = first_metadata_value(book, "DC", "publisher")
        language = first_metadata_value(book, "DC", "language")
        cover_path = save_epub_cover(book, file_path, cover_dir)

    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    return title, author, description, cover_path, isbn, publisher, language


def extract_series_from_filename(file_stem):
    import re

    match = re.search(r"\(([^,()]+),\s*#?\s*([0-9]+(?:\.[0-9]+)?)\)", file_stem)

    if not match:
        return None, None

    series = match.group(1).strip()
    series_index = match.group(2).strip()

    return series, series_index


def scan_library(library_dir, cover_dir):
    library_path = Path(library_dir)

    result = {
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "removed": 0,
        "missing_folder": False,
    }

    if not library_path.exists():
        result["missing_folder"] = True
        return result

    # Ta bort böcker från databasen om filen inte längre finns på disk.
    # Detta gör att "Skanna bibliotek" speglar biblioteksmappen exaktare.
    existing_items = LibraryItem.query.all()

    for existing_item in existing_items:
        if not existing_item.file_path:
            db.session.delete(existing_item)
            result["removed"] += 1
            continue

        if not Path(existing_item.file_path).exists():
            db.session.delete(existing_item)
            result["removed"] += 1

    db.session.commit()

    for file_path in library_path.rglob("*"):
        if not file_path.is_file():
            continue

        extension = file_path.suffix.lower()

        if extension not in EBOOK_EXTENSIONS:
            result["skipped"] += 1
            continue

        absolute_path = str(file_path.resolve())
        file_name = file_path.name
        size_bytes = os.path.getsize(absolute_path)

        title = clean_title(file_path.stem)
        author = None
        description = None
        cover_path = None
        isbn = None
        publisher = None
        language = None

        if extension == ".epub":
            (
                epub_title,
                epub_author,
                epub_description,
                epub_cover_path,
                epub_isbn,
                epub_publisher,
                epub_language,
            ) = get_epub_metadata(file_path, cover_dir)

            if epub_title:
                title = epub_title

            if epub_author:
                author = epub_author

            if epub_description:
                description = epub_description

            if epub_cover_path:
                cover_path = epub_cover_path

            if epub_isbn:
                isbn = epub_isbn

            if epub_publisher:
                publisher = epub_publisher

            if epub_language:
                language = epub_language

        existing = LibraryItem.query.filter_by(file_path=absolute_path).first()

        if existing:
            existing.file_name = file_name
            existing.extension = extension
            existing.size_bytes = size_bytes

            if not existing.manual_metadata:
                existing.title = title

                if author:
                    existing.author = author

                if isbn:
                    existing.isbn = isbn

                if publisher:
                    existing.publisher = publisher

                if language:
                    existing.language = language

            # Uppdatera alltid synopsis och omslag från filen,
            # även om titel/författare är manuellt låsta.
            # Uppdatera synopsis om ny metadata finns
            if description:
                existing.description = description

            # Viktigt:
            # Skriv bara över omslag om ett nytt omslag faktiskt hittades.
            # Om scanningen inte hittar omslag ska befintligt cover_path behållas.
            if cover_path and not existing.cover_locked:
                existing.cover_path = cover_path

            result["updated"] += 1
        else:
            item = LibraryItem(
                title=title,
                author=author,
                description=description,
                isbn=isbn,
                publisher=publisher,
                language=language,
                file_path=absolute_path,
                file_name=file_name,
                extension=extension,
                cover_path=cover_path,
                size_bytes=size_bytes,
                manual_metadata=False,
            )

            db.session.add(item)
            result["added"] += 1

    db.session.commit()

    return result
