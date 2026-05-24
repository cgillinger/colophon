# Colophon – e-book metadata manager
import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_IMAGE, ITEM_COVER
from flask_babel import gettext as _

from app.models import LibraryItem, db
from app.services.grouping import compute_group_key
from app.services.language_detect import (
    detect_language_from_text,
    extract_text_sample_from_epub,
)
from app.services.text_utils import clean_title, normalize_series_index

logger = logging.getLogger(__name__)


def _opf_meta_by_name(book, name):
    """Hitta <meta name="X" content="Y"/> i OPF-metadata."""
    try:
        for val, attrs in (book.get_metadata("OPF", "meta") or []):
            if (attrs or {}).get("name") == name:
                return (attrs.get("content") or "").strip() or None
    except Exception:
        pass
    return None


def _opf_meta_by_property(book, prop):
    """Hitta <meta property="X">Y</meta> i OPF-metadata (EPUB3)."""
    try:
        for val, attrs in (book.get_metadata("OPF", "meta") or []):
            if (attrs or {}).get("property") == prop:
                return (val or "").strip() or None
    except Exception:
        pass
    return None


EBOOK_EXTENSIONS = {".epub", ".mobi", ".azw3", ".kepub", ".pdf", ".cbz", ".cbr"}


# ---------------------------------------------------------------------------
# Internal text helpers
# ---------------------------------------------------------------------------

# "SeriesName## - Author - Title" / "SeriesName ## - Author - Title".
# Series must end with a non-digit so we don't grab partial years (e.g. "1968").
_FILENAME_SERIES_PATTERN = re.compile(
    r"^(?P<series>.+?\D)\s*(?P<index>\d{1,3})\s*-\s*[^-]+?\s*-\s*(?P<title>.+)$"
)


def _clean_title_from_filename(stem: str) -> dict:
    """Derive title (and possibly series + index) from a filename stem.

    Returns:
        {"title": str, "series": str | None, "series_index": str | None}
    """
    if not stem:
        return {"title": "", "series": None, "series_index": None}

    match = _FILENAME_SERIES_PATTERN.match(stem)
    if match:
        return {
            "title": match.group("title").strip(),
            "series": match.group("series").strip(),
            "series_index": match.group("index"),
        }

    title = stem.replace("_", " ").replace(".", " ").replace("-", " ")
    title = " ".join(title.split()).strip()
    return {"title": title, "series": None, "series_index": None}


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


_ROLE_ATTR_KEYS = (
    "{http://www.idpf.org/2007/opf}role",
    "opf:role",
    "role",
)
_logged_creator_role_keys: set = set()


def _creator_role(attrs):
    if not attrs:
        return ""
    for key in _ROLE_ATTR_KEYS:
        if key in attrs:
            if key not in _logged_creator_role_keys:
                _logged_creator_role_keys.add(key)
                logger.debug("EPUB creator role attribute key: %s", key)
            return (attrs.get(key) or "").strip()
    return ""


def _collect_authors(book):
    """Return all DC:creator entries that are authors (or have no role).

    EPUB allows opf:role on creators: "aut" (author), "edt" (editor),
    "trl" (translator), "ill" (illustrator), etc. If any creator declares
    role="aut", use only those. Otherwise (no roles set), use all creators
    — this is the dominant case in older EPUBs.
    """
    creators = book.get_metadata("DC", "creator") or []
    if not creators:
        return ""

    explicit_authors = []
    all_creators = []
    for value, attrs in creators:
        text = _clean_metadata_text(value)
        if not text:
            continue
        all_creators.append(text)
        if _creator_role(attrs) == "aut":
            explicit_authors.append(text)

    chosen = explicit_authors if explicit_authors else all_creators
    return ", ".join(chosen)


def _is_image_item(item):
    """True if the manifest item is an actual raster image, not e.g. the
    XHTML cover page that some EPUBs incorrectly register as <meta name=
    "cover" content="...">."""
    if item is None:
        return False
    media_type = (getattr(item, "media_type", "") or "").lower()
    if media_type.startswith("image/"):
        return True
    # Belt-and-suspenders: some malformed EPUBs leave media_type blank.
    # Fall back to extension check.
    name = (item.get_name() if hasattr(item, "get_name") else "") or ""
    return Path(name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _iter_image_items(book):
    """Yield every manifest item whose media_type is an image. ebooklib
    classifies the EPUB-standard cover image as ITEM_COVER (type 10),
    not ITEM_IMAGE (type 1), so neither type alone is enough — go by
    media_type instead."""
    try:
        for item in book.get_items():
            mt = (getattr(item, "media_type", "") or "").lower()
            if mt.startswith("image/"):
                yield item
    except Exception:
        return


def _resolve_image_from_xhtml(book, xhtml_item):
    """Parse an XHTML cover page and return the image item it references.
    Many EPUBs register a Cover.xhtml page (id="cover") that links to the
    actual image via <img src="..."> instead of pointing the OPF cover
    meta at the image directly. Falls back through this when no image
    is reachable by id or filename heuristics."""
    try:
        from posixpath import dirname, normpath
        from urllib.parse import unquote
        soup = BeautifulSoup(xhtml_item.get_content(), "html.parser")
        tag = soup.find("img") or soup.find("svg image") or soup.find("image")
        if not tag:
            return None
        src = tag.get("src") or tag.get("href") or tag.get("xlink:href") or ""
        src = unquote(src).strip()
        if not src:
            return None
        xhtml_dir = dirname(xhtml_item.get_name() or "")
        target = src if src.startswith("/") else (
            normpath(xhtml_dir + "/" + src) if xhtml_dir else src
        )
        target = target.lstrip("/")
        for item in _iter_image_items(book):
            name = item.get_name() or ""
            if name == target or name.endswith("/" + target) or target.endswith("/" + name):
                return item
    except Exception:
        pass
    return None


def _save_epub_cover(book, file_path, cover_dir):
    cover_item = None
    # Strategy 0: ITEM_COVER — the EPUB-standard cover image type. When
    # the EPUB follows the spec (most modern ones), this is the right
    # answer in one line.
    try:
        for item in book.get_items_of_type(ITEM_COVER):
            if _is_image_item(item):
                cover_item = item
                break
    except Exception:
        pass
    # Strategy 1: <meta name="cover" content="image-id">
    cover_xhtml_fallback = None
    if not cover_item:
        try:
            cover_id = _opf_meta_by_name(book, "cover")
            if cover_id:
                candidate = book.get_item_with_id(cover_id)
                if _is_image_item(candidate):
                    cover_item = candidate
                elif candidate is not None:
                    cover_xhtml_fallback = candidate
        except Exception:
            pass
    # Strategy 2: manifest item with id="cover"
    if not cover_item:
        try:
            candidate = book.get_item_with_id("cover")
            if _is_image_item(candidate):
                cover_item = candidate
            elif candidate is not None and cover_xhtml_fallback is None:
                cover_xhtml_fallback = candidate
        except Exception:
            pass
    # Strategy 3: image with "cover" in filename. Iterate by media_type
    # rather than ITEM_IMAGE so ITEM_COVER-classified images aren't
    # accidentally excluded.
    if not cover_item:
        try:
            for item in _iter_image_items(book):
                name = (item.get_name() or "").lower()
                if "cover" in name:
                    cover_item = item
                    break
        except Exception:
            pass
    # Strategy 4: parse the XHTML cover page for <img src=> and look up
    # that image in the manifest. Catches EPUBs where the cover page
    # links to an image with a non-cover-y filename (e.g. ISBN-named).
    if not cover_item and cover_xhtml_fallback is not None:
        cover_item = _resolve_image_from_xhtml(book, cover_xhtml_fallback)
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


def extract_epub_cover_to_disk(file_path, cover_dir):
    """Public helper: open `file_path` with ebooklib and extract the cover
    into `cover_dir`. Returns the absolute on-disk path on success or None.

    Used by the cover route to self-heal when a cache file is missing or
    corrupted — keeps the EPUB-as-source-of-truth invariant the user
    expects ("covers live in the EPUB, they can't disappear")."""
    try:
        book = epub.read_epub(str(file_path))
    except Exception:
        return None
    return _save_epub_cover(book, file_path, cover_dir)


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
        "series": "", "series_index": "", "genres": "",
        "published_date": "",
        "cover_path": None,
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
        logger.warning("Could not read metadata from %s: %s", file_path, exc)
        warnings.append(_("Metadata reading failed: %(exc)s", exc=exc))
        meta = {}

    base.update({k: v for k, v in meta.items() if v not in (None, "")})

    # Always check the filename — the file's own title may be missing or
    # malformed (e.g. "Author, First - Title"), and the filename often carries
    # series info that the epub metadata lacks.
    fn_meta = _clean_title_from_filename(file_path.stem)

    if not base["title"]:
        base["title"] = fn_meta["title"]
        if base["source"] != "filename":
            warnings.append(_("Title is missing in the file's metadata — using filename."))
        base["source"] = "filename"

    if fn_meta.get("series") and not base.get("series"):
        base["series"] = fn_meta["series"]
    if fn_meta.get("series_index") and not base.get("series_index"):
        base["series_index"] = fn_meta["series_index"]

    # Strip series/marketing noise and any "Lastname, First - " author prefix
    # from the title, and promote any captured series info into the dedicated
    # fields when they're empty.
    if base["title"]:
        info = clean_title(base["title"])
        base["title"] = info["cleaned_title"]
        if info["extracted_series"] and not base.get("series"):
            base["series"] = info["extracted_series"]
        if info["extracted_series_index"] and not base.get("series_index"):
            base["series_index"] = info["extracted_series_index"]

    # If the file didn't declare a usable language, try to detect one from
    # the text body. EPUB/KEPUB only — ebooklib can't read MOBI/AZW3.
    if not base["language"] or base["language"].lower() in ("und", "unknown"):
        if extension in (".epub", ".kepub"):
            sample = extract_text_sample_from_epub(str(file_path))
            detected = detect_language_from_text(sample)
            if detected:
                base["language"] = detected
                logger.debug(
                    "Detected language %s for %s", detected, file_path.name
                )

    base["quality"] = _assess_quality(base)
    return base


def _extract_epub_metadata(file_path, cover_dir, warnings: list) -> dict:
    book = epub.read_epub(str(file_path))
    title = _first_metadata_value(book, "DC", "title")
    author = _collect_authors(book)
    description = _first_metadata_value(book, "DC", "description")
    isbn_raw = _first_metadata_value(book, "DC", "identifier")
    publisher = _first_metadata_value(book, "DC", "publisher")
    language = _first_metadata_value(book, "DC", "language")

    # Calibre-serie (vanligast)
    series = _opf_meta_by_name(book, "calibre:series") or ""
    series_index = _opf_meta_by_name(book, "calibre:series_index") or ""

    # EPUB3-fallback: belongs-to-collection
    if not series:
        series = _opf_meta_by_property(book, "belongs-to-collection") or ""
        if series:
            series_index = _opf_meta_by_property(book, "group-position") or ""

    series_index = normalize_series_index(series_index)

    published_date = ""
    try:
        dates = book.get_metadata("DC", "date") or []
        if dates:
            raw_date = (dates[0][0] or "").strip()
            published_date = raw_date[:10] if len(raw_date) >= 10 else raw_date
    except Exception:
        logger.debug("Could not read dc:date", exc_info=True)

    genres = ""
    try:
        subjects = book.get_metadata("DC", "subject") or []
        cleaned = [
            _clean_metadata_text(s[0]) for s in subjects if s and s[0]
        ]
        genres = ", ".join(c for c in cleaned if c)
    except Exception:
        logger.debug("Could not read dc:subject", exc_info=True)

    cover_path = None
    if cover_dir:
        cover_path = _save_epub_cover(book, file_path, cover_dir)

    # Normalize ISBN — strip non-digits (ebooklib often returns "urn:isbn:…")
    isbn = ""
    if isbn_raw:
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
        "series": series,
        "series_index": series_index,
        "genres": genres,
        "published_date": published_date,
        "cover_path": cover_path,
        "source": "ebooklib",
    }


def _extract_ebook_meta_metadata(file_path, warnings: list) -> dict:
    try:
        from app.services.metadata_calibre import read_all_ebook_meta_fields
        fields = read_all_ebook_meta_fields(file_path)
    except Exception as exc:
        warnings.append(_("ebook-meta failed: %(exc)s", exc=exc))
        return {"source": "filename"}

    if not fields:
        warnings.append(_("ebook-meta returned no fields."))
        return {"source": "filename"}

    pub = (fields.get("published") or fields.get("publishing date") or "").strip()

    # ebook-meta prints series as "Series : Name #N" (or just "Series : Name").
    series_raw = (fields.get("series") or "").strip()
    series = ""
    series_index = ""
    if series_raw:
        m = re.match(r"^(.+?)\s*#\s*(\d+(?:\.\d+)?)\s*$", series_raw)
        if m:
            series = m.group(1).strip()
            series_index = m.group(2)
        else:
            series = series_raw

    return {
        "title": fields.get("title") or "",
        "author": fields.get("author(s)") or "",
        "description": fields.get("comments") or "",
        "isbn": "",
        "publisher": fields.get("publisher") or "",
        "language": fields.get("languages") or "",
        "series": series,
        "series_index": series_index,
        "genres": fields.get("tags") or "",
        "published_date": pub[:10] if len(pub) >= 10 else pub,
        "cover_path": None,
        "source": "ebook-meta",
    }


def upsert_library_item(file_path, metadata: dict, existing=None, db_session=None) -> LibraryItem:
    """Create or update a LibraryItem from a normalized metadata dict.

    Text fields are always overwritten from the EPUB's embedded metadata
    on re-scan. The previous manual_metadata gate was removed — manual
    edits via the modal write back to the EPUB file (via ebook-meta), so
    re-reading from the file picks up the curated values, not the
    pre-edit ones. cover_locked is still honoured.

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
        if metadata.get("genres"):
            existing.genres = metadata["genres"]
        if metadata.get("published_date"):
            existing.published_date = metadata["published_date"]
        if metadata.get("cover_path") and not existing.cover_locked:
            existing.cover_path = metadata["cover_path"]

        if existing.title != old_title or existing.author != old_author or not existing.group_key:
            existing.group_key = compute_group_key(existing.title or "", existing.author or "")

        return existing

    item_title = metadata.get("title") or _clean_title_from_filename(file_path.stem)["title"]
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
        genres=metadata.get("genres") or None,
        published_date=metadata.get("published_date") or None,
        cover_path=metadata.get("cover_path"),
        file_path=absolute_path,
        file_name=file_path.name,
        extension=extension,
        size_bytes=size_bytes,
        file_mtime=file_mtime,
        metadata_read_at=now,
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

    touched_items = []

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
            logger.warning("Could not read metadata from %s, using filename", file_path)
            meta = {
                "title": _clean_title_from_filename(file_path.stem)["title"],
                "source": "filename", "quality": "minimal", "warnings": [],
            }

        item = upsert_library_item(file_path, meta, existing=existing, db_session=session)
        touched_items.append(item)

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

    # Flush so touched items get their IDs and group_keys before sync.
    session.flush()

    # Group sync: cross-enrich metadata within each affected format group.
    if touched_items:
        from collections import defaultdict
        from app.services.metadata_writer import sync_group_metadata

        affected_keys = {it.group_key for it in touched_items if it.group_key}
        if affected_keys:
            groups: dict = defaultdict(list)
            for item in session.query(LibraryItem).filter(
                LibraryItem.group_key.in_(affected_keys)
            ).all():
                groups[item.group_key].append(item)

            for members in groups.values():
                if len(members) > 1:
                    sync_group_metadata(members)

    session.commit()
    return result


def scan_library(library_dir, cover_dir=None) -> dict:
    summary = scan_directory(library_dir, cover_dir=cover_dir)
    summary.setdefault("skipped", 0)
    summary.setdefault("missing_folder", not Path(library_dir).exists())
    return summary
