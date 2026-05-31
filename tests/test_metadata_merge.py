# Colophon – e-book metadata manager
"""Tests for the field-level metadata merge.

No network, no DB required. Covers the four behaviours the merge exists to
guarantee:
    - description = longest wins
    - genres = union of unique tags
    - series + index are coupled (taken together from one source)
    - the embedded file is always trusted; a wrong-book hit is gated out
"""
from unittest.mock import MagicMock

from app.services.metadata_merge import merge_candidates, _source_key


def _item(**kwargs):
    item = MagicMock()
    item.isbn = kwargs.get("isbn", "")
    item.title = kwargs.get("title", "")
    item.author = kwargs.get("author", "")
    item.language = kwargs.get("language", "")
    return item


def _cand(source, **kwargs):
    base = {
        "source": source,
        "title": "", "author": "", "description": "",
        "isbn": "", "publisher": "", "language": "",
        "series": "", "series_index": "", "genres": "",
        "published_date": "", "cover_url": "",
    }
    base.update(kwargs)
    return base


def _google(**kw):
    return _cand("Google Books API", **kw)


def _calibre(**kw):
    return _cand("Calibre: Goodreads", **kw)


def _wikipedia(**kw):
    return _cand("Wikipedia", **kw)


def _embedded(**kw):
    return _cand("Embedded file", **kw)


# ---------------------------------------------------------------------------
# Source bucketing
# ---------------------------------------------------------------------------

def test_source_key_buckets():
    assert _source_key("Google Books API") == "google"
    assert _source_key("Calibre: Goodreads, FictionDB") == "calibre"
    assert _source_key("Wikipedia") == "wikipedia"
    assert _source_key("Embedded file") == "embedded"
    assert _source_key("Inbäddad fil") == "embedded"
    assert _source_key("Something else") == "other"


# ---------------------------------------------------------------------------
# Per-field strategies
# ---------------------------------------------------------------------------

def test_union_takes_fields_from_complementary_sources():
    """Google has the synopsis+cover, the file has the series — keep both."""
    item = _item(title="The Hobbit", author="J.R.R. Tolkien")
    anchor = _google(
        title="The Hobbit", author="J.R.R. Tolkien",
        description="A long synopsis about a hobbit.",
        cover_url="http://x/cover.jpg",
    )
    embedded = _embedded(
        title="The Hobbit", author="J.R.R. Tolkien",
        series="Middle-earth", series_index="1",
    )
    payload, prov = merge_candidates(item, [anchor, embedded], anchor)
    assert payload["description"].startswith("A long synopsis")
    assert payload["cover_url"] == "http://x/cover.jpg"
    assert payload["series"] == "Middle-earth"
    assert payload["series_index"] == "1"
    assert prov["series"] == "Embedded file"
    assert prov["cover_url"] == "Google Books API"


def test_description_longest_wins():
    item = _item(title="Dune", author="Frank Herbert")
    short = _google(title="Dune", author="Frank Herbert", description="Short.")
    long = _calibre(
        title="Dune", author="Frank Herbert",
        description="A considerably longer and richer synopsis of the novel Dune.",
    )
    payload, prov = merge_candidates(item, [short, long], short)
    assert payload["description"].startswith("A considerably longer")
    assert prov["description"] == "Calibre: Goodreads"


def test_genres_union_dedup_and_cap():
    item = _item(title="Dune", author="Frank Herbert")
    a = _google(title="Dune", author="Frank Herbert", genres="Science Fiction, Fiction")
    b = _calibre(title="Dune", author="Frank Herbert", genres="Fiction, Space Opera")
    payload, _ = merge_candidates(item, [a, b], a)
    genres = [g.strip() for g in payload["genres"].split(",")]
    assert genres == ["Science Fiction", "Fiction", "Space Opera"]


def test_series_and_index_are_coupled_from_one_source():
    """The index must never come from a different book than the name."""
    item = _item(title="A Game of Thrones", author="George R.R. Martin")
    # Anchor names a series + its index; a second source has only a stray index.
    anchor = _calibre(
        title="A Game of Thrones", author="George R.R. Martin",
        series="A Song of Ice and Fire", series_index="1",
    )
    noise = _google(
        title="A Game of Thrones", author="George R.R. Martin",
        series="", series_index="99",
    )
    payload, prov = merge_candidates(item, [anchor, noise], anchor)
    assert payload["series"] == "A Song of Ice and Fire"
    assert payload["series_index"] == "1"
    assert prov["series"] == prov["series_index"] == "Calibre: Goodreads"


def test_embedded_series_beats_calibre_by_precedence():
    item = _item(title="Mistborn", author="Brandon Sanderson")
    embedded = _embedded(
        title="Mistborn", author="Brandon Sanderson",
        series="Mistborn", series_index="1",
    )
    calibre = _calibre(
        title="Mistborn", author="Brandon Sanderson",
        series="The Cosmere", series_index="3",
    )
    payload, prov = merge_candidates(item, [calibre, embedded], calibre)
    assert payload["series"] == "Mistborn"
    assert prov["series"] == "Embedded file"


# ---------------------------------------------------------------------------
# Trust gate
# ---------------------------------------------------------------------------

def test_wrong_book_is_gated_out():
    """A candidate describing a different book must not pollute the record."""
    item = _item(title="The Silmarillion", author="J.R.R. Tolkien")
    anchor = _google(
        title="The Silmarillion", author="J.R.R. Tolkien",
        description="The history of Arda.",
    )
    wrong = _calibre(
        title="Pride and Prejudice", author="Jane Austen",
        description="A romance in Regency England.",
        publisher="WrongHouse", isbn="0000000000000",
    )
    payload, prov = merge_candidates(item, [anchor, wrong], anchor)
    # The wrong book's publisher/description must be absent.
    assert payload.get("publisher", "") == ""
    assert "Arda" in payload["description"]
    assert "WrongHouse" not in payload.values()


def test_embedded_file_always_trusted_even_with_low_similarity():
    """The file IS the book — it bypasses the title-similarity gate."""
    item = _item(title="X", author="Y")
    anchor = _google(title="X", author="Y", description="desc")
    # Embedded title is messy/short but still carries the real series.
    embedded = _embedded(title="X", author="Y", publisher="RealPublisher")
    payload, prov = merge_candidates(item, [anchor, embedded], anchor)
    assert payload["publisher"] == "RealPublisher"
    assert prov["publisher"] == "Embedded file"


def test_shared_isbn_lets_a_dissimilar_title_contribute():
    item = _item(title="Naïve. Super", author="Erlend Loe", isbn="9780099285861")
    anchor = _google(
        title="Naive Super", author="Erlend Loe", isbn="9780099285861",
        description="short",
    )
    # Different-looking title but identical ISBN → trusted.
    alt = _calibre(
        title="Naiv.Super (Norwegian ed.)", author="Erlend Loe",
        isbn="9780099285861",
        description="A much longer description coming via the shared ISBN match.",
    )
    payload, prov = merge_candidates(item, [anchor, alt], anchor)
    assert payload["description"].startswith("A much longer")
    assert prov["description"] == "Calibre: Goodreads"


def test_empty_candidates_returns_empty():
    item = _item(title="X", author="Y")
    payload, prov = merge_candidates(item, [], None)
    assert payload == {}
    assert prov == {}
