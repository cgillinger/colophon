# Colophon – e-book metadata manager
"""LIBRIS metadata source — the Swedish national bibliography (KB).

International sources are sparsest exactly where a Swedish library needs them.
LIBRIS (Kungliga biblioteket's Xsearch API) fills that blind spot with
authoritative Swedish title / author / publisher / date / language / ISBN.

It does NOT provide series, synopsis or covers (Xsearch is weak there — the
other sources cover those), and its `description` field is catalogue noise
(record IDs, edit notes), not a real synopsis, so we ignore it.

Xsearch is keyless: https://libris.kb.se/xsearch?query=...&format=json&n=5
"""
import logging
import re
import time

import requests
from flask_babel import gettext as _

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_ENDPOINT = "https://libris.kb.se/xsearch"

# MARC 3-letter language codes → ISO 639-1.
_MARC_LANG = {
    "swe": "sv", "eng": "en", "ger": "de", "fre": "fr", "spa": "es",
    "ita": "it", "nor": "no", "dan": "da", "fin": "fi", "dut": "nl",
    "rus": "ru", "por": "pt",
}


def _reformat_creator(creator):
    """'Tamas, Gellert, 1963-' -> 'Gellert Tamas'. Accepts str or list."""
    if isinstance(creator, list):
        creator = creator[0] if creator else ""
    creator = (creator or "").strip()
    if not creator:
        return ""
    parts = [p.strip() for p in creator.split(",")]
    # Drop date-ish trailing parts (e.g. '1963-', '1947-2010').
    parts = [p for p in parts if p and not re.match(r"^\d{3,4}-?\d{0,4}\.?$", p)]
    if len(parts) >= 2:
        last, first = parts[0], parts[1]
        return f"{first} {last}".strip()
    return parts[0] if parts else ""


def _clean_publisher(publisher):
    """LIBRIS publisher is a messy list like ['Stockholm : Natur & kultur', 'Lettland']."""
    items = publisher if isinstance(publisher, list) else [publisher]
    for raw in items:
        raw = (raw or "").strip()
        if not raw:
            continue
        # 'City : Publisher' -> 'Publisher'
        name = raw.split(" : ", 1)[-1].strip() if " : " in raw else raw
        # Skip bare country/place leftovers (single capitalised word, no spaces).
        if name and not re.match(r"^[A-ZÅÄÖ][a-zåäö]+$", name):
            return name
        if name:
            return name
    return ""


def _clean_date(date):
    """Extract a 4-digit year; LIBRIS uses 'nnnn' for unknown and sometimes lists."""
    candidates = date if isinstance(date, list) else [date]
    for d in candidates:
        m = re.search(r"\d{4}", str(d or ""))
        if m:
            return m.group(0)
    return ""


def _clean_title(title):
    if isinstance(title, list):
        title = title[0] if title else ""
    title = (title or "").strip()
    title = re.sub(r"\[Elektronisk resurs\]", "", title, flags=re.IGNORECASE)
    return " ".join(title.split()).strip()


def _record_to_candidate(rec):
    title = _clean_title(rec.get("title"))
    if not title:
        return None

    isbn_raw = rec.get("isbn")
    if isinstance(isbn_raw, list):
        isbn_raw = isbn_raw[0] if isbn_raw else ""
    isbn = re.sub(r"[^0-9Xx]", "", str(isbn_raw or ""))
    isbn = isbn if len(isbn) in (10, 13) else ""

    lang = (rec.get("language") or "")
    if isinstance(lang, list):
        lang = lang[0] if lang else ""
    language = _MARC_LANG.get(str(lang).strip().lower(), "")

    subjects = rec.get("subject")
    if isinstance(subjects, str):
        subjects = [subjects]
    genres = ", ".join(s.strip() for s in (subjects or []) if isinstance(s, str) and s.strip())

    candidate = {
        "source": "LIBRIS",
        "title": title,
        "author": _reformat_creator(rec.get("creator")),
        "description": "",  # Xsearch 'description' is catalogue noise, not a synopsis
        "isbn": isbn,
        "publisher": _clean_publisher(rec.get("publisher")),
        "language": language,
        "series": "",
        "series_index": "",
        "genres": genres,
        "published_date": _clean_date(rec.get("date")),
        "cover_url": "",
    }
    fields = [f for f in ("title", "author", "isbn", "publisher", "language", "genres", "published_date")
              if candidate.get(f)]
    candidate["fields_found"] = fields
    return candidate


def libris_search_with_status(query_text="", title="", author="", isbn="") -> dict:
    """Search LIBRIS Xsearch and return a structured source result."""
    t0 = time.monotonic()

    def _result(ok, status, message, candidates=None):
        return {
            "source": "libris",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    isbn_digits = re.sub(r"[^0-9Xx]", "", isbn or "")
    if isbn_digits:
        query = f"isbn:({isbn_digits})"
    else:
        terms = " ".join(p for p in [title, author] if p).strip() or (query_text or "").strip()
        query = terms
    if not query:
        return _result(False, "no_result", _("LIBRIS: no search input."))

    try:
        resp = requests.get(
            _ENDPOINT,
            params={"query": query, "format": "json", "n": 5},
            headers={"User-Agent": "Colophon/1.0 (e-book metadata manager)"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return _result(False, "network_or_plugin_error", _("LIBRIS: network error (%(exc)s).", exc=exc))

    if not resp.ok:
        return _result(False, "network_or_plugin_error", _("LIBRIS: HTTP %(code)s.", code=resp.status_code))

    try:
        records = resp.json().get("xsearch", {}).get("list", [])
    except ValueError:
        return _result(False, "network_or_plugin_error", _("LIBRIS: invalid response."))

    candidates = []
    for rec in records:
        cand = _record_to_candidate(rec)
        if cand:
            candidates.append(cand)

    if candidates:
        return _result(True, "ok", _("LIBRIS: %(count)d hits.", count=len(candidates)), candidates=candidates)
    return _result(False, "no_result", _("LIBRIS: no hits."))
