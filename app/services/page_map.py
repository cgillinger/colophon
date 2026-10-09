# Colophon – e-book metadata manager
"""Virtual page numbers for EPUBs.

A percentage means something different on every device (font size, screen),
so it cannot be shown to a human as "where am I". A *virtual page* is a fixed
number of dense (non-whitespace) characters — the same unit the Kobo/browser
position bridge already uses (``kobo_location``) — so page 212 is the same
place on the phone, the iPad and the Kobo.

The map is built once per book from the source EPUB (never the KEPUB: the dense
text of the two is identical, and the browser reads the source) and cached as
JSON next to the other derived data. Building parses every spine document, so
it must never happen inside a write path (progress POST, Kobo PUT): those use
``load_page_map(item, build=False)`` and degrade to "no page" when the map
has not been built yet.
"""
import json
import logging
import math
import os
import posixpath
import re
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString

# Private helper on purpose: the spine order and `source` strings must be
# exactly what the Kobo bridge and the browser's `href` use.
from app.services.kobo_location import _spine_weights, dense_text

logger = logging.getLogger(__name__)

# Roughly one paperback page of text. Measured on a real Swedish trade
# paperback with an EPUB page-list: ~1 150 dense characters per printed page;
# dense fiction runs a little higher. 1 200 keeps the virtual count close to
# what the printed book would say.
PAGE_CHARS = 1200

# Publishers label page breaks in many shapes — "Page 72.", "p. 72", "72" —
# and the reader shows the label in parentheses next to the virtual page, so
# it is reduced to the bare number/roman numeral where it has that shape.
_LABEL_NOISE = re.compile(r"^(?:page|p\.|sida|s\.|seite)\s*", re.IGNORECASE)


def _is_pagebreak(el) -> bool:
    etype = el.get("epub:type") or ""
    if isinstance(etype, list):
        etype = " ".join(etype)
    return "pagebreak" in etype.split() or el.get("role") == "doc-pagebreak"


def _scan_document(markup: bytes, source: str):
    """``(dense_chars, page_breaks)`` for one spine document.

    Mirrors ``textWalker`` + ``dense`` in static/js/reader.js: text nodes under
    <body>, skipping script/style descendants and comments. If the rule here
    changes, the reader's must too, or every page number drifts.
    """
    soup = BeautifulSoup(markup, "html.parser")
    root = soup.body or soup
    total = 0
    breaks = []
    for node in root.descendants:
        if isinstance(node, NavigableString):
            if isinstance(node, Comment) or type(node) is not NavigableString:
                # Comments, doctype, CDATA, and bs4's Script/Stylesheet strings.
                continue
            if any(p.name in ("script", "style") for p in node.parents):
                continue
            total += len(dense_text(str(node)))
        elif _is_pagebreak(node):
            label = (
                node.get("title") or node.get("aria-label") or node.get_text() or ""
            ).strip()
            label = _LABEL_NOISE.sub("", label).rstrip(".").strip()
            if label:
                breaks.append({"source": source, "offset": total, "label": label})
    return total, breaks


def build_page_map(item) -> dict | None:
    path = getattr(item, "file_path", None)
    if not path or not str(path).lower().endswith(".epub"):
        return None
    spine = _spine_weights(path)
    if not spine:
        return None
    sections, page_list = [], []
    start = 0
    try:
        with zipfile.ZipFile(path) as z:
            for source, _size in spine:
                try:
                    markup = z.read(source)
                except KeyError:
                    chars, breaks = 0, []
                else:
                    chars, breaks = _scan_document(markup, source)
                sections.append({"source": source, "chars": chars, "start": start})
                page_list.extend(breaks)
                start += chars
    except (zipfile.BadZipFile, OSError) as exc:
        logger.debug("page_map: cannot read %s (%s)", path, exc)
        return None
    return {
        "page_chars": PAGE_CHARS,
        "sections": sections,
        "total_chars": start,
        "total_pages": max(1, math.ceil(start / PAGE_CHARS)),
        "page_list": page_list,
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    from flask import current_app

    path = Path(current_app.config.get("DATA_DIR", "/data")) / "page-maps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_file(item) -> Path | None:
    try:
        mtime = os.stat(item.file_path).st_mtime_ns
    except (OSError, TypeError):
        return None
    return _cache_dir() / f"{item.id}-{mtime}.json"


def load_page_map(item, build=True) -> dict | None:
    """The cached map; builds and caches it when absent and ``build`` is True."""
    path = getattr(item, "file_path", None)
    if not path or not str(path).lower().endswith(".epub"):
        return None
    cache = _cache_file(item)
    if cache is None:
        return None
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass  # corrupt cache: fall through and rebuild (if allowed)
    if not build:
        return None
    page_map = build_page_map(item)
    if page_map is None:
        return None
    for stale in cache.parent.glob(f"{item.id}-*.json"):
        if stale != cache:
            try:
                stale.unlink()
            except OSError:
                pass
    try:
        cache.write_text(json.dumps(page_map), encoding="utf-8")
    except OSError as exc:
        logger.warning("page_map: cannot cache for item %s (%s)", item.id, exc)
    return page_map


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _norm(source) -> str | None:
    if not source:
        return None
    return posixpath.normpath(str(source).split("#", 1)[0])


def _section(page_map, source):
    source = _norm(source)
    for sec in page_map.get("sections", []):
        if sec["source"] == source:
            return sec
    return None


def page_for_position(page_map, source, offset) -> int | None:
    """1-based virtual page of ``offset`` dense chars into ``source``."""
    if not page_map:
        return None
    sec = _section(page_map, source)
    if sec is None:
        return None
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0
    page = (sec["start"] + offset) // page_map["page_chars"] + 1
    return max(1, min(page, page_map["total_pages"]))


def position_for_page(page_map, page):
    """``(source, offset)`` where ``page`` begins — inverse of the above."""
    if not page_map or not page_map.get("sections"):
        return None
    try:
        page = int(page)
    except (TypeError, ValueError):
        return None
    page = max(1, min(page, page_map["total_pages"]))
    target = (page - 1) * page_map["page_chars"]
    populated = [s for s in page_map["sections"] if s["chars"] > 0]
    if not populated:
        sec = page_map["sections"][0]
        return sec["source"], 0
    for sec in populated:
        if target < sec["start"] + sec["chars"]:
            return sec["source"], max(0, target - sec["start"])
    last = populated[-1]
    return last["source"], max(0, last["chars"] - 1)


def print_page_for_position(page_map, source, offset) -> str | None:
    """Label of the last print page break at or before the position."""
    if not page_map or not page_map.get("page_list"):
        return None
    order = {s["source"]: i for i, s in enumerate(page_map["sections"])}
    src = _norm(source)
    if src not in order:
        return None
    try:
        offset = int(offset or 0)
    except (TypeError, ValueError):
        offset = 0
    found = None
    for entry in page_map["page_list"]:
        idx = order.get(entry["source"])
        if idx is None:
            continue
        if idx < order[src] or (idx == order[src] and entry["offset"] <= offset):
            found = entry["label"]
    return found
