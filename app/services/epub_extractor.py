import hashlib
import json
import os
import posixpath
import shutil
import zipfile
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)



HTML_EXTENSIONS = (".xhtml", ".html", ".htm", ".xht")


def clean_epub_internal_path(path):
    if not path:
        return None

    cleaned = unquote(str(path)).replace("\\", "/")
    cleaned = posixpath.normpath(cleaned)

    if cleaned in ["", "."]:
        return None

    if cleaned.startswith("/"):
        return None

    if cleaned == ".." or cleaned.startswith("../"):
        return None

    return cleaned


def safe_decode(raw_content):
    if isinstance(raw_content, str):
        return raw_content

    for encoding in ["utf-8", "utf-8-sig", "cp1252", "latin-1"]:
        try:
            return raw_content.decode(encoding)
        except Exception:
            continue

    return raw_content.decode("utf-8", errors="replace")


def local_name(tag):
    if not tag or not getattr(tag, "name", None):
        return ""

    return tag.name.split(":")[-1].lower()


def find_first_tag(soup, wanted_name):
    wanted_name = wanted_name.lower()
    return soup.find(lambda tag: local_name(tag) == wanted_name)


def find_all_tags(soup, wanted_name):
    wanted_name = wanted_name.lower()
    return soup.find_all(lambda tag: local_name(tag) == wanted_name)


def build_name_map(zip_file):
    name_map = {}

    for info in zip_file.infolist():
        safe_path = clean_epub_internal_path(info.filename)

        if not safe_path:
            continue

        name_map[safe_path] = info.filename

    return name_map


def zip_read(zip_file, name_map, wanted_path):
    safe_path = clean_epub_internal_path(wanted_path)

    if not safe_path:
        raise FileNotFoundError(wanted_path)

    actual_path = name_map.get(safe_path)

    if actual_path:
        return zip_file.read(actual_path)

    for known_safe_path, known_actual_path in name_map.items():
        if known_safe_path.lower() == safe_path.lower():
            return zip_file.read(known_actual_path)

    raise FileNotFoundError(wanted_path)


def safe_path_exists(name_map, wanted_path):
    wanted_path = wanted_path.lower()

    for safe_path in name_map.keys():
        if safe_path.lower() == wanted_path:
            return True

    return False


def get_existing_path_case_insensitive(name_map, wanted_path):
    wanted_path = wanted_path.lower()

    for safe_path in name_map.keys():
        if safe_path.lower() == wanted_path:
            return safe_path

    return None


def read_optional_file(zip_file, name_map, wanted_path):
    actual_safe_path = get_existing_path_case_insensitive(name_map, wanted_path)

    if not actual_safe_path:
        return None

    try:
        return zip_read(zip_file, name_map, actual_safe_path)
    except Exception:
        return None


def looks_like_reading_file(path):
    if not path:
        return False

    lower_path = path.lower()

    if not lower_path.endswith(HTML_EXTENSIONS):
        return False

    bad_names = [
        "nav.xhtml",
        "nav.html",
        "toc.xhtml",
        "toc.html",
        "contents.xhtml",
        "contents.html",
    ]

    for bad_name in bad_names:
        if lower_path.endswith(bad_name):
            return False

    return True


def looks_like_font_file(path):
    if not path:
        return False

    lower_path = path.lower()

    return lower_path.endswith((
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
    ))


def detect_blocking_drm(zip_file, name_map):
    if safe_path_exists(name_map, "META-INF/rights.xml"):
        return (
            True,
            "Den här EPUB-filen verkar vara DRM-skyddad/låst. Bookstation kan visa metadata och omslag, men själva boktexten är krypterad och kan därför inte läsas direkt.",
        )

    encryption_raw = read_optional_file(zip_file, name_map, "META-INF/encryption.xml")

    if not encryption_raw:
        return False, None

    encryption_text = safe_decode(encryption_raw)
    encryption_lower = encryption_text.lower()

    if "adobe" in encryption_lower or "adept" in encryption_lower:
        return (
            True,
            "Den här EPUB-filen verkar vara skyddad med Adobe/ADEPT DRM. Bookstation kan inte läsa själva boktexten utan att kringgå DRM.",
        )

    soup = BeautifulSoup(encryption_text, "xml")
    encrypted_paths = []

    for tag in soup.find_all(lambda t: local_name(t) == "cipherreference"):
        uri = tag.get("URI") or tag.get("uri")

        if not uri:
            continue

        safe_uri = clean_epub_internal_path(uri)

        if safe_uri:
            encrypted_paths.append(safe_uri)

    encrypted_reading_files = []

    for encrypted_path in encrypted_paths:
        lower_path = encrypted_path.lower()

        if looks_like_reading_file(lower_path):
            encrypted_reading_files.append(encrypted_path)

        if lower_path.endswith((".opf", ".ncx", ".xml")) and not looks_like_font_file(lower_path):
            encrypted_reading_files.append(encrypted_path)

    if encrypted_reading_files:
        return (
            True,
            "Den här EPUB-filen innehåller krypterade lässidor. Bookstation stoppar visningen så att du slipper rappakalja på skärmen.",
        )

    return False, None


def get_rootfile_path(zip_file, name_map):
    try:
        container_data = safe_decode(zip_read(zip_file, name_map, "META-INF/container.xml"))
        soup = BeautifulSoup(container_data, "xml")

        rootfile = find_first_tag(soup, "rootfile")

        if rootfile and rootfile.get("full-path"):
            return clean_epub_internal_path(rootfile.get("full-path"))

    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    for safe_path in name_map.keys():
        if safe_path.lower().endswith(".opf"):
            return safe_path

    return None


def normalize_epub_path(base_dir, href):
    href = unquote(str(href)).replace("\\", "/")
    return clean_epub_internal_path(posixpath.join(base_dir, href))


def get_spine_pages(zip_file, name_map):
    rootfile_path = get_rootfile_path(zip_file, name_map)

    if not rootfile_path:
        return []

    try:
        opf_data = safe_decode(zip_read(zip_file, name_map, rootfile_path))
        soup = BeautifulSoup(opf_data, "xml")

        base_dir = posixpath.dirname(rootfile_path)

        manifest_items = {}

        for item in find_all_tags(soup, "item"):
            item_id = item.get("id")
            href = item.get("href")
            media_type = item.get("media-type", "")

            if not item_id or not href:
                continue

            href_lower = href.lower()

            is_html = (
                "xhtml" in media_type
                or "html" in media_type
                or href_lower.endswith(HTML_EXTENSIONS)
            )

            if not is_html:
                continue

            full_path = normalize_epub_path(base_dir, href)

            if full_path:
                manifest_items[item_id] = full_path

        spine = find_first_tag(soup, "spine")

        if not spine:
            return []

        pages = []

        for itemref in find_all_tags(spine, "itemref"):
            idref = itemref.get("idref")

            if not idref:
                continue

            page_path = manifest_items.get(idref)

            if not page_path:
                continue

            if page_path not in name_map:
                continue

            if looks_like_reading_file(page_path):
                pages.append(page_path)

        return pages

    except Exception:
        return []


def detect_html_pages(name_map):
    pages = []

    for safe_path in name_map.keys():
        if looks_like_reading_file(safe_path):
            pages.append(safe_path)

    pages.sort()
    return pages


def is_probably_readable_html(raw_content):
    if not raw_content:
        return False

    text = safe_decode(raw_content)
    stripped = text.strip()
    lower = stripped.lower()

    if not stripped:
        return False

    replacement_count = stripped.count("\ufffd")

    if replacement_count > 20:
        return False

    html_markers = [
        "<html",
        "<body",
        "<p",
        "<div",
        "<section",
        "<article",
        "<h1",
        "<h2",
        "<span",
        "<?xml",
        "<!doctype",
    ]

    for marker in html_markers:
        if marker in lower:
            return True

    soup = BeautifulSoup(text, "html.parser")
    tags = soup.find_all(["html", "body", "p", "div", "section", "article", "span", "h1", "h2", "h3"])

    if len(tags) >= 2:
        return True

    return False


def detect_unreadable_pages(zip_file, name_map, pages):
    sample_pages = pages[:5]

    if not sample_pages:
        return False, None

    checked = 0
    unreadable = 0

    for page in sample_pages:
        try:
            raw_content = zip_read(zip_file, name_map, page)
        except Exception:
            continue

        checked += 1

        if not is_probably_readable_html(raw_content):
            unreadable += 1

    if checked > 0 and unreadable == checked:
        return (
            True,
            "Bookstation hittade sidor i EPUB-filen, men innehållet ser krypterat eller oläsbart ut. Därför visas inte boken som rappakalja.",
        )

    return False, None


def get_file_signature(file_path):
    stat = os.stat(file_path)
    source = f"{os.path.abspath(file_path)}|{stat.st_size}|{stat.st_mtime}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def get_epub_cache_dir(cache_base_dir, item_id):
    return Path(cache_base_dir) / str(item_id)


def safe_extract_all(zip_file, name_map, cache_dir):
    cache_root = Path(cache_dir).resolve()

    for safe_path, actual_path in name_map.items():
        try:
            info = zip_file.getinfo(actual_path)
        except Exception:
            continue

        if info.is_dir():
            continue

        target_path = (cache_root / safe_path).resolve()

        if not str(target_path).startswith(str(cache_root)):
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(target_path, "wb") as target_file:
                target_file.write(zip_file.read(actual_path))
        except Exception:
            continue


def load_cached_manifest(manifest_path, signature, cache_dir):
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)

        if manifest.get("signature") != signature:
            return None

        pages = manifest.get("pages", [])

        if not pages:
            return None

        for page in pages:
            page_path = (cache_dir / page).resolve()

            if not page_path.exists():
                return None

        return manifest

    except Exception:
        return None


def prepare_epub(item, cache_base_dir):
    if not os.path.exists(item.file_path):
        return {
            "ok": False,
            "pages": [],
            "error": "EPUB-filen finns inte längre på disken.",
        }

    cache_dir = get_epub_cache_dir(cache_base_dir, item.id)
    manifest_path = cache_dir / "bookstation_manifest.json"
    signature = get_file_signature(item.file_path)

    try:
        with zipfile.ZipFile(item.file_path, "r") as zip_file:
            name_map = build_name_map(zip_file)

            drm_detected, drm_message = detect_blocking_drm(zip_file, name_map)

            if drm_detected:
                return {
                    "ok": False,
                    "pages": [],
                    "error": drm_message,
                }

            cached_manifest = load_cached_manifest(manifest_path, signature, cache_dir)

            if cached_manifest:
                return {
                    "ok": True,
                    "pages": cached_manifest.get("pages", []),
                    "error": None,
                }

            if cache_dir.exists():
                shutil.rmtree(cache_dir)

            cache_dir.mkdir(parents=True, exist_ok=True)

            safe_extract_all(zip_file, name_map, cache_dir)

            pages = get_spine_pages(zip_file, name_map)

            if not pages:
                pages = detect_html_pages(name_map)

            if not pages:
                return {
                    "ok": False,
                    "pages": [],
                    "error": "Bookstation hittade inga läsbara HTML/XHTML-sidor i EPUB-filen.",
                }

            unreadable_detected, unreadable_message = detect_unreadable_pages(zip_file, name_map, pages)

            if unreadable_detected:
                return {
                    "ok": False,
                    "pages": [],
                    "error": unreadable_message,
                }

            manifest = {
                "signature": signature,
                "pages": pages,
            }

            with open(manifest_path, "w", encoding="utf-8") as manifest_file:
                json.dump(manifest, manifest_file, indent=2, ensure_ascii=False)

            return {
                "ok": True,
                "pages": pages,
                "error": None,
            }

    except zipfile.BadZipFile:
        return {
            "ok": False,
            "pages": [],
            "error": "Den här filen är inte en riktig EPUB eller så är den skadad.",
        }

    except Exception as error:
        return {
            "ok": False,
            "pages": [],
            "error": f"Bookstation kunde inte packa upp EPUB-filen: {error}",
        }
