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
    """Build a Flask app and wipe all rows that matter for these tests.

    Config caches env vars at class-definition time, so the SQLite DB
    path is fixed at the harness's launch env. We don't reuse rows
    between tests — wiping is enough for the isolation we need.
    """
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")

    from app import create_app
    from app.models import KoboBookState, KoboDevice, LibraryItem, db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True

    def _wipe():
        with flask_app.app_context():
            # Order matters: KoboBookState FK -> kobo_devices + library_items
            db.session.execute(text("DELETE FROM kobo_book_states"))
            db.session.execute(text("DELETE FROM kobo_devices"))
            db.session.execute(text("DELETE FROM library_items"))
            db.session.commit()

    _wipe()
    yield flask_app
    _wipe()


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
    assert resp.headers["x-kobo-sync"] == "done"
    assert resp.headers.get("x-kobo-synctoken")  # non-empty after Phase 2


# ---------------------------------------------------------------------------
# Phase 2 — delta sync, pagination, deletion detection
# ---------------------------------------------------------------------------

def test_sync_token_roundtrip():
    from datetime import datetime
    from app.services.kobo_sync import SyncToken

    original = SyncToken(since=datetime(2026, 5, 22, 10, 30, 45, 123000), page=3)
    encoded = original.encode()
    decoded = SyncToken.parse(encoded)
    assert decoded.since == original.since
    assert decoded.page == original.page


def test_sync_token_handles_empty_and_garbage():
    from app.services.kobo_sync import SyncToken
    assert SyncToken.parse(None).since is None
    assert SyncToken.parse("").since is None
    assert SyncToken.parse("not-base64!!!").since is None
    assert SyncToken.parse("Zm9vYmFy").since is None  # b64 but not our JSON


def test_second_sync_returns_only_changed(app, client):
    from datetime import datetime, timedelta
    from app.models import LibraryItem, db
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Delta test")
        old_time = datetime.utcnow() - timedelta(days=10)
        # Three books at different times
        for i in range(3):
            db.session.add(LibraryItem(
                title=f"Book {i}",
                file_path=f"/books/b{i}.epub",
                file_name=f"b{i}.epub",
                extension=".epub",
                created_at=old_time,
                updated_at=old_time,
            ))
        db.session.commit()

    # First sync — gets all three
    r1 = client.get(f"/kobo/{token}/v1/library/sync")
    assert r1.status_code == 200
    assert len(r1.get_json()) == 3
    token1 = r1.headers["x-kobo-synctoken"]
    assert token1

    # Second sync with token — nothing new, returns empty
    r2 = client.get(
        f"/kobo/{token}/v1/library/sync",
        headers={"x-kobo-synctoken": token1},
    )
    assert r2.status_code == 200
    assert r2.get_json() == []


def test_changed_book_appears_as_ChangedEntitlement(app, client):
    from datetime import datetime
    from app.models import LibraryItem, db
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Change test")
        item = LibraryItem(
            title="Original",
            file_path="/books/change.epub",
            file_name="change.epub",
            extension=".epub",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    # First sync — appears as NewEntitlement
    r1 = client.get(f"/kobo/{token}/v1/library/sync")
    token1 = r1.headers["x-kobo-synctoken"]
    assert "NewEntitlement" in r1.get_json()[0]

    # Modify and re-sync
    with app.app_context():
        item = LibraryItem.query.get(item_id)
        item.title = "Updated"
        item.updated_at = datetime.utcnow()
        db.session.commit()

    r2 = client.get(
        f"/kobo/{token}/v1/library/sync",
        headers={"x-kobo-synctoken": token1},
    )
    payload = r2.get_json()
    assert len(payload) == 1
    assert "ChangedEntitlement" in payload[0]
    assert payload[0]["ChangedEntitlement"]["ChangedEntitlement"]["BookMetadata"]["Title"] == "Updated"


def test_deleted_book_emits_DeletedEntitlement(app, client):
    from app.models import LibraryItem, db
    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Delete test")
        item = LibraryItem(
            title="To Be Deleted",
            file_path="/books/del.epub",
            file_name="del.epub",
            extension=".epub",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    r1 = client.get(f"/kobo/{token}/v1/library/sync")
    token1 = r1.headers["x-kobo-synctoken"]
    assert len(r1.get_json()) == 1

    # Delete the book from Colophon
    with app.app_context():
        LibraryItem.query.filter_by(id=item_id).delete()
        db.session.commit()

    r2 = client.get(
        f"/kobo/{token}/v1/library/sync",
        headers={"x-kobo-synctoken": token1},
    )
    payload = r2.get_json()
    assert len(payload) == 1
    assert "DeletedEntitlement" in payload[0]

    # And a third sync should not re-send the deletion
    token2 = r2.headers["x-kobo-synctoken"]
    r3 = client.get(
        f"/kobo/{token}/v1/library/sync",
        headers={"x-kobo-synctoken": token2},
    )
    assert r3.get_json() == []


def test_sync_pagination(app, client, monkeypatch):
    from app.models import LibraryItem, db
    from app.services import kobo_sync
    from app.services.kobo_auth import create_device

    # Force tiny page size so we don't need to insert 200+ rows
    monkeypatch.setattr(kobo_sync, "SYNC_PAGE_SIZE", 3)

    with app.app_context():
        _, token = create_device("Pagination test")
        for i in range(7):
            db.session.add(LibraryItem(
                title=f"Book {i:02d}",
                file_path=f"/books/p{i}.epub",
                file_name=f"p{i}.epub",
                extension=".epub",
            ))
        db.session.commit()

    seen_titles = []
    current_token = None
    pages = 0
    while True:
        headers = {"x-kobo-synctoken": current_token} if current_token else {}
        resp = client.get(f"/kobo/{token}/v1/library/sync", headers=headers)
        pages += 1
        for w in resp.get_json():
            inner = w.get("NewEntitlement") or w.get("ChangedEntitlement")
            if inner:
                seen_titles.append(list(inner.values())[0]["BookMetadata"]["Title"])
        if resp.headers["x-kobo-sync"] != "continue":
            break
        current_token = resp.headers["x-kobo-synctoken"]
        assert pages < 10, "pagination did not terminate"

    assert pages == 3  # 3 + 3 + 1
    assert len(seen_titles) == 7
    assert sorted(seen_titles) == [f"Book {i:02d}" for i in range(7)]


# ---------------------------------------------------------------------------
# Phase 2 — kepubify wrapper (no actual binary needed for tests)
# ---------------------------------------------------------------------------

def test_kepubify_returns_none_when_unavailable(app, monkeypatch, tmp_path):
    from app.services import kobo_kepub

    monkeypatch.setattr(kobo_kepub, "resolve_kepubify_path", lambda **_: None)
    monkeypatch.delenv("COLOPHON_KEPUBIFY_BIN", raising=False)

    source = tmp_path / "fake.epub"
    source.write_bytes(b"not a real epub")

    with app.app_context():
        result = kobo_kepub.convert_epub_to_kepub(99, str(source))
    assert result is None


def test_kepubify_uses_cache_on_second_call(app, monkeypatch, tmp_path):
    from app.services import kobo_kepub

    source = tmp_path / "book.epub"
    source.write_bytes(b"PK\x03\x04 fake")

    # Stub binary that just copies input to output
    fake_bin = tmp_path / "fake-kepubify"
    fake_bin.write_text(
        "#!/bin/sh\ncp \"$3\" \"$2/$(basename $3 .epub).kepub.epub\"\n"
    )
    fake_bin.chmod(0o755)

    monkeypatch.setattr(kobo_kepub, "resolve_kepubify_path", lambda **_: str(fake_bin))

    with app.app_context():
        first = kobo_kepub.convert_epub_to_kepub(7, str(source))
        assert first is not None
        assert first.endswith(".kepub.epub")
        # Second call must return same path without re-running the binary
        fake_bin.unlink()  # Remove it so a second conversion would fail
        second = kobo_kepub.convert_epub_to_kepub(7, str(source))
        assert second == first


def test_book_download_falls_back_to_raw_when_kepubify_missing(app, client, tmp_path, monkeypatch):
    from app.models import LibraryItem, db
    from app.services import kobo_kepub
    from app.services.kobo_auth import create_device

    epub_path = tmp_path / "raw.epub"
    epub_path.write_bytes(b"PK\x03\x04 raw epub content")

    monkeypatch.setattr(kobo_kepub, "convert_epub_to_kepub", lambda *a, **kw: None)

    with app.app_context():
        _, token = create_device("Fallback test")
        item = LibraryItem(
            title="Raw",
            file_path=str(epub_path),
            file_name="raw.epub",
            extension=".epub",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    resp = client.get(f"/kobo/{token}/v1/books/{item_id}/file/epub")
    assert resp.status_code == 200
    assert resp.data == b"PK\x03\x04 raw epub content"


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
