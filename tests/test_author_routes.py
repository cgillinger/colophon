# Colophon – tests for the author registry endpoints + curation cascades
"""authors_bp routes and the step-4 curation layer in author_resolver:
assign/confirm semantics, rename/merge cascades (with the listener
suppression), the create-time fuzzy guard, and the manage-view overview.
"""
import pytest
from flask import Flask

from app.models import db, Author, AuthorAlias, LibraryItem
from app.routes.authors import authors_bp
from app.services.author_resolver import (
    STATUS_LINKED,
    STATUS_NEW,
    STATUS_REVIEW,
    merge_authors,
    rename_author,
    resolve_pending_authors,
)


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.register_blueprint(authors_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


_counter = iter(range(1, 10_000))


def _add_item(author, title="A Book"):
    n = next(_counter)
    item = LibraryItem(
        title=title,
        author=author,
        file_path=f"/books/r-{n}.epub",
        file_name=f"r-{n}.epub",
        extension=".epub",
    )
    db.session.add(item)
    db.session.flush()
    return item


def _author(name, source="user_confirmed"):
    author = Author(canonical_name=name, source=source)
    db.session.add(author)
    db.session.flush()
    return author


# --------------------------------------------------------------------------
# assign — the combobox commit
# --------------------------------------------------------------------------

def test_assign_existing_links_and_promotes(client):
    author = _author("J.R.R. Tolkien", source="tentative")
    item = _add_item("Tolkein")  # was a review case
    db.session.commit()

    resp = client.post(f"/authors/items/{item.id}/assign",
                       json={"author_id": author.id})
    body = resp.get_json()

    assert body["ok"] is True
    assert item.author == "J.R.R. Tolkien"          # canonical on the item
    assert item.author_id == author.id
    assert item.author_status == STATUS_LINKED
    assert author.source == "user_confirmed"        # earned by confirmation
    # The old variant (typo included) became a cross-reference.
    assert AuthorAlias.query.filter_by(variant_key="tolkein").one().author_id == author.id


def test_assign_new_name_blocked_by_fuzzy_guard(client):
    _author("J.R.R. Tolkien")
    item = _add_item("J.R.R. Tolkein")
    db.session.commit()

    resp = client.post(f"/authors/items/{item.id}/assign",
                       json={"name": "J.R.R. Tolkein"})
    body = resp.get_json()

    # Guard 2: "1 character from Tolkien — sure it's a new author?"
    assert body["ok"] is False
    assert body["error"] == "similar_exists"
    assert body["similar"][0]["name"] == "J.R.R. Tolkien"
    assert Author.query.count() == 1  # nothing created


def test_assign_new_name_force_creates_confirmed(client):
    _author("J.R.R. Tolkien")
    item = _add_item("J.R.R. Tolkein")
    db.session.commit()

    resp = client.post(f"/authors/items/{item.id}/assign",
                       json={"name": "J.R.R. Tolkein", "force": True})
    body = resp.get_json()

    assert body["ok"] is True and body["created"] is True
    created = db.session.get(Author, item.author_id)
    assert created.canonical_name == "J.R.R. Tolkein"
    assert created.source == "user_confirmed"


def test_assign_typed_name_matching_existing_reuses_entry(client):
    author = _author("Astrid Lindgren")
    item = _add_item(None)
    db.session.commit()

    resp = client.post(f"/authors/items/{item.id}/assign",
                       json={"name": "Lindgren, Astrid"})  # signature variant
    assert resp.get_json()["ok"] is True
    assert item.author_id == author.id
    assert Author.query.count() == 1


# --------------------------------------------------------------------------
# rename / merge cascades
# --------------------------------------------------------------------------

def test_rename_cascades_to_all_books(app):
    author = _author("Tolkein", source="tentative")
    items = [_add_item(None) for _ in range(3)]
    for it in items:
        it.author = "Tolkein"
        it.author_id = author.id
        it.author_status = STATUS_LINKED
    db.session.commit()

    count = rename_author(db.session, author, "J.R.R. Tolkien")
    db.session.commit()

    assert count == 3
    for it in items:
        assert it.author == "J.R.R. Tolkien"
        assert it.author_id == author.id          # link survived the relabel
        assert it.author_status == STATUS_LINKED  # listener was suppressed
    assert author.source == "user_confirmed"
    # Old canonical survives as a cross-reference.
    assert AuthorAlias.query.filter_by(variant_key="tolkein").count() == 1


def test_rename_to_other_entrys_name_is_rejected(app):
    _author("J.R.R. Tolkien")
    other = _author("Tolkein")
    with pytest.raises(ValueError):
        rename_author(db.session, other, "Tolkien, J.R.R.")  # signature clash


def test_merge_moves_books_aliases_and_ids(app):
    target = _author("J.R.R. Tolkien")
    source = _author("Tolkein", source="tentative")
    source.wikidata_qid = "Q892"
    db.session.add(AuthorAlias(variant_key="tolkein", author_id=source.id))
    item = _add_item("Tolkein")
    item.author_id = source.id
    item.author_status = STATUS_LINKED
    db.session.commit()

    count = merge_authors(db.session, source, target)
    db.session.commit()

    assert count == 1
    assert item.author == "J.R.R. Tolkien"
    assert item.author_id == target.id
    assert target.wikidata_qid == "Q892"           # filled the empty slot
    assert db.session.get(Author, source.id) is None
    assert AuthorAlias.query.filter_by(variant_key="tolkein").one().author_id == target.id


def test_merge_endpoint(client):
    target = _author("J.R.R. Tolkien")
    source = _author("Tolkein")
    db.session.commit()
    resp = client.post(f"/authors/{source.id}/merge", json={"target_id": target.id})
    assert resp.get_json()["ok"] is True
    assert db.session.get(Author, source.id) is None


# --------------------------------------------------------------------------
# search / suggestions / confirm / delete
# --------------------------------------------------------------------------

def test_search_finds_signature_variant_first(client):
    _author("J.R.R. Tolkien")
    _author("Astrid Lindgren")
    db.session.commit()
    body = client.get("/authors/search?q=Tolkien, JRR").get_json()
    assert body["authors"][0]["name"] == "J.R.R. Tolkien"


def test_item_suggestions_for_review_case(client):
    _author("J.R.R. Tolkien")
    item = _add_item("J.R.R. Tolkein")
    db.session.commit()
    resolve_pending_authors(db.session, [item])
    db.session.commit()
    assert item.author_status == STATUS_REVIEW

    body = client.get(f"/authors/items/{item.id}/suggestions").get_json()
    assert body["author_status"] == STATUS_REVIEW
    assert body["suggestions"][0]["name"] == "J.R.R. Tolkien"
    assert body["suggestions"][0]["score"] >= 0.85


def test_confirm_promotes_tentative(client):
    author = _author("Selma Lagerlöf", source="tentative")
    db.session.commit()
    body = client.post(f"/authors/{author.id}/confirm").get_json()
    assert body["author"]["source"] == "user_confirmed"


def test_delete_refuses_when_in_use(client):
    author = _author("Selma Lagerlöf")
    item = _add_item("Selma Lagerlöf")
    item.author_id = author.id
    item.author_status = STATUS_LINKED
    db.session.commit()

    resp = client.post(f"/authors/{author.id}/delete")
    assert resp.status_code == 409
    assert db.session.get(Author, author.id) is not None


def test_delete_unused_entry(client):
    author = _author("Oanvänd Författare", source="tentative")
    db.session.add(AuthorAlias(variant_key="oanvänd författare", author_id=author.id))
    db.session.commit()
    resp = client.post(f"/authors/{author.id}/delete")
    assert resp.get_json()["ok"] is True
    assert Author.query.count() == 0
    assert AuthorAlias.query.count() == 0
