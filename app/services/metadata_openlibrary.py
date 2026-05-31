# Colophon – e-book metadata manager
"""Open Library metadata source.

Open Library (Internet Archive) is a keyless, ISBN-rich catalogue that is
especially strong for older and obscure titles. Its search returns title,
author, publisher, first-publish year, subjects, cover and an ISBN list; a
second call to the work record yields a real synopsis. Series coverage is
patchy (other sources handle that).

  search:      https://openlibrary.org/search.json?q=...&fields=...
  work/desc:   https://openlibrary.org/works/<id>.json
  cover:       https://covers.openlibrary.org/b/id/<cover_i>-L.jpg
"""
import logging
import re
import time

import requests
from flask_babel import gettext as _

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_SEARCH = "https://openlibrary.org/search.json"
_FIELDS = "title,author_name,first_publish_year,publisher,subject,series,key,isbn,cover_i"
_UA = "Colophon/1.0 (e-book metadata manager)"


def _pick_isbn(isbns):
    cleaned = []
    for raw in isbns or []:
        digits = re.sub(r"[^0-9Xx]", "", str(raw))
        if len(digits) in (10, 13):
            cleaned.append(digits)
    return next((i for i in cleaned if len(i) == 13), cleaned[0] if cleaned else "")


def _clean_subjects(subjects):
    """OL subjects mix genres with machine tags (award:..., place:..., =...)
    and over-specific topics — keep clean, human-ish tags and cap the list."""
    out = []
    for s in subjects or []:
        if not isinstance(s, str):
            continue
        s = s.strip()
        if not s or ":" in s or "=" in s or len(s) > 40:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= 10:
            break
    return out


def _fetch_description(work_key):
    """Fetch a work's synopsis via /works/<id>.json (best-effort)."""
    if not work_key:
        return ""
    try:
        resp = requests.get(
            f"https://openlibrary.org{work_key}.json",
            headers={"User-Agent": _UA}, timeout=_TIMEOUT,
        )
        if not resp.ok:
            return ""
        desc = resp.json().get("description")
        if isinstance(desc, dict):
            desc = desc.get("value", "")
        return (desc or "").strip()
    except (requests.RequestException, ValueError):
        return ""


def _doc_to_candidate(doc, with_description=True):
    title = (doc.get("title") or "").strip()
    if not title:
        return None

    authors = doc.get("author_name") or []
    author = ", ".join(a.strip() for a in authors if isinstance(a, str) and a.strip())

    publishers = doc.get("publisher") or []
    publisher = next((p.strip() for p in publishers if isinstance(p, str) and p.strip()), "")

    series_raw = doc.get("series")
    series = ""
    if isinstance(series_raw, list) and series_raw:
        series = str(series_raw[0]).strip()
    elif isinstance(series_raw, str):
        series = series_raw.strip()

    year = doc.get("first_publish_year")
    published_date = str(year) if year else ""

    cover_i = doc.get("cover_i")
    cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i else ""

    candidate = {
        "source": "Open Library",
        "title": title,
        "author": author,
        "description": _fetch_description(doc.get("key")) if with_description else "",
        "isbn": _pick_isbn(doc.get("isbn")),
        "publisher": publisher,
        "language": "",
        "series": series,
        "series_index": "",
        "genres": ", ".join(_clean_subjects(doc.get("subject"))),
        "published_date": published_date,
        "cover_url": cover_url,
    }
    fields = [f for f in ("title", "author", "description", "isbn", "publisher",
                          "series", "genres", "published_date") if candidate.get(f)]
    if cover_url:
        fields.append("cover")
    candidate["fields_found"] = fields
    return candidate


def openlibrary_search_with_status(query_text="", title="", author="", isbn="") -> dict:
    """Search Open Library and return a structured source result."""
    t0 = time.monotonic()

    def _result(ok, status, message, candidates=None):
        return {
            "source": "openlibrary",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    isbn_digits = re.sub(r"[^0-9Xx]", "", isbn or "")
    if isbn_digits:
        params = {"q": f"isbn:{isbn_digits}", "fields": _FIELDS, "limit": 1}
    else:
        q = " ".join(p for p in [title, author] if p).strip() or (query_text or "").strip()
        if not q:
            return _result(False, "no_result", _("Open Library: no search input."))
        params = {"q": q, "fields": _FIELDS, "limit": 2}

    try:
        resp = requests.get(_SEARCH, params=params, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        return _result(False, "network_or_plugin_error", _("Open Library: network error (%(exc)s).", exc=exc))

    if not resp.ok:
        return _result(False, "network_or_plugin_error", _("Open Library: HTTP %(code)s.", code=resp.status_code))

    try:
        docs = resp.json().get("docs", [])
    except ValueError:
        return _result(False, "network_or_plugin_error", _("Open Library: invalid response."))

    candidates = []
    for i, doc in enumerate(docs):
        # Only fetch the (extra HTTP) description for the top result.
        cand = _doc_to_candidate(doc, with_description=(i == 0))
        if cand:
            candidates.append(cand)

    if candidates:
        return _result(True, "ok", _("Open Library: %(count)d hits.", count=len(candidates)), candidates=candidates)
    return _result(False, "no_result", _("Open Library: no hits."))
