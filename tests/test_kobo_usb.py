# Colophon – e-book metadata manager
"""Reading a mounted Kobo — including the two ways it goes wrong.

A hot WAL makes a *healthy* database read as malformed if you open it in place;
a database with broken pages is genuinely corrupt and must still give up what
it can. Both are reproduced here rather than assumed.

The device's own bookmark (``OEBPS/ch.xhtml#kobo.8.1``) is already Colophon's
Source/Value pair, so USB import carries the exact reading position and not
just a percentage — which is what makes a Kobo that has been offline for weeks
worth plugging in.
"""
import os
import sqlite3

import pytest

CONTENT_DDL = """
CREATE TABLE content (
    ContentID TEXT PRIMARY KEY,
    ContentType INTEGER,
    BookID TEXT,
    Title TEXT,
    Attribution TEXT,
    ReadStatus INTEGER,
    ___PercentRead INTEGER,
    ChapterIDBookmarked TEXT,
    DateLastRead TEXT,
    Filler TEXT
)
"""


def _make_kobo_mount(tmp_path, rows=(), serial="N123"):
    """A directory shaped like a mounted Kobo, with a real SQLite database."""
    mount = tmp_path / "KOBOeReader"
    (mount / ".kobo" / "Kobo").mkdir(parents=True, exist_ok=True)
    (mount / ".kobo" / "version").write_text(f"{serial},4.9.77,4.45.23697\n")

    db_path = mount / ".kobo" / "KoboReader.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(CONTENT_DDL)
    conn.executemany(
        "INSERT INTO content (ContentID, ContentType, BookID, Title, Attribution,"
        " ReadStatus, ___PercentRead, ChapterIDBookmarked, DateLastRead, Filler)"
        " VALUES (?,6,NULL,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return mount, db_path


ROW = (
    "5d4dd4ba-324c-5198-9fa2-a756f9607786", "Children of Strife", "Adrian Tchaikovsky",
    1, 31, "OEBPS/chapter026.xhtml#kobo.8.1", "2026-08-08T22:26:31Z", "x",
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_a_kobo_mount_is_recognised_by_its_own_files(tmp_path):
    from app.services.kobo_usb import looks_like_kobo

    mount, _ = _make_kobo_mount(tmp_path, [ROW])
    assert looks_like_kobo(mount) is True
    assert looks_like_kobo(tmp_path) is False


def test_a_usb_stick_is_not_a_kobo(tmp_path):
    from app.services.kobo_usb import looks_like_kobo

    stick = tmp_path / "USB"
    (stick / "Books").mkdir(parents=True)
    assert looks_like_kobo(stick) is False


# ---------------------------------------------------------------------------
# Reading state off the device
# ---------------------------------------------------------------------------

def test_reads_status_percent_and_the_exact_position(tmp_path):
    from app.services.kobo_usb import read_device_state

    mount, _ = _make_kobo_mount(tmp_path, [ROW])
    entries, recovered = read_device_state(mount)

    assert recovered is False
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "Reading"
    assert entry["percent"] == 31.0
    # The bookmark splits straight into Colophon's own Source/Value pair.
    assert entry["location_source"] == "OEBPS/chapter026.xhtml"
    assert entry["location_value"] == "kobo.8.1"


def test_a_bookmarkless_book_still_reads(tmp_path):
    from app.services.kobo_usb import read_device_state

    row = ("uuid-2", "No Bookmark", "Someone", 1, 5, None, None, "x")
    mount, _ = _make_kobo_mount(tmp_path, [row])
    entry = read_device_state(mount)[0][0]
    assert entry["location_source"] is None and entry["location_value"] is None
    assert entry["percent"] == 5.0


def test_unread_books_are_not_reported(tmp_path):
    from app.services.kobo_usb import read_device_state

    row = ("uuid-3", "Untouched", "Someone", 0, 0, None, None, "x")
    mount, _ = _make_kobo_mount(tmp_path, [row])
    assert read_device_state(mount)[0] == []


def test_reads_a_database_with_a_hot_wal(tmp_path):
    """Opened in place with immutable=1 this reads as malformed — a healthy
    database reported as corrupt. The temp copy must bring the sidecars."""
    from app.services.kobo_usb import read_device_state

    mount, db_path = _make_kobo_mount(tmp_path, [ROW])

    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        "INSERT INTO content (ContentID, ContentType, BookID, Title, Attribution,"
        " ReadStatus, ___PercentRead, ChapterIDBookmarked, DateLastRead, Filler)"
        " VALUES ('uuid-wal',6,NULL,'Written To WAL','A',1,42,"
        "'OEBPS/c1.xhtml#kobo.2.1','2026-08-09T10:00:00Z','x')"
    )
    writer.commit()
    try:
        wal = str(db_path) + "-wal"
        assert os.path.exists(wal) and os.path.getsize(wal) > 0

        entries, recovered = read_device_state(mount)
        titles = {e["title"] for e in entries}
        assert "Written To WAL" in titles
        assert recovered is False
        # The device's files must come back untouched.
        assert os.path.getsize(wal) > 0
    finally:
        writer.close()


def test_salvages_what_it_can_from_a_corrupt_database(tmp_path):
    """Broken pages are real. Losing the rows on them is acceptable; losing
    the whole file is not."""
    from app.services.kobo_usb import read_device_state

    rows = [
        (f"uuid-{i}", f"Book {i}", "Author", 1, 10 + (i % 80),
         f"OEBPS/c{i}.xhtml#kobo.1.1", "2026-08-09T10:00:00Z", "y" * 900)
        for i in range(200)
    ]
    mount, db_path = _make_kobo_mount(tmp_path, rows)

    # Zero a couple of pages in the middle — never page 1, which is the header.
    page = 4096
    with open(db_path, "r+b") as fh:
        fh.seek(page * 4)
        fh.write(b"\x00" * (page * 2))

    # Sanity: a straight read really does fail now.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("SELECT COUNT(*) FROM content").fetchall()
        conn.execute("SELECT * FROM content").fetchall()
    conn.close()

    entries, recovered = read_device_state(mount)
    assert recovered is True
    assert 0 < len(entries) <= 200


def test_a_mount_without_a_database_reads_as_empty(tmp_path):
    from app.services.kobo_usb import read_device_state

    mount = tmp_path / "empty"
    mount.mkdir()
    assert read_device_state(mount) == ([], False)


# ---------------------------------------------------------------------------
# Importing into the library
# ---------------------------------------------------------------------------

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


def _add_book(title, path, **kwargs):
    from app.models import LibraryItem, db

    item = LibraryItem(
        title=title, file_path=path, file_name=os.path.basename(path),
        extension=".epub", **kwargs,
    )
    db.session.add(item)
    db.session.commit()
    return item


def test_import_matches_by_uuid_and_writes_the_exact_position(app, tmp_path):
    from app.models import LibraryItem, db
    from app.routes.kobo import _book_uuid
    from app.services.kobo_usb import import_device_state
    import json

    with app.app_context():
        item = _add_book("Children of Strife", "/books/cos.epub")
        row = (
            _book_uuid(item), "Children of Strife", "Adrian Tchaikovsky",
            1, 31, "OEBPS/chapter026.xhtml#kobo.8.1", "2026-08-08T22:26:31Z", "x",
        )
        mount, _ = _make_kobo_mount(tmp_path, [row])

        receipt = import_device_state(mount)
        assert receipt["applied"] == 1 and receipt["unmatched"] == []

        item = LibraryItem.query.get(item.id)
        assert item.read_status == "Reading"
        assert item.read_progress == 31.0
        assert json.loads(item.read_location_json) == {
            "Source": "OEBPS/chapter026.xhtml", "Type": "KoboSpan", "Value": "kobo.8.1",
        }
        del db


def test_import_obeys_furthest_read(app, tmp_path):
    """A device that is behind must not drag the library backwards — the same
    rule the wireless path uses, because it is the same helper."""
    from app.models import LibraryItem
    from app.routes.kobo import _book_uuid
    from app.services.kobo_usb import import_device_state

    with app.app_context():
        item = _add_book(
            "Ahead Already", "/books/ahead.epub",
            read_status="Reading", read_progress=80.0,
        )
        row = (_book_uuid(item), "Ahead Already", "A", 1, 20, None, None, "x")
        mount, _ = _make_kobo_mount(tmp_path, [row])

        receipt = import_device_state(mount)
        assert receipt["skipped"] == 1 and receipt["applied"] == 0
        assert LibraryItem.query.get(item.id).read_progress == 80.0


def test_import_does_not_trigger_a_redownload(app, tmp_path):
    """Writing reading state must never stamp content_updated_at."""
    from app.models import LibraryItem
    from app.routes.kobo import _book_uuid
    from app.services.kobo_usb import import_device_state

    with app.app_context():
        item = _add_book("Untouched Content", "/books/uc.epub")
        before = item.content_updated_at
        row = (_book_uuid(item), "Untouched Content", "A", 1, 44, None, None, "x")
        mount, _ = _make_kobo_mount(tmp_path, [row])

        import_device_state(mount)
        assert LibraryItem.query.get(item.id).content_updated_at == before


def test_sideloaded_books_match_on_filename(app, tmp_path):
    """A sideload's ContentID is a path, and the device stores .kepub.epub
    where the library has .epub."""
    from app.models import LibraryItem
    from app.services.kobo_usb import import_device_state

    with app.app_context():
        item = _add_book("Sideloaded", "/books/Sideloaded.epub")
        row = (
            "file:///mnt/onboard/Sideloaded.kepub.epub", "Sideloaded", "A",
            1, 12, None, None, "x",
        )
        mount, _ = _make_kobo_mount(tmp_path, [row])

        assert import_device_state(mount)["applied"] == 1
        assert LibraryItem.query.get(item.id).read_progress == 12.0


def test_unknown_books_are_reported_not_invented(app, tmp_path):
    from app.models import LibraryItem
    from app.services.kobo_usb import import_device_state

    with app.app_context():
        mount, _ = _make_kobo_mount(tmp_path, [ROW])
        receipt = import_device_state(mount)
        assert receipt["applied"] == 0
        assert receipt["unmatched"] == ["Children of Strife"]
        assert LibraryItem.query.count() == 0


def test_dry_run_changes_nothing(app, tmp_path):
    from app.models import LibraryItem
    from app.routes.kobo import _book_uuid
    from app.services.kobo_usb import import_device_state

    with app.app_context():
        item = _add_book("Preview Me", "/books/pm.epub")
        row = (_book_uuid(item), "Preview Me", "A", 1, 55, None, None, "x")
        mount, _ = _make_kobo_mount(tmp_path, [row])

        receipt = import_device_state(mount, dry_run=True)
        assert receipt["applied"] == 1 and receipt["dry_run"] is True
        assert LibraryItem.query.get(item.id).read_progress is None


def test_a_fabricated_source_from_the_old_bug_is_not_imported(tmp_path):
    """Real devices still carry bookmarks Colophon gave them before v1.28.2,
    where Source was the book UUID rather than a chapter file. Importing one
    would put that bug straight back into the database.

    Seen on a live device: 12f45e84-...-5b593b9f47a5#kobo.1.1
    """
    from app.services.kobo_usb import read_device_state

    row = (
        "uuid-legacy", "Bone Silence", "Alastair Reynolds", 2, 100,
        "12f45e84-b3a7-582b-94e5-5b593b9f47a5#kobo.1.1", "2026-05-28T12:00:00Z", "x",
    )
    mount, _ = _make_kobo_mount(tmp_path, [row])
    entry = read_device_state(mount)[0][0]

    assert entry["location_source"] is None
    assert entry["location_value"] is None
    # The rest of the row is still perfectly usable.
    assert entry["status"] == "Finished" and entry["percent"] == 100.0


# ---------------------------------------------------------------------------
# Detection has to work for the people who actually plug a Kobo in
# ---------------------------------------------------------------------------

def test_a_device_under_a_media_root_is_found(tmp_path, monkeypatch):
    """The containerised case. A bind mount of /media into a container shows
    up in the container's /proc/mounts as ONE entry, not one per device, so a
    reader plugged in afterwards is invisible to /proc/mounts alone."""
    from app.services.kobo_usb import connected_mounts

    media = tmp_path / "media" / "someuser"
    media.mkdir(parents=True)
    mount, _ = _make_kobo_mount(media, [ROW])

    monkeypatch.setenv("COLOPHON_USB_MOUNT_ROOTS", str(tmp_path / "media"))
    assert connected_mounts() == [str(mount)]


def test_a_device_directly_under_the_root_is_found(tmp_path, monkeypatch):
    """Some systems mount at /media/KOBOeReader, others at /media/<user>/…"""
    from app.services.kobo_usb import connected_mounts

    media = tmp_path / "media"
    media.mkdir()
    mount, _ = _make_kobo_mount(media, [ROW])

    monkeypatch.setenv("COLOPHON_USB_MOUNT_ROOTS", str(media))
    assert connected_mounts() == [str(mount)]


def test_nothing_plugged_in_finds_nothing(tmp_path, monkeypatch):
    """The server-only case: no removable media, no panel, no cost."""
    from app.services.kobo_usb import connected_mounts

    empty = tmp_path / "media"
    empty.mkdir()
    (empty / "some-usb-stick" / "Photos").mkdir(parents=True)

    monkeypatch.setenv("COLOPHON_USB_MOUNT_ROOTS", str(empty))
    assert connected_mounts() == []


def test_detection_can_be_switched_off(tmp_path, monkeypatch):
    from app.services.kobo_usb import connected_mounts

    media = tmp_path / "media"
    media.mkdir()
    _make_kobo_mount(media, [ROW])

    monkeypatch.setenv("COLOPHON_USB_MOUNT_ROOTS", "")
    assert connected_mounts() == []


def test_a_missing_root_is_not_an_error(monkeypatch):
    from app.services.kobo_usb import connected_mounts

    monkeypatch.setenv("COLOPHON_USB_MOUNT_ROOTS", "/definitely/not/here")
    assert connected_mounts() == []


def test_several_roots_are_all_searched(tmp_path, monkeypatch):
    import os as _os
    from app.services.kobo_usb import connected_mounts

    first, second = tmp_path / "media", tmp_path / "run-media"
    first.mkdir()
    second.mkdir()
    a, _ = _make_kobo_mount(first, [ROW])
    b = second / "KOBOeReader"
    (b / ".kobo").mkdir(parents=True)
    (b / ".kobo" / "version").write_text("N2,4.9.77\n")
    (b / ".kobo" / "KoboReader.sqlite").write_bytes(b"")

    monkeypatch.setenv("COLOPHON_USB_MOUNT_ROOTS", _os.pathsep.join([str(first), str(second)]))
    assert set(connected_mounts()) == {str(a), str(b)}


# ---------------------------------------------------------------------------
# Device inspection — read-only, and the only place orphans are visible
# ---------------------------------------------------------------------------

def test_inspect_separates_known_books_from_leftovers(app, tmp_path):
    """A device can hold entitlements Colophon no longer recognises.

    They come from an earlier library-wide delete-and-rescan, which minted new
    ids and therefore new UUIDs. Nothing else in Colophon can see them: it has
    no record of them, and on the device they look like ordinary books.
    """
    from app.routes.kobo import _book_uuid
    from app.services.kobo_usb import inspect_device

    with app.app_context():
        mine = _add_book("A Book I Still Have", "/books/mine.epub")
        known_uuid = _book_uuid(mine)

    mount, _ = _make_kobo_mount(tmp_path, [
        (known_uuid, "A Book I Still Have", "Someone", 1, 20, "#", None, "x"),
        ("11111111-1111-5111-8111-111111111111", "Leftover One", "Someone", 0, 0, "#", None, "x"),
        ("22222222-2222-5222-8222-222222222222", "Leftover Two", "Someone", 0, 0, "#", None, "x"),
    ])

    with app.app_context():
        inv = inspect_device(str(mount))

    assert inv["on_device"] == 3
    assert inv["known"] == 1
    assert inv["orphans"] == 2
    assert inv["orphans_with_reading"] == 0


def test_inspect_flags_leftovers_that_were_read(app, tmp_path):
    """Reading stranded on an unrecognised entry never reached the library.

    That is the only part of the mess that costs the user anything, so it is
    counted separately — the rest is clutter.
    """
    from app.services.kobo_usb import inspect_device

    mount, _ = _make_kobo_mount(tmp_path, [
        ("33333333-3333-5333-8333-333333333333", "Read On A Leftover", "X", 1, 40, "#", None, "x"),
        ("44444444-4444-5444-8444-444444444444", "Never Opened", "X", 0, 0, "#", None, "x"),
    ])

    with app.app_context():
        inv = inspect_device(str(mount))

    assert inv["orphans"] == 2
    assert inv["orphans_with_reading"] == 1
    assert inv["orphans_unread"] == 1
    # The sample leads with the furthest-read one, so the report names what matters.
    assert inv["sample"][0]["title"] == "Read On A Leftover"


def test_inspect_counts_books_the_reader_never_opened(app, tmp_path):
    """Unlike the import, the inventory must not filter on reading activity.

    _STATE_QUERY narrows to books with progress, which is right for importing
    and wrong for counting — it is what made the situation invisible.
    """
    from app.services.kobo_usb import inspect_device, read_device_state

    rows = [
        (f"5555555{i}-5555-5555-8555-55555555555{i}", f"Untouched {i}", "X", 0, 0, "#", None, "x")
        for i in range(4)
    ]
    mount, _ = _make_kobo_mount(tmp_path, rows)

    entries, _ = read_device_state(str(mount))
    with app.app_context():
        inv = inspect_device(str(mount))

    assert entries == []          # the importer correctly sees nothing to import
    assert inv["on_device"] == 4  # the inventory still knows they are there


def test_inspect_without_a_database_says_so(app, tmp_path):
    from app.services.kobo_usb import inspect_device

    empty = tmp_path / "NotAKobo"
    empty.mkdir()
    with app.app_context():
        assert inspect_device(str(empty)) is None
