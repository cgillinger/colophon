# Colophon – e-book metadata manager
"""Translate between a KOReader XPointer and Colophon's character position.

KOSync clients (CrossPoint on an Xteink, KOReader) report where the reader is
as an XPointer into the *source* EPUB:

    /body/DocFragment[3]/body/div[2]/p[42]/text()[1].17

i.e. spine document 3 (1-based), an element path with 1-based indices among
same-named siblings, the n-th text node of that element and a codepoint offset
inside it. Colophon's canonical position is ``(source, offset)`` where
``offset`` counts non-whitespace characters into the chapter
(``kobo_location.dense_text``) — the coordinate the Kobo bridge and the
browser reader already share. Both describe a point in the same text, so the
translation is exact in both directions; no percentage is involved.

The walk mirrors CrossPoint's own resolver
(``lib/KOReaderSync/ChapterXPathResolver.cpp``) rule for rule, because the
device resolves the XPointers we hand it with that code:

- expat, element names with any namespace prefix stripped, case kept;
- sibling indices count every child element of the parent by name;
- a text node is a run of character data between two markup boundaries
  (element start/end, comment, processing instruction, CDATA edge), counted
  per parent element, and only when it lies outside head/style/script/title/rp;
- the offset counts codepoints of that run as expat delivers them. Entities
  expat skips (``&nbsp;`` without a loaded DTD) are not delivered to
  CrossPoint, so they do not count toward the offset — but they are real text
  in the browser and the KEPUB, so they do count toward ``offset``.

Dense counting follows ``static/js/reader.js``: all body text except inside
``script``/``style``. Positions are never anchored in a whitespace-only run or
inside an element CrossPoint does not count; such a target moves forward to
the next character it can resolve.
"""
import html.entities
import logging
import os
import re
import zipfile
import xml.parsers.expat
from dataclasses import dataclass, field

from app.services.kobo_location import _spine_weights, dense_text

logger = logging.getLogger(__name__)

# ChapterXPathResolver's VisibleTextUtils::isNonVisibleElement.
_NON_VISIBLE = {"head", "style", "script", "title", "rp"}
# reader.js textWalker rejects text under these; everything else is counted.
_NOT_DENSE = {"style", "script"}

_WS = re.compile(r"\s")
_XPATH_RE = re.compile(r"^/body/DocFragment\[(\d+)\](.*)$")
_STEP_RE = re.compile(r"^([^\[\]/.]+)(?:\[(\d+)\])?$")


@dataclass
class _TextNode:
    path: tuple            # ((name, index), ...) below <body>
    index: int             # 1-based text()[n] within its element; 0 = not addressable
    chars: list = field(default_factory=list)   # the text, one entry per character
    counted: list = field(default_factory=list)  # True where CrossPoint counts the character
    dense: bool = True     # counts toward Colophon's offset
    dense_start: int = 0   # dense characters before this node


@dataclass
class _Document:
    nodes: list
    element_starts: dict   # path tuple -> dense characters before the element


def _local(name: str) -> str:
    return name.rsplit(":", 1)[-1]


def _parse(raw: bytes) -> _Document | None:
    """Walk one XHTML document into text nodes, CrossPoint style."""
    nodes: list[_TextNode] = []
    element_starts: dict[tuple, int] = {}
    state = {
        "in_body": False,
        "depth": 0,
        "body_depth": -1,
        "pending": True,
        "non_visible": 0,
        "not_dense": 0,
        "dense": 0,
    }
    path: list[tuple] = []
    siblings: list[dict] = []
    text_index: list[int] = []

    def start(name, _attrs):
        local = _local(name)
        if not state["in_body"]:
            if local == "body":
                state["in_body"] = True
                state["body_depth"] = state["depth"]
                siblings.append({})
                text_index.append(0)
            state["depth"] += 1
            return
        state["pending"] = True
        counts = siblings[-1]
        counts[local] = counts.get(local, 0) + 1
        path.append((local, counts[local]))
        siblings.append({})
        text_index.append(0)
        element_starts.setdefault(tuple(path), state["dense"])
        if state["non_visible"] or local.lower() in _NON_VISIBLE:
            state["non_visible"] += 1
        if state["not_dense"] or local.lower() in _NOT_DENSE:
            state["not_dense"] += 1
        state["depth"] += 1

    def end(name):
        local = _local(name)
        state["depth"] -= 1
        if not state["in_body"]:
            return
        if state["depth"] == state["body_depth"] and local == "body":
            state["in_body"] = False
            return
        if state["non_visible"]:
            state["non_visible"] -= 1
        if state["not_dense"]:
            state["not_dense"] -= 1
        state["pending"] = True
        if text_index:
            text_index.pop()
        if siblings:
            siblings.pop()
        if path:
            path.pop()

    def text(data, counted=True):
        if not state["in_body"] or not data:
            return
        dense = not state["not_dense"]
        if state["non_visible"]:
            # Not addressable on the device, but still text in the browser.
            node = _TextNode(tuple(path), 0, list(data), [counted] * len(data),
                             dense, state["dense"])
            nodes.append(node)
            if dense:
                state["dense"] += len(dense_text(data))
            return
        if state["pending"] or not nodes or nodes[-1].index == 0 or nodes[-1].path != tuple(path):
            if state["pending"]:
                text_index[-1] += 1
                state["pending"] = False
            nodes.append(_TextNode(tuple(path), text_index[-1], [], [], dense, state["dense"]))
        node = nodes[-1]
        node.chars.extend(data)
        node.counted.extend([counted] * len(data))
        if dense:
            state["dense"] += len(dense_text(data))

    def skipped(name, is_parameter):
        # Never delivered to CrossPoint (no handler there), but a real
        # character in every DOM that resolves the entity.
        if is_parameter:
            return
        codepoint = html.entities.name2codepoint.get(name)
        if codepoint is not None:
            text(chr(codepoint), counted=False)

    def boundary(*_args):
        if state["in_body"] and not state["non_visible"]:
            state["pending"] = True

    parser = xml.parsers.expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.SkippedEntityHandler = skipped
    parser.CommentHandler = boundary
    parser.ProcessingInstructionHandler = boundary
    parser.StartCdataSectionHandler = boundary
    parser.EndCdataSectionHandler = boundary
    try:
        parser.Parse(raw, True)
    except xml.parsers.expat.ExpatError as exc:
        logger.debug("koreader_xpath: cannot parse document (%s)", exc)
        return None
    return _Document(nodes, element_starts)


_doc_cache: dict[tuple, _Document] = {}
_DOC_CACHE_MAX = 64


def _document(path: str, source: str) -> _Document | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime_ns, st.st_size, source)
    cached = _doc_cache.get(key)
    if cached is not None:
        return cached
    try:
        with zipfile.ZipFile(path) as z:
            raw = z.read(source)
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        logger.debug("koreader_xpath: cannot read %s from %s (%s)", source, path, exc)
        return None
    doc = _parse(raw)
    if doc is None:
        return None
    if len(_doc_cache) >= _DOC_CACHE_MAX:
        _doc_cache.pop(next(iter(_doc_cache)))
    _doc_cache[key] = doc
    return doc


def _parse_xpath(xpath: str):
    """``(fragment, steps, text_index, char_offset)``, or None.

    ``text_index`` is None when the pointer names an element rather than a
    point inside its text. Steps carry index 0 when the pointer omits one.
    """
    m = _XPATH_RE.match((xpath or "").strip())
    if not m:
        return None
    fragment = int(m.group(1))
    rest = m.group(2)
    if rest.startswith("/body"):
        rest = rest[len("/body"):]
    elif rest and not rest.startswith("."):
        return None

    text_index = None
    char_offset = 0
    t = rest.rfind("/text()")
    if t >= 0:
        tail = rest[t + len("/text()"):]
        rest = rest[:t]
        tm = re.match(r"^(?:\[(\d+)\])?(?:\.(\d+))?$", tail)
        if not tm:
            return None
        text_index = int(tm.group(1) or 1)
        char_offset = int(tm.group(2) or 0)
    else:
        dm = re.search(r"\.(\d+)$", rest)
        if dm:
            rest = rest[: dm.start()]

    steps = []
    for part in [p for p in rest.split("/") if p]:
        sm = _STEP_RE.match(part)
        if not sm:
            return None
        steps.append((sm.group(1), int(sm.group(2) or 0)))
    return fragment, tuple(steps), text_index, char_offset


def _path_matches(path: tuple, steps: tuple) -> bool:
    if len(path) != len(steps):
        return False
    for (name, index), (want, want_index) in zip(path, steps):
        if name != want or (want_index and index != want_index):
            return False
    return True


def _spine_sources(item) -> list[str] | None:
    weights = _spine_weights(getattr(item, "file_path", None))
    return [source for source, _ in weights] if weights else None


def offset_for_xpath(item, xpath: str) -> tuple[str, int] | None:
    """``(source, offset)`` for a KOReader XPointer, or None if it can't resolve."""
    parsed = _parse_xpath(xpath)
    if parsed is None:
        return None
    fragment, steps, text_index, char_offset = parsed
    sources = _spine_sources(item)
    if not sources or not 1 <= fragment <= len(sources):
        return None
    source = sources[fragment - 1]
    doc = _document(item.file_path, source)
    if doc is None:
        return None

    if text_index is None:
        if not steps:
            return source, 0
        for path, dense in doc.element_starts.items():
            if _path_matches(path, steps):
                return source, dense
        return None

    for node in doc.nodes:
        if node.index != text_index or not _path_matches(node.path, steps):
            continue
        dense = node.dense_start
        seen = 0
        for ch, counted in zip(node.chars, node.counted):
            if counted:
                if seen >= char_offset:
                    break
                seen += 1
            if node.dense and not _WS.match(ch):
                dense += 1
        return source, dense
    return None


def xpath_for_offset(item, source: str, offset: int) -> str | None:
    """The KOReader XPointer for ``offset`` dense characters into ``source``."""
    if offset is None or not source:
        return None
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        return None
    sources = _spine_sources(item)
    if not sources or source not in sources:
        return None
    fragment = sources.index(source) + 1
    doc = _document(item.file_path, source)
    if doc is None:
        return None

    last = None
    for node in doc.nodes:
        if node.index == 0:
            continue
        cp = 0
        dense = node.dense_start
        for ch, counted in zip(node.chars, node.counted):
            visible = not _WS.match(ch)
            if visible:
                last = (node, cp)
                if dense >= offset:
                    return _format(fragment, node, cp)
                if node.dense:
                    dense += 1
            if counted:
                cp += 1
    if last is None:
        return f"/body/DocFragment[{fragment}]/body"
    return _format(fragment, *last)


def chapter_length(item, source: str) -> int | None:
    """Dense characters in ``source`` — the denominator for a within-chapter fraction."""
    if not source:
        return None
    doc = _document(getattr(item, "file_path", None) or "", source)
    if doc is None:
        return None
    return sum(len(dense_text("".join(n.chars))) for n in doc.nodes if n.dense)


def chapter_start_xpath(item, source: str) -> str | None:
    """The XPointer for the top of ``source``: chapter-level, no offset."""
    sources = _spine_sources(item)
    if not sources or source not in sources:
        return None
    return f"/body/DocFragment[{sources.index(source) + 1}]/body"


def _format(fragment: int, node: _TextNode, cp: int) -> str:
    steps = "".join(f"/{name}[{index}]" for name, index in node.path)
    return f"/body/DocFragment[{fragment}]/body{steps}/text()[{node.index}].{cp}"
