# Colophon – e-book metadata manager
"""OPDS + KOSync for CrossPoint/KOReader.

The rule these tests exist for: the device is told where the reader *is*
(the last-write-wins position), never how far they have *been* (the
furthest-read progress). CrossPoint jumps to whatever we answer when it is
ahead of its own place, so answering with the high-water mark is the
"85 % although I have read 10 %" bug. See docs/kobo-reading-state-sync.md.
"""
import hashlib
import json
import zipfile

import pytest

CHAPTERS = [
    "<html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>One</title></head><body>"
    "<h1>Chapter one</h1><p>It was a bright cold day.</p><p>The clocks struck thirteen.</p>"
    "</body></html>",
    "<html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>Two</title></head><body>"
    "<div><p>Second <em>chapter</em> text&#160;here.</p>"
    "<p>More words in the second chapter, enough to give it some length.</p></div>"
    "</body></html>",
    "<html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>Three</title></head><body>"
    "<p>The last chapter. It ends here.</p></body></html>",
]


def _make_epub(path, chapters=CHAPTERS):
    manifest = "".join(
        f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(chapters))
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            f"{manifest}</manifest><spine>{spine}</spine></package>",
        )
        for i, body in enumerate(chapters):
            z.writestr(f"OEBPS/c{i}.xhtml", body)
    return str(path)


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app
    from app.models import db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True

    def _wipe():
        with flask_app.app_context():
            for table in ("kosync_documents", "reader_devices", "kobo_book_states", "library_items"):
                db.session.execute(text(f"DELETE FROM {table}"))
            db.session.commit()

    _wipe()
    # No KEPUB in these tests: positions stay exact, the Kobo location is cleared.
    monkeypatch.setattr("app.services.kobo_location._kepub_path", lambda item: None)
    yield flask_app
    _wipe()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def book(app, tmp_path):
    from app.models import LibraryItem, db

    path = _make_epub(tmp_path / "Orwell - Nineteen.epub")
    with app.app_context():
        item = LibraryItem(
            title="Nineteen: A Novel", author="George Orwell", file_path=path,
            file_name="Orwell - Nineteen.epub", extension=".epub",
        )
        db.session.add(item)
        db.session.commit()
        return item.id, path


@pytest.fixture
def token(app):
    from app.services.reader_devices import create_device

    with app.app_context():
        _device, tok = create_device("X4 Pro", language="sv")
        return tok


def _doc_id(path):
    from app.services.kosync_documents import partial_md5

    return partial_md5(path)


def _item(app, item_id):
    from app.models import LibraryItem, db

    with app.app_context():
        item = db.session.get(LibraryItem, item_id)
        db.session.expunge(item)
        return item


def _set(app, item_id, **fields):
    from app.models import LibraryItem, db

    with app.app_context():
        item = db.session.get(LibraryItem, item_id)
        for key, value in fields.items():
            setattr(item, key, value)
        db.session.commit()


# ---------------------------------------------------------------------------
# XPointer <-> character offset
# ---------------------------------------------------------------------------

def test_xpath_matches_crosspoint_format_and_round_trips(app, book):
    from types import SimpleNamespace
    from app.services.koreader_xpath import offset_for_xpath, xpath_for_offset

    item = SimpleNamespace(file_path=book[1])
    # "Thecloc…" — offset 26 is the "T" of "The clocks" (whitespace excluded).
    dense = "Chapteroneitwasabrightcoldday.".__len__()
    xp = xpath_for_offset(item, "OEBPS/c0.xhtml", dense)
    assert xp == "/body/DocFragment[1]/body/p[2]/text()[1].0"
    assert offset_for_xpath(item, xp) == ("OEBPS/c0.xhtml", dense)
    for offset in range(0, 40):
        xp = xpath_for_offset(item, "OEBPS/c1.xhtml", offset)
        assert offset_for_xpath(item, xp) == ("OEBPS/c1.xhtml", offset), xp


def test_xpath_counts_text_nodes_split_by_inline_elements(app, book):
    from types import SimpleNamespace
    from app.services.koreader_xpath import offset_for_xpath

    item = SimpleNamespace(file_path=book[1])
    # "Second " | <em>chapter</em> | " text here." — the run after </em> is text()[2].
    assert offset_for_xpath(item, "/body/DocFragment[2]/body/div[1]/p[1]/text()[2].1") == (
        "OEBPS/c1.xhtml", len("Secondchapter"),
    )
    assert offset_for_xpath(item, "/body/DocFragment[2]/body/div[1]/p[1]/em[1]/text()[1].0") == (
        "OEBPS/c1.xhtml", len("Second"),
    )


def test_xpath_that_names_nothing_does_not_resolve(app, book):
    from types import SimpleNamespace
    from app.services.koreader_xpath import offset_for_xpath

    item = SimpleNamespace(file_path=book[1])
    assert offset_for_xpath(item, "/body/DocFragment[2]/body/div[1]/p[9]/text()[1].0") is None
    assert offset_for_xpath(item, "/body/DocFragment[9]/body/p[1]/text()[1].0") is None
    assert offset_for_xpath(item, "garbage") is None


# ---------------------------------------------------------------------------
# Document ids
# ---------------------------------------------------------------------------

def test_partial_md5_is_koreaders_algorithm(tmp_path):
    from app.services.kosync_documents import partial_md5

    data = bytes(range(256)) * 80  # 20 KiB: offsets 0, 1 KiB, 4 KiB, 16 KiB
    path = tmp_path / "f.bin"
    path.write_bytes(data)
    expected = hashlib.md5()
    for offset in (0, 1024, 4096, 16384):
        expected.update(data[offset:offset + 1024])
    assert partial_md5(str(path)) == expected.hexdigest()


def test_opds_filenames_follow_crosspoint_sanitising():
    from app.services.kosync_documents import opds_filenames

    names = opds_filenames("Regime Change: Inside", "Maggie Haberman & Jonathan Swan")
    assert names[0] == "Maggie Haberman & Jonathan Swan - Regime Change_ Inside.epub"
    assert "Regime Change_ Inside.epub" in names


def test_document_resolves_by_content_and_by_every_filename(app, book):
    from app.services.kosync_documents import filename_md5, resolve

    item_id, path = book
    with app.app_context():
        assert resolve(_doc_id(path)).id == item_id
        assert resolve(filename_md5("Orwell - Nineteen.epub")).id == item_id
        assert resolve(filename_md5("George Orwell - Nineteen_ A Novel.epub")).id == item_id
        assert resolve(filename_md5("unrelated.epub")) is None


def test_old_file_version_still_resolves_after_the_file_changes(app, book):
    from app.services.kosync_documents import resolve

    item_id, path = book
    with app.app_context():
        old = _doc_id(path)
        assert resolve(old).id == item_id
    _make_epub(path, CHAPTERS + ["<html><body><p>Appendix.</p></body></html>"])
    with app.app_context():
        new = _doc_id(path)
        assert new != old
        assert resolve(new).id == item_id
        assert resolve(old).id == item_id


def test_ambiguous_filename_resolves_to_nothing(app, book, tmp_path):
    from app.models import LibraryItem, db
    from app.services.kosync_documents import filename_md5, resolve

    other = _make_epub(tmp_path / "other.epub", CHAPTERS[:1])
    with app.app_context():
        db.session.add(LibraryItem(
            title="Nineteen: A Novel", author="George Orwell", file_path=other,
            file_name="other.epub", extension=".epub",
        ))
        db.session.commit()
        assert resolve(filename_md5("George Orwell - Nineteen_ A Novel.epub")) is None
        assert resolve(_doc_id(other)) is not None


# ---------------------------------------------------------------------------
# KOSync routes
# ---------------------------------------------------------------------------

def test_unknown_token_is_refused(client):
    assert client.get("/kosync/" + "a" * 32 + "/users/auth").status_code == 401
    assert client.get("/opds/" + "a" * 32 + "/").status_code == 401


def test_auth_accepts_any_credentials(client, token):
    resp = client.get(f"/kosync/{token}/users/auth", headers={"x-auth-user": "x", "x-auth-key": "y"})
    assert resp.status_code == 200
    assert client.post(f"/kosync/{token}/users/create", json={"username": "a"}).status_code == 201


def test_progress_alone_is_never_served_as_a_position(app, client, token, book):
    """85 % furthest-read with no position must not send the device to 85 %."""
    item_id, path = book
    _set(app, item_id, read_status="Reading", read_progress=85.0)
    resp = client.get(f"/kosync/{token}/syncs/progress/{_doc_id(path)}")
    assert resp.status_code == 404


def test_get_serves_the_last_position_not_the_furthest(app, client, token, book):
    item_id, path = book
    _set(
        app, item_id, read_status="Reading", read_progress=85.0,
        read_position_json=json.dumps({
            "source": "OEBPS/c0.xhtml", "offset": 30, "percent": 10.0,
            "page": None, "at": 1_700_000_000_000, "origin": "kobo",
        }),
    )
    body = client.get(f"/kosync/{token}/syncs/progress/{_doc_id(path)}").get_json()
    assert body["progress"] == "/body/DocFragment[1]/body/p[2]/text()[1].0"
    assert body["percentage"] < 0.4
    assert body["timestamp"] == 1_700_000_000


def test_unknown_document_is_404(client, token):
    assert client.get(f"/kosync/{token}/syncs/progress/{'0' * 32}").status_code == 404


def test_put_records_an_exact_position(app, client, token, book):
    item_id, path = book
    xp = "/body/DocFragment[2]/body/div[1]/p[2]/text()[1].5"
    resp = client.put(f"/kosync/{token}/syncs/progress", json={
        "document": _doc_id(path), "progress": xp, "percentage": 0.5,
        "device": "CrossPoint", "device_id": "x",
    })
    assert resp.status_code == 200
    item = _item(app, item_id)
    pos = json.loads(item.read_position_json)
    assert pos["source"] == "OEBPS/c1.xhtml"
    assert pos["origin"] == "kosync"
    assert item.read_status == "Reading"
    assert item.read_progress is not None
    # And it reads back as the very same pointer.
    body = client.get(f"/kosync/{token}/syncs/progress/{_doc_id(path)}").get_json()
    assert body["progress"] == xp


def test_put_at_the_end_never_marks_finished(app, client, token, book):
    item_id, path = book
    client.put(f"/kosync/{token}/syncs/progress", json={
        "document": _doc_id(path),
        "progress": "/body/DocFragment[3]/body/p[1]/text()[1].20", "percentage": 1.0,
    })
    assert _item(app, item_id).read_status == "Reading"


def test_put_whose_pointer_disagrees_with_its_percentage_falls_back_to_chapter(app, client, token, book):
    item_id, path = book
    client.put(f"/kosync/{token}/syncs/progress", json={
        "document": _doc_id(path),
        "progress": "/body/DocFragment[3]/body/p[1]/text()[1].3", "percentage": 0.02,
    })
    pos = json.loads(_item(app, item_id).read_position_json)
    assert pos["source"] == "OEBPS/c0.xhtml"
    assert pos["offset"] is None


def test_going_back_moves_the_position_but_keeps_the_furthest_progress(app, client, token, book):
    item_id, path = book
    doc = _doc_id(path)
    client.put(f"/kosync/{token}/syncs/progress", json={
        "document": doc, "progress": "/body/DocFragment[3]/body/p[1]/text()[1].3", "percentage": 0.9,
    })
    furthest = _item(app, item_id).read_progress
    client.put(f"/kosync/{token}/syncs/progress", json={
        "document": doc, "progress": "/body/DocFragment[1]/body/p[1]/text()[1].0", "percentage": 0.1,
    })
    item = _item(app, item_id)
    assert item.read_progress == furthest
    assert json.loads(item.read_position_json)["source"] == "OEBPS/c0.xhtml"


def test_put_for_an_unknown_document_writes_nothing(app, client, token, book):
    item_id, _path = book
    resp = client.put(f"/kosync/{token}/syncs/progress", json={
        "document": "f" * 32, "progress": "/body/DocFragment[1]/body/p[1]/text()[1].0", "percentage": 0.5,
    })
    assert resp.status_code == 200
    item = _item(app, item_id)
    assert item.read_position_json is None
    assert item.read_progress is None


# ---------------------------------------------------------------------------
# OPDS
# ---------------------------------------------------------------------------

def test_root_feed_offers_navigation_and_search(client, token):
    resp = client.get(f"/opds/{token}/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "{searchTerms}" in body
    assert f"/opds/{token}/reading" in body
    assert "Läser nu" in body  # the device was created with Swedish


def test_book_feed_has_an_epub_acquisition_and_only_epubs(app, client, token, book, tmp_path):
    from app.models import LibraryItem, db

    with app.app_context():
        db.session.add(LibraryItem(
            title="A PDF", file_path=str(tmp_path / "a.pdf"), file_name="a.pdf", extension=".pdf",
        ))
        db.session.commit()
    body = client.get(f"/opds/{token}/all").get_data(as_text=True)
    assert "Nineteen: A Novel" in body
    assert "<name>George Orwell</name>" in body
    assert f"/opds/{token}/book/{book[0]}.epub" in body
    assert 'type="application/epub+zip"' in body
    assert "A PDF" not in body


def test_download_serves_the_library_file_and_records_its_hash(app, client, token, book):
    from app.models import KosyncDocument

    item_id, path = book
    resp = client.get(f"/opds/{token}/book/{item_id}.epub")
    assert resp.status_code == 200
    with open(path, "rb") as fh:
        assert resp.data == fh.read()
    with app.app_context():
        assert KosyncDocument.query.filter_by(doc_hash=_doc_id(path), item_id=item_id).count() == 1


def test_search_finds_by_author(client, token, book):
    body = client.get(f"/opds/{token}/search?q=orwell").get_data(as_text=True)
    assert "Nineteen: A Novel" in body
