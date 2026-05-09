# Colophon – e-book metadata manager
"""Wikipedia REST API provider.

Used as a fast secondary source alongside Google Books in the progressive
metadata fetch flow. Wikipedia's REST summary endpoint typically responds
in well under 200ms, which lets the UI populate description and a thumbnail
cover long before slower sources (Calibre) finish.

Coverage is limited: ~75% for well-known novels, lower for niche titles.
The summary `extract` is the article lead, not a true book synopsis, so
it's most useful as a fallback when Google Books has nothing.
"""
import logging
import time

import requests
from flask_babel import gettext as _

logger = logging.getLogger(__name__)


WIKIPEDIA_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
USER_AGENT = "Colophon/1.0 (metadata-manager)"
TIMEOUT = 5


def _build_candidate(data):
    """Convert a Wikipedia REST summary response into the standard candidate schema."""
    extract = (data.get("extract") or "").strip()
    thumbnail = data.get("thumbnail") or {}
    cover_url = (thumbnail.get("source") or "").strip() if isinstance(thumbnail, dict) else ""
    content_urls = data.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {} if isinstance(content_urls, dict) else {}
    wikipedia_url = desktop.get("page", "") if isinstance(desktop, dict) else ""

    candidate = {
        "source": "Wikipedia",
        "title": (data.get("title") or "").strip(),
        "author": "",
        "description": extract,
        "isbn": "",
        "publisher": "",
        "language": (data.get("lang") or "").strip(),
        "series": "",
        "series_index": "",
        "cover_url": cover_url,
        "genres": "",
        "published_date": "",
        "wikidata_id": (data.get("wikibase_item") or "").strip(),
        "wikipedia_url": wikipedia_url,
    }

    fields_found = []
    if candidate["title"]:
        fields_found.append("title")
    if candidate["description"]:
        fields_found.append("description")
    if candidate["cover_url"]:
        fields_found.append("cover")
    if candidate["wikidata_id"]:
        fields_found.append("wikidata_id")
    candidate["fields_found"] = fields_found

    return candidate


def _fetch_summary(title_slug, lang):
    url = WIKIPEDIA_SUMMARY_URL.format(lang=lang, title=title_slug)
    headers = {"User-Agent": USER_AGENT}
    return requests.get(url, headers=headers, timeout=TIMEOUT)


def search_wikipedia(title, author="", lang="en"):
    """Search Wikipedia for a book and return a list of candidates.

    Returns a list of candidate dicts (0 or 1 entry — Wikipedia REST returns
    a single article per slug). Author is currently unused but kept in the
    signature for future infobox-based lookups.

    Network errors raise — callers wanting a structured result should use
    search_wikipedia_with_status().
    """
    raw_title = (title or "").strip()
    if not raw_title:
        return []

    slug = raw_title.replace(" ", "_")

    try:
        resp = _fetch_summary(slug, lang)
    except requests.RequestException:
        raise

    if resp.status_code == 404:
        # Common disambiguation pattern for novels — try the "(novel)" variant.
        try:
            resp = _fetch_summary(slug + "_(novel)", lang)
        except requests.RequestException:
            raise

    if resp.status_code != 200:
        return []

    try:
        data = resp.json()
    except ValueError:
        return []

    if not isinstance(data, dict):
        return []

    # The summary endpoint can return disambiguation pages — skip them.
    page_type = (data.get("type") or "").lower()
    if page_type == "disambiguation":
        return []

    candidate = _build_candidate(data)
    if not candidate["title"]:
        return []

    return [candidate]


def search_wikipedia_with_status(title="", author="", lang="en"):
    """Run a Wikipedia search and return a structured source result.

    Mirrors google_books_search_with_status so the pipeline can treat all
    sources uniformly. The returned dict always contains:
        source       "wikipedia"
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
            "source": "wikipedia",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    raw_title = (title or "").strip()
    if not raw_title:
        return _result(False, "no_result", _("Wikipedia: no title to search."))

    try:
        candidates = search_wikipedia(title=raw_title, author=author, lang=lang)
    except requests.RequestException as exc:
        return _result(
            False, "network_or_plugin_error",
            _("Wikipedia: network error (%(exc)s).", exc=exc),
        )
    except Exception as exc:
        logger.debug("Wikipedia search unexpected error: %s", exc, exc_info=True)
        return _result(
            False, "network_or_plugin_error",
            _("Wikipedia: unexpected error (%(exc)s).", exc=exc),
        )

    if candidates:
        return _result(
            True, "ok",
            _("Wikipedia: %(count)d hit.", count=len(candidates)),
            candidates=candidates,
        )

    return _result(False, "no_result", _("Wikipedia: no hits."))
