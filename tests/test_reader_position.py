# Colophon – e-book metadata manager
"""Exact position between the browser reader and a Kobo.

The reader posts "chapter X, N non-whitespace characters in"; the server turns
that into the KoboSpan the device would have used, and back again on resume.
These tests pin the route contract — the translation itself lives in
tests/test_kobo_location.py.
"""
import json
import zipfile

import pytest

KEPUB_CHAPTER = (
    "<html><body><div id=\"book-inner\">"
    "<style class=\"kobostylehacks\">div#book-inner { margin-top: 0; }</style>"
    "<p><span class=\"koboSpan\" id=\"kobo.1.1\">First sentence here. </span>"
    "<span class=\"koboSpan\" id=\"kobo.1.2\">Second one follows.</span></p>"
    "<p><span class=\"koboSpan\" id=\"kobo.2.1\">A later paragraph.</span></p>"
    "</div></body></html>"
)

CHAPTER = "OEBPS/chapter001.xhtml"


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app
    from app.models import db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True

    def _wipe():
        with flask_app.app_context():
            db.session.execute(text("DELETE FROM kobo_book_states"))
            db.session.execute(text("DELETE FROM library_items"))
            db.session.commit()

    _wipe()

    # Every item in these tests resolves to the same tiny KEPUB.
    kepub = tmp_path / "book.kepub.epub"
    with zipfile.ZipFile(kepub, "w") as z:
        z.writestr(CHAPTER, KEPUB_CHAPTER)
    monkeypatch.setattr(
        "app.services.kobo_location._kepub_path", lambda item: str(kepub)
    )

    yield flask_app
    _wipe()


@pytest.fixture
def client(app):
    return app.test_client()


def _make_item(**kwargs):
    from app.models import LibraryItem, db

    item = LibraryItem(
        title=kwargs.pop("title", "Position Book"),
        file_path=kwargs.pop("file_path", "/books/position.epub"),
        file_name="position.epub",
        extension=".epub",
        **kwargs,
    )
    db.session.add(item)
    db.session.commit()
    return item.id


def test_progress_with_an_offset_stores_the_matching_span(app, client):
    """The browser -> Kobo direction, which used to be chapter-level at best."""
    from app.models import LibraryItem

    with app.app_context():
        item_id = _make_item()

    resp = client.post(
        f"/reader/{item_id}/progress",
        json={"percent": 40.0, "status": "Reading", "href": CHAPTER, "offset": 25},
    )
    assert resp.status_code == 200

    with app.app_context():
        item = LibraryItem.query.get(item_id)
        stored = json.loads(item.read_location_json)
        # "Firstsentencehere." is 18 dense chars, so 25 lands in the second span.
        assert stored == {
            "Source": CHAPTER, "Type": "KoboSpan", "Value": "kobo.1.2",
        }
        assert item.read_location == "kobo.1.2"
        assert item.read_progress == 40.0


def test_progress_without_an_offset_still_clears_a_stale_location(app, client):
    """The v1.41.0 behaviour has to survive: a reader that can't offer a
    position must not leave an old one next to a newer percentage."""
    from app.models import LibraryItem

    stale = {"Source": "OEBPS/chapter099.xhtml", "Type": "KoboSpan", "Value": "kobo.4.1"}
    with app.app_context():
        item_id = _make_item(
            read_status="Reading",
            read_progress=10.0,
            read_location="kobo.4.1",
            read_location_json=json.dumps(stale),
        )

    client.post(
        f"/reader/{item_id}/progress", json={"percent": 55.0, "status": "Reading"}
    )

    with app.app_context():
        item = LibraryItem.query.get(item_id)
        assert item.read_location_json is None
        assert item.read_location is None
        assert item.read_progress == 55.0


def test_an_unresolvable_offset_does_not_invent_a_location(app, client):
    """A chapter we can't find in the KEPUB must fall back, not guess."""
    from app.models import LibraryItem

    with app.app_context():
        item_id = _make_item()

    client.post(
        f"/reader/{item_id}/progress",
        json={
            "percent": 40.0, "status": "Reading",
            "href": "OEBPS/not-in-this-book.xhtml", "offset": 25,
        },
    )

    with app.app_context():
        assert LibraryItem.query.get(item_id).read_location_json is None


def test_reader_page_offers_the_stored_position_back_as_an_offset(app, client):
    """The Kobo -> browser direction. The reader can't read KoboSpans, so the
    page hands it the character offset instead."""
    stored = {"Source": CHAPTER, "Type": "KoboSpan", "Value": "kobo.2.1"}
    with app.app_context():
        item_id = _make_item(
            read_status="Reading",
            read_progress=70.0,
            read_location="kobo.2.1",
            read_location_json=json.dumps(stored),
        )

    html = client.get(f"/reader/{item_id}").get_data(as_text=True)
    # "Firstsentencehere." + "Secondonefollows." = 18 + 17 dense characters.
    assert f'resumeHref: "{CHAPTER}"' in html
    assert "resumeOffset: 35" in html


def test_reader_page_without_a_stored_position_offers_nothing(app, client):
    with app.app_context():
        item_id = _make_item(read_status="Reading", read_progress=70.0)

    html = client.get(f"/reader/{item_id}").get_data(as_text=True)
    assert "resumeHref: null" in html
    assert "resumeOffset: null" in html


def test_round_trip_browser_to_span_to_browser(app, client):
    """Post an offset, read the page back, and land on the same offset.

    Resume now uses the recorded position, so it is the same number.
    """
    from app.models import LibraryItem

    with app.app_context():
        item_id = _make_item()

    client.post(
        f"/reader/{item_id}/progress",
        json={"percent": 40.0, "status": "Reading", "href": CHAPTER, "offset": 40},
    )
    html = client.get(f"/reader/{item_id}").get_data(as_text=True)

    with app.app_context():
        item = LibraryItem.query.get(item_id)
        assert json.loads(item.read_location_json)["Value"] == "kobo.2.1"
    # The stored position is exact (40), no longer snapped to the span start
    # (35) — the span-derived anchor is only the fallback without a position.
    assert "resumeOffset: 40" in html


def _epoch_ms(dt):
    from datetime import datetime
    return int((dt - datetime(1970, 1, 1)).total_seconds() * 1000)


def test_reset_guard_drops_stale_offline_progress(app, client):
    """A reset (ReadyToRead + NULL progress + bumped read_last_modified) must
    not be undone by a delayed offline flush stamped BEFORE the reset. The
    global flusher (offline-progress-sync.js) sends progress for every
    offline-read book on reconnect, so this guard is what keeps a reset done on
    another device from being resurrected."""
    from datetime import datetime
    from app.models import LibraryItem

    reset_at = datetime(2026, 1, 1, 12, 0, 0)
    with app.app_context():
        item_id = _make_item(
            read_status="ReadyToRead", read_progress=None, read_last_modified=reset_at
        )

    resp = client.post(
        f"/reader/{item_id}/progress",
        json={"percent": 50.0, "status": "Reading", "savedAt": _epoch_ms(reset_at) - 60000},
    )
    assert resp.status_code == 200
    assert resp.get_json()["applied"] is False
    with app.app_context():
        item = LibraryItem.query.get(item_id)
        assert item.read_progress is None
        assert item.read_status == "ReadyToRead"


def test_reset_guard_lets_through_progress_made_after_reset(app, client):
    """Progress stamped AFTER the reset is real reading and must apply — the
    guard only fires for the exact stale-post case."""
    from datetime import datetime
    from app.models import LibraryItem

    reset_at = datetime(2026, 1, 1, 12, 0, 0)
    with app.app_context():
        item_id = _make_item(
            read_status="ReadyToRead", read_progress=None, read_last_modified=reset_at
        )

    resp = client.post(
        f"/reader/{item_id}/progress",
        json={"percent": 50.0, "status": "Reading", "savedAt": _epoch_ms(reset_at) + 60000},
    )
    assert resp.status_code == 200
    assert resp.get_json()["applied"] is True
    with app.app_context():
        item = LibraryItem.query.get(item_id)
        assert item.read_progress == 50.0


def _position(app, item_id):
    from app.models import LibraryItem

    with app.app_context():
        raw = LibraryItem.query.get(item_id).read_position_json
        return json.loads(raw) if raw else None


def test_backward_post_drops_progress_but_moves_position(app, client):
    """Furthest-read-wins for progress, last-write-wins for position."""
    from app.models import LibraryItem

    with app.app_context():
        item_id = _make_item()
    client.post(f"/reader/{item_id}/progress", json={
        "percent": 60.0, "status": "Reading", "href": CHAPTER, "offset": 40})
    resp = client.post(f"/reader/{item_id}/progress", json={
        "percent": 20.0, "status": "Reading", "href": CHAPTER, "offset": 5})
    assert resp.get_json()["applied"] is False
    pos = _position(app, item_id)
    assert pos["offset"] == 5 and pos["source"] == CHAPTER
    assert pos["percent"] == 20.0 and pos["origin"] == "reader"
    with app.app_context():
        assert LibraryItem.query.get(item_id).read_progress == 60.0


def test_stale_saved_at_does_not_overwrite_position(app, client):
    import time

    now = int(time.time() * 1000)
    with app.app_context():
        item_id = _make_item()
    client.post(f"/reader/{item_id}/progress", json={
        "percent": 30.0, "status": "Reading", "href": CHAPTER, "offset": 30,
        "savedAt": now})
    client.post(f"/reader/{item_id}/progress", json={
        "percent": 30.0, "status": "Reading", "href": CHAPTER, "offset": 3,
        "savedAt": now - 60000})
    assert _position(app, item_id)["offset"] == 30


def test_reader_page_prefers_position_over_kobo_location(app, client):
    stored = {"Source": CHAPTER, "Type": "KoboSpan", "Value": "kobo.2.1"}
    with app.app_context():
        item_id = _make_item(
            read_status="Reading", read_progress=70.0,
            read_location="kobo.2.1", read_location_json=json.dumps(stored),
            read_position_json=json.dumps({
                "source": CHAPTER, "offset": 7, "percent": 12.5, "page": None,
                "at": 1234, "origin": "reader"}),
        )
    html = client.get(f"/reader/{item_id}").get_data(as_text=True)
    assert "resumeOffset: 7" in html
    assert "resumePercent: 12.5" in html
    assert "resumeAt: 1234" in html


def test_reset_clears_position(app, client):
    with app.app_context():
        item_id = _make_item()
    client.post(f"/reader/{item_id}/progress", json={
        "percent": 30.0, "status": "Reading", "href": CHAPTER, "offset": 30})
    assert _position(app, item_id) is not None
    client.post(f"/metadata/{item_id}/reset-read")
    assert _position(app, item_id) is None


def test_applied_kobo_put_records_a_kobo_position(app, client):
    from app.models import LibraryItem
    from app.routes.kobo import _book_uuid
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Position device")
        item_id = _make_item()
        book_uuid = _book_uuid(LibraryItem.query.get(item_id))
    put = client.put(
        f"/kobo/{token}/v1/library/{book_uuid}/state",
        json={"ReadingStates": [{
            "StatusInfo": {"Status": "Reading", "LastModified": "2026-05-28T10:00:00.000Z"},
            "CurrentBookmark": {
                "ProgressPercent": 33.0,
                "Location": {"Source": CHAPTER, "Value": "kobo.2.1", "Type": "KoboSpan"},
            },
            "LastModified": "2026-05-28T10:00:00.000Z",
        }]},
    )
    assert put.status_code == 200
    pos = _position(app, item_id)
    assert pos["origin"] == "kobo" and pos["offset"] == 35
    assert pos["source"] == CHAPTER and pos["percent"] == 33.0
