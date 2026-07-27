# Colophon – tests for the reader dictionary lookup
# (services/dictionaries.py + the /reader/dict/* routes)
import gzip
import hashlib
import io
import os
import struct
import tarfile

import pytest
from flask import Flask

from app.models import db, LibraryItem
from app.routes.reader import reader_bp
from app.services import dictionaries


# --------------------------------------------------------------------------
# Helpers: synthetic StarDict pairs
# --------------------------------------------------------------------------
def stardict_bytes(entries):
    """entries: [(word, text)] → (idx_bytes, dict_bytes)."""
    idx = b""
    dict_data = b""
    for word, text in entries:
        data = text.encode("utf-8")
        idx += word.encode("utf-8") + b"\x00" + struct.pack(">II", len(dict_data), len(data))
        dict_data += data
    return idx, dict_data


def install_pair(data_dir, pair, entries, typ="m"):
    d = os.path.join(data_dir, "dictionaries", pair)
    os.makedirs(d, exist_ok=True)
    idx, dict_data = stardict_bytes(entries)
    with open(os.path.join(d, f"{pair}.idx"), "wb") as fh:
        fh.write(idx)
    with open(os.path.join(d, f"{pair}.dict"), "wb") as fh:
        fh.write(dict_data)
    with open(os.path.join(d, f"{pair}.ifo"), "w") as fh:
        fh.write(f"StarDict's dict ifo file\nversion=3.0.0\nsametypesequence={typ}\n")


def archive_bytes(files, mode="w:xz"):
    """{basename: bytes} → tar archive bytes, members under a subdirectory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tar:
        for name, data in files.items():
            info = tarfile.TarInfo("some-dict-1.0/" + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clear_index_cache():
    dictionaries._index_cache.clear()
    yield
    dictionaries._index_cache.clear()


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "test.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["DATA_DIR"] = str(tmp_path / "data")
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    db.init_app(app)
    app.register_blueprint(reader_bp)
    with app.app_context():
        db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def english_dicts(app):
    data_dir = app.config["DATA_DIR"]
    install_pair(data_dir, "eng-eng", [
        ("run", "to move swiftly"),
        ("run", "a sequence of events"),      # adjacent duplicate headword
        ("bewildered", "confused and unable to think clearly"),
        ("carry", "to hold and transport"),
    ], typ="m")
    install_pair(data_dir, "eng-swe", [
        ("run", "<b>springa</b>"),
        ("bewildered", "<i>förvirrad</i>"),
    ], typ="h")
    return data_dir


# --------------------------------------------------------------------------
# Pure functions
# --------------------------------------------------------------------------
class TestCandidates:
    def test_exact_and_lowercase_first(self):
        cands = dictionaries._candidates("Bewildered")
        assert cands[0] == "Bewildered"
        assert cands[1] == "bewildered"

    def test_strips_surrounding_punctuation(self):
        assert dictionaries._candidates('“gaunt,”')[0] == "gaunt"

    def test_possessive(self):
        assert "dog" in dictionaries._candidates("dog’s")

    def test_plural_ies(self):
        assert "carry" in dictionaries._candidates("carries")

    def test_plural_s(self):
        assert "cat" in dictionaries._candidates("cats")

    def test_ing_with_doubled_consonant(self):
        assert "run" in dictionaries._candidates("running")

    def test_ed_with_silent_e(self):
        assert "love" in dictionaries._candidates("loved")

    def test_no_tiny_stems(self):
        # "is" must not stem to "i"
        assert "i" not in dictionaries._candidates("is")


class TestNormalizeLanguage:
    def test_region_variants(self):
        assert dictionaries.normalize_language("en-GB") == "en"
        assert dictionaries.normalize_language("EN_us") == "en"

    def test_empty(self):
        assert dictionaries.normalize_language(None) == ""

    def test_pairs_mapping(self):
        assert dictionaries.pairs_for_language("en-US") == ["eng-eng", "eng-swe"]
        assert dictionaries.pairs_for_language("fi") == []


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------
class TestLookup:
    def test_finds_definition_and_translation(self, app, english_dicts):
        result = dictionaries.lookup_word("en", "bewildered")
        assert result["status"] == "ok"
        kinds = {m["kind"] for m in result["matches"]}
        assert kinds == {"definition", "translation"}
        texts = [m["text"] for m in result["matches"]]
        assert "confused and unable to think clearly" in texts
        assert "<i>förvirrad</i>" in texts

    def test_adjacent_duplicate_headwords_all_returned(self, app, english_dicts):
        result = dictionaries.lookup_word("en", "run")
        defs = [m for m in result["matches"] if m["kind"] == "definition"]
        assert len(defs) == 2

    def test_morphology_fallback(self, app, english_dicts):
        result = dictionaries.lookup_word("en", "running")
        assert any(m["headword"] == "run" for m in result["matches"])

    def test_case_insensitive(self, app, english_dicts):
        result = dictionaries.lookup_word("en", "Bewildered")
        assert result["matches"]

    def test_miss_is_ok_with_empty_matches(self, app, english_dicts):
        result = dictionaries.lookup_word("en", "penetralium")
        assert result["status"] == "ok"
        assert result["matches"] == []

    def test_needs_download_when_missing(self, app):
        result = dictionaries.lookup_word("en", "word")
        assert result["status"] == "needs_download"
        assert result["language"] == "en"
        assert result["download_mb"] > 0
        assert set(result["pairs"]) == {"eng-eng", "eng-swe"}

    def test_unsupported_language(self, app):
        assert dictionaries.lookup_word("fi", "sana")["status"] == "unsupported_language"

    def test_html_type_flagged(self, app, english_dicts):
        result = dictionaries.lookup_word("en", "run")
        trans = [m for m in result["matches"] if m["kind"] == "translation"]
        assert trans[0]["type"] == "h"


# --------------------------------------------------------------------------
# Download + normalisation (network mocked)
# --------------------------------------------------------------------------
class TestEnsureDownloaded:
    PAIR = "tst-tst"

    def _manifest(self, body, algo="sha256"):
        return {
            "label": "Test", "kind": "definition",
            "url": "https://example.invalid/dict.tar.xz",
            "checksum_algo": algo,
            "checksum": hashlib.new(algo, body).hexdigest(),
            "archive_mb": 1, "license": "test",
        }

    def test_downloads_and_normalises_gzipped_members(self, app, monkeypatch):
        idx, dict_data = stardict_bytes([("hello", "greeting")])
        body = archive_bytes({
            "tst.ifo": b"version=3.0.0\nsametypesequence=m\nwordcount=1\n",
            "tst.idx.gz": gzip.compress(idx),
            "tst.dict.dz": gzip.compress(dict_data),
            "README": b"ignore me",
        })
        monkeypatch.setitem(dictionaries.MANIFEST, self.PAIR, self._manifest(body))
        monkeypatch.setattr(dictionaries.requests, "get",
                            lambda *a, **kw: FakeResponse(body))

        dictionaries.ensure_downloaded(self.PAIR)

        files = dictionaries._pair_files(self.PAIR)
        assert open(files["idx"], "rb").read() == idx
        assert open(files["dict"], "rb").read() == dict_data
        loaded = dictionaries._load_pair(self.PAIR)
        assert "hello" in loaded["index"]

    def test_checksum_mismatch_aborts(self, app, monkeypatch):
        body = archive_bytes({"tst.ifo": b"version=3\n"})
        spec = self._manifest(body)
        spec["checksum"] = "0" * 64
        monkeypatch.setitem(dictionaries.MANIFEST, self.PAIR, spec)
        monkeypatch.setattr(dictionaries.requests, "get",
                            lambda *a, **kw: FakeResponse(body))
        with pytest.raises(ValueError, match="checksum mismatch"):
            dictionaries.ensure_downloaded(self.PAIR)
        assert not dictionaries.is_downloaded(self.PAIR)

    def test_missing_idx_aborts(self, app, monkeypatch):
        body = archive_bytes({
            "tst.ifo": b"version=3\n",
            "tst.dict": b"data",
        })
        monkeypatch.setitem(dictionaries.MANIFEST, self.PAIR, self._manifest(body))
        monkeypatch.setattr(dictionaries.requests, "get",
                            lambda *a, **kw: FakeResponse(body))
        with pytest.raises(ValueError, match="no .idx"):
            dictionaries.ensure_downloaded(self.PAIR)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
class TestRoutes:
    def test_lookup_ok(self, client, english_dicts):
        resp = client.get("/reader/dict/lookup?word=bewildered&lang=en")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_lookup_rejects_empty_word(self, client):
        assert client.get("/reader/dict/lookup?lang=en").status_code == 400

    def test_lookup_rejects_absurd_word(self, client):
        assert client.get("/reader/dict/lookup?word=" + "a" * 100 + "&lang=en").status_code == 400

    def test_lookup_reports_needs_download(self, client):
        resp = client.get("/reader/dict/lookup?word=hello&lang=en")
        assert resp.get_json()["status"] == "needs_download"

    def test_download_unsupported_language(self, client):
        resp = client.post("/reader/dict/download", json={"language": "fi"})
        assert resp.status_code == 400

    def test_download_ok(self, client, monkeypatch):
        monkeypatch.setattr(dictionaries, "ensure_downloaded", lambda pair: None)
        resp = client.post("/reader/dict/download", json={"language": "en"})
        assert resp.status_code == 200
        assert resp.get_json()["pairs"] == ["eng-eng", "eng-swe"]

    def test_download_failure_is_502(self, client, monkeypatch):
        def boom(pair):
            raise ValueError("checksum mismatch")
        monkeypatch.setattr(dictionaries, "ensure_downloaded", boom)
        resp = client.post("/reader/dict/download", json={"language": "en"})
        assert resp.status_code == 502
        assert resp.get_json()["error"] == "download_failed"

    def _make_item(self, app):
        with app.app_context():
            item = LibraryItem(title="Wuthering Heights", author="Emily Brontë",
                               file_path="/books/wh.epub", file_name="wh.epub",
                               extension=".epub")
            db.session.add(item)
            db.session.commit()
            return item.id

    def test_explain_requires_ai(self, app, client, monkeypatch):
        import app.routes.reader as reader_routes
        monkeypatch.setattr(reader_routes, "ai_is_configured", lambda: False)
        item_id = self._make_item(app)
        resp = client.post(f"/reader/{item_id}/dict/explain",
                           json={"word": "gaunt", "sentence": "a range of gaunt thorns"})
        assert resp.status_code == 503
        assert resp.get_json()["error"] == "not_configured"

    def test_explain_ok(self, app, client, monkeypatch):
        import app.routes.reader as reader_routes
        monkeypatch.setattr(reader_routes, "ai_is_configured", lambda: True)
        monkeypatch.setattr(reader_routes, "explain_word_in_context",
                            lambda word, sentence, item: {"ok": True, "explanation": "mager, tärd"})
        item_id = self._make_item(app)
        resp = client.post(f"/reader/{item_id}/dict/explain",
                           json={"word": "gaunt", "sentence": "a range of gaunt thorns"})
        assert resp.status_code == 200
        assert resp.get_json()["explanation"] == "mager, tärd"

    def test_explain_rejects_missing_word(self, app, client, monkeypatch):
        import app.routes.reader as reader_routes
        monkeypatch.setattr(reader_routes, "ai_is_configured", lambda: True)
        item_id = self._make_item(app)
        resp = client.post(f"/reader/{item_id}/dict/explain", json={"sentence": "x"})
        assert resp.status_code == 400
