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

`build_author_proposal` is the same thing over a whole author: the AI is
asked to group the books into series as well as order them, and every
proposed series becomes one more group for the same review component.
Both flows share `_build_group`, so the status priority lives in one
place, and they share one Wikidata deadline per proposal.
"""
import logging
import time
from collections import Counter

from app.services.ai_metadata import (
    _norm_key,
    propose_author_series,
    propose_series_order,
)

logger = logging.getLogger(__name__)

# Statuses that never carry a number a user would want pre-checked, and so
# always sort after the statuses that represent an actual proposed change.
_TRAILING_STATUSES = {"not_in_series", "unknown", "unchanged", "standalone"}

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


def _book_payload(item) -> dict:
    """What the AI is told about one book. Same shape for both flows."""
    return {
        "id": item.id,
        "title": getattr(item, "title", "") or "",
        "author": getattr(item, "author", "") or "",
        "series": getattr(item, "series", "") or "",
        "series_index": getattr(item, "series_index", "") or "",
        "published_date": getattr(item, "published_date", "") or "",
        "file_name": getattr(item, "file_name", "") or "",
    }


def _make_wikidata_ordinal(wikidata_lookup):
    """One Wikidata cache and one deadline for a whole proposal.

    The budget is shared across every group, not reset per group: an
    author with many series is exactly the case the deadline exists for,
    and resetting it per series would let a large author hold the request
    open well past Gunicorn's timeout. Books past the deadline simply go
    unconfirmed (`ai_only`) instead.
    """
    cache = {}
    deadline = time.monotonic() + _WIKIDATA_BUDGET_SECONDS

    def _ordinal(item):
        cache_key = (_norm_key(item.title), _norm_key(item.author))
        if cache_key not in cache and time.monotonic() > deadline:
            return "", ""
        if cache_key not in cache:
            try:
                cache[cache_key] = wikidata_lookup(item.title, item.author)
            except Exception:
                logger.debug("wikidata lookup failed for %r", cache_key, exc_info=True)
                cache[cache_key] = {"ok": False, "candidates": []}
        result = cache[cache_key]
        if not isinstance(result, dict) or not result.get("ok"):
            return "", ""
        candidates = result.get("candidates") or []
        if not candidates:
            return "", ""
        candidate = candidates[0]
        return str(candidate.get("series") or ""), str(candidate.get("series_index") or "")

    return _ordinal


def _build_group(items, series_name, series_name_snapped, ranked_by_id,
                 excluded_ids, unranked_ids, wikidata_ordinal,
                 excluded_status="not_in_series", co_authored_ids=(),
                 standalone=False) -> dict:
    """One reviewable group: a row per item carrying the status the UI acts on.

    Shared by the single-series flow and the per-author flow so the
    priority order lives in exactly one place. First match wins:
    `excluded_status` -> `unknown` -> `unchanged` -> `conflict` ->
    `confirmed` -> `ai_only`. **`conflict` deliberately outranks
    `confirmed`**: a number someone already entered is never pre-ticked
    away, even when Wikidata backs the new one.

    Only the rows that reach the `confirmed`/`ai_only` branch cost a
    Wikidata round trip — the ones above are decided by what the library
    already records, and the excluded ones carry no number at all.
    """
    co_authored_ids = set(co_authored_ids or ())
    excluded_ids = set(excluded_ids or ())
    unranked_ids = set(unranked_ids or ())

    rows = []
    for item in items:
        current_series = getattr(item, "series", None) or ""
        current_index = getattr(item, "series_index", None) or ""
        ai_book = ranked_by_id.get(item.id)
        wikidata_series, wikidata_index = "", ""

        if item.id in excluded_ids:
            status = excluded_status
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
                wikidata_series, wikidata_index = wikidata_ordinal(item)
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
            "co_authored": item.id in co_authored_ids,
            "group_size": _group_size(item),
        })

    # A lone unconfirmed proposal is never trustworthy enough to pre-check.
    # Applied per group, so one thin series in an author's shelf cannot ride
    # in pre-ticked on the strength of a thicker one next to it.
    proposed_rows = [r for r in rows if r["proposed_index"] is not None]
    if len(proposed_rows) == 1 and not any(r["status"] == "confirmed" for r in rows):
        only = proposed_rows[0]
        if only["status"] == "ai_only":
            only["confidence"] = "low"

    return {
        "series_name": series_name,
        "series_name_snapped": bool(series_name_snapped),
        "standalone": bool(standalone),
        "warnings": _warnings(rows),
        "rows": _sort_rows(rows),
    }


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

    books = [_book_payload(item) for item in group_items]

    series_hint = _series_hint(group_items)
    ai_result = ai_propose(books, series_hint, known_series)
    if not ai_result.get("ok"):
        return ai_result

    # An empty name from the model would leave rows proposing no series at
    # all; the library's own spelling is the better answer.
    series_name = ai_result.get("series_name") or series_hint or ""

    group = _build_group(
        items=group_items,
        series_name=series_name,
        series_name_snapped=bool(ai_result.get("series_name_snapped")),
        ranked_by_id={b["id"]: b for b in ai_result.get("books") or []},
        excluded_ids=set(ai_result.get("not_in_series") or []),
        unranked_ids=set(ai_result.get("unranked") or []),
        wikidata_ordinal=_make_wikidata_ordinal(wikidata_lookup),
    )
    return {"ok": True, "groups": [group]}


def _author_representatives(author_id):
    """One `LibraryItem` per format group for this author, lowest id wins.

    The author filter is copied from `routes/metadata.py:bulk_metadata` —
    through `book_authors` so co-authored books show too, with the
    `author_id` mirror folded in for rows the resolver has not reached yet.
    """
    from app.models import BookAuthor, LibraryItem, db

    items = (
        LibraryItem.query
        .filter(db.or_(
            LibraryItem.id.in_(
                db.session.query(BookAuthor.item_id)
                .filter(BookAuthor.author_id == author_id)
            ),
            LibraryItem.author_id == author_id,
        ))
        .order_by(LibraryItem.id)
        .all()
    )

    representatives = {}
    for item in items:
        key = item.group_key or f"item:{item.id}"
        if key not in representatives or item.id < representatives[key].id:
            representatives[key] = item
    return list(representatives.values())


def _co_authored_ids(item_ids):
    """Ids with more than one row in `book_authors` — shown with a note,
    because a series decision there is not this author's alone."""
    from app.models import BookAuthor, db
    from sqlalchemy import func

    if not item_ids:
        return set()
    rows = (
        db.session.query(BookAuthor.item_id, func.count(BookAuthor.author_id))
        .filter(BookAuthor.item_id.in_(list(item_ids)))
        .group_by(BookAuthor.item_id)
        .all()
    )
    return {item_id for item_id, count in rows if count > 1}


def build_author_proposal(author_id, ai_propose_author=None,
                          wikidata_lookup=None, known_series=None) -> dict:
    """Group one author's books into series and order each of them.

    Same review component, same statuses and the same apply route as the
    single-series flow — only the selection is wider, and the AI is asked
    to do the grouping as well as the ordering. Pure read.

    The last group is the leftovers: books the model called standalone,
    plus any it never mentioned. They carry no number and get no
    checkbox, so this flow can never put an index on a book the model
    itself placed outside every series.
    """
    from app.models import Author, db

    author = db.session.get(Author, author_id) if author_id else None
    if author is None:
        return {"ok": False, "error": "no_author"}

    group_items = _author_representatives(author.id)
    if not group_items:
        return {"ok": False, "error": "no_books"}

    if known_series is None:
        known_series = _default_known_series()
    if wikidata_lookup is None:
        wikidata_lookup = _default_wikidata_lookup
    if ai_propose_author is None:
        ai_propose_author = propose_author_series

    ai_result = ai_propose_author(
        [_book_payload(item) for item in group_items], known_series
    )
    if not ai_result.get("ok"):
        return ai_result

    items_by_id = {item.id: item for item in group_items}
    co_authored = _co_authored_ids(items_by_id.keys())
    wikidata_ordinal = _make_wikidata_ordinal(wikidata_lookup)

    groups = []
    claimed = set()
    for series in ai_result.get("series") or []:
        ranked_by_id = {
            book["id"]: book
            for book in (series.get("books") or [])
            if book.get("id") in items_by_id and book["id"] not in claimed
        }
        if not ranked_by_id:
            continue
        members = [items_by_id[book_id] for book_id in ranked_by_id]
        groups.append(_build_group(
            items=members,
            series_name=series.get("name") or "",
            series_name_snapped=bool(series.get("name_snapped")),
            ranked_by_id=ranked_by_id,
            excluded_ids=set(),
            unranked_ids=set(),
            wikidata_ordinal=wikidata_ordinal,
            co_authored_ids=co_authored,
        ))
        claimed |= set(ranked_by_id)

    leftovers = [item for item in group_items if item.id not in claimed]
    if leftovers:
        standalone_ids = {
            book_id for book_id in (ai_result.get("standalone") or [])
            if book_id in items_by_id and book_id not in claimed
        }
        groups.append(_build_group(
            items=leftovers,
            series_name=None,
            series_name_snapped=False,
            ranked_by_id={},
            excluded_ids=standalone_ids,
            unranked_ids=set(),
            wikidata_ordinal=wikidata_ordinal,
            excluded_status="standalone",
            co_authored_ids=co_authored,
            standalone=True,
        ))

    return {"ok": True, "author_name": author.canonical_name, "groups": groups}


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
