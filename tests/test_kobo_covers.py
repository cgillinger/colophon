# Colophon – e-book metadata manager
"""The Kobo cover endpoint must downscale, not ship the original.

Originals are large — several MB happens — and the device fetches one per
book. A few hundred books is then hundreds of MB over WiFi every sync, which
is what makes the cover phase look hung. Measured on a real 639-book library:
187 MB against 20 MB at 320 px.
"""
import io
import os

import pytest


@pytest.fixture
def app(monkeypatch):
    """Same shape as tests/test_kobo_sync.py — no conftest in this project."""
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")

    from app import create_app
    from app.models import db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True

    def _wipe():
        with flask_app.app_context():
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


def _make_big_cover(path):
    """A cover noticeably wider than anything the Kobo asks for."""
    Image = pytest.importorskip("PIL.Image", reason="Pillow required")
    Image.new("RGB", (1600, 2400), (120, 40, 40)).save(path, "JPEG", quality=95)
    return str(path)


@pytest.fixture
def book_with_cover(app, tmp_path):
    from app.models import LibraryItem, db

    epub = tmp_path / "coverbook.epub"
    epub.write_bytes(b"PK\x03\x04stub")  # the route never opens the book file
    cover = _make_big_cover(tmp_path / "cover.jpg")

    from app.services.kobo_auth import create_device

    with app.app_context():
        _, token = create_device("Cover test")
        item = LibraryItem(
            title="The Cover Book",
            author="Test Author",
            file_path=str(epub),
            file_name=epub.name,
            extension=".epub",
            cover_path=cover,
        )
        db.session.add(item)
        db.session.commit()
        return item.id, cover, token


def _uuid_for(app, item_id):
    from app.models import LibraryItem
    from app.routes.kobo import _book_uuid

    with app.app_context():
        return _book_uuid(LibraryItem.query.get(item_id))


def _thumb_url(token, image_id):
    return f"/kobo/{token}/v1/books/{image_id}/thumbnail/200/300/false/image.jpg"


def test_thumbnail_is_scaled_down(app, client, book_with_cover):
    item_id, cover, token = book_with_cover
    image_id = _uuid_for(app, item_id)

    resp = client.get(_thumb_url(token, image_id))

    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert len(resp.data) < os.path.getsize(cover)

    from PIL import Image
    # Requested 200 snaps up to the 320 allowlist entry.
    assert Image.open(io.BytesIO(resp.data)).width == 320


def test_quality_variant_route_also_scales(app, client, book_with_cover):
    item_id, cover, token = book_with_cover
    image_id = _uuid_for(app, item_id)

    resp = client.get(
        f"/kobo/{token}/v1/books/{image_id}/thumbnail/200/300/85/false/image.jpg"
    )

    assert resp.status_code == 200
    assert len(resp.data) < os.path.getsize(cover)


def test_falls_back_to_the_original_when_scaling_fails(
    app, client, book_with_cover, monkeypatch
):
    """The contract is None => send the original. A host without Pillow works."""
    item_id, cover, token = book_with_cover
    image_id = _uuid_for(app, item_id)
    monkeypatch.setattr(
        "app.services.cover_thumbs.get_or_make_thumbnail", lambda *a, **k: None
    )

    resp = client.get(_thumb_url(token, image_id))

    assert resp.status_code == 200
    assert len(resp.data) == os.path.getsize(cover)


def test_missing_cover_is_404(app, client, book_with_cover):
    from app.models import LibraryItem, db

    item_id, _, token = book_with_cover
    image_id = _uuid_for(app, item_id)
    with app.app_context():
        LibraryItem.query.get(item_id).cover_path = None
        db.session.commit()

    assert client.get(_thumb_url(token, image_id)).status_code == 404


def test_uuid_lookup_is_stamped_for_the_indexed_path(app, client, book_with_cover):
    """The brute-force scan must fill kobo_book_id so it isn't repeated.

    It used to run per thumbnail request: a full table load plus a uuid5 per
    book, thousands of times over during one cover phase.
    """
    from app.models import LibraryItem

    item_id, _, token = book_with_cover
    image_id = _uuid_for(app, item_id)

    with app.app_context():
        assert LibraryItem.query.get(item_id).kobo_book_id is None

    assert client.get(_thumb_url(token, image_id)).status_code == 200

    with app.app_context():
        assert LibraryItem.query.get(item_id).kobo_book_id == image_id


def test_sync_stamps_the_uuid(app, client, book_with_cover):
    """Building an entitlement is the normal fill path."""
    from app.models import LibraryItem

    item_id, _, token = book_with_cover
    image_id = _uuid_for(app, item_id)

    assert client.get(f"/kobo/{token}/v1/library/sync").status_code == 200

    with app.app_context():
        assert LibraryItem.query.get(item_id).kobo_book_id == image_id


def test_second_request_is_served_from_cache(app, client, book_with_cover):
    item_id, _, token = book_with_cover
    image_id = _uuid_for(app, item_id)
    url = _thumb_url(token, image_id)

    first = client.get(url)
    second = client.get(url)

    assert first.data == second.data
