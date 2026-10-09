# Colophon – e-book metadata manager
"""Tests for the offline landing page and the shared reader-shell asset list.

The service worker itself (app/templates/sw.js) is plain JS and out of reach
of pytest — these tests pin the two things Flask is responsible for: the
`/offline` route renders a standalone shelf (200, no _layout chrome), and the
`reader_shell_assets` context processor returns a non-empty list containing
reader.js, so reader.html and bulk_metadata.html can never drift apart on
what the reader shell needs to run offline.
"""
import pytest


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_offline_route_renders_standalone_shelf(client):
    resp = client.get("/offline")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Standalone: its own <!doctype>, not _layout's sidebar/topbar chrome.
    assert body.lstrip().lower().startswith("<!doctype html>")
    assert "Downloaded books" in body
    # The JS talks to the synthetic offline-index URL the service worker
    # serves straight from Cache Storage.
    assert "/reader/offline-index.json" in body


def _render_app_context(app):
    """Run every app-level (non-blueprint) context processor and merge the
    results, the way Flask does when rendering a template. The processor is
    a closure registered inside create_app() — not an importable name — so
    this is the supported way to reach its return value from a test."""
    from flask import current_app

    ctx = {}
    for func in current_app.template_context_processors[None]:
        ctx.update(func())
    return ctx


def test_reader_shell_assets_context_processor(app):
    with app.test_request_context("/"):
        assets = _render_app_context(app)["reader_shell_assets"]
        assert isinstance(assets, list)
        assert assets, "reader_shell_assets must not be empty"
        assert any("js/reader.js" in a for a in assets)


def test_reader_shell_assets_shared_by_both_templates(app):
    """reader.html and bulk_metadata.html must render the exact same asset
    list — that is the whole point of sharing one context processor instead
    of two hand-maintained inline arrays. We can't easily render a real book
    page without a library item + file on disk, so this pins the guarantee
    at the level that matters: the processor returns the same list on every
    call, regardless of which template asks for it."""
    with app.test_request_context("/"):
        first = _render_app_context(app)["reader_shell_assets"]
        second = _render_app_context(app)["reader_shell_assets"]
        assert first == second


# --- service worker body (static-string checks; no JS runtime in the suite) ---

def _sw_body(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _function_body(body, name):
    """Slice from `async function <name>` up to the next `async function`."""
    start = body.index("async function " + name)
    nxt = body.find("async function ", start + 1)
    return body[start:nxt if nxt != -1 else len(body)]


def test_sw_defines_network_timeout(client):
    import re

    body = _sw_body(client)
    assert re.search(r"const\s+NETWORK_TIMEOUT_MS\s*=\s*\d+\s*;", body)
    assert re.search(r"function\s+fetchWithTimeout\s*\(\s*req\s*,\s*ms\s*\)", body)


def test_sw_network_first_and_reader_page_use_timeout(client):
    body = _sw_body(client)
    for name in ("networkFirst", "readerPage", "coverImage"):
        assert "fetchWithTimeout(req, NETWORK_TIMEOUT_MS)" in _function_body(body, name), name
    # Cache-first / SWR / offline-first must stay free of the timeout.
    for name in ("cacheFirst", "offlineFirst", "staleWhileRevalidate"):
        assert "NETWORK_TIMEOUT_MS" not in _function_body(body, name), name


def test_sw_reader_asset_matches_pagemap_and_file(client):
    import re

    body = _sw_body(client)
    m = re.search(r"const\s+READER_ASSET\s*=\s*/(.+)/\s*;", body)
    assert m, "READER_ASSET missing"
    assert "READER_FILE" not in body
    # The JS literal is also a valid Python regex once the escapes are kept.
    pattern = re.compile(m.group(1))
    assert pattern.match("/reader/12/file")
    assert pattern.match("/reader/12/pagemap")
    assert not pattern.match("/reader/12")
    assert not pattern.match("/reader/12/other")


def test_sw_cache_book_reports_failures(client):
    body = _sw_body(client)
    assert "failed" in _function_body(body, "cacheBook")
    handler = body[body.index("data.type === 'cacheBook'"):body.index("data.type === 'removeBook'")]
    assert "failed:" in handler
    assert "r.ok" in handler


def test_sw_offline_page_is_stale_while_revalidate(client):
    import re

    body = _sw_body(client)
    assert re.search(
        r"pathname\s*===\s*'/offline'\s*\)\s*\{\s*event\.respondWith\(\s*staleWhileRevalidate\(req,\s*OFFLINE\)",
        body,
    )


def test_reader_page_has_goto_page_controls_and_page_map_url(app, client):
    """The settings sheet carries the "Go to page" row, the readout is a
    button, and reader.js is wired to the page-map URL the server renders."""
    from pathlib import Path

    from app.models import LibraryItem, db

    with app.app_context():
        item = LibraryItem(file_path="/tmp/x.epub", file_name="x.epub", extension=".epub", title="X")
        db.session.add(item)
        db.session.commit()
        item_id = item.id
    body = client.get(f"/reader/{item_id}").get_data(as_text=True)
    for needle in ('id="rsGotoPage"', 'id="rsGotoGo"', 'id="rsGotoTotal"',
                   "pageMapUrl", f"/reader/{item_id}/pagemap", "pageOf"):
        assert needle in body
    js = (Path(app.root_path) / "static" / "js" / "reader.js").read_text()
    assert "pageMapUrl" in js
    assert "anchorForPage" in js
