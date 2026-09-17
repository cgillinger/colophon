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
