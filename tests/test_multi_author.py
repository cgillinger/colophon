# Colophon – tests for multi-author support (v1.36.0)
"""'&'-splitting in the resolver, book_authors links, split rules,
split_author_entity, multi-aware merge/rename cascades, set_item_authors,
and the /authors/check + /authors/<id>/split endpoints.
"""
import json

import pytest
from flask import Flask

from app.models import (
    db,
    Author,
    AuthorAlias,
    AuthorSplitRule,
    BookAuthor,
    LibraryItem,
)
from app.services.author_resolver import (
    STATUS_LINKED,
    STATUS_MISSING,
    STATUS_NEW,
    merge_authors,
    rename_author,
    resolve_pending_authors,
    set_item_authors,
    split_author_entity,
)


@pytest.fixture
def session(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "test.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.remove()
        db.drop_all()


_counter = iter(range(1, 10_000))


def _add_item(session, author, title="A Book"):
    n = next(_counter)
    item = LibraryItem(
        title=title,
        author=author,
        file_path=f"/books/book-{n}.epub",
        file_name=f"book-{n}.epub",
        extension=".epub",
    )
    session.add(item)
    return item


def _link_ids(item):
    return [
        row.author_id
        for row in BookAuthor.query.filter_by(item_id=item.id)
        .order_by(BookAuthor.position)
        .all()
    ]


def _names(item):
    return [
        db.session.get(Author, aid).canonical_name for aid in _link_ids(item)
    ]


# --------------------------------------------------------------------------
# Resolver: '&' splits, other separators stay opaque
# --------------------------------------------------------------------------

def test_ampersand_string_links_two_authors(session):
    item = _add_item(session, "Sören Karlsson & Deanne Rauscher")
    resolve_pending_authors(session)
    session.commit()

    assert item.author_status == STATUS_NEW
    assert _names(item) == ["Sören Karlsson", "Deanne Rauscher"]
    assert item.author_id == _link_ids(item)[0]  # primary mirror


def test_second_book_by_same_pair_links_exactly(session):
    _add_item(session, "Sören Karlsson & Deanne Rauscher")
    resolve_pending_authors(session)
    session.commit()

    item2 = _add_item(session, "Sören Karlsson & Deanne Rauscher", title="B")
    resolve_pending_authors(session)
    session.commit()

    assert item2.author_status == STATUS_LINKED
    assert Author.query.count() == 2  # no new entries


def test_och_fused_string_stays_one_entity(session):
    item = _add_item(session, "Sören Karlsson och Deanne Rauscher")
    resolve_pending_authors(session)
    session.commit()

    assert len(_link_ids(item)) == 1
    author = db.session.get(Author, item.author_id)
    assert author.canonical_name == "Sören Karlsson och Deanne Rauscher"


def test_single_author_book_gets_one_link(session):
    item = _add_item(session, "Selma Lagerlöf")
    resolve_pending_authors(session)
    session.commit()

    assert _link_ids(item) == [item.author_id]


def test_empty_author_clears_links(session):
    item = _add_item(session, "A & B")
    resolve_pending_authors(session)
    session.commit()

    item.author = ""
    session.commit()
    resolve_pending_authors(session)
    session.commit()

    assert item.author_status == STATUS_MISSING
    assert _link_ids(item) == []
    # Both tentative entries lost their last book — GC'd.
    assert Author.query.count() == 0


def test_duplicate_name_in_string_dedupes(session):
    item = _add_item(session, "Selma Lagerlöf & Selma Lagerlöf")
    resolve_pending_authors(session)
    session.commit()

    assert len(_link_ids(item)) == 1


# --------------------------------------------------------------------------
# Split rules
# --------------------------------------------------------------------------

def _fused_with_books(session, fused_name, count=2):
    items = [
        _add_item(session, fused_name, title=f"T{i}") for i in range(count)
    ]
    resolve_pending_authors(session)
    session.commit()
    fused = db.session.get(Author, items[0].author_id)
    return fused, items


def test_split_relinks_books_and_leaves_rule(session):
    fused, items = _fused_with_books(
        session, "Sören Karlsson och Deanne Rauscher"
    )
    a = Author(canonical_name="Sören Karlsson", source="user_confirmed")
    b = Author(canonical_name="Deanne Rauscher", source="user_confirmed")
    session.add_all([a, b])
    session.flush()

    count = split_author_entity(session, fused, [a, b])
    session.commit()

    assert count == 2
    for item in items:
        assert _names(item) == ["Sören Karlsson", "Deanne Rauscher"]
        assert item.author == "Sören Karlsson & Deanne Rauscher"
        assert item.author_status == STATUS_LINKED
        assert item.author_id == a.id
    # Fused entity gone; rule persists the decision.
    assert db.session.get(Author, fused.id) is None
    rule = AuthorSplitRule.query.filter_by(
        source_key="sören karlsson och deanne rauscher"
    ).one()
    assert json.loads(rule.author_ids) == [a.id, b.id]


def test_rescan_of_fused_string_honours_split_rule(session):
    fused, _items = _fused_with_books(
        session, "Sören Karlsson och Deanne Rauscher", count=1
    )
    a = Author(canonical_name="Sören Karlsson", source="user_confirmed")
    b = Author(canonical_name="Deanne Rauscher", source="user_confirmed")
    session.add_all([a, b])
    session.flush()
    split_author_entity(session, fused, [a, b])
    session.commit()

    # A new upload still carries the fused string inside the file.
    item = _add_item(session, "Sören Karlsson och Deanne Rauscher", title="New")
    resolve_pending_authors(session)
    session.commit()

    assert item.author_status == STATUS_LINKED
    assert _link_ids(item) == [a.id, b.id]
    # No fused entity was recreated.
    assert Author.query.count() == 2


def test_split_requires_two_distinct_parts(session):
    fused, _ = _fused_with_books(session, "A och B", count=1)
    solo = Author(canonical_name="Solo", source="user_confirmed")
    session.add(solo)
    session.flush()
    with pytest.raises(ValueError):
        split_author_entity(session, fused, [solo])


def test_delete_split_part_drops_rule(session):
    from app.services.author_resolver import remove_author_from_split_rules

    fused, items = _fused_with_books(session, "A och B", count=1)
    a = Author(canonical_name="A", source="user_confirmed")
    b = Author(canonical_name="B", source="user_confirmed")
    session.add_all([a, b])
    session.flush()
    split_author_entity(session, fused, [a, b])
    session.commit()

    remove_author_from_split_rules(session, a.id)
    session.commit()
    # 2-part rule loses one part → rule deleted.
    assert AuthorSplitRule.query.count() == 0


# --------------------------------------------------------------------------
# Cascades with co-authors
# --------------------------------------------------------------------------

def test_rename_rebuilds_joined_string(session):
    item = _add_item(session, "Sören Karlsson & Deanne Rauscher")
    resolve_pending_authors(session)
    session.commit()

    first = db.session.get(Author, _link_ids(item)[0])
    rename_author(session, first, "Sören M. Karlsson")
    session.commit()

    assert item.author == "Sören M. Karlsson & Deanne Rauscher"
    assert item.author_status == STATUS_LINKED


def test_merge_repoints_coauthor_link(session):
    item = _add_item(session, "Sören Karlsson & Deanne Rauscher")
    resolve_pending_authors(session)
    session.commit()

    second = db.session.get(Author, _link_ids(item)[1])
    target = Author(canonical_name="Deanne M. Rauscher", source="user_confirmed")
    session.add(target)
    session.flush()

    merge_authors(session, second, target)
    session.commit()

    assert _link_ids(item)[1] == target.id
    assert item.author == "Sören Karlsson & Deanne M. Rauscher"


def test_merge_collapses_duplicate_link(session):
    item = _add_item(session, "A & B")
    resolve_pending_authors(session)
    session.commit()
    a_id, b_id = _link_ids(item)

    merge_authors(
        session, db.session.get(Author, b_id), db.session.get(Author, a_id)
    )
    session.commit()

    assert _link_ids(item) == [a_id]
    assert item.author == db.session.get(Author, a_id).canonical_name


def test_merge_updates_split_rule_ids(session):
    fused, _ = _fused_with_books(session, "A och B", count=1)
    a = Author(canonical_name="A", source="user_confirmed")
    b = Author(canonical_name="B", source="user_confirmed")
    session.add_all([a, b])
    session.flush()
    split_author_entity(session, fused, [a, b])
    session.commit()

    c = Author(canonical_name="C", source="user_confirmed")
    session.add(c)
    session.flush()
    merge_authors(session, b, c)
    session.commit()

    rule = AuthorSplitRule.query.filter_by(source_key="a och b").one()
    assert json.loads(rule.author_ids) == [a.id, c.id]


# --------------------------------------------------------------------------
# set_item_authors (modal multi-save)
# --------------------------------------------------------------------------

def test_set_item_authors_links_ordered_and_confirms(session):
    item = _add_item(session, "Sören Karlsson och Deanne Rauscher")
    resolve_pending_authors(session)
    session.commit()
    fused_id = item.author_id

    set_item_authors(session, item, [
        {"author_id": None, "name": "Sören Karlsson"},
        {"author_id": None, "name": "Deanne Rauscher"},
    ])
    session.commit()

    assert item.author == "Sören Karlsson & Deanne Rauscher"
    assert item.author_status == STATUS_LINKED
    assert _names(item) == ["Sören Karlsson", "Deanne Rauscher"]
    for aid in _link_ids(item):
        assert db.session.get(Author, aid).source == "user_confirmed"
    # The walked-away-from fused tentative is GC'd.
    assert db.session.get(Author, fused_id) is None


def test_set_item_authors_reuses_existing_entry(session):
    existing = Author(canonical_name="Deanne Rauscher", source="user_confirmed")
    session.add(existing)
    session.flush()
    key_alias = AuthorAlias(variant_key="deanne rauscher", author_id=existing.id)
    session.add(key_alias)

    item = _add_item(session, "X")
    resolve_pending_authors(session)
    session.commit()

    set_item_authors(session, item, [
        {"author_id": None, "name": "Sören Karlsson"},
        {"author_id": None, "name": "Deanne Rauscher"},
    ])
    session.commit()

    assert _link_ids(item)[1] == existing.id
    assert Author.query.filter_by(canonical_name="Deanne Rauscher").count() == 1


def test_set_item_authors_single_records_old_variant_alias(session):
    item = _add_item(session, "Tolkein, J.R.R.")  # typo spelling
    resolve_pending_authors(session)
    session.commit()

    author = Author(canonical_name="J.R.R. Tolkien", source="user_confirmed")
    session.add(author)
    session.flush()
    set_item_authors(session, item, [{"author_id": author.id, "name": "J.R.R. Tolkien"}])
    session.commit()

    alias = AuthorAlias.query.filter_by(variant_key="tolkein, j.r.r.").one()
    assert alias.author_id == author.id


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    from app.routes.authors import authors_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "r.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.register_blueprint(authors_bp)
    with app.app_context():
        db.create_all()
        with app.test_client() as c:
            yield c
        db.session.remove()
        db.drop_all()


def test_check_endpoint_finds_existing(client):
    author = Author(canonical_name="Selma Lagerlöf", source="user_confirmed")
    db.session.add(author)
    db.session.flush()
    db.session.add(AuthorAlias(variant_key="selma lagerlöf", author_id=author.id))
    db.session.commit()

    resp = client.post("/authors/check", json={"name": "Selma Lagerlöf"})
    body = resp.get_json()
    assert body["ok"] and body["author"]["id"] == author.id


def test_check_endpoint_flags_similar(client):
    author = Author(canonical_name="Michael Connelly", source="user_confirmed")
    db.session.add(author)
    db.session.commit()

    resp = client.post("/authors/check", json={"name": "Michael Connolly"})
    body = resp.get_json()
    assert body["ok"] and body["author"] is None
    assert body["similar"] and body["similar"][0]["id"] == author.id


def test_split_endpoint_happy_path(client):
    item = _add_item(db.session, "Sören Karlsson och Deanne Rauscher")
    resolve_pending_authors(db.session)
    db.session.commit()
    fused_id = item.author_id

    resp = client.post(f"/authors/{fused_id}/split", json={
        "parts": [{"name": "Sören Karlsson"}, {"name": "Deanne Rauscher"}],
    })
    body = resp.get_json()
    assert body["ok"] and body["relinked"] == 1
    assert item.author == "Sören Karlsson & Deanne Rauscher"
    assert db.session.get(Author, fused_id) is None


def test_split_endpoint_rejects_single_part(client):
    item = _add_item(db.session, "A och B")
    resolve_pending_authors(db.session)
    db.session.commit()

    resp = client.post(f"/authors/{item.author_id}/split", json={
        "parts": [{"name": "A"}],
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "need_two_parts"
