# Colophon – e-book metadata manager
"""Tests for compute_group_key.

No DB or network required.
"""
from app.services.grouping import compute_group_key


def test_same_title_same_key():
    assert compute_group_key("12|21|12") == compute_group_key("12|21|12")


def test_case_insensitive():
    assert compute_group_key("The Great Gatsby") == compute_group_key("the great gatsby")


def test_brackets_stripped():
    assert compute_group_key("Book [Series]") == compute_group_key("Book")


def test_parentheses_stripped():
    assert compute_group_key("Book (1st ed.)") == compute_group_key("Book")


def test_punctuation_ignored():
    assert compute_group_key("It's a Wonderful Life!") == compute_group_key("its a wonderful life")


def test_unicode_normalization():
    # Accented characters are stripped, so "naïve" matches "naive"
    assert compute_group_key("Naïve") == compute_group_key("Naive")


def test_whitespace_collapsed():
    assert compute_group_key("Book   Title") == compute_group_key("Book Title")


def test_different_titles_different_keys():
    assert compute_group_key("1968") != compute_group_key("Agent to the Stars")


def test_empty_title_returns_empty():
    assert compute_group_key("") == ""
    assert compute_group_key(None) == ""


def test_author_does_not_affect_key():
    # Same title + different authors = same group_key (key is title-only)
    assert compute_group_key("Foo", "Larry Enright") == compute_group_key("Foo", "Enright, Larry")


def test_returns_16_char_hex():
    key = compute_group_key("Test")
    assert len(key) == 16
    assert all(c in "0123456789abcdef" for c in key)
