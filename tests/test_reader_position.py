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

    Not exactly the same number — the span is a chunk, so resume lands at its
    start — but within that chunk, which is the promise.
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
    # kobo.2.1 starts at 35 dense characters; 40 was 5 characters into it.
    assert "resumeOffset: 35" in html
