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


# --- detect_language_confident: two samples from inside the book -----------
#
# The first pages are the worst place to ask a book what language it is in:
# copyright boilerplate and publisher blurbs are routinely in another
# language than the text. These tests drive the two-sample path with a
# synthetic EPUB rather than a fixture file, so they stay fast and hermetic.

import zipfile

from app.services.language_detect import detect_language_confident

_SV = (
    "Det här är en längre svensk text som handlar om en stad och dess "
    "invånare under ett helt sekel. Den innehåller tillräckligt många ord "
    "för att språkdetekteringen ska bli säker på sin sak, och den fortsätter "
    "en bra bit till för att nå över minimigränsen för antal tecken. "
) * 3

_EN = (
    "This is a longer English passage about a ship and the people aboard it "
    "during a very long voyage. It contains more than enough words for the "
    "detector to be confident about what it is looking at, and it keeps "
    "going for a while yet to clear the minimum character threshold. "
) * 3


def _make_epub(path, chapter_texts):
    """Write a minimal but real EPUB whose spine lists chapters in order."""
    manifest = "".join(
        f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(chapter_texts))
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapter_texts)))
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="id">test</dc:identifier><dc:title>T</dc:title>'
        '<dc:language>en</dc:language></metadata>'
        f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>"
    )
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("content.opf", opf)
        for i, text in enumerate(chapter_texts):
            z.writestr(f"c{i}.xhtml", f"<html><body><p>{text}</p></body></html>")
    return str(path)


def test_confident_detection_agrees_on_a_consistent_book(tmp_path):
    path = _make_epub(tmp_path / "sv.epub", [_SV] * 10)
    result = detect_language_confident(path)
    assert result is not None
    assert result["code"] == "sv"
    assert result["agree"] is True
    assert result["prob"] > 0.9


def test_samples_that_disagree_report_agree_false(tmp_path):
    # Swedish through the first half, English through the second: the 30%
    # and 60% probes land on different languages.
    path = _make_epub(tmp_path / "mixed.epub", [_SV] * 5 + [_EN] * 5)
    result = detect_language_confident(path)
    assert result is not None
    assert result["agree"] is False


def test_too_little_text_returns_none(tmp_path):
    path = _make_epub(tmp_path / "thin.epub", ["Hi.", "Bye.", "Hm."])
    assert detect_language_confident(path) is None


def test_unreadable_file_returns_none(tmp_path):
    bad = tmp_path / "not-an-epub.epub"
    bad.write_text("this is not a zip archive")
    assert detect_language_confident(str(bad)) is None


def test_skips_front_matter_in_another_language(tmp_path):
    # The real-world case: English copyright boilerplate up front, Swedish
    # book. Sampling from the start would answer "en"; sampling from inside
    # must answer "sv".
    path = _make_epub(tmp_path / "frontmatter.epub", [_EN] * 2 + [_SV] * 8)
    result = detect_language_confident(path)
    assert result is not None
    assert result["code"] == "sv"
