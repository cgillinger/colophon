# Colophon – e-book metadata manager
"""Tests for the Phase 1 Kobo sync surface.

Splits into pure-logic tests (no DB) and integration tests that spin
up a Flask app with an in-memory SQLite database.
"""
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Pure logic — no Flask, no DB
# ---------------------------------------------------------------------------

def test_token_generation_format():
    from app.services.kobo_auth import generate_token, is_valid_token_format
    token = generate_token()
    assert len(token) == 32
    assert is_valid_token_format(token)
    assert all(c in "0123456789abcdef" for c in token)


def test_token_format_validation():
    from app.services.kobo_auth import is_valid_token_format
    assert is_valid_token_format("a" * 32)
    assert is_valid_token_format("0123456789abcdef0123456789abcdef")
    assert not is_valid_token_format("")
    assert not is_valid_token_format(None)
    assert not is_valid_token_format("too-short")
    assert not is_valid_token_format("X" * 32)  # uppercase / non-hex
    assert not is_valid_token_format("a" * 33)  # wrong length


def test_token_hash_is_deterministic():
    from app.services.kobo_auth import hash_token
    h1 = hash_token("abc123")
    h2 = hash_token("abc123")
    assert h1 == h2
    assert len(h1) == 64
    assert hash_token("abc123") != hash_token("abc124")


def test_book_uuid_is_deterministic():
    from app.routes.kobo import _book_uuid
    u1 = _book_uuid(42)
    u2 = _book_uuid(42)
    assert u1 == u2
    assert _book_uuid(42) != _book_uuid(43)
    # UUID format: 8-4-4-4-12 hex chars
    assert len(u1) == 36
    assert u1.count("-") == 4


def test_iso_format():
    from app.routes.kobo import _iso
    dt = datetime(2026, 5, 22, 10, 30, 45)
    formatted = _iso(dt)
    assert formatted == "2026-05-22T10:30:45.000Z"
    # None falls back to "now" without crashing
    assert _iso(None).endswith("Z")


# ---------------------------------------------------------------------------
# Integration — Flask app with in-memory SQLite
# ---------------------------------------------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Build a Flask app pointed at a temp SQLite file."""
    monkeypatch.setenv("COLOPHON_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COLOPHON_LIBRARY_DIR", str(tmp_path / "books"))
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")

    from app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_ping_requires_valid_token(client):
    resp = client.get("/kobo/" + ("a" * 32) + "/ping")
    assert resp.status_code == 401


def test_create_and_use_device(app, client):
    from app.services.kobo_auth import create_device

    with app.app_context():
        device, token = create_device("Test Kobo")
        assert device.id is not None
        assert device.api_key_prefix == token[:8]
        assert device.api_key_hash != token
        assert device.sync_count == 0

    # Ping with the real token works
    resp = client.get(f"/kobo/{token}/ping")
    assert resp.status_code == 200
    assert resp.data == b"pong"


def test_revoked_device_cannot_sync(app, client):
    from app.services.kobo_auth import create_device, revoke_device

    with app.app_context():
        device, token = create_device("To be revoked")
        device_id = device.id

    resp = client.get(f"/kobo/{token}/ping")
    assert resp.status_code == 200

    with app.app_context():
        assert revoke_device(device_id)

    resp = client.get(f"/kobo/{token}/ping")
    assert resp.status_code == 401


def test_initialization_returns_resources_map(app, client):
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Init test")

    resp = client.get(f"/kobo/{token}/v1/initialization")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "Resources" in data
    # Sync URL must point back at our host, not Kobo store
    sync_url = data["Resources"]["library_sync"]
    assert "/kobo/" in sync_url
    assert token in sync_url
    assert "storeapi.kobo.com" not in sync_url
    # Image template URL must be present and use the same token
    assert "image_url_template" in data["Resources"]
    assert token in data["Resources"]["image_url_template"]


def test_library_sync_returns_epubs(app, client):
    from app.models import LibraryItem, db
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Sync test")
        # Insert one EPUB and one MOBI; only the EPUB should appear
        epub = LibraryItem(
            title="The Test Book",
            author="Jane Doe",
            file_path="/books/test.epub",
            file_name="test.epub",
            extension=".epub",
            size_bytes=12345,
        )
        mobi = LibraryItem(
            title="A MOBI Book",
            file_path="/books/test.mobi",
            file_name="test.mobi",
            extension=".mobi",
        )
        db.session.add_all([epub, mobi])
        db.session.commit()

    resp = client.get(f"/kobo/{token}/v1/library/sync")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    wrapper = payload[0]
    assert "NewEntitlement" in wrapper
    inner = wrapper["NewEntitlement"]["NewEntitlement"]
    assert inner["BookMetadata"]["Title"] == "The Test Book"
    assert inner["BookMetadata"]["Contributors"] == ["Jane Doe"]
    assert inner["BookMetadata"]["DownloadUrls"][0]["Url"].endswith(
        "/file/epub"
    )
    # Headers the Kobo expects on a sync response
    assert "x-kobo-sync" in resp.headers


def test_library_sync_increments_sync_count(app, client):
    from app.services.kobo_auth import create_device
    from app.models import KoboDevice

    with app.app_context():
        device, token = create_device("Counter test")
        device_id = device.id

    client.get(f"/kobo/{token}/v1/library/sync")
    client.get(f"/kobo/{token}/v1/library/sync")

    with app.app_context():
        d = KoboDevice.query.get(device_id)
        assert d.sync_count == 2
        assert d.last_sync_at is not None


def test_book_file_streams_existing_epub(app, client, tmp_path):
    from app.models import LibraryItem, db
    from app.services.kobo_auth import create_device

    # Real file on disk so send_file can read it
    epub_path = tmp_path / "real.epub"
    epub_path.write_bytes(b"PK\x03\x04 fake epub")

    with app.app_context():
        _, token = create_device("Download test")
        item = LibraryItem(
            title="Download Me",
            file_path=str(epub_path),
            file_name="real.epub",
            extension=".epub",
            size_bytes=len(epub_path.read_bytes()),
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    resp = client.get(f"/kobo/{token}/v1/books/{item_id}/file/epub")
    assert resp.status_code == 200
    assert resp.data.startswith(b"PK")


def test_book_file_404_for_missing_id(app, client):
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("404 test")

    resp = client.get(f"/kobo/{token}/v1/books/99999/file/epub")
    assert resp.status_code == 404
