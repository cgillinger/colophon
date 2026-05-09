# Colophon – e-book metadata manager
"""Tests for language detection.

No DB or network required. Uses the deterministic seed configured in
app.services.language_detect.
"""
from app.services.language_detect import detect_language_from_text


def test_detect_english():
    assert detect_language_from_text(
        "This is a sample English text for testing purposes. "
        "It contains enough words for the detector to be confident."
    ) == "en"


def test_detect_swedish():
    assert detect_language_from_text(
        "Det här är en exempeltext på svenska för att testa språkdetektering. "
        "Den innehåller tillräckligt många ord för att vara pålitlig."
    ) == "sv"


def test_short_text_returns_none():
    assert detect_language_from_text("Hi") is None


def test_empty_text_returns_none():
    assert detect_language_from_text("") is None
    assert detect_language_from_text(None) is None


def test_whitespace_only_returns_none():
    assert detect_language_from_text("   \n   \t   ") is None
