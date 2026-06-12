# Colophon – e-book metadata manager
"""Tests for the author authority matcher (pure functions, no DB/network).

Layer semantics under test:
  1. normalize_author_name — exact-match key after light normalisation
  2. author_signature — format-/order-invariant, auto-apply safe
  3. fuzzy_similarity — suggest-only distance
plus resolve_author, the layered entry point.
"""
from app.services.author_authority import (
    FUZZY_SUGGEST_THRESHOLD,
    author_signature,
    fuzzy_similarity,
    normalize_author_name,
    resolve_author,
)


# --- Layer 1: normalize_author_name ---

def test_normalize_casefold():
    assert normalize_author_name("TOLKIEN") == normalize_author_name("tolkien")


def test_normalize_whitespace():
    assert normalize_author_name("  J.R.R.   Tolkien ") == "j.r.r. tolkien"


def test_normalize_unicode_nfc():
    # Composed é vs e + combining acute
    assert normalize_author_name("Bré") == normalize_author_name("Bré")


def test_normalize_keeps_punctuation():
    # Punctuation differences are NOT layer 1's job
    assert normalize_author_name("J.R.R. Tolkien") != normalize_author_name("JRR Tolkien")


def test_normalize_empty():
    assert normalize_author_name("") == ""
    assert normalize_author_name(None) == ""


# --- Layer 2: author_signature ---

def test_signature_initials_variants_collapse():
    expected = author_signature("J.R.R. Tolkien")
    assert author_signature("J. R. R. Tolkien") == expected
    assert author_signature("JRR Tolkien") == expected
    assert author_signature("Tolkien, J.R.R.") == expected


def test_signature_order_invariant():
    assert author_signature("Smith, John") == author_signature("John Smith")


def test_signature_spaced_initials():
    assert author_signature("George R. R. Martin") == author_signature("George RR Martin")


def test_signature_hyphenated_name():
    assert author_signature("Jean-Paul Sartre") == author_signature("Jean Paul Sartre")


def test_signature_distinct_people_differ():
    # One character apart but different real people — must NOT collide
    assert author_signature("Michael Connelly") != author_signature("Michael Connolly")


def test_signature_initial_vs_full_name_differ():
    # "J. Tolkien" could be someone else than "John Tolkien"
    assert author_signature("J. Tolkien") != author_signature("John Tolkien")


def test_signature_keeps_diacritics():
    # Müller/Muller is fuzzy territory (layer 3), not auto-apply
    assert author_signature("Hans Müller") != author_signature("Hans Muller")


def test_signature_multi_author_no_single_collision():
    # Comma-joined multi-author string must not collide with either author
    multi = author_signature("John Smith, Jane Doe")
    assert multi != author_signature("John Smith")
    assert multi != author_signature("Jane Doe")


def test_signature_empty():
    assert author_signature("") == ""
    assert author_signature(None) == ""


# --- Layer 3: fuzzy_similarity ---

def test_fuzzy_transliteration_variants():
    assert fuzzy_similarity("Fyodor Dostoevsky", "Fyodor Dostoyevsky") >= FUZZY_SUGGEST_THRESHOLD


def test_fuzzy_order_and_transliteration():
    assert fuzzy_similarity("Dostoevsky, Fyodor", "Fyodor Dostoyevsky") >= FUZZY_SUGGEST_THRESHOLD


def test_fuzzy_umlaut_expansion():
    assert fuzzy_similarity("Hans Müller", "Hans Mueller") >= FUZZY_SUGGEST_THRESHOLD


def test_fuzzy_diacritic_only_difference_is_near_identical():
    assert fuzzy_similarity("Pär Lagerkvist", "Par Lagerkvist") == 1.0


def test_fuzzy_lookalike_names_score_high_hence_suggest_only():
    # Two distinct real authors score above threshold — which is exactly
    # why layer 3 must never auto-merge (the iron rule).
    assert fuzzy_similarity("Michael Connelly", "Michael Connolly") >= FUZZY_SUGGEST_THRESHOLD


def test_fuzzy_unrelated_names_below_threshold():
    assert fuzzy_similarity("J.R.R. Tolkien", "Astrid Lindgren") < FUZZY_SUGGEST_THRESHOLD


def test_fuzzy_empty():
    assert fuzzy_similarity("", "Tolkien") == 0.0
    assert fuzzy_similarity("Tolkien", None) == 0.0


# --- resolve_author ---

def _registry():
    """A small registry: id 1 = Tolkien, id 2 = Lindgren."""
    authors = [(1, "J.R.R. Tolkien"), (2, "Astrid Lindgren")]
    exact = {normalize_author_name(name): aid for aid, name in authors}
    signatures = {author_signature(name): aid for aid, name in authors}
    return exact, signatures, authors


def test_resolve_exact_hit():
    exact, signatures, authors = _registry()
    assert resolve_author("j.r.r. tolkien", exact, signatures, authors) == ("exact", 1)


def test_resolve_signature_hit():
    exact, signatures, authors = _registry()
    assert resolve_author("Tolkien, JRR", exact, signatures, authors) == ("signature", 1)


def test_resolve_fuzzy_suggests_never_links():
    exact, signatures, authors = _registry()
    kind, suggestions = resolve_author("J.R.R. Tolkein", exact, signatures, authors)
    assert kind == "suggest"
    assert suggestions[0][0] == 1
    assert suggestions[0][1] >= FUZZY_SUGGEST_THRESHOLD


def test_resolve_suggestions_sorted_best_first():
    exact = {}
    signatures = {}
    candidates = [(1, "Michael Connolly"), (2, "Michael Connelly")]
    kind, suggestions = resolve_author("Michael Connelly", exact, signatures, candidates)
    assert kind == "suggest"
    assert suggestions[0][0] == 2
    assert suggestions[0][1] >= suggestions[-1][1]


def test_resolve_new_author():
    exact, signatures, authors = _registry()
    assert resolve_author("Selma Lagerlöf", exact, signatures, authors) == ("new", None)


def test_resolve_multi_author_string_is_new_not_false_merge():
    exact, signatures, authors = _registry()
    kind, _ = resolve_author("J.R.R. Tolkien, Astrid Lindgren", exact, signatures, authors)
    assert kind == "new"


def test_resolve_empty_input():
    exact, signatures, authors = _registry()
    assert resolve_author("", exact, signatures, authors) == ("none", None)
    assert resolve_author("   ", exact, signatures, authors) == ("none", None)


def test_resolve_without_fuzzy_candidates():
    exact, signatures, _ = _registry()
    assert resolve_author("J.R.R. Tolkein", exact, signatures) == ("new", None)
