"""
Cover search service — cascading search across multiple cover sources.
All sources are optional; unconfigured sources are silently skipped.
"""

import logging

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds per external request


def search_covers(title="", author="", isbn=""):
    """Search all available cover sources. Returns list of dicts:
    [{"source": str, "cover_url": str, "thumbnail_url": str, "note": str,
      "width": int|None, "height": int|None}]
    """
    from app.services.app_settings import get_setting

    candidates = []

    # 1. Open Library (ISBN required, no key)
    if _is_enabled(get_setting, "COVER_OPENLIBRARY_ENABLED"):
        candidates.extend(_search_openlibrary(isbn))

    # 2. Google Books zoom trick (no key required)
    if _is_enabled(get_setting, "COVER_GOOGLE_ZOOM_ENABLED"):
        candidates.extend(_search_google_books_zoom(title, author, isbn))

    # 3. Hardcover API (optional token)
    candidates.extend(_search_hardcover(title, author, isbn, get_setting))

    # 4. LibraryThing (optional dev key)
    candidates.extend(_search_librarything(isbn, get_setting))

    # 5. Wikidata / Wikimedia Commons (no key)
    if _is_enabled(get_setting, "COVER_WIKIDATA_ENABLED"):
        candidates.extend(_search_wikidata(title, author, isbn))

    # 6. DuckDuckGo image search (no key, last fallback)
    if _is_enabled(get_setting, "COVER_DDGS_ENABLED"):
        candidates.extend(_search_ddgs(title, author, isbn))

    return _deduplicate(candidates)


def _is_enabled(get_setting, key):
    return (get_setting(key, "true") or "true").lower() == "true"


# ---------------------------------------------------------------------------
# 1. Open Library Covers
# ---------------------------------------------------------------------------
def _search_openlibrary(isbn):
    if not isbn:
        return []
    clean = isbn.replace("-", "").strip()
    if not clean:
        return []
    candidates = []
    for size, label in [("L", "Stor"), ("M", "Medium")]:
        url = f"https://covers.openlibrary.org/b/isbn/{clean}-{size}.jpg"
        try:
            resp = requests.head(url, timeout=_TIMEOUT, allow_redirects=True)
            if resp.ok:
                cl = int(resp.headers.get("Content-Length", 0))
                if cl > 1000:
                    candidates.append({
                        "source": "Open Library",
                        "cover_url": url,
                        "thumbnail_url": f"https://covers.openlibrary.org/b/isbn/{clean}-S.jpg",
                        "note": f"Open Library ({label})",
                        "width": None, "height": None,
                    })
                    break  # Take largest available
        except requests.RequestException:
            continue
    return candidates


# ---------------------------------------------------------------------------
# 2. Google Books zoom trick
# ---------------------------------------------------------------------------
def _search_google_books_zoom(title, author, isbn):
    from app.services.metadata_sources import google_books_search
    query_parts = [p for p in [isbn, title, author] if p]
    query_text = " ".join(query_parts).strip()
    if not query_text:
        return []
    try:
        results = google_books_search(
            query_text=query_text,
            title=title or "", author=author or "", isbn=isbn or "",
        )
    except Exception as exc:
        logger.warning("Google Books zoom search error: %s", exc)
        return []
    candidates = []
    for result in results:
        cover_url = result.get("cover_url", "")
        if not cover_url:
            continue
        full_url = cover_url.replace("&zoom=1", "&zoom=0").replace("&zoom=5", "&zoom=0")
        full_url = full_url.replace("http://", "https://")
        thumb = cover_url.replace("http://", "https://")
        candidates.append({
            "source": "Google Books",
            "cover_url": full_url,
            "thumbnail_url": thumb,
            "note": f"Google Books — {result.get('title', '')}",
            "width": None, "height": None,
        })
    return candidates[:5]


# ---------------------------------------------------------------------------
# 3. Hardcover API (GraphQL)
# ---------------------------------------------------------------------------
def _search_hardcover(title, author, isbn, get_setting):
    """Query Hardcover's public GraphQL API for cover images."""
    token = (get_setting("HARDCOVER_API_TOKEN") or "").strip()

    if isbn:
        query_str = isbn.replace("-", "")
    elif title:
        query_str = f"{title} {author}".strip()
    else:
        return []

    graphql_query = """
    query SearchBooks($query: String!) {
      search(query: $query, query_type: "books", per_page: 3) {
        results {
          ... on Book {
            title
            image { url }
            contributions { author { name } }
          }
        }
      }
    }
    """

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.post(
            "https://api.hardcover.app/v1/graphql",
            json={"query": graphql_query, "variables": {"query": query_str}},
            headers=headers,
            timeout=_TIMEOUT,
        )
        if not resp.ok:
            logger.warning("Hardcover HTTP %s", resp.status_code)
            return []
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("Hardcover error: %s", exc)
        return []
    except (ValueError, KeyError):
        return []

    candidates = []
    try:
        results = data.get("data", {}).get("search", {}).get("results", [])
        for book in results:
            if not isinstance(book, dict):
                continue
            image = book.get("image") or {}
            url = image.get("url", "")
            if not url:
                continue
            book_title = book.get("title", "")
            candidates.append({
                "source": "Hardcover",
                "cover_url": url,
                "thumbnail_url": url,
                "note": f"Hardcover — {book_title}",
                "width": None, "height": None,
            })
    except Exception as exc:
        logger.warning("Hardcover parse error: %s", exc)

    return candidates[:3]


# ---------------------------------------------------------------------------
# 4. LibraryThing Covers
# ---------------------------------------------------------------------------
def _search_librarything(isbn, get_setting):
    """LibraryThing cover lookup. Requires dev key and ISBN."""
    key = (get_setting("LIBRARYTHING_DEV_KEY") or "").strip()
    if not key or not isbn:
        return []
    clean = isbn.replace("-", "").strip()
    if not clean:
        return []

    url = f"https://covers.librarything.com/devkey/{key}/large/isbn/{clean}"
    try:
        resp = requests.head(url, timeout=_TIMEOUT, allow_redirects=True)
        if resp.ok:
            cl = int(resp.headers.get("Content-Length", 0))
            if cl > 1000:  # Skip 1x1 placeholder GIFs
                return [{
                    "source": "LibraryThing",
                    "cover_url": url,
                    "thumbnail_url": f"https://covers.librarything.com/devkey/{key}/small/isbn/{clean}",
                    "note": "LibraryThing",
                    "width": None, "height": None,
                }]
    except requests.RequestException:
        pass
    return []


# ---------------------------------------------------------------------------
# 5. Wikidata / Wikimedia Commons
# ---------------------------------------------------------------------------
def _search_wikidata(title, author, isbn):
    """Search Wikidata for books with cover images on Wikimedia Commons."""
    if not isbn and not title:
        return []

    if isbn:
        clean = isbn.replace("-", "").strip()
        filter_clause = f'?item wdt:P212 "{clean}".'
    else:
        # Title-based search is unreliable via SPARQL; skip
        return []

    sparql = f"""
    SELECT ?item ?itemLabel ?image WHERE {{
      {filter_clause}
      ?item wdt:P18 ?image.
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,sv". }}
    }} LIMIT 1
    """

    try:
        resp = requests.get(
            "https://query.wikidata.org/sparql",
            params={"query": sparql, "format": "json"},
            headers={"User-Agent": "Colophon/1.0 (book metadata manager)"},
            timeout=_TIMEOUT,
        )
        if not resp.ok:
            return []
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    candidates = []
    for binding in data.get("results", {}).get("bindings", []):
        image_url = binding.get("image", {}).get("value", "")
        label = binding.get("itemLabel", {}).get("value", "")
        if not image_url:
            continue
        thumb_url = image_url
        if "Special:FilePath" in image_url:
            thumb_url = image_url + "?width=300"
        candidates.append({
            "source": "Wikimedia Commons",
            "cover_url": image_url,
            "thumbnail_url": thumb_url,
            "note": f"Wikidata — {label}",
            "width": None, "height": None,
        })

    return candidates[:2]


# ---------------------------------------------------------------------------
# 6. DuckDuckGo image search (no-key fallback)
# ---------------------------------------------------------------------------
def _search_ddgs(title, author, isbn):
    """Last-resort image search via DuckDuckGo. No API key needed."""
    query_parts = []
    if title:
        query_parts.append(title)
    if author:
        query_parts.append(author)
    query_parts.append("book cover")
    query = " ".join(query_parts).strip()
    if not query or query == "book cover":
        return []

    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=5))
    except ImportError:
        logger.info("ddgs package not installed — skipping DuckDuckGo fallback")
        return []
    except Exception as exc:
        logger.warning("DuckDuckGo image search error: %s", exc)
        return []

    candidates = []
    for r in results:
        image_url = r.get("image", "")
        thumb_url = r.get("thumbnail", "") or image_url
        img_title = r.get("title", "")
        if not image_url:
            continue
        candidates.append({
            "source": "DuckDuckGo",
            "cover_url": image_url,
            "thumbnail_url": thumb_url,
            "note": f"DuckDuckGo — {img_title[:80]}",
            "width": r.get("width"),
            "height": r.get("height"),
        })

    return candidates


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
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
