# Colophon – the cover scenario ("Fetch covers for these")
"""The filter-driven cover flow is the one scenario that still drives the
generic enrichment engine. Two things have to hold.

1. Applying a cover is a *narrow* write. It sets the cover and nothing
   else — and it refreshes `completeness_score`, because the traffic light
   in the library view reads that number and the cover weighs 3 of its 10.
   `cover_apply_json` already did; the form route the batch used did not,
   so a batch of covers left every dot and counter one band too red.

2. The flow previews before it writes. It asks the stream for a dry run,
   exactly like every other scenario, and applies per book from the review
   grid. The spec for this step originally said to run the stream *without*
   `dry_run` — that would write auto-applied text fields to the files with
   no review, which is what invariant 1 of the plan forbids. The cover URL
   is in `book_done` either way (the pipeline downloads a `preview_<id>`
   file regardless), so there is nothing to gain by it.
"""
import os
import re
from unittest.mock import patch

import pytest
from flask import Flask
from flask_babel import Babel

from app.models import db, LibraryItem
from app.routes.metadata import metadata_bp
from app.services.grouping import compute_group_key
from app.services.metadata_pipeline import completeness_score

_JS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "static", "js",
)


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    cover_dir = tmp_path / "covers"
    cover_dir.mkdir()
    app.config["COVER_DIR"] = str(cover_dir)
    db.init_app(app)
    Babel(app)
    app.register_blueprint(metadata_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _add_item():
    item = LibraryItem(
        title="A Book Without A Cover",
        author="Some Author",
        description="A synopsis long enough to count as present for the scorer.",
        publisher="A Publisher",
        genres="Science Fiction",
        published_date="2019",
        series="A Series",
        file_path="/books/a.epub",
        file_name="a.epub",
        extension=".epub",
    )
    item.group_key = compute_group_key(item.title, item.author)
    item.completeness_score = completeness_score(item)
    db.session.add(item)
    db.session.commit()
    return item


def _fake_cover(app, item_id):
    """A cover big enough not to read as a placeholder (>= 5 kB)."""
    path = os.path.join(app.config["COVER_DIR"], f"{item_id}.jpg")
    with open(path, "wb") as fh:
        fh.write(b"\xff" * 6000)
    return path


def test_apply_cover_refreshes_the_completeness_score(client, app):
    """The dot and its counters read this number; a cover is worth 3 of 10."""
    with app.app_context():
        item = _add_item()
        item_id = item.id
        before = item.completeness_score
        assert before == 3, "only the cover should be missing in this fixture"
        path = _fake_cover(app, item_id)

        with patch("app.routes.metadata.download_cover_to_file", return_value=path), \
             patch("app.routes.metadata.write_metadata_to_file",
                   return_value={"ok": True, "error": None}):
            client.post(
                f"/metadata/{item_id}/cover/apply",
                data={"cover_url": "http://example.invalid/c.jpg"},
            )

        refreshed = db.session.get(LibraryItem, item_id)
        assert refreshed.cover_path == path
        assert refreshed.completeness_score == 0


def test_apply_cover_touches_nothing_but_the_cover(client, app):
    with app.app_context():
        item = _add_item()
        item_id = item.id
        snapshot = {
            f: getattr(item, f)
            for f in ("title", "author", "description", "publisher",
                      "genres", "published_date", "series", "isbn", "language")
        }
        path = _fake_cover(app, item_id)

        with patch("app.routes.metadata.download_cover_to_file", return_value=path), \
             patch("app.routes.metadata.write_metadata_to_file",
                   return_value={"ok": True, "error": None}):
            client.post(
                f"/metadata/{item_id}/cover/apply",
                data={"cover_url": "http://example.invalid/c.jpg"},
            )

        refreshed = db.session.get(LibraryItem, item_id)
        for field, value in snapshot.items():
            assert getattr(refreshed, field) == value, field


def test_cover_flow_asks_the_stream_for_a_dry_run():
    """Invariant 1: no batch flow writes before the user has reviewed."""
    with open(os.path.join(_JS_DIR, "covers-batch.js"), encoding="utf-8") as fh:
        source = fh.read()
    assert "/metadata/bulk/stream" in source
    assert "dry_run=1" in source


def test_only_the_single_book_modal_streams_without_dry_run():
    """A guard on the whole frontend, not just on the file added here.

    The single-book modal writes on an explicit, one-book action and is
    outside the batch invariant. Every other caller of the stream must
    preview first; if a new one appears without `dry_run=1`, this goes red
    before it reaches the library.
    """
    allowed = {"book-modal.js"}
    offenders = []
    for name in sorted(os.listdir(_JS_DIR)):
        if not name.endswith(".js") or name in allowed:
            continue
        with open(os.path.join(_JS_DIR, name), encoding="utf-8") as fh:
            source = fh.read()
        # Every mention of the endpoint counts, however the URL is quoted or
        # assembled: the earlier version anchored on `var ` and a
        # single-quoted literal, so a `const`, a template literal or a
        # double-quoted string would have slipped past the guard entirely.
        # The window is generous enough to cover a URL built over several
        # concatenated lines, and tight enough not to borrow a `dry_run=1`
        # from an unrelated call further down the file.
        for match in re.finditer(r"metadata/bulk/stream", source):
            window = source[match.end():match.end() + 400]
            if "dry_run=1" not in window:
                offenders.append(f"{name}:{source.count(chr(10), 0, match.start()) + 1}")
    assert offenders == [], f"stream called without dry_run in: {offenders}"
