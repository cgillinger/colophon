# Colophon – e-book metadata manager
"""Series order: the reading half of the series scenario.

This is the counterpart to `language_check.py` for the series-order
scenario. `build_series_proposal` asks (through an injected `ai_propose`,
defaulting to `ai_metadata.propose_series_order`) for a reading order over a
group of books believed to belong to one series, cross-checks the answer
against an injected Wikidata lookup, and classifies every row with a status
the UI can act on. Nothing in this module writes to the database or to a
file — it only reads `LibraryItem` rows already in the session. Applying a
confirmed change is a separate, explicit step: `apply_series_changes`.
"""
import logging
import time
from collections import Counter

from app.services.ai_metadata import _norm_key, propose_series_order

logger = logging.getLogger(__name__)

# Statuses that never carry a number a user would want pre-checked, and so
# always sort after the statuses that represent an actual proposed change.
_TRAILING_STATUSES = {"not_in_series", "unknown", "unchanged"}

# Wikidata is asked one book at a time over SPARQL, and the proposal is a
# plain POST the user is waiting on. Past this many seconds the remaining
# books simply go unconfirmed (status "ai_only") rather than holding the
# request open until Gunicorn's 300 s timeout.
_WIKIDATA_BUDGET_SECONDS = 90


def _try_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _index_equal(a, b):
    """Compare two series-index strings: numerically when both parse as a
    number, otherwise casefolded string equality. Empty vs empty is equal;
    empty vs a value is not.
    """
    a = "" if a is None else str(a).strip()
    b = "" if b is None else str(b).strip()
    if not a and not b:
        return True
    if not a or not b:
        return False
    fa, fb = _try_float(a), _try_float(b)
    if fa is not None and fb is not None:
        return fa == fb
    return a.casefold() == b.casefold()


def _series_loosely_matches(a, b):
    ka, kb = _norm_key(a), _norm_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


def _index_sort_key(value):
    f = _try_float(value)
    if f is not None:
        return (0, f)
    return (1, str(value or ""))


def _series_hint(group_items):
    """The most common non-empty `series` spelling among `group_items`."""
    counts = Counter()
    for item in group_items:
        value = (getattr(item, "series", None) or "").strip()
        if value:
            counts[value] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _default_known_series():
    """Distinct non-empty series names already in the library, normalized
    key -> display spelling. Same vocabulary source as
    `ai_metadata.build_library_context`'s series extract.
    """
    from app.models import LibraryItem, db

    rows = (
        db.session.query(LibraryItem.series)
        .filter(LibraryItem.series.isnot(None), LibraryItem.series != "")
        .all()
    )
    known = {}
    for (series,) in rows:
        key = _norm_key(series)
        if key and key not in known:
            known[key] = " ".join(str(series).split())
    return known


def _default_wikidata_lookup(title, author):
    from app.services.metadata_wikidata import wikidata_search_with_status

    return wikidata_search_with_status(title=title, author=author)


def _group_size(item):
    group_key = getattr(item, "group_key", None)
    if not group_key:
        return 1
    try:
        from app.models import LibraryItem

        return LibraryItem.query.filter_by(group_key=group_key).count()
    except Exception:
        return 1


def _warnings(rows):
    values = [r["proposed_index"] for r in rows if r["proposed_index"]]
    counts = Counter(values)
    duplicate_indexes = sorted(
        (v for v, c in counts.items() if c > 1), key=_index_sort_key
    )

    int_values = []
    for value in values:
        f = _try_float(value)
        if f is not None and f == int(f):
            int_values.append(int(f))
    gaps = []
    if int_values:
        present = set(int_values)
        gaps = [str(n) for n in range(min(int_values), max(int_values) + 1)
                if n not in present]

    return {"duplicate_indexes": duplicate_indexes, "gaps": gaps}


def _sort_rows(rows):
    primary = [r for r in rows if r["status"] not in _TRAILING_STATUSES]
    trailing = [r for r in rows if r["status"] in _TRAILING_STATUSES]
    primary.sort(key=lambda r: (_index_sort_key(r["proposed_index"]), _norm_key(r["title"])))
    trailing.sort(key=lambda r: _norm_key(r["title"]))
    return primary + trailing


def build_series_proposal(group_items, ai_propose=None, wikidata_lookup=None,
                          known_series=None) -> dict:
    """Propose a reading order for `group_items` (one representative per
    format group — the caller already picked them). Pure read: never
    writes to the database.

    `ai_propose(books, series_hint, known_series) -> dict` defaults to
    `propose_series_order`. `wikidata_lookup(title, author) -> dict`
    defaults to a wrapper around `wikidata_search_with_status`; any
    exception it raises is caught and treated as "no answer" — Wikidata
    must never stop the proposal. `known_series` defaults to the library's
    own series vocabulary when not injected.

    An error from `ai_propose` is returned unchanged:
    {"ok": False, "error": "<code>"}.
    """
    if known_series is None:
        known_series = _default_known_series()
    if wikidata_lookup is None:
        wikidata_lookup = _default_wikidata_lookup
    if ai_propose is None:
        ai_propose = propose_series_order

    books = [{
        "id": item.id,
        "title": getattr(item, "title", "") or "",
        "author": getattr(item, "author", "") or "",
        "series": getattr(item, "series", "") or "",
        "series_index": getattr(item, "series_index", "") or "",
        "published_date": getattr(item, "published_date", "") or "",
        "file_name": getattr(item, "file_name", "") or "",
    } for item in group_items]

    series_hint = _series_hint(group_items)
    ai_result = ai_propose(books, series_hint, known_series)
    if not ai_result.get("ok"):
        return ai_result

    # An empty name from the model would leave rows proposing no series at
    # all; the library's own spelling is the better answer.
    series_name = ai_result.get("series_name") or series_hint or ""
    ai_book_by_id = {b["id"]: b for b in ai_result.get("books") or []}
    not_in_series_ids = set(ai_result.get("not_in_series") or [])
    unranked_ids = set(ai_result.get("unranked") or [])

    wikidata_cache = {}
    deadline = time.monotonic() + _WIKIDATA_BUDGET_SECONDS

    def _wikidata_ordinal(item):
        cache_key = (_norm_key(item.title), _norm_key(item.author))
        if cache_key not in wikidata_cache and time.monotonic() > deadline:
            return "", ""
        if cache_key not in wikidata_cache:
            try:
                wikidata_cache[cache_key] = wikidata_lookup(item.title, item.author)
            except Exception:
                logger.debug("wikidata lookup failed for %r", cache_key, exc_info=True)
                wikidata_cache[cache_key] = {"ok": False, "candidates": []}
        result = wikidata_cache[cache_key]
        if not isinstance(result, dict) or not result.get("ok"):
            return "", ""
        candidates = result.get("candidates") or []
        if not candidates:
            return "", ""
        candidate = candidates[0]
        return str(candidate.get("series") or ""), str(candidate.get("series_index") or "")

    rows = []
    for item in group_items:
        current_series = getattr(item, "series", None) or ""
        current_index = getattr(item, "series_index", None) or ""
        ai_book = ai_book_by_id.get(item.id)
        wikidata_series, wikidata_index = "", ""

        if item.id in not_in_series_ids:
            status = "not_in_series"
            proposed_series = None
            proposed_index = None
            confidence = None
            reason = ""
        elif item.id in unranked_ids or ai_book is None:
            status = "unknown"
            proposed_series = None
            proposed_index = None
            confidence = None
            reason = ""
        else:
            proposed_series = series_name
            proposed_index = ai_book["index"]
            confidence = ai_book.get("confidence")
            reason = ai_book.get("reason", "")
            if (_norm_key(proposed_series) == _norm_key(current_series)
                    and _index_equal(proposed_index, current_index)):
                status = "unchanged"
            elif current_index and not _index_equal(proposed_index, current_index):
                status = "conflict"
            else:
                # Only now is a second opinion worth a network round trip:
                # the rows above are decided by what the library already
                # records, and the ones excluded above have no number at all.
                wikidata_series, wikidata_index = _wikidata_ordinal(item)
                if (wikidata_index
                        and _series_loosely_matches(wikidata_series, proposed_series)
                        and _index_equal(wikidata_index, proposed_index)):
                    status = "confirmed"
                else:
                    status = "ai_only"

        rows.append({
            "item_id": item.id,
            "title": getattr(item, "title", "") or "",
            "author": getattr(item, "author", "") or "",
            "current_series": current_series,
            "current_index": current_index,
            "proposed_series": proposed_series,
            "proposed_index": proposed_index,
            "status": status,
            "confidence": confidence,
            "reason": reason,
            "wikidata_index": wikidata_index or None,
            "co_authored": False,
            "group_size": _group_size(item),
        })

    # A lone unconfirmed proposal is never trustworthy enough to pre-check.
    proposed_rows = [r for r in rows if r["proposed_index"] is not None]
    if len(proposed_rows) == 1 and not any(r["status"] == "confirmed" for r in rows):
        only = proposed_rows[0]
        if only["status"] == "ai_only":
            only["confidence"] = "low"

    return {
        "ok": True,
        "groups": [{
            "series_name": series_name,
            "series_name_snapped": bool(ai_result.get("series_name_snapped")),
            "warnings": _warnings(rows),
            "rows": _sort_rows(rows),
        }],
    }


def apply_series_changes(changes, write_files=False, cover_dir=None):
    """Write the confirmed series/series_index values. DB always; files
    only when asked.

    `changes` is [{"item_id": int, "series": str, "series_index": str}].
    Each change is expanded to every format sibling (same `group_key`) and
    applied through apply_metadata_to_item with
    selected_fields={"series", "series_index"} — nothing else may ride
    along. A missing/None series_index is sent as an empty string rather
    than crashing the writer.
    """
    from app.models import LibraryItem, db
    from app.services.metadata_writer import apply_metadata_to_item

    updated = 0
    files_written = 0
    errors = []

    for change in changes or []:
        item = db.session.get(LibraryItem, change.get("item_id"))
        if item is None:
            errors.append({"item_id": change.get("item_id"), "error": "not_found"})
            continue

        series = change.get("series") or ""
        series_index = change.get("series_index") or ""

        siblings = [item]
        if item.group_key:
            siblings = LibraryItem.query.filter_by(group_key=item.group_key).all()

        for sibling in siblings:
            try:
                result = apply_metadata_to_item(
                    item=sibling,
                    result={"series": series, "series_index": series_index},
                    cover_dir=cover_dir,
                    overwrite=True,
                    write_to_file=write_files,
                    selected_fields={"series", "series_index"},
                )
            except Exception as exc:
                logger.exception("series apply failed for item %s", sibling.id)
                errors.append({"item_id": sibling.id, "error": str(exc)})
                continue

            updated += 1
            if write_files:
                if result.get("file_updated"):
                    files_written += 1
                elif result.get("file_write_error"):
                    errors.append({
                        "item_id": sibling.id,
                        "error": result.get("file_write_error"),
                    })

    db.session.commit()
    return {
        "ok": True,
        "updated": updated,
        "files_written": files_written,
        "errors": errors,
    }
