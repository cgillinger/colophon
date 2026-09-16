# Colophon – dry-run mode for the bulk metadata SSE stream
"""GET /metadata/bulk/stream?dry_run=1 must classify auto_apply exactly as
today, but never call apply_metadata_to_item and report apply_details=None
on book_done. A control test without dry_run proves the mock is actually
exercised by this harness (so a false-green dry_run test isn't hiding a
harness that never reaches the apply call at all)."""
import json
import signal
from unittest.mock import patch

import pytest
from flask import Flask
from flask_babel import Babel

from app.models import db, LibraryItem
from app.routes.metadata import metadata_bp
from app.services.grouping import compute_group_key


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    cover_dir = tmp_path / "covers"
    cover_dir.mkdir()
    app.config["COVER_DIR"] = str(cover_dir)
    db.init_app(app)
    # bulk_stream's background thread calls gettext() (_()) while building
    # book_done events; without an initialized Babel extension that raises
    # KeyError('babel') deep inside the thread, which silently dies the
    # thread before it ever puts the final `None` sentinel on the queue —
    # and generate() then blocks on ev_queue.get() forever.
    Babel(app)
    app.register_blueprint(metadata_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _add_item(title="Original Title", author="Original Author"):
    item = LibraryItem(
        title=title,
        author=author,
        description="Original description",
        file_path=f"/books/{title}.epub",
        file_name=f"{title}.epub",
        extension=".epub",
    )
    item.group_key = compute_group_key(item.title, item.author)
    db.session.add(item)
    db.session.commit()
    return item


# Mocked enrichment result: classifies as auto_apply, and proposes DIFFERENT
# values than the item's originals so a real apply would be visible in the DB.
_FAKE_RESULT = {
    "ok": True,
    "classification": "auto_apply",
    "score": 95,
    "best": {"source": "Google Books", "title": "Mockad titel"},
    "fetched_payload": {
        "title": "Mockad titel",
        "description": "Mockad beskrivning",
    },
    "source_results": [{"ok": True, "source": "google", "status": "ok"}],
    "provenance": {},
    "warnings": [],
}

_FAKE_APPLY_RESULT = {
    "fields_added": [],
    "fields_replaced": [],
    "fields_skipped": [],
    "file_updated": True,
    "file_write_error": None,
}


def _get_with_timeout(client, url, timeout=10):
    """Fetch the SSE stream and force full consumption of the response
    generator, under a SIGALRM safety valve — a hung background thread
    (bulk_stream's _run) would otherwise block ev_queue.get() forever and
    hang the suite instead of failing the test."""
    def _handler(signum, frame):
        raise TimeoutError(f"GET {url} did not complete within {timeout}s (SSE stream hung)")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        resp = client.get(url)
        resp.get_data()  # force the generator to run to completion now
        return resp
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _book_done_events(resp):
    events = []
    for line in resp.get_data(as_text=True).splitlines():
        if not line.startswith("data: "):
            continue
        events.append(json.loads(line[len("data: "):]))
    return [e for e in events if e.get("type") == "book_done"]


def test_dry_run_does_not_call_apply_or_touch_db(client, app):
    item = _add_item()
    item_id = item.id

    with patch(
        "app.services.metadata_pipeline.run_metadata_enrichment",
        return_value=_FAKE_RESULT,
    ), patch(
        "app.services.metadata_writer.apply_metadata_to_item",
        return_value=_FAKE_APPLY_RESULT,
    ) as mock_apply:
        _get_with_timeout(client, f"/metadata/bulk/stream?item_ids={item_id}&dry_run=1")

    mock_apply.assert_not_called()

    with app.app_context():
        fresh = db.session.get(LibraryItem, item_id)
        assert fresh.title == "Original Title"
        assert fresh.description == "Original description"


def test_dry_run_reports_auto_apply_with_no_apply_details(client, app):
    item = _add_item()
    item_id = item.id

    with patch(
        "app.services.metadata_pipeline.run_metadata_enrichment",
        return_value=_FAKE_RESULT,
    ), patch(
        "app.services.metadata_writer.apply_metadata_to_item",
        return_value=_FAKE_APPLY_RESULT,
    ):
        resp = _get_with_timeout(client, f"/metadata/bulk/stream?item_ids={item_id}&dry_run=1")

    events = _book_done_events(resp)
    assert len(events) == 1
    assert events[0]["classification"] == "auto_apply"
    assert events[0]["apply_details"] is None


def test_without_dry_run_still_calls_apply(client, app):
    """Control: same setup, no dry_run — proves the mock and harness are
    actually wired to observe a real apply. Must stay green before and
    after the dry_run change."""
    item = _add_item()
    item_id = item.id

    with patch(
        "app.services.metadata_pipeline.run_metadata_enrichment",
        return_value=_FAKE_RESULT,
    ), patch(
        "app.services.metadata_writer.apply_metadata_to_item",
        return_value=_FAKE_APPLY_RESULT,
    ) as mock_apply:
        resp = _get_with_timeout(client, f"/metadata/bulk/stream?item_ids={item_id}")

    mock_apply.assert_called_once()

    events = _book_done_events(resp)
    assert len(events) == 1
    assert events[0]["classification"] == "auto_apply"
    assert events[0]["apply_details"] is not None
