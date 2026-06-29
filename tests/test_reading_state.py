# Colophon – e-book metadata manager
"""Tests for the shared reading-state writer.

apply_reading_state() is the single code path both the Kobo sync PUT handler
and the in-browser reader use, so these tests lock in the monotonic /
last-write-wins rules that keep the two in sync. Pure logic — no DB or network
(the helper only mutates attributes on the passed object).
"""
import json
from datetime import datetime, timedelta

from app.services.reading_state import apply_reading_state

T0 = datetime(2026, 1, 1, 12, 0, 0)
T1 = T0 + timedelta(hours=1)


class _Item:
    """Minimal stand-in for LibraryItem's reading-state attributes."""

    def __init__(self, **kw):
        self.read_status = "ReadyToRead"
        self.read_progress = None
        self.read_location = None
        self.read_location_json = None
        self.read_last_modified = None
        self.read_started_at = None
        self.read_finished_at = None
        self.times_started = 0
        self.__dict__.update(kw)


def test_reading_start_sets_started_and_progress():
    item = _Item()
    assert apply_reading_state(item, "Reading", 30, modified_at=T0) is True
    assert item.read_status == "Reading"
    assert item.read_progress == 30
    assert item.times_started == 1
    assert item.read_started_at == T0


def test_finished_is_not_downgraded_by_later_reading():
    item = _Item(
        read_status="Finished", read_progress=100.0,
        read_finished_at=T0, read_last_modified=T0,
    )
    # A later "Reading 40%" must be dropped (monotonic), regardless of time.
    assert apply_reading_state(item, "Reading", 40, modified_at=T1) is False
    assert item.read_status == "Finished"
    assert item.read_progress == 100.0


def test_equal_rank_older_timestamp_loses_when_no_progress():
    # With no incoming progress to compare, equal-rank still falls back to
    # last-write-wins on the timeline: an older write loses.
    item = _Item(read_status="Reading", read_progress=50, read_last_modified=T1)
    assert apply_reading_state(item, "Reading", None, modified_at=T0) is False
    assert item.read_progress == 50


def test_equal_rank_newer_timestamp_wins():
    item = _Item(read_status="Reading", read_progress=50, read_last_modified=T0)
    assert apply_reading_state(item, "Reading", 60, modified_at=T1) is True
    assert item.read_progress == 60
    assert item.read_last_modified == T1


def test_location_none_does_not_clobber_existing():
    # The browser reader resumes by percent and passes no location; an
    # existing (Kobo-written) location must survive.
    item = _Item(read_status="Reading", read_location="kobo-span-xyz", read_last_modified=T0)
    assert apply_reading_state(item, "Reading", 70, modified_at=T1) is True
    assert item.read_location == "kobo-span-xyz"


def test_location_written_when_provided():
    item = _Item(read_status="Reading", read_last_modified=T0)
    apply_reading_state(item, "Reading", 70, location="epubcfi(/6/4)", modified_at=T1)
    assert item.read_location == "epubcfi(/6/4)"


def test_finished_coerces_progress_and_sets_finished_at():
    item = _Item(read_status="Reading", read_progress=98, read_last_modified=T0)
    assert apply_reading_state(item, "Finished", 99.2, modified_at=T1) is True
    assert item.read_progress == 100.0
    assert item.read_finished_at == T1


def test_times_started_only_increments_on_first_reading():
    item = _Item()
    apply_reading_state(item, "Reading", 10, modified_at=T0)
    apply_reading_state(item, "Reading", 20, modified_at=T1)
    assert item.times_started == 1


def test_missing_modified_at_defaults_to_now():
    item = _Item()
    assert apply_reading_state(item, "Reading", 5) is True
    assert item.read_last_modified is not None


# --- Furthest-read-wins (v1.28.1) ---------------------------------------------
# At equal status rank, progress may never go backwards, and the furthest page
# read wins even against a newer wall-clock timestamp. This is what stops a
# stray progress=0.0 PUT (cover-reset / sync echo) from wiping a real position.


def test_equal_rank_lower_progress_rejected_even_if_newer():
    # The production regression: 24% stored, a newer PUT reports 0.0 — it must
    # be dropped, not overwrite the position.
    item = _Item(read_status="Reading", read_progress=24.0, read_last_modified=T0)
    assert apply_reading_state(item, "Reading", 0.0, modified_at=T1) is False
    assert item.read_progress == 24.0
    assert item.read_last_modified == T0


def test_equal_rank_higher_progress_wins_even_if_older():
    # Behaviour change: a higher progress applies even with an OLDER timestamp
    # (furthest page beats the clock). The timeline marker must not regress.
    item = _Item(read_status="Reading", read_progress=50.0, read_last_modified=T1)
    assert apply_reading_state(item, "Reading", 60.0, modified_at=T0) is True
    assert item.read_progress == 60.0
    assert item.read_last_modified == T1  # advanced-only: kept the newer marker


def test_equal_rank_higher_progress_and_newer_timestamp_wins():
    item = _Item(read_status="Reading", read_progress=50.0, read_last_modified=T0)
    assert apply_reading_state(item, "Reading", 60.0, modified_at=T1) is True
    assert item.read_progress == 60.0
    assert item.read_last_modified == T1


def test_lower_status_still_rejected():
    # Monotonic rule unchanged: Finished -> Reading is dropped regardless of
    # progress or timestamp.
    item = _Item(
        read_status="Finished", read_progress=100.0,
        read_finished_at=T0, read_last_modified=T0,
    )
    assert apply_reading_state(item, "Reading", 40.0, modified_at=T1) is False
    assert item.read_status == "Finished"
    assert item.read_progress == 100.0


def test_reading_to_finished_with_lower_progress_coerces_to_100():
    # Status escalation always applies (skips the equal-rank furthest-read
    # check) and Finished coerces progress to 100 even if the reported number
    # is lower.
    item = _Item(read_status="Reading", read_progress=80.0, read_last_modified=T0)
    assert apply_reading_state(item, "Finished", 10.0, modified_at=T1) is True
    assert item.read_status == "Finished"
    assert item.read_progress == 100.0
    assert item.read_finished_at == T1


# --- Full Location storage (v1.28.2) ------------------------------------------
# A dict location (the Kobo's full CurrentBookmark.Location: Value+Type+Source)
# is stored verbatim in read_location_json; a string stays legacy; no location
# (the browser reader) never touches read_location_json.


def test_dict_location_stored_as_json_and_value_mirrored():
    item = _Item(read_status="Reading", read_progress=10.0, read_last_modified=T0)
    loc = {"Value": "epubcfi(/6/4!/2)", "Type": "KoboSpan", "Source": "uuid-123"}
    assert apply_reading_state(item, "Reading", 20.0, location=loc, modified_at=T1) is True
    assert json.loads(item.read_location_json) == loc
    assert item.read_location == "epubcfi(/6/4!/2)"  # Value mirrored for display


def test_string_location_is_legacy_and_leaves_json_untouched():
    item = _Item(read_status="Reading", read_progress=10.0, read_last_modified=T0)
    assert apply_reading_state(item, "Reading", 20.0, location="span-xyz", modified_at=T1) is True
    assert item.read_location == "span-xyz"
    assert item.read_location_json is None


def test_no_location_does_not_touch_location_json():
    # The in-browser reader passes no location and resumes by percent — it must
    # never clobber a full Location the Kobo wrote.
    existing = json.dumps({"Value": "v", "Type": "KoboSpan", "Source": "uuid-1"})
    item = _Item(read_status="Reading", read_progress=10.0,
                 read_location_json=existing, read_last_modified=T0)
    assert apply_reading_state(item, "Reading", 30.0, modified_at=T1) is True
    assert item.read_location_json == existing


def test_dropped_update_does_not_store_location():
    # A furthest-wins drop (lower progress) must not persist its location either.
    item = _Item(read_status="Reading", read_progress=40.0, read_last_modified=T0)
    loc = {"Value": "back", "Type": "KoboSpan", "Source": "uuid-9"}
    assert apply_reading_state(item, "Reading", 5.0, location=loc, modified_at=T1) is False
    assert item.read_location_json is None
    assert item.read_location is None


def test_reset_to_readytoread_not_blocked_by_furthest_read_rule():
    # A deliberate reset (re-read from start) is performed by the reset
    # endpoint writing fields directly — it does NOT route through
    # apply_reading_state, so the never-go-backwards rule can't block it. Guard
    # that design: the helper itself (correctly) refuses a ReadyToRead/0
    # downgrade via the monotonic rule, which is exactly why reset bypasses it.
    item = _Item(read_status="Reading", read_progress=24.0, read_last_modified=T1)
    # Routing a reset through the helper is rejected (monotonic downgrade):
    assert apply_reading_state(item, "ReadyToRead", 0, modified_at=T1 + timedelta(hours=2)) is False
    assert item.read_status == "Reading"
    assert item.read_progress == 24.0
    # The reset endpoint instead clears the fields directly (mirrored here):
    item.read_status = "ReadyToRead"
    item.read_progress = None
    item.read_location = None
    assert item.read_status == "ReadyToRead"
    assert item.read_progress is None
