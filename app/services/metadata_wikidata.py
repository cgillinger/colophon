# Colophon – e-book metadata manager
"""Wikidata metadata source — structured series + ordinal.

Wikidata is the only source that gives a **structured** series *and* its position
(part-of-series P179 + the series-ordinal qualifier P1545) without scraping. That
complements Hardcover, which returns a series *name* but no reliable index.

Lookup strategy (no API key needed):
  1. wbsearchentities — find candidate entities by title (Wikidata's own search
     ranking; far more reliable than SPARQL label matching).
  2. one SPARQL query over those candidate QIDs that resolves, with labels:
     P31 (instance of — to keep only books/works), P179+P1545 (series + ordinal),
     P136 (genre), P577 (publication date), P50 (author), P18 (cover image).
  3. pick the book-type entity whose author best matches the query.

Coverage is limited to *notable* works — that's expected; the merge just uses
what comes back and the trust-gate filters wrong matches.
"""
import logging
import time
from difflib import SequenceMatcher

import requests
from flask_babel import gettext as _

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_API = "https://www.wikidata.org/w/api.php"
_SPARQL = "https://query.wikidata.org/sparql"
_UA = "Colophon/1.0 (self-hosted e-book metadata manager)"

# instance-of (P31) values that count as a book/literary work.
_BOOK_TYPES = {
    "Q571",       # book
    "Q7725634",   # literary work
    "Q47461344",  # written work
    "Q8261",      # novel
    "Q49084",     # short story
    "Q1004",      # comic? (kept loose)
    "Q25379",     # play
}


def _qid(uri):
    return uri.rsplit("/", 1)[-1] if uri else ""


def _similar(a, b):
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _search_entities(title):
    """Return up to 7 candidate QIDs for a title via wbsearchentities."""
    qids = []
    for lang in ("en", "sv"):
        try:
            resp = requests.get(
                _API,
                params={
                    "action": "wbsearchentities", "search": title,
                    "language": lang, "uselang": lang, "type": "item",
                    "limit": 7, "format": "json",
                },
                headers={"User-Agent": _UA},
                timeout=_TIMEOUT,
            )
            if not resp.ok:
                continue
            for hit in resp.json().get("search", []):
                qid = hit.get("id")
                if qid and qid not in qids:
                    qids.append(qid)
        except (requests.RequestException, ValueError):
            continue
        if qids:
            break
    return qids[:7]


def _sparql_for_qids(qids):
    """One SPARQL query resolving structured fields for the candidate QIDs."""
    values = " ".join(f"wd:{q}" for q in qids)
    query = f"""
    SELECT ?work ?workLabel ?type ?seriesLabel ?ordinal ?genreLabel ?date ?authorLabel ?image WHERE {{
      VALUES ?work {{ {values} }}
      ?work wdt:P31 ?type .
      OPTIONAL {{ ?work p:P179 ?ss. ?ss ps:P179 ?series. OPTIONAL {{ ?ss pq:P1545 ?ordinal. }} }}
      OPTIONAL {{ ?work wdt:P136 ?genre. }}
      OPTIONAL {{ ?work wdt:P577 ?date. }}
      OPTIONAL {{ ?work wdt:P50 ?author. }}
      OPTIONAL {{ ?work wdt:P18 ?image. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,sv". }}
    }}
    """
    resp = requests.get(
        _SPARQL,
        params={"query": query, "format": "json"},
        headers={"User-Agent": _UA},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("results", {}).get("bindings", [])


def _aggregate(bindings):
    """Collapse the row-per-value SPARQL result into one record per work."""
    works = {}
    for b in bindings:
        def val(key):
            return (b.get(key, {}) or {}).get("value", "")

        qid = _qid(val("work"))
        if not qid:
            continue
        w = works.setdefault(qid, {
            "qid": qid, "title": val("workLabel"), "types": set(),
            "series": "", "series_index": "", "genres": [],
            "date": "", "authors": [], "image": "",
        })
        w["types"].add(_qid(val("type")))
        if val("seriesLabel") and not w["series"]:
            w["series"] = val("seriesLabel")
            w["series_index"] = val("ordinal")
        elif val("seriesLabel") and val("ordinal") and not w["series_index"]:
            w["series_index"] = val("ordinal")
        g = val("genreLabel")
        if g and g not in w["genres"] and not g.startswith("Q"):
            w["genres"].append(g)
        if val("date") and not w["date"]:
            w["date"] = val("date")[:10]
        a = val("authorLabel")
        if a and a not in w["authors"] and not a.startswith("Q"):
            w["authors"].append(a)
        if val("image") and not w["image"]:
            w["image"] = val("image")
    return list(works.values())


def _best_work(works, title, author):
    """Choose the book-type work that best matches the query."""
    books = [w for w in works if w["types"] & _BOOK_TYPES]
    if not books:
        return None
    if author:
        scored = sorted(
            books,
            key=lambda w: max((_similar(author, a) for a in w["authors"]), default=0.0),
            reverse=True,
        )
        if max((_similar(author, a) for a in scored[0]["authors"]), default=0.0) >= 0.5:
            return scored[0]
    # fall back to closest title match
    return max(books, key=lambda w: _similar(title, w["title"]))


def wikidata_search_with_status(query_text="", title="", author="", isbn="") -> dict:
    """Search Wikidata and return a structured source result (series + ordinal)."""
    t0 = time.monotonic()

    def _result(ok, status, message, candidates=None):
        return {
            "source": "wikidata",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    title = (title or "").strip()
    if not title:
        return _result(False, "no_result", _("Wikidata: no title to search."))

    qids = _search_entities(title)
    if not qids:
        return _result(False, "no_result", _("Wikidata: no entities found."))

    try:
        bindings = _sparql_for_qids(qids)
    except requests.RequestException as exc:
        return _result(False, "network_or_plugin_error", _("Wikidata: SPARQL error (%(exc)s).", exc=exc))
    except ValueError:
        return _result(False, "network_or_plugin_error", _("Wikidata: invalid SPARQL response."))

    work = _best_work(_aggregate(bindings), title, author)
    if not work:
        return _result(False, "no_result", _("Wikidata: no matching book found."))

    candidate = {
        "source": "Wikidata",
        "title": work["title"],
        "author": ", ".join(work["authors"]),
        "description": "",
        "isbn": "",
        "publisher": "",
        "language": "",
        "series": work["series"],
        "series_index": work["series_index"],
        "genres": ", ".join(work["genres"][:12]),
        "published_date": work["date"],
        "cover_url": work["image"],
    }
    fields_found = [
        f for f in ("title", "author", "series", "genres", "published_date")
        if candidate.get(f)
    ]
    if candidate["series_index"]:
        fields_found.append("series_index")
    if candidate["cover_url"]:
        fields_found.append("cover")
    candidate["fields_found"] = fields_found

    return _result(True, "ok", _("Wikidata: 1 match (%(title)s).", title=work["title"]), candidates=[candidate])
