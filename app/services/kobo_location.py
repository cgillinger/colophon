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

There are two translations here, and they differ in precision:

**From a percentage** (``location_for_percent``): work out which spine document
the percentage falls in and name that document. The result is a real content
document from the book's own spine — not a fabricated ``Source`` (the v1.28.2
bug was ``Source = book_uuid``, which resolves to nothing on the device).
Chapter-level, which is the best a percentage can carry. Weighting uses the
*uncompressed* size of each spine document, which is why this reads the zip
directly instead of going through ebooklib — ``ZipInfo`` carries the byte
counts and ebooklib does not expose them.

**From a character offset** (``span_for_offset`` / ``offset_for_span``): exact.
kepubify preserves the text stream character for character and renames no file
— only the wrapping differs (every text chunk becomes a
``<span class="koboSpan" id="kobo.N.M">``). So "how many characters into this
chapter am I" means the same thing on both sides, and it bridges the two
coordinate systems without reimplementing kepubify's segmentation or parsing a
single CFI. Measured on a real book: 144 documents, 16,825 spans, zero
mismatches against the source EPUB.

Offsets count **non-whitespace characters only** — see ``dense_text`` for why,
and note that ``static/js/reader.js`` implements the same rule.
"""
import logging
import os
import posixpath
import re
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


# ---------------------------------------------------------------------------
# Character-offset bridge: browser position <-> KoboSpan
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")


def dense_text(text: str) -> str:
    """The text with every whitespace character removed.

    Offsets are counted in this space — "how many *visible* characters into the
    chapter am I" — and that choice is what makes the bridge exact rather than
    approximate. The two representations do not agree on whitespace: the source
    EPUB has newlines between block elements that live in no ``koboSpan`` at
    all, so a rule that merely collapsed runs would drift by one character per
    paragraph. Ignoring whitespace entirely sidesteps every such difference.

    Verified on a real book: across all 144 spine documents (16,825 spans), the
    dense text of the KEPUB is identical to the dense body text of the source
    EPUB. Zero mismatches.

    ``static/js/reader.js`` implements the same rule; they must not diverge.
    """
    return _WHITESPACE.sub("", text or "")


def _dense_starts(chunks: list[str]) -> list[int]:
    """Dense start offset of each chunk, given they are concatenated.

    Whitespace contributes nothing, so unlike a collapsing rule this needs no
    cross-boundary bookkeeping — each chunk simply begins where the previous
    one ended.
    """
    starts: list[int] = []
    total = 0
    for chunk in chunks:
        starts.append(total)
        total += len(dense_text(chunk))
    return starts


_span_cache: dict[str, tuple[tuple, dict[str, tuple[list[str], list[str]]]]] = {}


def _kepub_path(item) -> str | None:
    """Path to the cached KEPUB — the exact bytes the device downloaded.

    ``convert_epub_to_kepub`` keys its cache on (item id, source mtime), so as
    long as the source file is untouched this is byte-identical to what the
    Kobo holds, which is what makes the span ids agree.
    """
    path = getattr(item, "file_path", None)
    if not path or not str(path).lower().endswith(".epub"):
        return None
    try:
        from app.services.kobo_kepub import convert_epub_to_kepub

        return convert_epub_to_kepub(getattr(item, "id", None), path)
    except Exception as exc:  # kepubify missing, conversion failed, …
        logger.debug("kobo_location: no kepub for item %s (%s)", getattr(item, "id", None), exc)
        return None


def _spans_in_document(item, source) -> tuple[list[str], list[str]] | None:
    """``(span_ids, span_texts)`` in document order for one chapter."""
    kepub = _kepub_path(item)
    if not kepub or not source:
        return None
    try:
        st = os.stat(kepub)
    except OSError:
        return None

    fingerprint = (st.st_mtime_ns, st.st_size)
    cached = _span_cache.get(kepub)
    if not cached or cached[0] != fingerprint:
        cached = (fingerprint, {})
        _span_cache[kepub] = cached
    per_doc = cached[1]

    wanted = posixpath.normpath(str(source).split("#", 1)[0])
    if wanted in per_doc:
        return per_doc[wanted]

    try:
        from bs4 import BeautifulSoup

        with zipfile.ZipFile(kepub) as z:
            raw = z.read(wanted).decode("utf-8", "replace")
        soup = BeautifulSoup(raw, "html.parser")
        ids: list[str] = []
        texts: list[str] = []
        # Only koboSpan elements — never every text node. The kepub injects a
        # <style class="kobostylehacks"> block whose CSS would otherwise be
        # counted as body text and shift every offset in the document.
        for el in soup.find_all("span", class_="koboSpan"):
            span_id = el.get("id")
            if not span_id:
                continue
            ids.append(span_id)
            texts.append(el.get_text())
    except (KeyError, zipfile.BadZipFile, OSError, ValueError, ImportError) as exc:
        logger.debug("kobo_location: cannot read spans from %s/%s (%s)", kepub, wanted, exc)
        return None

    if not ids:
        return None
    per_doc[wanted] = (ids, texts)
    return ids, texts


def span_for_offset(item, source, offset) -> str | None:
    """The ``kobo.N.M`` covering ``offset`` characters into ``source``.

    ``offset`` counts non-whitespace characters (:func:`dense_text`), the same
    way the browser reader counts them. Returns ``None`` when the document has no
    spans (no kepub, unreadable, an image-only page).
    """
    if offset is None:
        return None
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        return None

    spans = _spans_in_document(item, source)
    if not spans:
        return None
    ids, texts = spans
    starts = _dense_starts(texts)

    chosen = ids[0]
    for span_id, start in zip(ids, starts):
        if start > offset:
            break
        chosen = span_id
    return chosen


def offset_for_span(item, source, span_id) -> int | None:
    """Characters into ``source`` where ``span_id`` begins — the inverse."""
    if not span_id:
        return None
    spans = _spans_in_document(item, source)
    if not spans:
        return None
    ids, texts = spans
    try:
        index = ids.index(str(span_id))
    except ValueError:
        return None
    return _dense_starts(texts)[index]


def location_for_offset(item, source, offset) -> dict | None:
    """A full ``Location`` object for a character offset into ``source``."""
    span_id = span_for_offset(item, source, offset)
    if not span_id:
        return None
    return {
        "Source": posixpath.normpath(str(source).split("#", 1)[0]),
        "Type": KOBO_SPAN_TYPE,
        "Value": span_id,
    }
