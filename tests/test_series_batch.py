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

from app.models import db, LibraryItem
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
