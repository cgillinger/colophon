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
    STATUS_STALE,
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


def test_fuzzy_near_miss_links_literal_and_proposes(session):
    known = _confirmed_author(session, "J.R.R. Tolkien")
    item = _add_item(session, "J.R.R. Tolkein")  # typo
    counts = resolve_pending_authors(session)
    session.commit()

    # v2: the iron rule still never *merges* on fuzzy — but the book is
    # never left unlinked either. The literal string becomes a tentative
    # entry the book links to; the fuzzy hit is a merge proposal.
    assert counts == {STATUS_REVIEW: 1}
    assert item.author_status == STATUS_REVIEW
    linked = db.session.get(Author, item.author_id)
    assert linked.canonical_name == "J.R.R. Tolkein"
    assert linked.source == "tentative"
    assert item.suggested_author_id == known.id
    assert Author.query.count() == 2


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
# The stale listener (models.py) — author edits re-enter the queue WITH memory
# --------------------------------------------------------------------------

def test_author_edit_marks_stale_and_keeps_link(session):
    item = _add_item(session, "J.R.R. Tolkien")
    resolve_pending_authors(session)
    session.commit()
    tolkien_id = item.author_id
    assert tolkien_id is not None

    item.author = "Ursula K. Le Guin"
    session.commit()

    # v2: the link is memory, not collateral — kept while awaiting re-resolution.
    assert item.author_id == tolkien_id
    assert item.author_status == STATUS_STALE


def test_unrelated_edit_relinks_new_entry_and_gcs_old_tentative(session):
    item = _add_item(session, "J.R.R. Tolkien")
    resolve_pending_authors(session)
    session.commit()
    old_id = item.author_id

    item.author = "Ursula K. Le Guin"
    session.commit()
    resolve_pending_authors(session)
    session.commit()

    # A genuinely different name: linked to its own new entry, no proposal.
    assert item.author_status == STATUS_NEW
    assert db.session.get(Author, item.author_id).canonical_name == "Ursula K. Le Guin"
    assert item.suggested_author_id is None
    # The walked-away-from tentative entry had no other books — GC'd.
    assert db.session.get(Author, old_id) is None


def test_stale_exact_match_relinks_deterministically(session):
    other = _confirmed_author(session, "Ursula K. Le Guin")
    item = _add_item(session, "J.R.R. Tolkien")
    resolve_pending_authors(session)
    session.commit()

    item.author = "Le Guin, Ursula K."  # signature form of the other entry
    session.commit()
    resolve_pending_authors(session)
    session.commit()

    assert item.author_id == other.id
    assert item.author_status == STATUS_LINKED
    assert item.suggested_author_id is None


def test_spelling_correction_keeps_same_person_as_proposal(session):
    item = _add_item(session, "Mary Doria Russel")  # file's typo, one l
    resolve_pending_authors(session)
    session.commit()
    old_entry = db.session.get(Author, item.author_id)

    item.author = "Mary Doria Russell"  # enrichment corrects the spelling
    session.commit()
    resolve_pending_authors(session)
    session.commit()

    # Never unlinked: the corrected string is its own (new) entry, and the
    # book's previous entry — near-certainly the same person — is the proposal.
    assert item.author_id is not None
    linked = db.session.get(Author, item.author_id)
    assert linked.canonical_name == "Mary Doria Russell"
    assert item.author_status == STATUS_REVIEW
    assert item.suggested_author_id == old_entry.id
    # The proposal target is protected from GC while referenced.
    assert db.session.get(Author, old_entry.id) is not None


def test_gc_spares_confirmed_entries(session):
    author = _confirmed_author(session, "Selma Lagerlöf")
    item = _add_item(session, "Selma Lagerlöf")
    resolve_pending_authors(session)
    session.commit()
    assert item.author_id == author.id

    item.author = "Hjalmar Söderberg"
    session.commit()
    resolve_pending_authors(session)
    session.commit()

    # Confirmed entries are standing knowledge — never auto-removed.
    assert db.session.get(Author, author.id) is not None


def test_gc_on_last_book_deleted(session):
    from app.services.author_resolver import gc_orphaned_author

    item = _add_item(session, "Engångsförfattare")
    resolve_pending_authors(session)
    session.commit()
    tentative_id = item.author_id

    confirmed = _confirmed_author(session, "Selma Lagerlöf")
    session.commit()

    session.delete(item)
    session.commit()
    assert gc_orphaned_author(session, tentative_id) is True
    assert gc_orphaned_author(session, confirmed.id) is False
    session.commit()

    assert db.session.get(Author, tentative_id) is None
    assert AuthorAlias.query.filter_by(author_id=tentative_id).count() == 0
    assert db.session.get(Author, confirmed.id) is not None


# --------------------------------------------------------------------------
# The full Russell regression chain (prod incident 2026-06-12):
# seed from file typo → user reorders via rename → enrichment corrects
# spelling. Invariant: the book is linked at every step.
# --------------------------------------------------------------------------

def test_russell_chain_link_never_breaks(session):
    from app.services.author_resolver import merge_authors, rename_author

    # 1. Seeding: file's dc:creator is misspelled, lastname-first.
    item = _add_item(session, "Russel, Mary Doria", title="The Sparrow")
    resolve_pending_authors(session)
    session.commit()
    entry = db.session.get(Author, item.author_id)
    assert entry.source == "tentative"

    # 2. User reorders the name in /authors (faithfully keeping the typo).
    rename_author(session, entry, "Mary Doria Russel")
    session.commit()
    assert item.author == "Mary Doria Russel"
    assert item.author_id == entry.id          # cascade kept the link
    assert entry.source == "user_confirmed"    # rename counts as confirmation

    # 3. Enrichment corrects the spelling (this severed the link in prod).
    item.author = "Mary Doria Russell"
    session.commit()
    assert item.author_id == entry.id          # stale, but still linked
    resolve_pending_authors(session)
    session.commit()

    assert item.author_id is not None          # THE invariant
    new_entry = db.session.get(Author, item.author_id)
    assert new_entry.canonical_name == "Mary Doria Russell"
    assert item.author_status == STATUS_REVIEW
    assert item.suggested_author_id == entry.id

    # 4. One click in /authors: merge settles the proposal.
    merge_authors(session, entry, new_entry)
    session.commit()
    assert item.author_id == new_entry.id
    assert item.author_status == STATUS_LINKED
    assert item.suggested_author_id is None
    # All observed spellings survive as aliases of the surviving entry.
    keys = {a.variant_key for a in AuthorAlias.query.filter_by(author_id=new_entry.id)}
    assert "russel, mary doria" in keys
    assert "mary doria russel" in keys
    assert "mary doria russell" in keys


def test_is_known_variant_matches_alias_and_canonical(session):
    from app.services.author_resolver import is_known_variant

    item = _add_item(session, "Russel, Mary Doria")
    resolve_pending_authors(session)
    session.commit()
    author_id = item.author_id

    assert is_known_variant(session, author_id, "Russel, Mary Doria") is True
    assert is_known_variant(session, author_id, "RUSSEL, MARY DORIA") is True
    assert is_known_variant(session, author_id, "Mary Doria Russell") is False
    assert is_known_variant(session, None, "Russel, Mary Doria") is False


def test_merge_keep_old_direction_also_settles(session):
    item = _add_item(session, "Mary Doria Russel")
    resolve_pending_authors(session)
    session.commit()
    old_entry = db.session.get(Author, item.author_id)

    item.author = "Mary Doria Russell"
    session.commit()
    resolve_pending_authors(session)
    session.commit()
    new_entry = db.session.get(Author, item.author_id)

    from app.services.author_resolver import merge_authors
    merge_authors(session, new_entry, old_entry)  # user keeps the OLD entry
    session.commit()

    assert item.author_id == old_entry.id
    assert item.author == old_entry.canonical_name
    assert item.author_status == STATUS_LINKED
    assert item.suggested_author_id is None


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
