# Colophon – e-book metadata manager
"""Translate between a reading percentage and a Kobo ``Location``.

The Kobo positions a book by ``CurrentBookmark.Location`` — a span id resolved
against the content document it lives in — while Colophon's canonical progress
is a plain percentage. When the two come from different readers they can drift
apart: the in-browser reader advances ``read_progress`` but has no Kobo span to
offer (EPUB CFIs and KoboSpans are different coordinate systems), so a location
written by the Kobo weeks ago stays behind while the percentage moves on.
Shipping that pair unchanged makes the device obey the stale location and
recompute a *lower* percentage from it, which ``apply_reading_state`` then
rejects as a regression — a deadlock no re-sync can break.

This module closes the gap from the other side: given a percentage, work out
which spine document it falls in and name that document. The result is a real
content document from the book's own spine — not a fabricated ``Source`` (the
v1.28.2 bug was ``Source = book_uuid``, which resolves to nothing on the
device). Resolution is chapter-level, which is the best a percentage can carry.

Weighting uses the *uncompressed* size of each spine document, which is why
this reads the zip directly instead of going through ebooklib — ``ZipInfo``
carries the byte counts and ebooklib does not expose them.
"""
import logging
import os
import posixpath
import zipfile
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# The span every kepubify-generated content document starts with: first
# paragraph, first segment. Pairing it with a document Source puts the reader
# at the top of that document.
FIRST_SPAN = "kobo.1.1"

KOBO_SPAN_TYPE = "KoboSpan"

# Parsing a spine costs a zip open + two XML parses. A single Kobo sync builds
# a DTO for every book in the library, so keep the result around, keyed on
# identity *and* mtime/size so an edited file is re-read.
_spine_cache: dict[str, tuple[tuple, list[tuple[str, int]]]] = {}


def _spine_weights(path: str) -> list[tuple[str, int]] | None:
    """Ordered ``[(source, uncompressed_bytes), …]`` for one EPUB's spine.

    ``source`` is the archive-relative path of the content document — the same
    form the Kobo reports in ``Location.Source`` (e.g. ``OEBPS/chapter020.xhtml``),
    which is the OPF's directory joined with the manifest href.

    Returns ``None`` when the file isn't a readable EPUB with a usable spine.
    """
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None

    fingerprint = (st.st_mtime_ns, st.st_size)
    cached = _spine_cache.get(path)
    if cached and cached[0] == fingerprint:
        return cached[1]

    try:
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                return None
            opf_path = rootfile.get("full-path")
            if not opf_path:
                return None

            opf = ET.fromstring(z.read(opf_path))
            opf_dir = posixpath.dirname(opf_path)

            manifest = {
                el.get("id"): el.get("href")
                for el in opf.findall(".//{*}manifest/{*}item")
                if el.get("id") and el.get("href")
            }

            weights: list[tuple[str, int]] = []
            for ref in opf.findall(".//{*}spine/{*}itemref"):
                href = manifest.get(ref.get("idref"))
                if not href:
                    continue
                # Manifest hrefs are relative to the OPF; may be URL-encoded
                # or contain a fragment — neither belongs in a Source.
                href = href.split("#", 1)[0]
                source = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
                try:
                    size = z.getinfo(source).file_size
                except KeyError:
                    size = 0
                weights.append((source, size))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError, ValueError) as exc:
        logger.debug("kobo_location: cannot read spine from %s (%s)", path, exc)
        return None

    if not weights or sum(size for _, size in weights) <= 0:
        return None

    _spine_cache[path] = (fingerprint, weights)
    return weights


def _bounds(weights: list[tuple[str, int]]):
    """Yield ``(source, start_percent, end_percent)`` over the whole spine."""
    total = sum(size for _, size in weights)
    running = 0
    for source, size in weights:
        start = running * 100.0 / total
        running += size
        yield source, start, running * 100.0 / total


def location_for_percent(item, percent) -> dict | None:
    """Build the ``Location`` object for ``percent`` through ``item``'s file.

    Returns ``None`` when there is nothing trustworthy to derive from — no
    percentage, no readable EPUB, empty spine. Callers fall back to sending
    ``Location: null``, which leaves the device's own bookmark alone.
    """
    if percent is None:
        return None
    try:
        percent = float(percent)
    except (TypeError, ValueError):
        return None

    weights = _spine_weights(getattr(item, "file_path", None))
    if not weights:
        return None

    percent = max(0.0, min(100.0, percent))
    source = weights[-1][0]
    for candidate, _start, end in _bounds(weights):
        if percent <= end:
            source = candidate
            break

    return {"Source": source, "Type": KOBO_SPAN_TYPE, "Value": FIRST_SPAN}


def range_for_source(item, source) -> tuple[float, float] | None:
    """The ``(start, end)`` percentages ``source`` spans in the whole book.

    Used to judge whether a stored location still agrees with the stored
    percentage. It must be a *range*, not just the start: a bookmark sits
    somewhere inside its document, so reading through a long chapter legitimately
    moves the percentage far past where that chapter began. Comparing against
    the start alone would call a perfectly good position stale and rewind the
    reader to the chapter boundary on every sync — the worse the fewer chapters
    a book has.

    Returns ``None`` when the spine can't be read or ``source`` isn't part of it.
    """
    if not source:
        return None
    weights = _spine_weights(getattr(item, "file_path", None))
    if not weights:
        return None

    wanted = posixpath.normpath(str(source).split("#", 1)[0])
    for candidate, start, end in _bounds(weights):
        if candidate == wanted:
            return start, end
    return None


def percent_for_source(item, source) -> float | None:
    """Where ``source`` starts, as a percentage of the whole book."""
    span = range_for_source(item, source)
    return None if span is None else span[0]
