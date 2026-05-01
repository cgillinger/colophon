import hashlib
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)



load_dotenv()

USER_AGENT = "Bookstation/0.1 Google Books metadata"
TIMEOUT = 16


def clean_text(value):
    if not value:
        return ""

    value = str(value)

    if "<" in value and ">" in value:
        soup = BeautifulSoup(value, "html.parser")
        value = soup.get_text(" ", strip=True)

    return " ".join(value.split()).strip()


def normalize_isbn(value):
    if not value:
        return ""

    return re.sub(r"[^0-9Xx]", "", str(value)).upper()


def normalize_compare(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-zåäö0-9]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split()).strip()


def get_google_books_key():
    return os.environ.get("BOOKSTATION_GOOGLE_BOOKS_KEY", "").strip()


def safe_get_json(url, params=None):
    try:
        headers = {
            "User-Agent": USER_AGENT,
        }

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


def pick_best_isbn(identifiers):
    if not identifiers:
        return ""

    isbn_13 = ""
    isbn_10 = ""

    for item in identifiers:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "")
        item_value = normalize_isbn(item.get("identifier", ""))

        if item_type == "ISBN_13" and item_value:
            isbn_13 = item_value

        if item_type == "ISBN_10" and item_value:
            isbn_10 = item_value

    return isbn_13 or isbn_10


def google_books_image_url(image_links):
    if not isinstance(image_links, dict):
        return ""

    cover_url = (
        image_links.get("extraLarge")
        or image_links.get("large")
        or image_links.get("medium")
        or image_links.get("small")
        or image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or ""
    )

    cover_url = clean_text(cover_url)

    if cover_url.startswith("http://"):
        cover_url = "https://" + cover_url[len("http://"):]

    return cover_url


def result_from_google_volume(volume):
    if not isinstance(volume, dict):
        return None

    info = volume.get("volumeInfo", {})

    if not isinstance(info, dict):
        return None

    title = clean_text(info.get("title", ""))

    subtitle = clean_text(info.get("subtitle", ""))

    if subtitle and subtitle.lower() not in title.lower():
        title = clean_text(f"{title}: {subtitle}")

    if not title:
        return None

    authors = info.get("authors", [])

    if isinstance(authors, list):
        author = ", ".join([clean_text(row) for row in authors if clean_text(row)])
    else:
        author = clean_text(authors)

    result = {
        "source": "Google Books API",
        "title": title,
        "author": author,
        "description": clean_text(info.get("description", "")),
        "isbn": pick_best_isbn(info.get("industryIdentifiers", [])),
        "publisher": clean_text(info.get("publisher", "")),
        "language": clean_text(info.get("language", "")),
        "series": "",
        "series_index": "",
        "cover_url": google_books_image_url(info.get("imageLinks", {})),
    }

    return result


def is_google_books_url(value):
    value = clean_text(value)

    if not value.startswith(("http://", "https://")):
        return False

    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except Exception:
        return False

    return (
        "google." in host
        or host == "books.google.com"
        or host == "www.books.google.com"
    ) and "/books" in path


def extract_google_books_volume_id(value):
    value = clean_text(value)

    try:
        parsed = urlparse(value)
    except Exception:
        return ""

    query = parse_qs(parsed.query or "")

    if "id" in query and query["id"]:
        return clean_text(query["id"][0])

    parts = [part for part in parsed.path.split("/") if part]

    if "edition" in parts:
        index = parts.index("edition")

        if len(parts) > index + 2:
            return clean_text(parts[index + 2])

    if parts:
        candidate = clean_text(parts[-1])

        if re.match(r"^[A-Za-z0-9_-]{6,}$", candidate):
            return candidate

    return ""


def google_books_volume_search(volume_id):
    volume_id = clean_text(volume_id)

    if not volume_id:
        return []

    params = {}

    google_key = get_google_books_key()

    if google_key:
        params["key"] = google_key

    data = safe_get_json(
        f"https://www.googleapis.com/books/v1/volumes/{volume_id}",
        params=params,
    )

    if not data:
        return []

    result = result_from_google_volume(data)

    if not result:
        return []

    return [result]


def google_books_search(query_text="", title="", author="", isbn=""):
    results = []

    query_text = clean_text(query_text)

    if is_google_books_url(query_text):
        volume_id = extract_google_books_volume_id(query_text)
        return google_books_volume_search(volume_id)

    isbn_value = normalize_isbn(isbn) or normalize_isbn(query_text)

    if isbn_value:
        q = f"isbn:{isbn_value}"
    elif query_text:
        q = query_text
    else:
        parts = []

        if title:
            parts.append(f"intitle:{title}")

        if author:
            parts.append(f"inauthor:{author}")

        q = " ".join(parts).strip()

    if not q:
        return results

    params = {
        "q": q,
        "maxResults": 20,
        "printType": "books",
    }

    google_key = get_google_books_key()

    if google_key:
        params["key"] = google_key

    data = safe_get_json(
        "https://www.googleapis.com/books/v1/volumes",
        params=params,
    )

    if not data:
        return results

    for volume in data.get("items", []):
        result = result_from_google_volume(volume)

        if result:
            results.append(result)

    return deduplicate_results(results)


def deduplicate_results(results):
    seen = set()
    unique_results = []

    for result in results:
        key = (
            result.get("source", "").lower(),
            result.get("title", "").lower(),
            result.get("author", "").lower(),
            result.get("isbn", "").lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        unique_results.append(result)

    return unique_results


def extension_from_content_type(content_type):
    content_type = (content_type or "").lower()

    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"

    if "png" in content_type:
        return ".png"

    if "webp" in content_type:
        return ".webp"

    return ".jpg"


def extension_from_url(url):
    try:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()

        if suffix in [".jpg", ".jpeg", ".png", ".webp"]:
            return suffix
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    return ""


def download_cover_to_file(cover_url, cover_dir, item_id):
    cover_url = clean_text(cover_url)

    if not cover_url:
        return None

    if not cover_url.startswith(("http://", "https://")):
        return None

    try:
        response = requests.get(
            cover_url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

        content_type = response.headers.get("Content-Type", "")

        if "image" not in content_type.lower():
            return None

        extension = (
            extension_from_url(response.url)
            or extension_from_url(cover_url)
            or extension_from_content_type(content_type)
        )

        cover_dir_path = Path(cover_dir)
        cover_dir_path.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha1(cover_url.encode("utf-8")).hexdigest()[:16]
        cover_filename = f"google_cover_{item_id}_{digest}{extension}"
        cover_path = cover_dir_path / cover_filename

        total_bytes = 0
        max_bytes = 12 * 1024 * 1024

        with open(cover_path, "wb") as cover_file:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue

                total_bytes += len(chunk)

                if total_bytes > max_bytes:
                    try:
                        os.remove(cover_path)
                    except Exception:
                        logger.debug("Tystat fel ignorerat", exc_info=True)
                    return None

                cover_file.write(chunk)

        if total_bytes < 500:
            try:
                os.remove(cover_path)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)
            return None

        return str(cover_path.resolve())

    except Exception:
        return None


def similarity(a, b):
    a = normalize_compare(a)
    b = normalize_compare(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def score_metadata_result(item, result):
    score = 0.0

    item_isbn = normalize_isbn(item.isbn or "")
    result_isbn = normalize_isbn(result.get("isbn", ""))

    if item_isbn and result_isbn and item_isbn == result_isbn:
        score += 80

    title_score = similarity(item.title or "", result.get("title", ""))
    author_score = similarity(item.author or "", result.get("author", ""))

    score += title_score * 45

    if item.author and result.get("author"):
        score += author_score * 25

    if result.get("description"):
        score += 5

    if result.get("cover_url"):
        score += 5

    return round(score, 1)


def choose_best_metadata(item, results, minimum_score=40):
    if not results:
        return None, 0

    scored = []

    for result in results:
        score = score_metadata_result(item, result)
        scored.append((score, result))

    scored.sort(key=lambda row: row[0], reverse=True)

    best_score, best_result = scored[0]

    if best_score < minimum_score:
        return None, best_score

    return best_result, best_score


def search_cover_candidates(item):
    candidates = []

    query_parts = []

    if item.isbn:
        query_parts.append(item.isbn)

    if item.title:
        query_parts.append(item.title)

    if item.author:
        query_parts.append(item.author)

    query_text = " ".join(query_parts).strip()

    results = google_books_search(
        query_text=query_text,
        title=item.title or "",
        author=item.author or "",
        isbn=item.isbn or "",
    )

    for result in results:
        cover_url = result.get("cover_url", "")

        if not cover_url:
            continue

        candidates.append(
            {
                "source": result.get("source", "Google Books API"),
                "title": result.get("title", item.title or ""),
                "cover_url": cover_url,
                "note": "Omslag från Google Books API",
            }
        )

    seen = set()
    unique = []

    for candidate in candidates:
        url = candidate.get("cover_url", "")

        if not url or url in seen:
            continue

        seen.add(url)
        unique.append(candidate)

    return unique[:40]


def search_all_sources(
    title="",
    author="",
    isbn="",
    query_text="",
    include_calibre=True,
):
    """Search every available metadata source and return a combined list.

    Sources currently queried:
        1. Google Books API
        2. Calibre plugins via fetch-ebook-metadata (if installed)

    Each result-dict has the standard schema:
        source, title, author, description, isbn, publisher, language,
        series, series_index, cover_url
    """
    results = []

    google_results = google_books_search(
        query_text=query_text,
        title=title,
        author=author,
        isbn=isbn,
    )
    if google_results:
        results.extend(google_results)

    if include_calibre:
        from app.services.metadata_calibre import fetch_calibre_metadata

        calibre_results = fetch_calibre_metadata(title=title, author=author)
        if calibre_results:
            results.extend(calibre_results)

    return deduplicate_results(results)
