# Colophon – tests for the DB-aware author resolution layer (step 3)
"""resolve_pending_authors / AuthorRegistry — DB-only linking semantics.

Covers the four author states (linked/new/review/missing), registry
growth (tentative canonicals + aliases), the iron rule (fuzzy never
links), the reset listener in models.py, and the Kobo invariant that
linking never bumps content_updated_at.
"""
import pytest
from flask import Flask

from app.models import db, Author, AuthorAlias, LibraryItem
from app.services.author_resolver import (
    STATUS_LINKED,
    STATUS_MISSING,
    STATUS_NEW,
    STATUS_REVIEW,
    resolve_pending_authors,
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


def _confirmed_author(session, name):
    author = Author(canonical_name=name, source="user_confirmed")
    session.add(author)
    session.flush()
    return author


# --------------------------------------------------------------------------
# The four states
# --------------------------------------------------------------------------

def test_unknown_author_creates_tentative_and_links(session):
    item = _add_item(session, "J.R.R. Tolkien")
    counts = resolve_pending_authors(session)
    session.commit()

    assert counts == {STATUS_NEW: 1}
    assert item.author_status == STATUS_NEW
    author = db.session.get(Author, item.author_id)
    assert author.canonical_name == "J.R.R. Tolkien"
    assert author.source == "tentative"
    # The observed spelling is recorded as an alias (normalized).
    alias = AuthorAlias.query.one()
    assert alias.variant_key == "j.r.r. tolkien"
    assert alias.author_id == author.id


def test_signature_variant_links_to_existing(session):
    author = _confirmed_author(session, "J.R.R. Tolkien")
    item = _add_item(session, "Tolkien, J.R.R.")
    counts = resolve_pending_authors(session)
    session.commit()

    assert counts == {STATUS_LINKED: 1}
    assert item.author_id == author.id
    assert item.author_status == STATUS_LINKED
    # The variant was recorded as an alias for a future layer-1 hit.
    assert AuthorAlias.query.filter_by(variant_key="tolkien, j.r.r.").count() == 1


def test_exact_case_variant_links(session):
    author = _confirmed_author(session, "Astrid Lindgren")
    item = _add_item(session, "astrid lindgren")
    resolve_pending_authors(session)
    assert item.author_id == author.id
    assert item.author_status == STATUS_LINKED


def test_fuzzy_near_miss_is_review_only(session):
    _confirmed_author(session, "J.R.R. Tolkien")
    item = _add_item(session, "J.R.R. Tolkein")  # typo
    counts = resolve_pending_authors(session)
    session.commit()

    # Iron rule: fuzzy proposes, never links — and no tentative is created.
    assert counts == {STATUS_REVIEW: 1}
    assert item.author_id is None
    assert item.author_status == STATUS_REVIEW
    assert Author.query.count() == 1


def test_no_author_is_missing(session):
    item = _add_item(session, None)
    counts = resolve_pending_authors(session)
    assert counts == {STATUS_MISSING: 1}
    assert item.author_id is None
    assert item.author_status == STATUS_MISSING


# --------------------------------------------------------------------------
# Registry growth within a batch
# --------------------------------------------------------------------------

def test_second_book_by_new_author_links_in_same_batch(session):
    first = _add_item(session, "Selma Lagerlöf")
    second = _add_item(session, "Lagerlöf, Selma")
    counts = resolve_pending_authors(session)
    session.commit()

    # Design: "The next book by that person becomes a ✅."
    assert counts == {STATUS_NEW: 1, STATUS_LINKED: 1}
    assert Author.query.count() == 1
    assert first.author_id == second.author_id
    assert second.author_status == STATUS_LINKED


def test_multi_author_string_is_own_unit_never_false_merge(session):
    _confirmed_author(session, "John Smith")
    _confirmed_author(session, "Jane Doe")
    item = _add_item(session, "John Smith, Jane Doe")
    resolve_pending_authors(session)

    # Treated as one opaque unit: a new tentative, linked to neither person.
    assert item.author_status == STATUS_NEW
    linked = db.session.get(Author, item.author_id)
    assert linked.canonical_name == "John Smith, Jane Doe"
    assert linked.source == "tentative"


# --------------------------------------------------------------------------
# Pending semantics
# --------------------------------------------------------------------------

def test_resolved_items_are_not_retouched(session):
    item = _add_item(session, "J.R.R. Tolkien")
    resolve_pending_authors(session)
    session.commit()
    first_id = item.author_id

    counts = resolve_pending_authors(session)
    assert counts == {}
    assert item.author_id == first_id


def test_explicit_item_list_bounds_the_pass(session):
    in_scope = _add_item(session, "Author One")
    backlog = _add_item(session, "Author Two")
    counts = resolve_pending_authors(session, [in_scope])

    assert counts == {STATUS_NEW: 1}
    assert in_scope.author_status == STATUS_NEW
    assert backlog.author_status is None  # untouched — next scan's job


# --------------------------------------------------------------------------
# The reset listener (models.py) — author edits invalidate resolution
# --------------------------------------------------------------------------

def test_author_edit_resets_resolution(session):
    item = _add_item(session, "J.R.R. Tolkien")
    resolve_pending_authors(session)
    session.commit()
    assert item.author_id is not None

    item.author = "Ursula K. Le Guin"
    session.commit()

    assert item.author_id is None
    assert item.author_status is None  # back in the pending queue


def test_explicit_confirmation_is_not_reset(session):
    author = _confirmed_author(session, "J.R.R. Tolkien")
    item = _add_item(session, "Tolkein")  # will not matter — overwritten
    session.commit()

    # Step-4 combobox semantics: author + author_id set in the same flush.
    item.author = "J.R.R. Tolkien"
    item.author_id = author.id
    item.author_status = STATUS_LINKED
    session.commit()

    assert item.author_id == author.id
    assert item.author_status == STATUS_LINKED


# --------------------------------------------------------------------------
# Kobo invariant — linking alone must not re-ship entitlements
# --------------------------------------------------------------------------

def test_linking_does_not_bump_content_updated_at(session):
    _confirmed_author(session, "J.R.R. Tolkien")
    item = _add_item(session, "J.R.R. Tolkien")
    session.commit()
    stamp = item.content_updated_at
    assert stamp is not None

    resolve_pending_authors(session)
    session.commit()

    assert item.author_status == STATUS_LINKED
    assert item.content_updated_at == stamp
