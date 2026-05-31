# Colophon – e-book metadata manager
"""Hardcover metadata source.

Hardcover (https://hardcover.app) exposes an official GraphQL API. Its book
search returns Typesense documents that already carry the fields Colophon's
weakest sources lack — most importantly **series** and genres — plus a clean
synopsis, cover and rating for popular/English titles. This is the robust
successor to the dead Goodreads API.

A token (METADATA token / Cover-search Hardcover token) gives better rate
limits but the API also answers anonymously. The cover-only client already
lives in services/cover_search.py:_search_hardcover; this module parses the
*full* document into the standard candidate schema for the field-level merge.
"""
import logging
import time

import requests
from flask_babel import gettext as _

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_ENDPOINT = "https://api.hardcover.app/v1/graphql"

# Whole Typesense result blob; we parse the document fields ourselves.
_QUERY = """
query SearchBooks($query: String!) {
  search(query: $query, query_type: "books", per_page: 3) {
    results
  }
}
"""


def _as_list(value):
    if isinstance(value, list):
        return [v for v in value if v]
    if value:
        return [value]
    return []


def _pick_isbn(isbns):
    """Prefer a 13-digit ISBN, else the first plausible one."""
    cleaned = []
    for raw in _as_list(isbns):
        digits = "".join(ch for ch in str(raw) if ch.isdigit() or ch in "Xx")
        if len(digits) in (10, 13):
            cleaned.append(digits)
    isbn13 = next((i for i in cleaned if len(i) == 13), "")
    return isbn13 or (cleaned[0] if cleaned else "")


def _candidate_from_document(doc):
    if not isinstance(doc, dict):
        return None

    title = (doc.get("title") or "").strip()
    if not title:
        return None

    author = ", ".join(str(a).strip() for a in _as_list(doc.get("author_names")) if str(a).strip())
    genres = ", ".join(str(g).strip() for g in _as_list(doc.get("genres")) if str(g).strip())

    # Series: the search document carries series name(s) but no reliable
    # position, so we take the name only — the merge couples name+index from a
    # single source, and an index from a different book would be worse than none.
    series_names = _as_list(doc.get("series_names"))
    series = str(series_names[0]).strip() if series_names else ""

    image = doc.get("image") or {}
    cover_url = (image.get("url") if isinstance(image, dict) else "") or ""

    release_year = doc.get("release_year")
    published_date = str(release_year).strip() if release_year else ""

    candidate = {
        "source": "Hardcover",
        "title": title,
        "author": author,
        "description": (doc.get("description") or "").strip(),
        "isbn": _pick_isbn(doc.get("isbns")),
        "publisher": "",          # not present in the search document
        "language": "",           # not present in the search document
        "series": series,
        "series_index": "",
        "genres": genres,
        "published_date": published_date,
        "cover_url": cover_url.strip(),
    }

    fields_found = [
        f for f in (
            "title", "author", "description", "isbn",
            "series", "genres", "published_date",
        ) if candidate.get(f)
    ]
    if candidate["cover_url"]:
        fields_found.append("cover")
    candidate["fields_found"] = fields_found
    return candidate


def hardcover_search_with_status(query_text="", title="", author="", isbn="") -> dict:
    """Search Hardcover and return a structured source result.

    Same shape as google_books_search_with_status():
        source "hardcover", ok, status, duration_ms, message, candidates, raw_debug
    """
    from app.services.app_settings import get_setting

    t0 = time.monotonic()

    def _result(ok, status, message, candidates=None):
        return {
            "source": "hardcover",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    if isbn:
        query_str = "".join(ch for ch in isbn if ch.isdigit() or ch in "Xx")
    else:
        query_str = " ".join(p for p in [title, author] if p).strip() or query_text.strip()

    if not query_str:
        return _result(False, "no_result", _("Hardcover: no search input."))

    token = (get_setting("HARDCOVER_API_TOKEN") or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.post(
            _ENDPOINT,
            json={"query": _QUERY, "variables": {"query": query_str}},
            headers=headers,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return _result(False, "network_or_plugin_error", _("Hardcover: network error (%(exc)s).", exc=exc))

    if resp.status_code == 429:
        return _result(False, "rate_limited", _("Hardcover: rate limit reached."))
    if not resp.ok:
        return _result(False, "network_or_plugin_error", _("Hardcover: HTTP %(code)s.", code=resp.status_code))

    try:
        data = resp.json()
    except ValueError:
        return _result(False, "network_or_plugin_error", _("Hardcover: invalid response."))

    try:
        results_data = (data.get("data") or {}).get("search", {}).get("results", {})
        hits = results_data.get("hits", []) if isinstance(results_data, dict) else []
    except AttributeError:
        hits = []

    candidates = []
    for hit in hits:
        doc = hit.get("document", {}) if isinstance(hit, dict) else {}
        candidate = _candidate_from_document(doc)
        if candidate:
            candidates.append(candidate)

    if candidates:
        return _result(True, "ok", _("Hardcover: %(count)d hits.", count=len(candidates)), candidates=candidates)
    return _result(False, "no_result", _("Hardcover: no hits."))
