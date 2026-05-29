# Colophon – e-book metadata manager
"""Tests for the shared reading-state writer.

apply_reading_state() is the single code path both the Kobo sync PUT handler
and the in-browser reader use, so these tests lock in the monotonic /
last-write-wins rules that keep the two in sync. Pure logic — no DB or network
(the helper only mutates attributes on the passed object).
"""
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


def test_equal_rank_older_timestamp_loses():
    item = _Item(read_status="Reading", read_progress=50, read_last_modified=T1)
    assert apply_reading_state(item, "Reading", 60, modified_at=T0) is False
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
