# Colophon – e-book metadata manager
"""Shared reading-state write logic.

The canonical reading progress for a book lives on ``LibraryItem``
(``read_status`` / ``read_progress`` / ``read_location`` / timestamps), not
per device. Both the Kobo sync PUT handler (``routes/kobo.py``) and the
in-browser reader (``routes/reader.py``) feed updates through this one
function so the two can never drift apart in how they enforce monotonic
status or last-write-wins ordering.

This was extracted from the Kobo handler; it carries that handler's rules
verbatim so existing Kobo behaviour is unchanged.
"""
import json
from datetime import datetime

# Monotonic status ranks: a book only ever moves forward.
READ_STATUS_RANK = {"ReadyToRead": 0, "Reading": 1, "Finished": 2}

# Progress is a percentage (0–100). Differences smaller than this are treated
# as "the same page" so float noise from round-tripping a device's own
# coordinates can't read as a regression and flap the position.
PROGRESS_EPSILON = 0.01


def _as_progress(value):
    """Coerce an incoming progress value to float, or None if absent/invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_reading_state(item, status, progress=None, location=None, modified_at=None):
    """Apply a reading-state update to ``item`` in place.

    Rules (identical to the Kobo PUT handler this was extracted from):
      - Status is monotonic: ReadyToRead < Reading < Finished. A lower-ranked
        incoming status is dropped regardless of timestamp.
      - Equal-rank updates use **furthest-read-wins**, like an e-reader's "sync
        to the furthest page read": progress may never go backwards, and a
        higher-or-equal progress applies even when its timestamp is *older* than
        what is stored (furthest page beats the wall clock). Only when progress
        is missing on either side — nothing to compare — do we fall back to
        last-write-wins on ``modified_at``. This is what stops a stray
        ``progress=0.0`` PUT (a cover-reset / sync echo from the device) with a
        newer timestamp from wiping a real position.
      - ``read_started_at`` / ``times_started`` are set on the first transition
        into ``Reading``; ``read_finished_at`` on the first into ``Finished``,
        which also coerces progress to 100.
      - ``location`` is only touched when truthy, so a caller that has no
        location (the browser reader, which resumes by percent) never clobbers a
        location written by another device. A ``dict`` (the Kobo's full
        ``CurrentBookmark.Location``: Value + Type + Source) is stored verbatim
        in ``read_location_json`` and its ``Value`` mirrored to ``read_location``
        for display; a plain string (legacy) updates ``read_location`` only.
      - ``read_last_modified`` only ever advances, so an applied older-timestamp
        "furthest page" update can't drag the timeline marker (and the Kobo
        delta it drives) backwards.

    Deliberate resets (re-read from the start) go through the dedicated
    reset endpoint, which writes the fields directly and does NOT call this
    helper, so the never-go-backwards rule never blocks a reset.

    Does NOT commit — the caller owns the transaction. Returns ``True`` if the
    update was applied, ``False`` if it was dropped by the rules above.
    """
    status = status or item.read_status or "ReadyToRead"

    current_rank = READ_STATUS_RANK.get(item.read_status or "ReadyToRead", 0)
    incoming_rank = READ_STATUS_RANK.get(status, 0)

    # Monotonic — finished books stay finished, etc.
    if incoming_rank < current_rank:
        return False

    # Equal status rank: furthest-read-wins (status escalation skips this and
    # always applies — e.g. Reading -> Finished, even with a lower progress).
    if incoming_rank == current_rank:
        incoming_progress = _as_progress(progress)
        current_progress = item.read_progress
        if incoming_progress is not None and current_progress is not None:
            if incoming_progress < current_progress - PROGRESS_EPSILON:
                # Would move the position backwards — drop it, even if newer.
                return False
            # incoming >= current: apply regardless of timestamp ordering.
        elif (
            item.read_last_modified
            and modified_at
            and modified_at <= item.read_last_modified
        ):
            # No progress to compare — keep last-write-wins on the timeline.
            return False

    item.read_status = status
    if progress is not None:
        try:
            item.read_progress = float(progress)
        except (TypeError, ValueError):
            pass
    if location:
        if isinstance(location, dict):
            # Full Kobo Location object — keep it verbatim so the device can
            # resolve the exact span on resume, and mirror Value for display.
            item.read_location_json = json.dumps(location)
            item.read_location = location.get("Value")
        else:
            # Legacy/string location (e.g. existing callers/tests).
            item.read_location = location
    # Timeline marker advances only — never regress it, even when we apply an
    # older-timestamped furthest-page update above.
    incoming_mod = modified_at or datetime.utcnow()
    if not item.read_last_modified or incoming_mod >= item.read_last_modified:
        item.read_last_modified = incoming_mod

    if status == "Reading" and not item.read_started_at:
        item.read_started_at = item.read_last_modified
        item.times_started = (item.times_started or 0) + 1
    if status == "Finished":
        if not item.read_finished_at:
            item.read_finished_at = item.read_last_modified
        # Devices sometimes report 99.x on finished books; coerce to 100.
        if item.read_progress is None or item.read_progress < 100:
            item.read_progress = 100.0

    return True
