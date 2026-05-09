# Colophon – e-book metadata manager
"""Tests for clean_title.

No DB or network required.
"""
from app.services.text_utils import clean_title


def test_strip_series_book():
    r = clean_title("Absolution Gap (Revelation Space Book 3)")
    assert r["cleaned_title"] == "Absolution Gap"
    assert r["extracted_series"] == "Revelation Space"
    assert r["extracted_series_index"] == "3"
    assert r["was_modified"] is True


def test_strip_marketing():
    r = clean_title("A Hidden Place (Now a major Netflix series)")
    assert r["cleaned_title"] == "A Hidden Place"
    assert r["was_modified"] is True


def test_strip_hash_series():
    r = clean_title("Axis (Spin #2)")
    assert r["cleaned_title"] == "Axis"
    assert r["extracted_series"] == "Spin"
    assert r["extracted_series_index"] == "2"


def test_strip_volume_series():
    r = clean_title("The Way of Kings (The Stormlight Archive Vol. 1)")
    assert r["cleaned_title"] == "The Way of Kings"
    assert r["extracted_series"] == "The Stormlight Archive"
    assert r["extracted_series_index"] == "1"


def test_swedish_bok_label():
    r = clean_title("Brand (Millennium Bok 4)")
    assert r["cleaned_title"] == "Brand"
    assert r["extracted_series"] == "Millennium"
    assert r["extracted_series_index"] == "4"


def test_no_change():
    r = clean_title("1968")
    assert r["cleaned_title"] == "1968"
    assert r["was_modified"] is False
    assert r["extracted_series"] is None


def test_empty_input():
    r = clean_title("")
    assert r["cleaned_title"] == ""
    assert r["was_modified"] is False
    assert r["extracted_series"] is None


def test_none_input():
    r = clean_title(None)
    assert r["cleaned_title"] == ""
    assert r["was_modified"] is False


def test_strip_author_prefix():
    r = clean_title("Birmingham, John - Angels of Vengeance")
    assert r["cleaned_title"] == "Angels of Vengeance"
    assert r["was_modified"] is True


def test_strip_author_prefix_swedish():
    r = clean_title("Lindqvist, John Ajvide - Låt den rätte komma in")
    assert r["cleaned_title"] == "Låt den rätte komma in"
    assert r["was_modified"] is True


def test_strip_author_prefix_with_initial():
    r = clean_title("Tolkien, J. R. R. - The Hobbit")
    assert r["cleaned_title"] == "The Hobbit"
    assert r["was_modified"] is True


def test_no_false_positive_on_commas():
    r = clean_title("Dr. Jekyll and Mr. Hyde")
    assert r["cleaned_title"] == "Dr. Jekyll and Mr. Hyde"
    assert r["was_modified"] is False


def test_no_false_positive_on_subtitle_dash():
    r = clean_title("Neuromancer - 20th Anniversary Edition")
    assert r["cleaned_title"] == "Neuromancer - 20th Anniversary Edition"
    assert r["was_modified"] is False
