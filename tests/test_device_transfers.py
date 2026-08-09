# Colophon – e-book metadata manager
"""Channel-aware sync: the ledger, and the exclusion that makes it worth having.

The failure this prevents: a Kobo cannot tell a sideloaded file (ContentID = a
path) from a cloud entitlement (ContentID = a UUID), so a book sent both by USB
and by WiFi appears twice on the device. The ledger records what Colophon put
there over USB, and the wireless sync withholds those books.

Mounts are faked as directories — the two files that identify a Kobo are just
``.kobo/version`` and ``.kobo/Kobo/Kobo eReader.conf``.
"""
import os

import pytest


def _make_mount(tmp_path, serial="N123456789", token=None, api_endpoint=None):
    """A directory shaped like a mounted Kobo."""
    mount = tmp_path / "KOBOeReader"
    (mount / ".kobo" / "Kobo").mkdir(parents=True, exist_ok=True)
    (mount / ".kobo" / "version").write_text(
        f"{serial},4.9.77,4.45.23697,4.9.77,4.9.77,00000000-0000-0000-0000-000000000390\n"
    )
    if api_endpoint is None and token is not None:
        api_endpoint = f"http://192.168.50.8:5055/kobo/{token}"
    if api_endpoint is None:
        api_endpoint = "https://storeapi.kobo.com"
    conf = (
        "[General]\n[ApplicationPreferences]\n[OneStoreServices]\n"
        f"api_endpoint={api_endpoint}\n[OverDrive]\n"
    )
    (mount / ".kobo" / "Kobo" / "Kobo eReader.conf").write_text(conf)
    return mount


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app
    from app.models import db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True

    def _wipe():
        with flask_app.app_context():
            db.session.execute(text("DELETE FROM device_transfers"))
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


def _add_book(title, path):
    from app.models import LibraryItem, db

    item = LibraryItem(
        title=title, file_path=path, file_name=os.path.basename(path),
        extension=".epub",
    )
    db.session.add(item)
    db.session.commit()
    return item


# ---------------------------------------------------------------------------
# Reading a device's identity off the mount
# ---------------------------------------------------------------------------

def test_serial_is_the_first_field_of_the_version_file(tmp_path):
    from app.services.device_transfers import read_device_serial

    mount = _make_mount(tmp_path, serial="N428430054827")
    assert read_device_serial(mount) == "N428430054827"
    assert read_device_serial(tmp_path / "not-a-mount") is None


def test_token_is_read_from_the_endpoint_we_wrote(app, tmp_path):
    from app.services.device_transfers import read_device_token

    with app.app_context():
        token = "c6732a90275ad4cebd4eda948c908aa1"
        assert read_device_token(_make_mount(tmp_path, token=token)) == token


def test_a_stock_device_yields_no_token(app, tmp_path):
    """A Kobo pointing at the real store must not look like one of ours."""
    from app.services.device_transfers import read_device_token

    with app.app_context():
        assert read_device_token(_make_mount(tmp_path)) is None


def test_a_foreign_endpoint_yields_no_token(app, tmp_path):
    from app.services.device_transfers import read_device_token

    with app.app_context():
        mount = _make_mount(tmp_path, api_endpoint="http://someone-else/kobo/not-a-token")
        assert read_device_token(mount) is None


def test_a_utf16_conf_still_parses(app, tmp_path):
    """Confs turn up UTF-16-with-BOM; read as UTF-8 the regex misses and the
    device looks unconfigured instead of merely differently encoded."""
    from app.services.device_transfers import read_device_token

    token = "c6732a90275ad4cebd4eda948c908aa1"
    mount = _make_mount(tmp_path, token=token)
    conf = mount / ".kobo" / "Kobo" / "Kobo eReader.conf"
    conf.write_bytes(conf.read_text().encode("utf-16"))

    with app.app_context():
        assert read_device_token(mount) == token


def test_mount_resolves_to_the_registered_device_and_learns_its_serial(app, tmp_path):
    from app.services.device_transfers import device_for_mount
    from app.services.kobo_auth import create_device

    with app.app_context():
        registered, token = create_device("Kobon")
        mount = _make_mount(tmp_path, serial="N999", token=token)

        device, serial = device_for_mount(mount)
        assert device is not None and device.id == registered.id
        assert serial == "N999"
        assert device.device_serial == "N999"   # learned on first sight


def test_a_revoked_device_does_not_resolve(app, tmp_path):
    from app.services.device_transfers import device_for_mount
    from app.services.kobo_auth import create_device, revoke_device

    with app.app_context():
        registered, token = create_device("Retired")
        mount = _make_mount(tmp_path, token=token)
        revoke_device(registered.id)

        device, serial = device_for_mount(mount)
        assert device is None
        assert serial is not None   # still identifiable, just not registered


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

def test_recording_is_idempotent_and_completes_what_it_knows(app):
    """A row booked against a bare serial must converge onto the device once
    it is paired — not become a second row."""
    from app.models import DeviceTransfer, db
    from app.services.device_transfers import record_transfer, transferred_item_ids
    from app.services.kobo_auth import create_device

    with app.app_context():
        device, _ = create_device("Kobon")
        item = _add_book("Sent by USB", "/books/usb.epub")

        assert record_transfer(db.session, item.id, serial="N999") is True
        db.session.commit()
        assert DeviceTransfer.query.count() == 1

        # Same device, now known by id too.
        assert record_transfer(db.session, item.id, device=device, serial="N999") is False
        db.session.commit()
        assert DeviceTransfer.query.count() == 1
        row = DeviceTransfer.query.one()
        assert row.device_id == device.id and row.device_serial == "N999"

        # Reachable from either identity.
        assert transferred_item_ids(device) == {item.id}
        assert transferred_item_ids(serial="N999") == {item.id}


def test_the_serial_bridge_finds_rows_booked_before_pairing(app):
    from app.models import db
    from app.services.device_transfers import record_transfer, transferred_item_ids
    from app.services.kobo_auth import create_device

    with app.app_context():
        item = _add_book("Booked early", "/books/early.epub")
        record_transfer(db.session, item.id, serial="N999")
        db.session.commit()

        device, _ = create_device("Paired later")
        device.device_serial = "N999"
        db.session.commit()

        # Looked up by device alone — the serial is picked up from its row.
        assert transferred_item_ids(device) == {item.id}


def test_removing_a_transfer_lets_wifi_have_the_book_back(app):
    from app.models import db
    from app.services.device_transfers import (
        record_transfer, remove_transfer, transferred_item_ids,
    )
    from app.services.kobo_auth import create_device

    with app.app_context():
        device, _ = create_device("Kobon")
        item = _add_book("Round trip", "/books/rt.epub")
        record_transfer(db.session, item.id, device=device)
        db.session.commit()
        assert transferred_item_ids(device) == {item.id}

        assert remove_transfer(db.session, item.id, device=device) == 1
        db.session.commit()
        assert transferred_item_ids(device) == set()


def test_deleting_a_book_takes_its_ledger_rows_with_it(app):
    """A stale row would exclude a book from the wireless sync forever."""
    from app.models import DeviceTransfer, LibraryItem, db
    from app.services.device_transfers import record_transfer
    from app.services.kobo_auth import create_device

    with app.app_context():
        device, _ = create_device("Kobon")
        item = _add_book("Doomed", "/books/doomed.epub")
        record_transfer(db.session, item.id, device=device)
        db.session.commit()

        db.session.delete(LibraryItem.query.get(item.id))
        db.session.commit()
        assert DeviceTransfer.query.count() == 0


def test_nothing_is_recorded_without_an_identity(app):
    from app.models import db
    from app.services.device_transfers import record_transfer

    with app.app_context():
        item = _add_book("Anonymous", "/books/anon.epub")
        assert record_transfer(db.session, item.id) is False


# ---------------------------------------------------------------------------
# The exclusion — the whole point of the ledger
# ---------------------------------------------------------------------------

def test_wifi_sync_withholds_a_usb_transferred_book(app, client):
    """End-to-end over HTTP: the USB book must not be offered, the other must."""
    from app.models import db
    from app.services.device_transfers import record_transfer
    from app.services.kobo_auth import create_device

    with app.app_context():
        device, token = create_device("Kobon")
        by_usb = _add_book("Went by USB", "/books/usb.epub")
        by_wifi = _add_book("Should be offered", "/books/wifi.epub")
        record_transfer(db.session, by_usb.id, device=device)
        db.session.commit()

    payload = client.get(f"/kobo/{token}/v1/library/sync").get_json()
    titles = {e["NewEntitlement"]["BookMetadata"]["Title"] for e in payload}
    assert titles == {"Should be offered"}


def test_withholding_is_not_a_deletion(app, client):
    """Filtering the book out must not make the deletion detector think it
    vanished — that would withdraw a book the device is happily reading."""
    from app.models import db
    from app.services.device_transfers import record_transfer
    from app.services.kobo_auth import create_device
    from app.services.kobo_sync import SyncToken, compute_delta
    from app.routes.kobo import _epub_items_query

    with app.app_context():
        device, _token = create_device("Kobon")
        item = _add_book("Went by USB", "/books/usb.epub")
        other = _add_book("Ordinary", "/books/ordinary.epub")
        record_transfer(db.session, item.id, device=device)
        db.session.commit()

        delta = compute_delta(device.id, SyncToken(), _epub_items_query)
        assert [i.id for i in delta.new_items] == [other.id]
        assert delta.deleted_item_ids == []


def test_a_book_already_synced_by_wifi_keeps_being_updated(app):
    """If it is already a cloud book on the device, withholding it would only
    freeze its reading state — it wouldn't remove anything."""
    from app.models import KoboBookState, db
    from app.services.device_transfers import record_transfer
    from app.services.kobo_auth import create_device
    from app.services.kobo_sync import SyncToken, compute_delta
    from app.routes.kobo import _epub_items_query

    with app.app_context():
        device, _ = create_device("Kobon")
        item = _add_book("Already a cloud book", "/books/cloud.epub")
        db.session.add(KoboBookState(
            device_id=device.id, library_item_id=item.id, revision_id="rev",
        ))
        record_transfer(db.session, item.id, device=device)
        db.session.commit()

        delta = compute_delta(device.id, SyncToken(), _epub_items_query)
        seen = [i.id for i in delta.changed_items + delta.reading_state_items]
        assert seen == [item.id]
        assert delta.deleted_item_ids == []


def test_another_device_is_unaffected(app):
    """The ledger is per device — a USB send to one Kobo must not hide the
    book from another."""
    from app.models import db
    from app.services.device_transfers import record_transfer
    from app.services.kobo_auth import create_device
    from app.services.kobo_sync import SyncToken, compute_delta
    from app.routes.kobo import _epub_items_query

    with app.app_context():
        mine, _ = create_device("Mine")
        theirs, _ = create_device("Theirs")
        item = _add_book("Shared title", "/books/shared.epub")
        record_transfer(db.session, item.id, device=mine)
        db.session.commit()

        assert compute_delta(mine.id, SyncToken(), _epub_items_query).new_items == []
        assert [
            i.id for i in compute_delta(theirs.id, SyncToken(), _epub_items_query).new_items
        ] == [item.id]
