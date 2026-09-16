# Colophon – tests for the series-order scenario (step 4, backend)
"""services/series_batch: the reading half of the series scenario.

`build_series_proposal` never writes — it takes a group of format
representatives plus injected `ai_propose` / `wikidata_lookup` / `known_series`
callables and returns a row-per-book proposal with a status that says
whether a number can be trusted. `propose_series_order` (in ai_metadata.py)
is the AI call itself: sanitizing what the model returns is more load-bearing
than the HTTP call, so most of its tests are about filtering hallucinated or
duplicate ids rather than the request.

The routes are thin: /propose only reads, /apply delegates to
`series_batch.apply_series_changes`, which mirrors
`language_check.apply_language_changes` but fans a change out to every
format sibling (same group_key).
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.models import db, LibraryItem, Author, BookAuthor
from app.services import ai_metadata
from app.services.ai_metadata import MAX_SERIES_BOOKS, propose_series_order
from app.services.series_batch import apply_series_changes, build_series_proposal


# --------------------------------------------------------------------------
# build_series_proposal — DB fixture + helpers
# --------------------------------------------------------------------------

@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


_counter = iter(range(1, 100_000))


def _add(title=None, author="An Author", series="", series_index="", group_key=None):
    n = next(_counter)
    item = LibraryItem(
        title=title or f"Book {n}",
        author=author,
        series=series,
        series_index=series_index,
        extension=".epub",
        file_path=f"/books/b{n}.epub",
        file_name=f"b{n}.epub",
        group_key=group_key,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _fake_ai(result):
    """A stand-in for propose_series_order with the same contract."""
    def _call(books, series_hint=None, known_series=None):
        return result
    return _call


def _no_wikidata(title, author):
    return {"ok": False, "candidates": []}


def _wikidata_ordinal(series, index):
    def _call(title, author):
        return {"ok": True, "candidates": [{"series": series, "series_index": index}]}
    return _call


def _row_for(proposal, item_id):
    rows = proposal["groups"][0]["rows"]
    return next(r for r in rows if r["item_id"] == item_id)


# --- 1. AI and Wikidata agree on the index → confirmed --------------------

def test_ai_and_wikidata_agree_is_confirmed(app):
    book = _add(title="Kråkflickan", series="", series_index="")
    ai_result = {
        "ok": True, "series_name": "Kråkflickan", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "known"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book],
        ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_wikidata_ordinal("Kråkflickan", "3"),
        known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "confirmed"
    assert row["proposed_series"] == "Kråkflickan"
    assert row["proposed_index"] == "3"
    assert row["wikidata_index"] == "3"
    assert row["co_authored"] is False
    assert row["group_size"] == 1


# --- 2. AI alone, no Wikidata answer, several books → ai_only -------------

def test_ai_only_with_several_books(app):
    b1 = _add(title="Book A")
    b2 = _add(title="Book B")
    ai_result = {
        "ok": True, "series_name": "Some Series", "series_name_snapped": False,
        "books": [
            {"id": b1.id, "index": "1", "confidence": "medium", "reason": "r1"},
            {"id": b2.id, "index": "2", "confidence": "medium", "reason": "r2"},
        ],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [b1, b2], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    for item_id in (b1.id, b2.id):
        row = _row_for(proposal, item_id)
        assert row["status"] == "ai_only"
        assert row["confidence"] == "medium"  # not downgraded — 2 rows, not 1


# --- 3. Existing series_index differs from the proposal → conflict --------

def test_existing_index_conflicts_even_when_wikidata_confirms(app):
    book = _add(title="Kråkflickan", series="Kråkflickan", series_index="5")
    ai_result = {
        "ok": True, "series_name": "Kråkflickan", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_wikidata_ordinal("Kråkflickan", "3"),  # confirms the AI
        known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "conflict"
    assert row["current_index"] == "5"
    assert row["proposed_index"] == "3"


# --- 4. Proposal equals current values → unchanged -------------------------

def test_matching_proposal_is_unchanged(app):
    book = _add(title="Kråkflickan", series="Kråkflickan", series_index="3")
    ai_result = {
        "ok": True, "series_name": "Kråkflickan", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "unchanged"


# --- 5. Id in not_in_series → status not_in_series, no proposed index -----

def test_not_in_series_gets_no_proposed_index(app):
    book = _add(title="Omnibus")
    ai_result = {
        "ok": True, "series_name": "Some Series", "series_name_snapped": False,
        "books": [], "not_in_series": [book.id], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "not_in_series"
    assert row["proposed_index"] is None
    assert row["proposed_series"] is None


# --- 6. Id the AI never mentioned → unknown --------------------------------

def test_unmentioned_id_is_unknown(app):
    book = _add(title="Mystery Book")
    ai_result = {
        "ok": True, "series_name": "Some Series", "series_name_snapped": False,
        "books": [], "not_in_series": [], "unranked": [book.id],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "unknown"
    assert row["proposed_index"] is None


# --- 7. Series name snaps to the library's own spelling --------------------

def test_series_name_snaps_to_library_spelling(app):
    book = _add(title="Kråkflickan del 1")
    ai_result = {
        "ok": True, "series_name": "Kråkflickan", "series_name_snapped": True,
        "books": [{"id": book.id, "index": "1", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata,
        known_series={"kråkflickan": "Kråkflickan"},
    )

    group = proposal["groups"][0]
    assert group["series_name"] == "Kråkflickan"
    assert group["series_name_snapped"] is True


# --- 8. Duplicate indexes and a gap land in warnings -----------------------

def test_duplicate_and_gap_warnings(app):
    b1 = _add(title="Book A")
    b2 = _add(title="Book B")
    b3 = _add(title="Book C")
    ai_result = {
        "ok": True, "series_name": "Some Series", "series_name_snapped": False,
        "books": [
            {"id": b1.id, "index": "1", "confidence": "medium", "reason": "r"},
            {"id": b2.id, "index": "1", "confidence": "medium", "reason": "r"},
            {"id": b3.id, "index": "3", "confidence": "medium", "reason": "r"},
        ],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [b1, b2, b3], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    warnings = proposal["groups"][0]["warnings"]
    assert warnings["duplicate_indexes"] == ["1"]
    assert warnings["gaps"] == ["2"]


# --- 9. A single unconfirmed book is never pre-checked ----------------------

def test_single_unconfirmed_book_is_downgraded_to_low_confidence(app):
    book = _add(title="Lonely Book")
    ai_result = {
        "ok": True, "series_name": "Some Series", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "1", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "ai_only"
    assert row["confidence"] == "low"


# --- 10. A Wikidata lookup that raises never crashes the proposal ---------

def test_wikidata_exception_does_not_stop_the_proposal(app):
    b1 = _add(title="Book A")
    b2 = _add(title="Book B")
    ai_result = {
        "ok": True, "series_name": "Some Series", "series_name_snapped": False,
        "books": [
            {"id": b1.id, "index": "1", "confidence": "high", "reason": "r"},
            {"id": b2.id, "index": "2", "confidence": "high", "reason": "r"},
        ],
        "not_in_series": [], "unranked": [],
    }

    def _boom(title, author):
        raise RuntimeError("wikidata is down")

    proposal = build_series_proposal(
        [b1, b2], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_boom, known_series={},
    )

    assert proposal["ok"] is True
    statuses = [r["status"] for r in proposal["groups"][0]["rows"]]
    assert "confirmed" not in statuses


# --------------------------------------------------------------------------
# propose_series_order — patch requests.post and ai_is_configured
# --------------------------------------------------------------------------

def _books_payload(n):
    return [
        {"id": i, "title": f"Book {i}", "author": "A", "series": "",
         "series_index": "", "published_date": "", "file_name": ""}
        for i in range(1, n + 1)
    ]


def _ai_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {},
    }
    return resp


# --- 11. Too many books → too_many, no HTTP call ---------------------------

def test_too_many_books_is_rejected_without_a_request():
    books = _books_payload(MAX_SERIES_BOOKS + 1)
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post") as post:
        result = propose_series_order(books)

    assert result == {"ok": False, "error": "too_many"}
    post.assert_not_called()


# --- 12. Hallucinated ids filtered; both-lists id lands only in not_in_series

def test_hallucinated_and_overlapping_ids_are_sanitized():
    books = _books_payload(2)
    answer = {
        "series_name": "Series",
        "books": [
            {"id": 1, "index": "1", "confidence": "high", "reason": "r"},
            {"id": 2, "index": "2", "confidence": "high", "reason": "r"},
            {"id": 999, "index": "9", "confidence": "high", "reason": "hallucinated"},
        ],
        "not_in_series": [2],
    }
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = propose_series_order(books)

    assert result["ok"] is True
    kept_ids = [b["id"] for b in result["books"]]
    assert kept_ids == [1]
    assert 999 not in kept_ids
    assert result["not_in_series"] == [2]


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

from flask_babel import Babel

from app.routes.metadata import metadata_bp


@pytest.fixture
def route_app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "r.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    covers = tmp_path / "covers"
    covers.mkdir()
    app.config["COVER_DIR"] = str(covers)
    db.init_app(app)
    Babel(app)
    app.register_blueprint(metadata_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


# --- 13. /propose never writes ---------------------------------------------

def test_propose_route_never_writes(route_app):
    """The read-only invariant, proven at the HTTP boundary.

    The AI and Wikidata are stubbed so the route walks its whole real path
    and returns actual rows — a test that let the AI fall through to
    "not configured" would assert nothing, since an error return never
    reaches the writer either.
    """
    with route_app.app_context():
        item = _add(title="Kråkflickan", series="Kråkflickan", series_index="1")
        item_id = item.id
        before = item.series_index

    ai_result = {
        "ok": True, "series_name": "Kråkflickan", "series_name_snapped": False,
        "books": [{"id": item_id, "index": "2", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    with patch("app.services.series_batch.propose_series_order",
               _fake_ai(ai_result)), \
         patch("app.services.series_batch._default_wikidata_lookup",
               _no_wikidata), \
         patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        resp = route_app.test_client().post(
            "/metadata/series/propose", json={"item_ids": [item_id]}
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    # The proposal really did produce a change to review...
    assert body["groups"][0]["rows"][0]["proposed_index"] == "2"
    # ...and still nothing was written.
    writer.assert_not_called()
    with route_app.app_context():
        assert db.session.get(LibraryItem, item_id).series_index == before


# --- 13b. Wikidata is only consulted when it can change the answer ---------

def test_wikidata_is_not_asked_for_rows_the_library_already_decides(app):
    """A conflict and an unchanged row are settled by what is recorded, and
    an excluded book has no number to confirm. Asking Wikidata about them is
    a SPARQL round trip per book that the user waits through for nothing.
    """
    conflicting = _add(title="Book A", series="S", series_index="9")
    unchanged = _add(title="Book B", series="S", series_index="2")
    excluded = _add(title="Book C")
    ai_result = {
        "ok": True, "series_name": "S", "series_name_snapped": False,
        "books": [
            {"id": conflicting.id, "index": "1", "confidence": "high", "reason": "r"},
            {"id": unchanged.id, "index": "2", "confidence": "high", "reason": "r"},
        ],
        "not_in_series": [excluded.id], "unranked": [],
    }
    lookup = MagicMock(return_value={"ok": False, "candidates": []})

    proposal = build_series_proposal(
        [conflicting, unchanged, excluded], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=lookup, known_series={},
    )

    assert _row_for(proposal, conflicting.id)["status"] == "conflict"
    assert _row_for(proposal, unchanged.id)["status"] == "unchanged"
    assert _row_for(proposal, excluded.id)["status"] == "not_in_series"
    lookup.assert_not_called()


# --- 13c. An empty series name falls back to the library's spelling -------

def test_empty_series_name_falls_back_to_the_library(app):
    book = _add(title="Book A", series="Kråkflickan")
    ai_result = {
        "ok": True, "series_name": "", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "1", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    assert proposal["groups"][0]["series_name"] == "Kråkflickan"
    assert _row_for(proposal, book.id)["proposed_series"] == "Kråkflickan"


# --- 14. /apply with write_files=False writes DB only -----------------------

def test_apply_route_db_only_by_default(route_app):
    with route_app.app_context():
        item = _add(title="Kråkflickan")
        item_id = item.id

    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": False, "file_write_error": None}
        resp = route_app.test_client().post(
            "/metadata/series/apply",
            json={
                "write_files": False,
                "changes": [{"item_id": item_id, "series": "Kråkflickan", "series_index": "3"}],
            },
        )

    assert resp.get_json()["updated"] == 1
    kwargs = writer.call_args.kwargs
    assert kwargs["write_to_file"] is False
    assert kwargs["selected_fields"] == {"series", "series_index"}


# --- 15. /apply writes every format sibling ---------------------------------

def test_apply_route_writes_all_format_siblings(route_app):
    with route_app.app_context():
        item1 = _add(title="Kråkflickan", group_key="gk1")
        _add(title="Kråkflickan", group_key="gk1")
        item_id = item1.id

    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": False, "file_write_error": None}
        resp = route_app.test_client().post(
            "/metadata/series/apply",
            json={
                "write_files": False,
                "changes": [{"item_id": item_id, "series": "Kråkflickan", "series_index": "3"}],
            },
        )

    assert resp.get_json()["updated"] == 2
    assert writer.call_count == 2


def test_series_db_change_stamps_content_updated_at(app):
    """Deliberate, and contrary to the plan's invariant 3 — same as language.

    `series` and `series_index` are device-visible columns
    (models._DEVICE_CONTENT_COLUMNS), so ordering a series advances
    content_updated_at even with "write to the files too" left unticked,
    and a synced Kobo re-downloads the book. That is why the modal says so
    instead of promising otherwise. If this test goes red, someone removed
    those fields from that set and the UI text is now a lie.
    """
    item = _add(title="Kråkflickan", series="Kråkflickan")
    item.content_updated_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    before = item.content_updated_at

    apply_series_changes(
        [{"item_id": item.id, "series": "Kråkflickan", "series_index": "2"}],
        write_files=False,
    )

    refreshed = db.session.get(LibraryItem, item.id)
    assert refreshed.series_index == "2"
    assert refreshed.content_updated_at > before


# --------------------------------------------------------------------------
# apply_series_changes — direct service check (empty/blank series_index
# must not crash the writer call)
# --------------------------------------------------------------------------

def test_apply_series_changes_handles_blank_index(app):
    item = _add(title="Kråkflickan")
    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": False, "file_write_error": None}
        result = apply_series_changes(
            [{"item_id": item.id, "series": "Kråkflickan", "series_index": None}],
            write_files=False,
        )

    assert result["ok"] is True
    kwargs = writer.call_args.kwargs
    assert kwargs["result"]["series_index"] == ""


# --------------------------------------------------------------------------
# propose_author_series — one author's whole shelf, several series at once.
# `ai_metadata.propose_author_series(books, known_series=None)` mirrors
# `propose_series_order`'s sanitizing, but over several proposed series
# instead of one. These tests do not exist yet in production code and are
# expected to be red until the function is written.
# --------------------------------------------------------------------------

# --- 16. Too many books → too_many, no HTTP call ---------------------------

def test_author_series_too_many_books_is_rejected_without_a_request():
    from app.services.ai_metadata import propose_author_series

    books = _books_payload(MAX_SERIES_BOOKS + 1)
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post") as post:
        result = propose_author_series(books)

    assert result == {"ok": False, "error": "too_many"}
    post.assert_not_called()


# --- 17. Hallucinated id dropped; duplicate across series kept in the
#         first; an id in both a series and standalone lands only in
#         standalone ---------------------------------------------------------

def test_author_series_sanitizes_hallucinated_duplicate_and_overlapping_ids():
    from app.services.ai_metadata import propose_author_series

    books = _books_payload(3)
    answer = {
        "series": [
            {"name": "Series A", "books": [
                {"id": 1, "index": "1", "confidence": "high", "reason": "r"},
                {"id": 2, "index": "2", "confidence": "high", "reason": "r"},
                {"id": 3, "index": "3", "confidence": "high", "reason": "r"},
            ]},
            {"name": "Series B", "books": [
                {"id": 2, "index": "1", "confidence": "high", "reason": "r"},
                {"id": 999, "index": "9", "confidence": "high", "reason": "hallucinated"},
            ]},
        ],
        "standalone": [3],
    }
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = propose_author_series(books)

    assert result["ok"] is True
    assert len(result["series"]) == 1
    series_a = result["series"][0]
    assert series_a["name"] == "Series A"
    assert [b["id"] for b in series_a["books"]] == [1, 2]
    assert result["standalone"] == [3]
    assert result["unranked"] == []


# --- 18. Empty-named series dropped; a series emptied by sanitizing is
#         dropped too — their books fall through to unranked --------------

def test_author_series_drops_empty_and_emptied_series():
    from app.services.ai_metadata import propose_author_series

    books = _books_payload(4)
    answer = {
        "series": [
            {"name": "", "books": [
                {"id": 1, "index": "1", "confidence": "high", "reason": "r"},
            ]},
            {"name": "Ghost Series", "books": [
                {"id": 999, "index": "1", "confidence": "high", "reason": "r"},
            ]},
        ],
        "standalone": [],
    }
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = propose_author_series(books)

    assert result["ok"] is True
    assert result["series"] == []
    assert result["unranked"] == [1, 2, 3, 4]


# --- 19. Two series names that normalize to the same key merge ------------

def test_author_series_merges_series_with_the_same_normalized_name():
    from app.services.ai_metadata import propose_author_series

    books = _books_payload(2)
    answer = {
        "series": [
            {"name": "Harry Potter", "books": [
                {"id": 1, "index": "1", "confidence": "high", "reason": "r"},
            ]},
            {"name": "harry potter", "books": [
                {"id": 1, "index": "99", "confidence": "high", "reason": "dup"},
                {"id": 2, "index": "2", "confidence": "high", "reason": "r"},
            ]},
        ],
        "standalone": [],
    }
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = propose_author_series(books)

    assert result["ok"] is True
    assert len(result["series"]) == 1
    merged = result["series"][0]
    assert merged["name"] == "Harry Potter"
    assert [b["id"] for b in merged["books"]] == [1, 2]
    assert [b["index"] for b in merged["books"]] == ["1", "2"]  # first wins


# --- 20. Snapping to known_series; unmatched names pass through -----------

def test_author_series_snaps_known_names_and_leaves_others_alone():
    from app.services.ai_metadata import propose_author_series

    books = _books_payload(2)
    answer = {
        "series": [
            {"name": "HARRY POTTER", "books": [
                {"id": 1, "index": "1", "confidence": "high", "reason": "r"},
            ]},
            {"name": "Unknown Saga", "books": [
                {"id": 2, "index": "1", "confidence": "high", "reason": "r"},
            ]},
        ],
        "standalone": [],
    }
    known_series = {"harry potter": "Harry Potter (svensk utgåva)"}
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = propose_author_series(books, known_series=known_series)

    assert result["ok"] is True
    by_name = {s["name"]: s for s in result["series"]}
    assert "Harry Potter (svensk utgåva)" in by_name
    assert by_name["Harry Potter (svensk utgåva)"]["name_snapped"] is True
    assert "Unknown Saga" in by_name
    assert by_name["Unknown Saga"]["name_snapped"] is False


# --- 21. A book entry with no index is dropped from the series and its id
#         shows up in unranked ---------------------------------------------

def test_author_series_drops_entries_with_no_index():
    from app.services.ai_metadata import propose_author_series

    books = _books_payload(2)
    answer = {
        "series": [{"name": "S", "books": [
            {"id": 1, "index": "", "confidence": "high", "reason": "r"},
            {"id": 2, "index": "2", "confidence": "high", "reason": "r"},
        ]}],
        "standalone": [],
    }
    with patch.object(ai_metadata, "ai_is_configured", return_value=True), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = propose_author_series(books)

    assert result["ok"] is True
    assert len(result["series"]) == 1
    assert [b["id"] for b in result["series"][0]["books"]] == [2]
    assert result["unranked"] == [1]


# --------------------------------------------------------------------------
# build_author_proposal — one author's whole shelf, several series in one
# pass. DB fixture (`app`) + injected `ai_propose_author` / `wikidata_lookup`,
# same style as build_series_proposal's tests above.
# --------------------------------------------------------------------------

def _add_author(name="An Author", source="user_confirmed"):
    author = Author(canonical_name=name, source=source)
    db.session.add(author)
    db.session.commit()
    return author


def _link(item, author, position=0):
    link = BookAuthor(item_id=item.id, author_id=author.id, position=position)
    db.session.add(link)
    db.session.commit()
    return link


# --- 22. Two series + one standalone book → three groups, standalone last -

def test_author_proposal_builds_one_group_per_series_plus_a_standalone_tail(app):
    from app.services.series_batch import build_author_proposal

    author = _add_author("An Author")
    b1, b2, b3, b4, b5 = (_add(title=f"Book {n}") for n in range(1, 6))
    for b in (b1, b2, b3, b4, b5):
        _link(b, author)

    def ai_stub(books, known_series=None):
        return {
            "ok": True,
            "series": [
                {"name": "S1", "name_snapped": False, "books": [
                    {"id": b1.id, "index": "1", "confidence": "high", "reason": "r"},
                    {"id": b2.id, "index": "2", "confidence": "high", "reason": "r"},
                ]},
                {"name": "S2", "name_snapped": False, "books": [
                    {"id": b3.id, "index": "1", "confidence": "high", "reason": "r"},
                    {"id": b4.id, "index": "2", "confidence": "high", "reason": "r"},
                ]},
            ],
            "standalone": [b5.id],
            "unranked": [],
        }

    proposal = build_author_proposal(
        author.id, ai_propose_author=ai_stub, wikidata_lookup=_no_wikidata, known_series={},
    )

    assert proposal["ok"] is True
    assert proposal["author_name"] == "An Author"
    groups = proposal["groups"]
    assert len(groups) == 3
    assert groups[0]["standalone"] is False
    assert groups[1]["standalone"] is False
    tail = groups[2]
    assert tail["standalone"] is True
    assert tail["series_name"] is None
    row = next(r for r in tail["rows"] if r["item_id"] == b5.id)
    assert row["status"] == "standalone"
    assert row["proposed_series"] is None
    assert row["proposed_index"] is None


# --- 23. No standalone and no unranked books → no standalone group --------

def test_author_proposal_omits_standalone_group_when_everything_is_ranked(app):
    from app.services.series_batch import build_author_proposal

    author = _add_author("An Author")
    b1, b2 = _add(title="Book A"), _add(title="Book B")
    for b in (b1, b2):
        _link(b, author)

    def ai_stub(books, known_series=None):
        return {
            "ok": True,
            "series": [{"name": "S1", "name_snapped": False, "books": [
                {"id": b1.id, "index": "1", "confidence": "high", "reason": "r"},
                {"id": b2.id, "index": "2", "confidence": "high", "reason": "r"},
            ]}],
            "standalone": [],
            "unranked": [],
        }

    proposal = build_author_proposal(
        author.id, ai_propose_author=ai_stub, wikidata_lookup=_no_wikidata, known_series={},
    )

    assert proposal["ok"] is True
    assert len(proposal["groups"]) == 1
    assert all(not g["standalone"] for g in proposal["groups"])


# --- 24. co_authored reflects the number of book_authors rows -------------

def test_author_proposal_flags_co_authored_books(app):
    from app.services.series_batch import build_author_proposal

    author_a = _add_author("Author A")
    author_b = _add_author("Author B")
    co_book = _add(title="Co-written")
    solo_book = _add(title="Solo")
    _link(co_book, author_a, position=0)
    _link(co_book, author_b, position=1)
    _link(solo_book, author_a, position=0)

    def ai_stub(books, known_series=None):
        return {
            "ok": True, "series": [],
            "standalone": [co_book.id, solo_book.id], "unranked": [],
        }

    proposal = build_author_proposal(
        author_a.id, ai_propose_author=ai_stub, wikidata_lookup=_no_wikidata, known_series={},
    )

    tail = proposal["groups"][-1]
    co_row = next(r for r in tail["rows"] if r["item_id"] == co_book.id)
    solo_row = next(r for r in tail["rows"] if r["item_id"] == solo_book.id)
    assert co_row["co_authored"] is True
    assert solo_row["co_authored"] is False


# --- 25. Only one representative per group_key reaches the AI -------------

def test_author_proposal_sends_one_representative_per_format_group(app):
    from app.services.series_batch import build_author_proposal

    author = _add_author("An Author")
    gk_low = _add(title="Format A", group_key="gk1")
    gk_high = _add(title="Format B", group_key="gk1")
    standalone_item = _add(title="Standalone")
    for b in (gk_low, gk_high, standalone_item):
        _link(b, author)

    captured = []

    def ai_spy(books, known_series=None):
        captured.extend(books)
        ids = [b["id"] for b in books]
        return {"ok": True, "series": [], "standalone": ids, "unranked": []}

    build_author_proposal(
        author.id, ai_propose_author=ai_spy, wikidata_lookup=_no_wikidata, known_series={},
    )

    lowest_gk_id = min(gk_low.id, gk_high.id)
    sent_ids = {b["id"] for b in captured}
    assert sent_ids == {lowest_gk_id, standalone_item.id}
    assert len(captured) == 2


# --- 26. Per-group single-unconfirmed downgrade applies group by group ----

def test_author_proposal_downgrades_only_the_lone_unconfirmed_group(app):
    from app.services.series_batch import build_author_proposal

    author = _add_author("An Author")
    solo = _add(title="Lonely Book")
    t1, t2, t3 = (_add(title=f"Trio {n}") for n in range(1, 4))
    for b in (solo, t1, t2, t3):
        _link(b, author)

    def ai_stub(books, known_series=None):
        return {
            "ok": True,
            "series": [
                {"name": "Solo Series", "name_snapped": False, "books": [
                    {"id": solo.id, "index": "1", "confidence": "high", "reason": "r"},
                ]},
                {"name": "Trio Series", "name_snapped": False, "books": [
                    {"id": t1.id, "index": "1", "confidence": "medium", "reason": "r"},
                    {"id": t2.id, "index": "2", "confidence": "medium", "reason": "r"},
                    {"id": t3.id, "index": "3", "confidence": "medium", "reason": "r"},
                ]},
            ],
            "standalone": [], "unranked": [],
        }

    proposal = build_author_proposal(
        author.id, ai_propose_author=ai_stub, wikidata_lookup=_no_wikidata, known_series={},
    )

    solo_group = next(g for g in proposal["groups"] if g["series_name"] == "Solo Series")
    trio_group = next(g for g in proposal["groups"] if g["series_name"] == "Trio Series")

    solo_row = solo_group["rows"][0]
    assert solo_row["status"] == "ai_only"
    assert solo_row["confidence"] == "low"

    for row in trio_group["rows"]:
        assert row["status"] == "ai_only"
        assert row["confidence"] == "medium"


# --- 27. An author with no books → no_books, and the AI is never asked ----

def test_author_proposal_no_books_is_an_error(app):
    from app.services.series_batch import build_author_proposal

    author = _add_author("Friendless Author")

    def _boom_ai(books, known_series=None):
        raise AssertionError("ai should not be called when there are no books")

    proposal = build_author_proposal(
        author.id, ai_propose_author=_boom_ai, wikidata_lookup=_no_wikidata, known_series={},
    )

    assert proposal == {"ok": False, "error": "no_books"}


# --- 28. conflict still outranks confirmed inside an author group ---------

def test_author_proposal_conflict_outranks_confirmed(app):
    from app.services.series_batch import build_author_proposal

    author = _add_author("An Author")
    book = _add(title="Kråkflickan", series="Kråkflickan", series_index="5")
    _link(book, author)

    def ai_stub(books, known_series=None):
        return {
            "ok": True,
            "series": [{"name": "Kråkflickan", "name_snapped": False, "books": [
                {"id": book.id, "index": "3", "confidence": "high", "reason": "r"},
            ]}],
            "standalone": [], "unranked": [],
        }

    proposal = build_author_proposal(
        author.id, ai_propose_author=ai_stub,
        wikidata_lookup=_wikidata_ordinal("Kråkflickan", "3"),  # agrees with the proposal
        known_series={},
    )

    group = proposal["groups"][0]
    row = group["rows"][0]
    assert row["status"] == "conflict"
    assert row["current_index"] == "5"
    assert row["proposed_index"] == "3"


# --- 29. /metadata/series/propose-author never writes; bad author_id → 400

def test_propose_author_route_never_writes_and_validates_author_id(route_app):
    with route_app.app_context():
        author = _add_author("Kråkflickans skapare")
        book = _add(title="Kråkflickan", series="Kråkflickan", series_index="1")
        _link(book, author)
        author_id = author.id
        item_id = book.id
        before = book.series_index

    ai_result = {
        "ok": True,
        "series": [{"name": "Kråkflickan", "name_snapped": False, "books": [
            {"id": item_id, "index": "2", "confidence": "high", "reason": "r"},
        ]}],
        "standalone": [], "unranked": [],
    }

    with patch("app.services.series_batch.propose_author_series",
               lambda books, known_series=None: ai_result), \
         patch("app.services.series_batch._default_wikidata_lookup", _no_wikidata), \
         patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        resp = route_app.test_client().post(
            "/metadata/series/propose-author", json={"author_id": author_id}
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    row = next(r for r in body["groups"][0]["rows"] if r["item_id"] == item_id)
    assert row["proposed_index"] == "2"
    writer.assert_not_called()
    with route_app.app_context():
        assert db.session.get(LibraryItem, item_id).series_index == before

    resp_missing = route_app.test_client().post("/metadata/series/propose-author", json={})
    assert resp_missing.status_code == 400
    assert resp_missing.get_json() == {"ok": False, "error": "no_author"}

    resp_unknown = route_app.test_client().post(
        "/metadata/series/propose-author", json={"author_id": 999999}
    )
    assert resp_unknown.status_code == 400
    assert resp_unknown.get_json() == {"ok": False, "error": "no_author"}


# --------------------------------------------------------------------------
# 30-35. The "normalize" status — same meaning, different text on the page.
# --------------------------------------------------------------------------

# --- 30. Byte-identical text and index → unchanged --------------------------

def test_byte_identical_proposal_is_unchanged(app):
    book = _add(title="Children of Time", series="Children of Time", series_index="3")
    ai_result = {
        "ok": True, "series_name": "Children of Time", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "unchanged"


# --- 31. Same meaning, different case and zero-padding → normalize ---------

def test_case_and_padding_difference_is_normalize(app):
    book = _add(title="Children of Time", series="Children of time", series_index="03")
    ai_result = {
        "ok": True, "series_name": "Children of Time", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "normalize"


# --- 32. Case-only difference in the series name (identical index) --------

def test_series_case_only_difference_is_normalize(app):
    book = _add(title="Children of Time", series="children of time", series_index="3")
    ai_result = {
        "ok": True, "series_name": "Children of Time", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "normalize"


# --- 33. Zero-padding-only difference in the index (identical series text) -

def test_index_padding_only_difference_is_normalize(app):
    book = _add(title="Children of Time", series="Children of Time", series_index="03")
    ai_result = {
        "ok": True, "series_name": "Children of Time", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "3", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "normalize"


# --- 34. A normalize row sorts among the primary rows, not the trailing block

def test_normalize_row_sorts_with_primary_rows_by_index(app):
    from app.services.series_batch import _build_group

    ai_only_item = _add(title="AI Only Book")
    normalize_item = _add(title="Normalize Book", series="the series", series_index="01")
    unchanged_item = _add(title="Unchanged Book", series="The Series", series_index="9")

    ranked_by_id = {
        ai_only_item.id: {"id": ai_only_item.id, "index": "2", "confidence": "high", "reason": "r"},
        normalize_item.id: {"id": normalize_item.id, "index": "1", "confidence": "high", "reason": "r"},
        unchanged_item.id: {"id": unchanged_item.id, "index": "9", "confidence": "high", "reason": "r"},
    }

    group = _build_group(
        items=[ai_only_item, normalize_item, unchanged_item],
        series_name="The Series",
        series_name_snapped=False,
        ranked_by_id=ranked_by_id,
        excluded_ids=set(),
        unranked_ids=set(),
        wikidata_ordinal=lambda item: ("", ""),
    )

    statuses_by_id = {r["item_id"]: r["status"] for r in group["rows"]}
    assert statuses_by_id[normalize_item.id] == "normalize"
    assert statuses_by_id[ai_only_item.id] == "ai_only"
    assert statuses_by_id[unchanged_item.id] == "unchanged"

    ordered_ids = [r["item_id"] for r in group["rows"]]
    assert ordered_ids == [normalize_item.id, ai_only_item.id, unchanged_item.id]


# --- 35. Whitespace-only difference in the series name ---------------------
# `_norm_key` (app/services/ai_metadata.py) collapses internal whitespace via
# `" ".join(str(value or "").split())`, so "The  Expanse" and "The Expanse"
# share a norm key. With an identical index this is the same-meaning,
# different-text case → normalize, not conflict/ai_only.

def test_series_internal_whitespace_difference_is_normalize(app):
    book = _add(title="Leviathan Wakes", series="The  Expanse", series_index="1")
    ai_result = {
        "ok": True, "series_name": "The Expanse", "series_name_snapped": False,
        "books": [{"id": book.id, "index": "1", "confidence": "high", "reason": "r"}],
        "not_in_series": [], "unranked": [],
    }

    proposal = build_series_proposal(
        [book], ai_propose=_fake_ai(ai_result),
        wikidata_lookup=_no_wikidata, known_series={},
    )

    row = _row_for(proposal, book.id)
    assert row["status"] == "normalize"


# --------------------------------------------------------------------------
# 36-44. rename_series — deterministic series-name rewrite, index untouched.
# --------------------------------------------------------------------------

# --- 36. Renaming keeps each book's own series_index ------------------------

def test_rename_series_keeps_each_books_own_index(app):
    from app.services.series_batch import rename_series

    b1 = _add(title="Book 1", series="the expanse", series_index="1")
    b2 = _add(title="Book 2", series="The Expance", series_index="2")
    b3 = _add(title="Book 3", series="The Expanse", series_index="3")

    result = rename_series([b1.id, b2.id, b3.id], "The Expanse")

    assert result["ok"] is True
    for item, expected_index in ((b1, "1"), (b2, "2"), (b3, "3")):
        refreshed = db.session.get(LibraryItem, item.id)
        assert refreshed.series == "The Expanse"
        assert refreshed.series_index == expected_index


# --- 37. A blank name is rejected and nothing is written --------------------

def test_rename_series_blank_name_writes_nothing(app):
    from app.services.series_batch import rename_series

    book = _add(title="Book 1", series="Old Name", series_index="1")

    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        result = rename_series([book.id], "   ")

    assert result == {"ok": False, "error": "no_name"}
    writer.assert_not_called()
    refreshed = db.session.get(LibraryItem, book.id)
    assert refreshed.series == "Old Name"
    assert refreshed.series_index == "1"


# --- 38. Empty item_ids is rejected -----------------------------------------

def test_rename_series_no_books_is_an_error(app):
    from app.services.series_batch import rename_series

    result = rename_series([], "The Expanse")
    assert result == {"ok": False, "error": "no_books"}


# --- 39. The name is whitespace-normalized on the way in and out -----------

def test_rename_series_normalizes_whitespace_in_the_name(app):
    from app.services.series_batch import rename_series

    book = _add(title="Book 1", series="Old Name", series_index="1")

    result = rename_series([book.id], "  The   Expanse  ")

    assert result["series_name"] == "The Expanse"
    refreshed = db.session.get(LibraryItem, book.id)
    assert refreshed.series == "The Expanse"


# --- 40. write_files=False writes DB only, never the file -------------------

def test_rename_series_write_files_false_is_db_only(app):
    from app.services.series_batch import rename_series

    book = _add(title="Book 1", series="Old Name", series_index="1")

    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": False, "file_write_error": None}
        rename_series([book.id], "New Name", write_files=False)

    assert writer.call_count == 1
    kwargs = writer.call_args.kwargs
    assert kwargs["write_to_file"] is False
    assert kwargs["selected_fields"] == {"series", "series_index"}


# --- 41. Format siblings sharing a group_key are both renamed --------------

def test_rename_series_renames_all_format_siblings(app):
    from app.services.series_batch import rename_series

    item1 = _add(title="Book 1", series="Old Name", series_index="1", group_key="gk1")
    item2 = _add(title="Book 1 (mobi)", series="Old Name", series_index="1", group_key="gk1")

    result = rename_series([item1.id], "New Name")

    assert result["updated"] == 2
    for item in (item1, item2):
        refreshed = db.session.get(LibraryItem, item.id)
        assert refreshed.series == "New Name"


# --- 42. Route: renaming via POST /metadata/series/rename -------------------

def test_rename_route_renames_books(route_app):
    with route_app.app_context():
        item = _add(title="Book 1", series="Old Name", series_index="1")
        item_id = item.id

    resp = route_app.test_client().post(
        "/metadata/series/rename",
        json={"item_ids": [item_id], "series": "New Name"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    with route_app.app_context():
        assert db.session.get(LibraryItem, item_id).series == "New Name"


# --- 43. Route: a blank series name is rejected with HTTP 400 --------------

def test_rename_route_blank_series_is_bad_request(route_app):
    with route_app.app_context():
        item = _add(title="Book 1", series="Old Name", series_index="1")
        item_id = item.id

    resp = route_app.test_client().post(
        "/metadata/series/rename",
        json={"item_ids": [item_id], "series": "   "},
    )

    assert resp.status_code == 400
    assert resp.get_json() == {"ok": False, "error": "no_name"}
    with route_app.app_context():
        assert db.session.get(LibraryItem, item_id).series == "Old Name"
