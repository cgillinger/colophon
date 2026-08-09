# Colophon – e-book metadata manager
"""Tests for deriving a Kobo Location from a reading percentage.

The bug these lock down: Colophon used to ship ``ProgressPercent`` and a
``Location`` that described *different* places in the book. The Kobo obeys the
Location, recomputes a lower percentage from it, and sends that back — where
the furthest-read rule rejects it as a regression. Server and device then
disagree permanently, and re-syncing re-sends the same stale position.

Real EPUBs on disk, because the whole point is reading the spine's byte
weights out of the zip.
"""
import json
import posixpath
import zipfile

import pytest

from app.routes.kobo import _faithful_location
from app.services.kobo_location import (
    location_for_percent,
    percent_for_source,
)

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/package.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

CHAPTER_BYTES = 1000  # 10 chapters of equal weight -> 10 % each


def _make_epub(path, chapter_count=10, opf_dir="OEBPS"):
    """Write an EPUB whose spine is `chapter_count` equally sized documents."""
    names = [f"chapter{i:03d}.xhtml" for i in range(1, chapter_count + 1)]
    manifest = "".join(
        f'<item id="c{i}" href="{n}" media-type="application/xhtml+xml"/>'
        for i, n in enumerate(names, 1)
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(1, chapter_count + 1))
    opf = (
        '<?xml version="1.0"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>"
    )
    opf_path = f"{opf_dir}/package.opf" if opf_dir else "package.opf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", CONTAINER.replace("OEBPS/package.opf", opf_path))
        z.writestr(opf_path, opf)
        for n in names:
            z.writestr(posixpath.join(opf_dir, n) if opf_dir else n, b"x" * CHAPTER_BYTES)
    return [posixpath.join(opf_dir, n) if opf_dir else n for n in names]


class _Item:
    """Just the attributes the location helpers read off a LibraryItem."""

    def __init__(self, file_path, read_progress=None, read_location_json=None):
        self.id = 1
        self.file_path = str(file_path)
        self.read_progress = read_progress
        self.read_location_json = read_location_json
        self.read_location = None


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "book.epub"
    sources = _make_epub(path)
    return path, sources


# ---------------------------------------------------------------------------
# location_for_percent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "percent,expected_index",
    [(0, 0), (5, 0), (10, 0), (10.5, 1), (55, 5), (99.9, 9), (100, 9)],
)
def test_location_lands_in_the_document_holding_that_percent(book, percent, expected_index):
    path, sources = book
    loc = location_for_percent(_Item(path), percent)
    assert loc["Source"] == sources[expected_index]
    assert loc["Type"] == "KoboSpan"
    assert loc["Value"] == "kobo.1.1"


def test_source_includes_the_opf_directory(book):
    """The Kobo reports Source as an archive-relative path ("OEBPS/ch.xhtml"),
    not the manifest href. Getting this wrong makes the span unresolvable."""
    path, _ = book
    assert location_for_percent(_Item(path), 50)["Source"].startswith("OEBPS/")


def test_spine_without_opf_directory_has_bare_sources(tmp_path):
    path = tmp_path / "flat.epub"
    sources = _make_epub(path, opf_dir="")
    assert location_for_percent(_Item(path), 55)["Source"] == sources[5] == "chapter006.xhtml"


def test_no_percent_no_location(book):
    path, _ = book
    assert location_for_percent(_Item(path), None) is None


def test_percent_out_of_range_is_clamped(book):
    path, sources = book
    assert location_for_percent(_Item(path), -20)["Source"] == sources[0]
    assert location_for_percent(_Item(path), 500)["Source"] == sources[-1]


@pytest.mark.parametrize("bad", ["", "/nope/missing.epub", None])
def test_unreadable_file_yields_none(bad):
    assert location_for_percent(_Item(bad or ""), 50) is None


def test_non_epub_file_yields_none(tmp_path):
    path = tmp_path / "notazip.epub"
    path.write_bytes(b"this is not a zip archive")
    assert location_for_percent(_Item(path), 50) is None


def test_result_is_cached_but_invalidated_when_the_file_changes(tmp_path):
    path = tmp_path / "book.epub"
    _make_epub(path, chapter_count=10)
    assert location_for_percent(_Item(path), 95)["Source"] == "OEBPS/chapter010.xhtml"
    # Rewrite with a different spine; mtime/size change must bust the cache.
    _make_epub(path, chapter_count=4)
    assert location_for_percent(_Item(path), 95)["Source"] == "OEBPS/chapter004.xhtml"


# ---------------------------------------------------------------------------
# percent_for_source (the inverse, used for the consistency check)
# ---------------------------------------------------------------------------

def test_percent_for_source_returns_the_documents_start(book):
    path, sources = book
    assert percent_for_source(_Item(path), sources[0]) == pytest.approx(0)
    assert percent_for_source(_Item(path), sources[5]) == pytest.approx(50)


def test_percent_for_unknown_source_is_none(book):
    path, _ = book
    assert percent_for_source(_Item(path), "OEBPS/not-in-this-book.xhtml") is None
    assert percent_for_source(_Item(path), None) is None


def test_round_trip_percent_to_source_and_back(book):
    path, _ = book
    loc = location_for_percent(_Item(path), 42)
    assert percent_for_source(_Item(path), loc["Source"]) == pytest.approx(40)


# ---------------------------------------------------------------------------
# _faithful_location — the consistency rule
# ---------------------------------------------------------------------------

def test_consistent_stored_location_is_echoed_verbatim(book):
    """A Kobo-written location that still matches the percentage must survive
    untouched — exact-span resume is the whole point of storing it."""
    path, sources = book
    stored = {"Source": sources[5], "Type": "KoboSpan", "Value": "kobo.47.3"}
    item = _Item(path, read_progress=52.0, read_location_json=json.dumps(stored))
    assert _faithful_location(item) == stored


def test_stale_stored_location_is_replaced_by_one_derived_from_progress(book):
    """The production failure: progress said 60 %, the stored location pointed
    at 26 %. The device obeyed the location and got stuck there."""
    path, sources = book
    stored = {"Source": sources[2], "Type": "KoboSpan", "Value": "kobo.1.1"}  # 20 %
    item = _Item(path, read_progress=60.0, read_location_json=json.dumps(stored))
    loc = _faithful_location(item)
    assert loc["Source"] == sources[5]  # 50–60 %, where the percentage actually points
    assert loc["Value"] == "kobo.1.1"


def test_drift_within_tolerance_keeps_the_exact_span(book):
    """Paging inside one chapter moves the percentage past the chapter start;
    that must not throw away the device's precise position."""
    path, sources = book
    stored = {"Source": sources[5], "Type": "KoboSpan", "Value": "kobo.90.1"}  # starts at 50 %
    item = _Item(path, read_progress=54.0, read_location_json=json.dumps(stored))
    assert _faithful_location(item) == stored


def test_no_stored_location_derives_from_progress(book):
    """A book read only in the browser has no location at all — it should still
    open near the right place on the Kobo."""
    path, sources = book
    assert _faithful_location(_Item(path, read_progress=75.0))["Source"] == sources[7]


def test_no_progress_and_no_location_is_null(book):
    path, _ = book
    assert _faithful_location(_Item(path)) is None


def test_stored_location_kept_when_progress_is_unknown(book):
    path, sources = book
    stored = {"Source": sources[3], "Type": "KoboSpan", "Value": "kobo.4.1"}
    item = _Item(path, read_progress=None, read_location_json=json.dumps(stored))
    assert _faithful_location(item) == stored


def test_foreign_source_is_not_second_guessed(book):
    """A Source we can't find in this spine (foreign or renamed file) gives us
    no basis to call it stale — echo it rather than overriding on a guess."""
    path, _ = book
    stored = {"Source": "OEBPS/somewhere-else.xhtml", "Type": "KoboSpan", "Value": "kobo.9.1"}
    item = _Item(path, read_progress=60.0, read_location_json=json.dumps(stored))
    assert _faithful_location(item) == stored


def test_unparseable_stored_location_falls_back_to_derived(book):
    path, sources = book
    item = _Item(path, read_progress=30.0, read_location_json="{not json")
    assert _faithful_location(item)["Source"] == sources[2]


def test_unreadable_book_with_stored_location_still_echoes_it(tmp_path):
    """No spine to measure against -> we can't judge staleness; keep what we
    have rather than dropping the device's position."""
    stored = {"Source": "OEBPS/ch1.xhtml", "Type": "KoboSpan", "Value": "kobo.1.1"}
    item = _Item(tmp_path / "missing.epub", read_progress=60.0,
                 read_location_json=json.dumps(stored))
    assert _faithful_location(item) == stored
