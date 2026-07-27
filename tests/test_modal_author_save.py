# Colophon – modal save author semantics (DESIGN-robust-author-links.md)
"""save-json free-text author: a name the user types in the edit modal is
a deliberate act — a brand-new name becomes a user_confirmed entry
(the modal hint promises "saving confirms the spelling"), while a fuzzy
near-match keeps its 'review' proposal so the typo guard still runs."""
from unittest.mock import patch

import pytest
from flask import Flask

from app.models import db, Author, LibraryItem
from app.routes.metadata import metadata_bp
from app.services.author_resolver import resolve_pending_authors


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.register_blueprint(metadata_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _resolved_item(author="Larry Enright"):
    item = LibraryItem(
        title="A Book",
        author=author,
        file_path="/books/x.epub",
        file_name="x.epub",
        extension=".epub",
    )
    db.session.add(item)
    resolve_pending_authors(db.session)
    db.session.commit()
    return item


def _save(client, item, author):
    with patch(
        "app.routes.metadata.write_metadata_to_file",
        return_value={"ok": True},
    ):
        return client.post(
            f"/metadata/{item.id}/save-json",
            json={"title": item.title, "author": author},
        )


def test_typed_brand_new_author_is_user_confirmed(client):
    item = _resolved_item()

    body = _save(client, item, "Ursula K. Le Guin").get_json()

    assert body["ok"] is True
    assert body["author_status"] == "linked"
    entry = db.session.get(Author, item.author_id)
    assert entry.canonical_name == "Ursula K. Le Guin"
    assert entry.source == "user_confirmed"
    assert item.suggested_author_id is None


def test_typed_near_match_keeps_review_proposal(client):
    known = Author(canonical_name="J.R.R. Tolkien", source="user_confirmed")
    db.session.add(known)
    db.session.flush()
    item = _resolved_item()

    body = _save(client, item, "J.R.R. Tolkein").get_json()  # typo

    # The typo guard still gets a say: linked to the literal entry, but the
    # entry stays tentative and the proposal points at the near-match.
    assert body["author_status"] == "review"
    entry = db.session.get(Author, item.author_id)
    assert entry.canonical_name == "J.R.R. Tolkein"
    assert entry.source == "tentative"
    assert item.suggested_author_id == known.id


def test_unchanged_author_field_promotes_nothing(client):
    item = _resolved_item()
    entry_before = db.session.get(Author, item.author_id)
    assert entry_before.source == "tentative"

    body = _save(client, item, item.author).get_json()  # untouched field

    assert body["ok"] is True
    entry = db.session.get(Author, item.author_id)
    assert entry.source == "tentative"  # no silent confirmation


def test_typed_existing_author_links_without_new_entry(client):
    known = Author(canonical_name="Vernor Vinge", source="user_confirmed")
    db.session.add(known)
    db.session.flush()
    item = _resolved_item()

    body = _save(client, item, "Vernor Vinge").get_json()

    assert body["author_status"] == "linked"
    assert item.author_id == known.id
