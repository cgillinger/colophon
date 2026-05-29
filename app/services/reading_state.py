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
from datetime import datetime

# Monotonic status ranks: a book only ever moves forward.
READ_STATUS_RANK = {"ReadyToRead": 0, "Reading": 1, "Finished": 2}


def apply_reading_state(item, status, progress=None, location=None, modified_at=None):
    """Apply a reading-state update to ``item`` in place.

    Rules (identical to the Kobo PUT handler this was extracted from):
      - Status is monotonic: ReadyToRead < Reading < Finished. A lower-ranked
        incoming status is dropped regardless of timestamp.
      - Equal-rank updates follow last-write-wins on ``modified_at``: an older
        timestamp loses to the existing row.
      - ``read_started_at`` / ``times_started`` are set on the first transition
        into ``Reading``; ``read_finished_at`` on the first into ``Finished``,
        which also coerces progress to 100.
      - ``read_location`` is only touched when a truthy ``location`` is given,
        so a caller that has no location (the browser reader, which resumes by
        percent) never clobbers a location written by another device.

    Does NOT commit — the caller owns the transaction. Returns ``True`` if the
    update was applied, ``False`` if it was dropped by the rules above.
    """
    status = status or item.read_status or "ReadyToRead"

    current_rank = READ_STATUS_RANK.get(item.read_status or "ReadyToRead", 0)
    incoming_rank = READ_STATUS_RANK.get(status, 0)

    # Monotonic — finished books stay finished, etc.
    if incoming_rank < current_rank:
        return False

    # Last-write-wins on the timeline (only when status doesn't escalate).
    if (
        incoming_rank == current_rank
        and item.read_last_modified
        and modified_at
        and modified_at <= item.read_last_modified
    ):
        return False

    item.read_status = status
    if progress is not None:
        try:
            item.read_progress = float(progress)
        except (TypeError, ValueError):
            pass
    if location:
        item.read_location = location
    item.read_last_modified = modified_at or datetime.utcnow()

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
