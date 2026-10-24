# Colophon – e-book metadata manager
"""KOSync — reading position for CrossPoint (Xteink) and KOReader.

The device asks "where is this book?" and says "I am here", nothing else.
How it decides between the two matters for everything below. CrossPoint's
smart sync (``KOReaderSyncActivity::performSync``) compares positions and
**jumps to whichever is further along** — no timestamps. So what we answer
with is obeyed whenever it is ahead of the device. That makes one rule
load-bearing:

**We answer with the position (where the reader last was, last-write-wins),
never with ``read_progress`` (the furthest point ever reached).** Progress is a
high-water mark; one peek at the last chapter raises it for good. Serving it
as a position is exactly the "it says 85 % but I have read 10 %" bug v1.63.0
fixed for the browser reader. No position → 404, and the device keeps its
own.

Writes from the device go through the same helpers as the Kobo and the
browser: ``apply_reading_state`` for progress/status (furthest-read-wins,
monotonic status) and ``record_position`` for where the reader is. Two
deliberate differences:

- The status sent is always ``Reading``. A device that pages to the end once
  must not mark a book Finished: status is monotonic, so that could only be
  undone by a reset.
- The position is exact (``services/koreader_xpath.py``), and is checked
  against the device's own percentage before it is believed. A pointer that
  lands in a chapter the percentage does not fall in is dropped to chapter
  level instead of moving the reader somewhere wrong.

Unknown documents (a book Colophon never had) are acknowledged and dropped,
as the Kobo path does with foreign UUIDs, with a warning in the log.
"""
import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request

from app.models import db
from app.services.kobo_location import location_for_offset, location_for_percent, range_for_source
from app.services.kosync_documents import resolve
from app.services.koreader_xpath import (
    chapter_length,
    chapter_start_xpath,
    offset_for_xpath,
    xpath_for_offset,
)
from app.services.page_map import load_page_map, page_for_position
from app.services.reader_devices import find_device_by_token, touch_device
from app.services.reading_state import apply_reading_state, read_position, record_position

logger = logging.getLogger(__name__)

kosync_bp = Blueprint("kosync", __name__, url_prefix="/kosync")

# How far outside its chapter the device's percentage may fall before we stop
# believing the pointer. Percentages are computed differently on each side
# (CrossPoint and Colophon weigh chapters by size, not identically).
CHAPTER_SLACK = 5.0


def require_reader(f):
    @wraps(f)
    def wrapper(token, *args, **kwargs):
        device = find_device_by_token(token)
        if device is None:
            logger.info("KOSync auth failed for token prefix %s...", token[:8])
            return jsonify({"message": "Unauthorized"}), 401
        return f(device, *args, **kwargs)
    return wrapper


def _now_ms() -> int:
    return int((datetime.utcnow() - datetime(1970, 1, 1)).total_seconds() * 1000)


def _percent_at(item, source, offset) -> float | None:
    """Where ``offset`` into ``source`` sits in the whole book, 0–100."""
    span = range_for_source(item, source)
    if span is None:
        return None
    start, end = span
    if offset is None:
        return start
    length = chapter_length(item, source)
    if not length:
        return start
    return start + (end - start) * min(1.0, max(0.0, offset / length))


def _stored_position(item):
    """``(source, offset, at_ms, origin)`` of where the reader last was."""
    pos = read_position(item)
    if pos and pos.get("source"):
        return pos["source"], pos.get("offset"), pos.get("at"), pos.get("origin")
    return None


# ---------------------------------------------------------------------------
# Account endpoints. The token in the path is the credential; KOSync's own
# username/key headers are accepted and ignored, so any values work.
# ---------------------------------------------------------------------------

@kosync_bp.route("/<token>/users/auth")
@require_reader
def users_auth(device):
    touch_device(device)
    return jsonify({"authorized": "OK"})


@kosync_bp.route("/<token>/users/create", methods=["POST"])
@require_reader
def users_create(device):
    touch_device(device)
    payload = request.get_json(silent=True) or {}
    return jsonify({"username": payload.get("username") or device.name}), 201


@kosync_bp.route("/<token>/healthcheck")
@require_reader
def healthcheck(device):
    return jsonify({"state": "OK"})


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

@kosync_bp.route("/<token>/syncs/progress/<document>")
@require_reader
def get_progress(device, document):
    touch_device(device)
    item = resolve(document)
    if item is None:
        logger.info("KOSync GET: unknown document %s", document)
        return jsonify({"message": "Not found"}), 404

    stored = _stored_position(item)
    if stored is None:
        # Never fall back to read_progress: it is how far the reader has
        # been, not where they are (see the module docstring).
        return jsonify({"message": "Not found"}), 404
    source, offset, at_ms, origin = stored

    xpath = xpath_for_offset(item, source, offset) if offset is not None else None
    if xpath is None:
        offset = None
        xpath = chapter_start_xpath(item, source)
    if xpath is None:
        return jsonify({"message": "Not found"}), 404
    percent = _percent_at(item, source, offset)
    return jsonify({
        "document": document,
        "progress": xpath,
        "percentage": round((percent or 0.0) / 100.0, 6),
        "device": f"Colophon ({origin})" if origin else "Colophon",
        "device_id": "colophon",
        "timestamp": int((at_ms or _now_ms()) // 1000),
    })


@kosync_bp.route("/<token>/syncs/progress", methods=["PUT"])
@require_reader
def put_progress(device):
    touch_device(device, mark_sync=True)
    payload = request.get_json(silent=True) or {}
    document = str(payload.get("document") or "")
    now_ms = _now_ms()
    answer = jsonify({"document": document, "timestamp": now_ms // 1000})

    item = resolve(document)
    if item is None:
        logger.warning(
            "KOSync PUT: document %s from %s matches no single book "
            "(not from this library, or ambiguous — see above), dropped",
            document, device.name,
        )
        return answer

    try:
        fraction = float(payload.get("percentage"))
        device_percent = max(0.0, min(100.0, fraction * 100.0))
    except (TypeError, ValueError):
        device_percent = None

    source = offset = None
    target = offset_for_xpath(item, str(payload.get("progress") or ""))
    if target is not None:
        source, offset = target
        span = range_for_source(item, source)
        if device_percent is not None and span is not None and not (
            span[0] - CHAPTER_SLACK <= device_percent <= span[1] + CHAPTER_SLACK
        ):
            logger.warning(
                "KOSync PUT: book_id=%s pointer %s lands at %.1f–%.1f %% but the "
                "device says %.1f %% — keeping chapter level only",
                item.id, payload.get("progress"), span[0], span[1], device_percent,
            )
            source = offset = None

    if source is not None:
        percent = _percent_at(item, source, offset)
    elif device_percent is not None:
        percent = device_percent
        loc = location_for_percent(item, percent)
        source = loc["Source"] if loc else None
    else:
        logger.info("KOSync PUT: book_id=%s carried no usable position", item.id)
        return answer

    location = location_for_offset(item, source, offset) if offset is not None else None
    applied = apply_reading_state(
        item,
        "Reading",
        progress=percent,
        location=location,
        modified_at=datetime.utcnow(),
        clear_location=location is None,
    )
    page = None
    if source and offset is not None:
        page = page_for_position(load_page_map(item, build=False), source, offset)
    recorded = record_position(
        item,
        source=source,
        offset=offset,
        percent=percent,
        at_ms=now_ms,
        origin="kosync",
        page=page,
    )
    if applied or recorded:
        db.session.commit()
    logger.info(
        "KOSync PUT: book_id=%s device=%s percent=%.1f exact=%s progress_applied=%s",
        item.id, device.name, percent or 0.0, offset is not None, applied,
    )
    return answer
