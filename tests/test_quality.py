"""Tests for field-level quality heuristics.

No DB or network required.
"""
from app.services.quality import (
    evaluate_quality,
    is_better_author,
    is_better_genre,
    is_better_isbn,
    is_better_publisher,
    is_better_synopsis,
    is_better_title,
)


def test_better_synopsis_longer():
    is_better, reason = is_better_synopsis("Short.", "A much longer description that gives way more context.")
    assert is_better is True
    assert "Längre" in reason


def test_better_synopsis_not_much_longer():
    is_better, _ = is_better_synopsis("A reasonable description.", "A reasonable description!")
    assert is_better is False


def test_better_synopsis_empty_existing():
    is_better, reason = is_better_synopsis("", "Anything non-empty")
    assert is_better is True
    assert "tom" in reason.lower()


def test_better_isbn_13_over_asin():
    is_better, reason = is_better_isbn("B007OQUOY0", "9781475039573")
    assert is_better is True
    assert "ISBN-13" in reason


def test_better_isbn_13_over_10():
    is_better, reason = is_better_isbn("0345391802", "9780345391803")
    assert is_better is True
    assert "ISBN-10" in reason


def test_better_isbn_no_change_when_existing_is_isbn13():
    is_better, _ = is_better_isbn("9780345391803", "9780345391810")
    assert is_better is False


def test_better_author_no_brackets():
    is_better, reason = is_better_author(
        "Reynolds, Alastair [Alastair, Reynolds]", "Alastair Reynolds"
    )
    assert is_better is True
    assert "hakparenteser" in reason


def test_better_author_no_change_when_clean():
    is_better, _ = is_better_author("Alastair Reynolds", "Alastair Reynolds Jr.")
    assert is_better is False


def test_better_publisher_not_author():
    is_better, reason = is_better_publisher(
        "Larry Enright", "Tor Books", author="Larry Enright"
    )
    assert is_better is True
    assert "författarnamn" in reason


def test_better_publisher_no_change_when_distinct():
    is_better, _ = is_better_publisher(
        "Penguin Books", "Tor Books", author="Larry Enright"
    )
    assert is_better is False


def test_better_genre_more_specific():
    is_better, reason = is_better_genre("Fiction", "Science Fiction, Space Opera, Hard SF")
    assert is_better is True
    assert "specifik" in reason


def test_better_title_no_parentheses():
    is_better, reason = is_better_title(
        "Absolution Gap (Revelation Space Book 3)", "Absolution Gap"
    )
    assert is_better is True
    assert "Renare" in reason


def test_evaluate_quality_dispatches_correctly():
    is_better, _ = evaluate_quality(
        "publisher", "Larry Enright", "Tor Books", author="Larry Enright"
    )
    assert is_better is True


def test_evaluate_quality_unknown_field():
    is_better, reason = evaluate_quality("unknown_field", "a", "b")
    assert is_better is False
    assert reason == ""
