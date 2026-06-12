# Colophon – tests for the in-app upload feature
import io
import os

import pytest
from flask import Flask

from app.models import db, LibraryItem
from app.routes.scan import scan_bp, sanitize_upload_filename


# --------------------------------------------------------------------------
# sanitize_upload_filename — pure, no app needed
# --------------------------------------------------------------------------
class TestSanitizeUploadFilename:
    def test_keeps_plain_name(self):
        assert sanitize_upload_filename("Book.epub") == "Book.epub"

    def test_preserves_swedish_letters(self):
        assert sanitize_upload_filename("Röde Orm.epub") == "Röde Orm.epub"

    def test_strips_directory_components(self):
        assert sanitize_upload_filename("../../etc/passwd") == "passwd"
        assert sanitize_upload_filename("/abs/path/Book.epub") == "Book.epub"
        assert sanitize_upload_filename("sub\\dir\\Book.epub") == "Book.epub"

    def test_strips_filesystem_hostile_chars(self):
        assert sanitize_upload_filename('Book:"<>|?*.epub') == "Book.epub"

    def test_collapses_whitespace_and_trims_dots(self):
        assert sanitize_upload_filename("  My   Book .epub  ") == "My Book .epub"
        assert sanitize_upload_filename("...Book.epub") == "Book.epub"

    def test_empty_becomes_placeholder(self):
        assert sanitize_upload_filename("") == "upload"
        assert sanitize_upload_filename("///") == "upload"

    def test_strips_control_chars(self):
        assert sanitize_upload_filename("Bo\x00ok\t.epub") == "Book.epub"


# --------------------------------------------------------------------------
# /upload route — minimal app bound to a temp DB + temp LIBRARY_DIR
# --------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "test.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["LIBRARY_DIR"] = str(tmp_path / "books")
    app.config["COVER_DIR"] = str(tmp_path / "covers")
    os.makedirs(app.config["LIBRARY_DIR"], exist_ok=True)
    os.makedirs(app.config["COVER_DIR"], exist_ok=True)

    db.init_app(app)
    app.register_blueprint(scan_bp)
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def _file(name, data=b"%PDF-1.4 fake"):
    return (io.BytesIO(data), name)


class TestUploadRoute:
    def test_adds_a_supported_file(self, client, tmp_path):
        resp = client.post(
            "/upload",
            data={"files": _file("Min Bok.pdf")},
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        assert body["added"] == 1
        assert body["results"][0]["status"] == "added"
        # File landed in LIBRARY_DIR and a row exists with a filename-derived title.
        assert (tmp_path / "books" / "Min Bok.pdf").exists()
        item = LibraryItem.query.first()
        assert item is not None
        assert item.title == "Min Bok"
        assert item.created_at is not None  # drives the "Nytillagt" badge

    def test_rejects_unsupported_extension(self, client, tmp_path):
        resp = client.post(
            "/upload",
            data={"files": _file("notes.txt", b"hello")},
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        assert body["errors"] == 1
        assert body["results"][0]["reason"] == "unsupported"
        assert not (tmp_path / "books" / "notes.txt").exists()
        assert LibraryItem.query.count() == 0

    def test_skips_duplicate_same_name(self, client):
        client.post("/upload", data={"files": _file("Dup.pdf")},
                    content_type="multipart/form-data")
        resp = client.post("/upload", data={"files": _file("Dup.pdf")},
                           content_type="multipart/form-data")
        body = resp.get_json()
        assert body["skipped"] == 1
        assert body["results"][0]["status"] == "skipped"
        assert LibraryItem.query.count() == 1  # no duplicate row

    def test_no_files_is_400(self, client):
        resp = client.post("/upload", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_reports_author_status(self, client):
        # A fake PDF has no embedded metadata → no author → ❓ missing.
        resp = client.post(
            "/upload",
            data={"files": _file("Min Bok.pdf")},
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        assert body["authors"] == {"missing": 1}
        assert body["results"][0]["author_status"] == "missing"
        item = LibraryItem.query.first()
        assert item.author_status == "missing"

    def test_path_traversal_name_is_contained(self, client, tmp_path):
        resp = client.post(
            "/upload",
            data={"files": _file("../../evil.pdf")},
            content_type="multipart/form-data",
        )
        assert resp.get_json()["added"] == 1
        # Written as a basename inside LIBRARY_DIR, never escaping it.
        assert (tmp_path / "books" / "evil.pdf").exists()
        assert not (tmp_path.parent / "evil.pdf").exists()
