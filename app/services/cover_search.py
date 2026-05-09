"""
Cover search service — multiple sources, deduplicated by URL.
Sources are tried in order; each returns a list of candidate dicts.
"""

import logging

import requests

from app.services.app_settings import get_setting

logger = logging.getLogger(__name__)


def search_covers(title="", author="", isbn=""):
    """Search all configured cover sources.

    Returns list of:
      {"source": str, "cover_url": str, "thumbnail_url": str,
       "note": str, "width": int|None, "height": int|None}
    """
    candidates = []

    if (get_setting("COVER_OPENLIBRARY_ENABLED", "true") or "true").lower() == "true":
        candidates.extend(_search_openlibrary(isbn))

    if (get_setting("COVER_GOOGLE_ZOOM_ENABLED", "true") or "true").lower() == "true":
        candidates.extend(_search_google_books_zoom(title, author, isbn))

    cse_key = (get_setting("GOOGLE_CSE_API_KEY") or "").strip()
    cse_id = (get_setting("GOOGLE_CSE_ID") or "").strip()
    if cse_key and cse_id:
        candidates.extend(_search_google_cse(title, author, isbn, cse_key, cse_id))

    bing_key = (get_setting("BING_API_KEY") or "").strip()
    if bing_key:
        candidates.extend(_search_bing(title, author, isbn, bing_key))

    return _deduplicate(candidates)


# ---------------------------------------------------------------------------
# Source implementations
# ---------------------------------------------------------------------------

def _search_openlibrary(isbn):
    """Direct URL-based lookup via ISBN. HEAD-checks that the image is real."""
    if not isbn:
        return []

    clean_isbn = isbn.replace("-", "").strip()
    if not clean_isbn:
        return []

    for size, label in [("L", "Stor"), ("M", "Medium")]:
        url = f"https://covers.openlibrary.org/b/isbn/{clean_isbn}-{size}.jpg"
        try:
            resp = requests.head(url, timeout=5, allow_redirects=True)
            if not resp.ok:
                continue
            content_length = int(resp.headers.get("Content-Length", 0))
            if content_length < 1000:
                continue
            return [{
                "source": "Open Library",
                "cover_url": url,
                "thumbnail_url": f"https://covers.openlibrary.org/b/isbn/{clean_isbn}-S.jpg",
                "note": f"Open Library ({label})",
                "width": None,
                "height": None,
            }]
        except requests.RequestException:
            continue

    return []


def _search_google_books_zoom(title, author, isbn):
    """Google Books search with full-size URL upgrade."""
    from app.services.metadata_sources import google_books_search

    parts = []
    if isbn:
        parts.append(isbn)
    if title:
        parts.append(title)
    if author:
        parts.append(author)
    query_text = " ".join(parts).strip()
    if not query_text:
        return []

    try:
        results = google_books_search(
            query_text=query_text,
            title=title,
            author=author,
            isbn=isbn or "",
        )
    except Exception as exc:
        logger.warning("Google Books search error: %s", exc)
        return []

    candidates = []
    for result in results:
        cover_url = result.get("cover_url", "")
        if not cover_url:
            continue

        # Zoom trick: zoom=1/5 → zoom=0 for the highest resolution
        full_url = cover_url.replace("&zoom=1", "&zoom=0").replace("&zoom=5", "&zoom=0")
        full_url = full_url.replace("http://", "https://")
        thumbnail_url = cover_url.replace("http://", "https://")

        candidates.append({
            "source": "Google Books",
            "cover_url": full_url,
            "thumbnail_url": thumbnail_url,
            "note": f"Google Books — {result.get('title', '')}",
            "width": None,
            "height": None,
        })

    return candidates[:5]


def _search_google_cse(title, author, isbn, api_key, cse_id):
    """Image search via Google Custom Search API."""
    parts = []
    if title:
        parts.append(title)
    if author:
        parts.append(author)
    parts.append("book cover")
    query = " ".join(parts).strip()

    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cse_id,
                "q": query,
                "searchType": "image",
                "num": 5,
                "imgSize": "large",
                "safe": "active",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning("Google CSE HTTP %s", resp.status_code)
            return []
        items = resp.json().get("items", [])
    except requests.RequestException as exc:
        logger.warning("Google CSE error: %s", exc)
        return []

    candidates = []
    for item in items:
        image = item.get("image", {})
        url = item.get("link", "")
        if not url:
            continue
        candidates.append({
            "source": "Google bildsökning",
            "cover_url": url,
            "thumbnail_url": image.get("thumbnailLink", "") or url,
            "note": (item.get("title") or "")[:100],
            "width": image.get("width"),
            "height": image.get("height"),
        })
    return candidates


def _search_bing(title, author, isbn, api_key):
    """Image search via Bing Image Search API v7."""
    parts = []
    if title:
        parts.append(title)
    if author:
        parts.append(author)
    parts.append("book cover")
    query = " ".join(parts).strip()

    try:
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/images/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={
                "q": query,
                "count": 5,
                "imageType": "Photo",
                "safeSearch": "Moderate",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning("Bing Image Search HTTP %s", resp.status_code)
            return []
        values = resp.json().get("value", [])
    except requests.RequestException as exc:
        logger.warning("Bing error: %s", exc)
        return []

    candidates = []
    for item in values:
        url = item.get("contentUrl", "")
        if not url:
            continue
        candidates.append({
            "source": "Bing bildsökning",
            "cover_url": url,
            "thumbnail_url": item.get("thumbnailUrl", "") or url,
            "note": (item.get("name") or "")[:100],
            "width": item.get("width"),
            "height": item.get("height"),
        })
    return candidates


def _deduplicate(candidates):
    seen = set()
    unique = []
    for c in candidates:
        url = c.get("cover_url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(c)
    return unique
