# Colophon – e-book metadata manager
"""Virtual page map: counting, the pure position<->page helpers, the route."""
import json
import os
import zipfile

import pytest

from app.services import page_map as pm

CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)
OPF = (
    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
    '<manifest>'
    '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="c3" href="ch3.xhtml" media-type="application/xhtml+xml"/>'
    '</manifest><spine><itemref idref="c1"/><itemref idref="c2"/>'
    '<itemref idref="c3"/></spine></package>'
)


def _doc(body, head=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


# ch1: 1000 dense chars of text plus script/style/comment that must not count.
CH1 = _doc(
    "<p>" + "a" * 600 + " " + "b" * 400 + "</p><script>var x = 12345;</script>"
    "<style>p { color: red }</style><!-- hidden comment -->"
)
# ch2: 2000 dense chars, with a print page break after 500.
CH2 = _doc(
    "<p>" + "c" * 500 + '</p><span epub:type="pagebreak" title="198"></span>'
    "<p>" + "d" * 1500 + "</p>"
)
# ch3: 600 dense chars.
CH3 = _doc("<p>" + "e" * 600 + "</p>")


def _write_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/ch1.xhtml", CH1)
        z.writestr("OEBPS/ch2.xhtml", CH2)
        z.writestr("OEBPS/ch3.xhtml", CH3)


@pytest.fixture
def epub(tmp_path):
    p = tmp_path / "book.epub"
    _write_epub(p)
    return str(p)


class _Item:
    def __init__(self, path, id=1):
        self.id = id
        self.file_path = path


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app
    from app.models import db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["DATA_DIR"] = str(tmp_path / "data")

    def _wipe():
        with flask_app.app_context():
            db.session.execute(text("DELETE FROM kobo_book_states"))
            db.session.execute(text("DELETE FROM library_items"))
            db.session.commit()

    _wipe()
    yield flask_app
    _wipe()


def test_section_counts_exclude_script_style_and_comments(epub, monkeypatch):
    # The arithmetic below is written for 1500 chars/page; pin it so the
    # constant can be tuned without rewriting every expected number.
    monkeypatch.setattr(pm, "PAGE_CHARS", 1500)
    m = pm.build_page_map(_Item(epub))
    assert [s["chars"] for s in m["sections"]] == [1000, 2000, 600]
    assert [s["start"] for s in m["sections"]] == [0, 1000, 3000]
    assert m["sections"][0]["source"] == "OEBPS/ch1.xhtml"
    assert m["total_chars"] == 3600
    assert m["total_pages"] == 3  # ceil(3600 / 1500)
    assert m["page_chars"] == 1500


def test_non_epub_gives_none(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    assert pm.build_page_map(_Item(str(f))) is None
    assert pm.load_page_map(_Item(str(f))) is None


def test_page_position_round_trip_at_section_boundaries(epub, monkeypatch):
    monkeypatch.setattr(pm, "PAGE_CHARS", 1500)
    m = pm.build_page_map(_Item(epub))
    assert pm.page_for_position(m, "OEBPS/ch1.xhtml", 0) == 1
    assert pm.page_for_position(m, "OEBPS/ch2.xhtml", 0) == 1   # abs 1000
    assert pm.page_for_position(m, "OEBPS/ch2.xhtml", 500) == 2  # abs 1500
    assert pm.page_for_position(m, "OEBPS/ch3.xhtml", 599) == 3
    assert pm.page_for_position(m, "OEBPS/ch3.xhtml#frag", 0) == 3
    assert pm.page_for_position(m, "OEBPS/nope.xhtml", 0) is None
    assert pm.position_for_page(m, 1) == ("OEBPS/ch1.xhtml", 0)
    assert pm.position_for_page(m, 2) == ("OEBPS/ch2.xhtml", 500)
    assert pm.position_for_page(m, 3) == ("OEBPS/ch3.xhtml", 0)  # abs 3000
    # Clamped
    assert pm.position_for_page(m, 99) == pm.position_for_page(m, 3)
    assert pm.position_for_page(m, 0) == pm.position_for_page(m, 1)
    for p in (1, 2, 3):
        src, off = pm.position_for_page(m, p)
        assert pm.page_for_position(m, src, off) == p


def test_position_for_page_skips_empty_sections():
    m = {
        "page_chars": 10,
        "sections": [
            {"source": "a", "chars": 10, "start": 0},
            {"source": "empty", "chars": 0, "start": 10},
            {"source": "b", "chars": 10, "start": 10},
        ],
        "total_chars": 20, "total_pages": 2, "page_list": [],
    }
    assert pm.position_for_page(m, 2) == ("b", 0)


def test_page_list_and_print_page_lookup(epub):
    m = pm.build_page_map(_Item(epub))
    assert m["page_list"] == [
        {"source": "OEBPS/ch2.xhtml", "offset": 500, "label": "198"}
    ]
    assert pm.print_page_for_position(m, "OEBPS/ch1.xhtml", 900) is None
    assert pm.print_page_for_position(m, "OEBPS/ch2.xhtml", 499) is None
    assert pm.print_page_for_position(m, "OEBPS/ch2.xhtml", 500) == "198"
    assert pm.print_page_for_position(m, "OEBPS/ch3.xhtml", 0) == "198"


def test_cache_written_reused_and_stale_removed(app, epub, tmp_path):
    item = _Item(epub, id=7)
    with app.app_context():
        assert pm.load_page_map(item, build=False) is None
        m = pm.load_page_map(item, build=True)
        files = list((tmp_path / "data" / "page-maps").glob("7-*.json"))
        assert len(files) == 1
        # Reused: a build would produce different data than the planted cache.
        planted = dict(m, total_pages=42)
        files[0].write_text(json.dumps(planted))
        assert pm.load_page_map(item, build=False)["total_pages"] == 42
        # Touch the source -> new key, old file removed.
        st = os.stat(epub)
        os.utime(epub, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        pm.load_page_map(item, build=True)
        after = list((tmp_path / "data" / "page-maps").glob("7-*.json"))
        assert len(after) == 1 and after[0] != files[0]


def test_route_available_for_epub_and_not_for_other(app, epub):
    from app.models import LibraryItem, db

    with app.app_context():
        a = LibraryItem(title="A", file_path=epub, file_name="b.epub", extension=".epub")
        b = LibraryItem(title="B", file_path="/books/x.mobi", file_name="x.mobi", extension=".mobi")
        db.session.add_all([a, b])
        db.session.commit()
        aid, bid = a.id, b.id
    client = app.test_client()
    r = client.get(f"/reader/{aid}/pagemap")
    assert r.status_code == 200
    body = r.get_json()
    assert body["available"] is True and body["total_pages"] == 3
    r = client.get(f"/reader/{bid}/pagemap")
    assert r.status_code == 200 and r.get_json() == {"available": False}
