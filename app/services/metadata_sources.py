# Colophon – e-book metadata manager
import hashlib
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask_babel import gettext as _
import logging

logger = logging.getLogger(__name__)



load_dotenv()

USER_AGENT = "Colophon/0.1 Google Books metadata"
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
    from app.services.app_settings import get_setting
    return (get_setting("GOOGLE_BOOKS_KEY") or "").strip()


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

    categories = info.get("categories", [])
    if isinstance(categories, list):
        genres = ", ".join(clean_text(c) for c in categories if clean_text(c))
    else:
        genres = clean_text(categories)

    published_date = clean_text(info.get("publishedDate", ""))[:10]

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
        "genres": genres,
        "published_date": published_date,
    }

    fields_found = []
    if result["title"]: fields_found.append("title")
    if result["author"]: fields_found.append("author")
    if result["description"]: fields_found.append("description")
    if result["isbn"]: fields_found.append("isbn")
    if result["publisher"]: fields_found.append("publisher")
    if result["cover_url"]: fields_found.append("cover")
    if result["genres"]: fields_found.append("genres")
    if result["published_date"]: fields_found.append("published_date")
    result["fields_found"] = fields_found

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


def score_metadata_result_explained(item, result) -> dict:
    """Compute score and expose individual scoring signals plus warnings.

    Extends score_metadata_result() without changing its return value.
    Scoring scale (max ~160):
        ISBN exact match        +80
        title similarity        × 45
        author similarity       × 25  (only when both sides have author)
        has description         +5
        has cover URL           +5

    Batch classification thresholds (see classify_enrichment_result):
        >= 90 + ISBN match  →  auto_apply candidate
        50–89               →  review_needed
        40–49               →  manual_only
        < 40                →  no_match

    Returns dict with keys: score, signals, warnings
    """
    item_isbn = normalize_isbn(item.isbn or "")
    result_isbn = normalize_isbn(result.get("isbn", ""))

    isbn_exact_match = bool(item_isbn and result_isbn and item_isbn == result_isbn)
    title_sim = similarity(item.title or "", result.get("title", ""))
    author_sim = similarity(item.author or "", result.get("author", ""))
    has_description = bool(result.get("description"))
    has_cover = bool(result.get("cover_url"))

    score = 0.0
    if isbn_exact_match:
        score += 80
    score += title_sim * 45
    if item.author and result.get("author"):
        score += author_sim * 25
    if has_description:
        score += 5
    if has_cover:
        score += 5

    warnings = []
    item_lang = (getattr(item, "language", None) or "").strip().lower()
    result_lang = (result.get("language") or "").strip().lower()
    if item_lang and result_lang and item_lang != result_lang:
        warnings.append(_("Language differs from current metadata"))
    if isbn_exact_match and title_sim < 0.7:
        warnings.append(_("ISBN matches but the title differs"))
    if not result.get("author"):
        warnings.append(_("Author missing in the match"))
    if not result.get("isbn"):
        warnings.append(_("ISBN missing in the match"))

    return {
        "score": round(score, 1),
        "signals": {
            "isbn_exact_match": isbn_exact_match,
            "title_similarity": round(title_sim, 2),
            "author_similarity": round(author_sim, 2),
            "has_description": has_description,
            "has_cover": has_cover,
        },
        "warnings": warnings,
    }


def classify_enrichment_result(score: float, signals: dict) -> str:
    """Map a score + signals to a batch-apply policy classification.

    Returns one of:
        auto_apply    — score >= 90 AND ISBN exact match; safe for optional
                        batch auto-apply when user has enabled it
        review_needed — score 50-89, or score >= 90 without ISBN confirmation
        manual_only   — score 40-49; show in manual preview, do not auto-apply
        no_match      — score < 40; treat as no reliable match
    """
    if score < 40:
        return "no_match"
    if score < 50:
        return "manual_only"
    if score >= 90 and signals.get("isbn_exact_match"):
        return "auto_apply"
    return "review_needed"


def choose_best_metadata_explained(item, results, minimum_score=40) -> dict:
    """Like choose_best_metadata() but returns full scoring explanation.

    Returns dict with keys:
        best            dict | None  — best candidate
        score           float
        signals         dict         — from score_metadata_result_explained
        warnings        list[str]
        classification  str          — from classify_enrichment_result
        all_scored      list[dict]   — every candidate with score/signals/warnings
    """
    if not results:
        return {
            "best": None, "score": 0.0,
            "signals": {}, "warnings": [],
            "classification": "no_match", "all_scored": [],
        }

    all_scored = []
    for candidate in results:
        explained = score_metadata_result_explained(item, candidate)
        all_scored.append({
            "candidate": candidate,
            "score": explained["score"],
            "signals": explained["signals"],
            "warnings": explained["warnings"],
            "classification": classify_enrichment_result(
                explained["score"], explained["signals"]
            ),
        })

    all_scored.sort(key=lambda x: x["score"], reverse=True)
    top = all_scored[0]

    if top["score"] < minimum_score:
        return {
            "best": None,
            "score": top["score"],
            "signals": top["signals"],
            "warnings": top["warnings"],
            "classification": "no_match",
            "all_scored": all_scored,
        }

    return {
        "best": top["candidate"],
        "score": top["score"],
        "signals": top["signals"],
        "warnings": top["warnings"],
        "classification": top["classification"],
        "all_scored": all_scored,
    }


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
                "note": _("Cover from Google Books API"),
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


# ---------------------------------------------------------------------------
# Structured source results (Phase 5)
# ---------------------------------------------------------------------------

def google_books_search_with_status(
    query_text="", title="", author="", isbn=""
) -> dict:
    """Run a Google Books search and return a structured source result.

    The returned dict always contains:
        source       "google_books"
        ok           bool
        status       ok | no_result | network_or_plugin_error
        duration_ms  int
        message      str
        candidates   list[dict]
        raw_debug    {returncode, stderr_excerpt}
    """
    t0 = time.monotonic()

    def _result(ok, status, message, candidates=None):
        return {
            "source": "google_books",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    try:
        candidates = google_books_search(
            query_text=query_text, title=title, author=author, isbn=isbn
        )
    except Exception as exc:
        return _result(
            False, "network_or_plugin_error",
            _("Google Books: network error (%(exc)s).", exc=exc),
        )

    if candidates:
        n = len(candidates)
        return _result(
            True, "ok",
            _("Google Books: %(count)d hits.", count=n),
            candidates=candidates,
        )

    return _result(False, "no_result", _("Google Books: no hits."))


def search_all_sources_with_status(
    title="",
    author="",
    isbn="",
    query_text="",
    include_calibre=True,
) -> dict:
    """Search all sources and return both candidates and per-source statuses.

    A failure in one source never hides results from another.

    Returns:
        candidates     list[dict]   — merged, deduplicated candidates for scoring
        source_results list[dict]   — one structured status dict per source
    """
    from app.services.metadata_calibre import fetch_calibre_metadata_with_status

    source_results = []

    google_sr = google_books_search_with_status(
        query_text=query_text, title=title, author=author, isbn=isbn
    )
    source_results.append(google_sr)

    if include_calibre:
        calibre_sr = fetch_calibre_metadata_with_status(title=title, author=author)
        source_results.append(calibre_sr)

    all_candidates = []
    for sr in source_results:
        all_candidates.extend(sr.get("candidates", []))

    return {
        "candidates": deduplicate_results(all_candidates),
        "source_results": source_results,
    }
