# Colophon – tests for the language check scenario
"""services/language_check: what it reports, and what applying a finding
writes. The apply path is the one with teeth — it must write `language`
and nothing else, and it must not write files unless asked.

One expectation here contradicts a line in docs/plan-batch-scenarios.md.
The plan's invariant 3 says a DB-only change must not stamp
content_updated_at. That is not true for `language`, because `language`
is in models._DEVICE_CONTENT_COLUMNS — and it should be: the Kobo uses
the language for dictionary and hyphenation, so a correction has to
reach the device. test_language_only_db_change_still_stamps_content
pins that behaviour deliberately rather than papering over it.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from flask import Flask

from app.models import db, LibraryItem
from app.services.language_check import (
    apply_language_changes,
    check_language,
    is_missing_language,
    iter_language_findings,
)


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


_counter = iter(range(1, 10_000))


def _add(language="en", extension=".epub", path=None, title=None):
    n = next(_counter)
    item = LibraryItem(
        title=title or f"Book {n}",
        author="An Author",
        language=language,
        extension=extension,
        file_path=path if path is not None else f"/books/b{n}{extension}",
        file_name=f"b{n}{extension}",
    )
    db.session.add(item)
    db.session.commit()
    return item


# --- what counts as "nobody has said" -------------------------------------

@pytest.mark.parametrize("value", ["", "   ", "und", "UNKNOWN", "xx"])
def test_placeholder_languages_count_as_missing(app, value):
    assert is_missing_language(_add(language=value)) is True


def test_a_real_language_is_not_missing(app):
    assert is_missing_language(_add(language="sv")) is False


# --- check_language -------------------------------------------------------

def test_non_epub_is_unreadable_without_opening_anything(app):
    item = _add(extension=".pdf")
    assert check_language(item)["status"] == "unreadable"


def test_missing_file_is_unreadable(app):
    item = _add(path="/books/gone.epub")
    assert check_language(item)["status"] == "unreadable"


def test_agreeing_language_reports_nothing(app, tmp_path):
    book = tmp_path / "b.epub"
    book.write_bytes(b"x")
    item = _add(language="en", path=str(book))
    with patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.99, "agree": True},
    ):
        assert check_language(item) is None


def test_regional_variant_counts_as_the_same_language(app, tmp_path):
    book = tmp_path / "b.epub"
    book.write_bytes(b"x")
    item = _add(language="en-GB", path=str(book))
    with patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.99, "agree": True},
    ):
        assert check_language(item) is None


def test_disagreement_is_reported_as_differs(app, tmp_path):
    book = tmp_path / "b.epub"
    book.write_bytes(b"x")
    item = _add(language="sv", path=str(book))
    with patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.97, "agree": True},
    ):
        finding = check_language(item)
    assert finding["status"] == "differs"
    assert finding["stored"] == "sv"
    assert finding["detected"] == "en"
    assert finding["agree"] is True


def test_empty_stored_language_is_reported_as_missing(app, tmp_path):
    book = tmp_path / "b.epub"
    book.write_bytes(b"x")
    item = _add(language="", path=str(book))
    with patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "sv", "prob": 0.95, "agree": False},
    ):
        finding = check_language(item)
    assert finding["status"] == "missing"
    assert finding["agree"] is False


# --- iterating the library ------------------------------------------------

def test_iteration_yields_findings_then_a_summary(app, tmp_path):
    book = tmp_path / "b.epub"
    book.write_bytes(b"x")
    _add(language="sv", path=str(book))   # will differ
    _add(extension=".pdf")                # unreadable
    with patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.9, "agree": True},
    ):
        events = list(iter_language_findings())

    summary = events[-1]
    assert summary["status"] == "summary"
    assert summary["total"] == 2
    assert summary["unreadable"] == 1
    assert [e["status"] for e in events[:-1]] == ["differs"]


def test_iteration_is_read_only(app, tmp_path):
    """The preview must not write. Nothing in the walk may call the writer."""
    book = tmp_path / "b.epub"
    book.write_bytes(b"x")
    item = _add(language="sv", path=str(book))
    before = item.language

    with patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.9, "agree": True},
    ), patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        list(iter_language_findings())

    writer.assert_not_called()
    assert db.session.get(LibraryItem, item.id).language == before


# --- applying -------------------------------------------------------------

def test_apply_writes_db_but_not_the_file_by_default(app):
    item = _add(language="sv")
    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": False, "file_write_error": None}
        result = apply_language_changes([{"item_id": item.id, "code": "en"}])

    assert result["updated"] == 1
    assert result["files_written"] == 0
    kwargs = writer.call_args.kwargs
    assert kwargs["write_to_file"] is False


def test_apply_writes_language_and_nothing_else(app):
    """A scenario touches at most the fields it is about. This one is
    about exactly one field, so the writer must be told exactly that."""
    item = _add(language="sv")
    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": True, "file_write_error": None}
        apply_language_changes(
            [{"item_id": item.id, "code": "en"}], write_files=True
        )

    kwargs = writer.call_args.kwargs
    assert kwargs["selected_fields"] == {"language"}
    assert set(kwargs["result"].keys()) == {"language"}
    assert kwargs["result"]["language"] == "en"
    assert kwargs["write_to_file"] is True


def test_apply_reports_file_write_errors_without_failing_the_run(app):
    item = _add(language="sv")
    with patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {
            "file_updated": False,
            "file_write_error": "unsupported_format",
        }
        result = apply_language_changes(
            [{"item_id": item.id, "code": "en"}], write_files=True
        )

    assert result["ok"] is True
    assert result["updated"] == 1
    assert result["errors"] == [
        {"item_id": item.id, "error": "unsupported_format"}
    ]


def test_apply_skips_unknown_items(app):
    result = apply_language_changes([{"item_id": 9999, "code": "en"}])
    assert result["updated"] == 0
    assert result["errors"][0]["error"] == "not_found"


def test_language_only_db_change_still_stamps_content(app):
    """Deliberate, and contrary to the plan's invariant 3.

    `language` is a device-visible column (models._DEVICE_CONTENT_COLUMNS),
    so correcting it advances content_updated_at even with no file write.
    That is what we want: the Kobo picks the dictionary and hyphenation
    from this field, so a correction has to reach the device. If this test
    ever goes red, someone removed `language` from that set — and quietly
    stopped language fixes from ever reaching a reader.
    """
    item = _add(language="sv")
    item.content_updated_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    before = item.content_updated_at

    item.language = "en"
    db.session.commit()

    assert db.session.get(LibraryItem, item.id).content_updated_at > before


# --- the routes -----------------------------------------------------------
#
# The stream is a preview. If it can ever write, the whole scenario is
# pointless — so this is the test that guards it at the HTTP boundary,
# not just at the service one.

import json
import signal
from unittest.mock import patch as _patch

from flask_babel import Babel

from app.routes.metadata import metadata_bp


@pytest.fixture
def route_app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "r.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    covers = tmp_path / "covers"
    covers.mkdir()
    app.config["COVER_DIR"] = str(covers)
    db.init_app(app)
    Babel(app)          # bulk routes call gettext inside worker threads
    app.register_blueprint(metadata_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _sse(client, url, timeout=15):
    """Consume an SSE response fully, under a safety valve."""
    def _boom(signum, frame):
        raise TimeoutError(f"{url} hung")

    old = signal.signal(signal.SIGALRM, _boom)
    signal.alarm(timeout)
    try:
        resp = client.get(url)
        body = resp.get_data(as_text=True)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    return resp, [
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")
    ]


def test_stream_never_writes(route_app, tmp_path):
    book = tmp_path / "s.epub"
    book.write_bytes(b"x")
    with route_app.app_context():
        _add(language="sv", path=str(book))

    with _patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.98, "agree": True},
    ), _patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        resp, events = _sse(route_app.test_client(), "/metadata/language-check/stream")

    assert resp.status_code == 200
    writer.assert_not_called()
    assert [e["type"] for e in events if e["type"] == "finding"] == ["finding"]
    assert events[-1]["type"] == "done"
    assert events[-1]["total"] == 1


def test_apply_route_rejects_an_empty_change_set(route_app):
    resp = route_app.test_client().post(
        "/metadata/language-check/apply",
        json={"changes": [], "write_files": False},
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_apply_route_passes_write_files_through(route_app):
    with route_app.app_context():
        item = _add(language="sv")
        item_id = item.id

    with _patch("app.services.metadata_writer.apply_metadata_to_item") as writer:
        writer.return_value = {"file_updated": True, "file_write_error": None}
        resp = route_app.test_client().post(
            "/metadata/language-check/apply",
            json={"changes": [{"item_id": item_id, "code": "en"}], "write_files": True},
        )

    assert resp.get_json()["updated"] == 1
    assert writer.call_args.kwargs["write_to_file"] is True
    assert writer.call_args.kwargs["selected_fields"] == {"language"}


def test_closing_the_stream_aborts_the_scan(route_app, tmp_path):
    """A browser that walks away must stop the scan behind it.

    The three other SSE routes in routes/metadata.py set the abort flag when
    their generator is closed; this one did not, so closing the tab left the
    worker thread reading every remaining EPUB for nobody. Here the generator
    is closed by hand after the first event, which is what Flask does to it
    when the client disconnects.
    """
    from app.routes import metadata as metadata_routes

    book = tmp_path / "a.epub"
    book.write_bytes(b"x")
    with route_app.app_context():
        _add(language="sv", path=str(book))

    metadata_routes._abort_event.clear()

    with _patch(
        "app.services.language_check.detect_language_confident",
        return_value={"code": "en", "prob": 0.98, "agree": True},
    ):
        with route_app.test_request_context("/metadata/language-check/stream"):
            response = metadata_routes.language_check_stream()
            stream = response.response
            next(iter(stream))          # first event out, client still there
            stream.close()              # …and now the client is gone

    assert metadata_routes._abort_event.is_set(), (
        "closing the stream left the language scan running: the worker thread "
        "keeps opening EPUBs for a client that is no longer listening"
    )
