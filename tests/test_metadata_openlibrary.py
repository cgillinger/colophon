# Colophon – e-book metadata manager
"""Tests for the Open Library source. No network."""
import app.services.metadata_openlibrary as ol
from app.services.metadata_openlibrary import _pick_isbn, _clean_subjects, _doc_to_candidate


_DOC = {
    "title": "A Fire upon the Deep",
    "author_name": ["Vernor Vinge"],
    "first_publish_year": 1992,
    "publisher": ["Gollancz", "Orion"],
    "subject": ["Fiction", "award:hugo_award=1993", "Science fiction",
                "place:the galaxy", "Aliens", "A ridiculously long over-specific subject tag that should be dropped"],
    "isbn": ["0312851820", "9780765329820"],
    "cover_i": 9261466,
    "key": "/works/OL1975714W",
}


def test_pick_isbn_prefers_13():
    assert _pick_isbn(["0312851820", "9780765329820"]) == "9780765329820"
    assert _pick_isbn(["0312851820"]) == "0312851820"
    assert _pick_isbn([]) == ""


def test_clean_subjects_drops_machine_tags_and_caps():
    cleaned = _clean_subjects(_DOC["subject"])
    assert "Fiction" in cleaned
    assert "Science fiction" in cleaned
    assert "Aliens" in cleaned
    assert "award:hugo_award=1993" not in cleaned   # has : and =
    assert "place:the galaxy" not in cleaned         # has :
    assert all(len(s) <= 40 for s in cleaned)         # long tag dropped


def test_doc_to_candidate(monkeypatch):
    monkeypatch.setattr(ol, "_fetch_description", lambda key: "A synopsis.")
    c = _doc_to_candidate(_DOC, with_description=True)
    assert c["source"] == "Open Library"
    assert c["author"] == "Vernor Vinge"
    assert c["publisher"] == "Gollancz"
    assert c["published_date"] == "1992"
    assert c["isbn"] == "9780765329820"
    assert c["description"] == "A synopsis."
    assert c["cover_url"].endswith("9261466-L.jpg")
    assert "cover" in c["fields_found"]


def test_doc_without_description_skips_fetch(monkeypatch):
    def _boom(key):
        raise AssertionError("should not fetch description for non-top docs")
    monkeypatch.setattr(ol, "_fetch_description", _boom)
    c = _doc_to_candidate(_DOC, with_description=False)
    assert c["description"] == ""


def test_doc_requires_title():
    assert _doc_to_candidate({"author_name": ["X"]}) is None


def test_search_with_status(monkeypatch):
    monkeypatch.setattr(ol, "_fetch_description", lambda key: "desc")

    class _Resp:
        ok = True
        status_code = 200
        def json(self):
            return {"docs": [_DOC]}

    monkeypatch.setattr(ol.requests, "get", lambda *a, **k: _Resp())
    sr = ol.openlibrary_search_with_status(title="A Fire upon the Deep", author="Vernor Vinge")
    assert sr["ok"] is True
    assert sr["source"] == "openlibrary"
    assert sr["candidates"][0]["publisher"] == "Gollancz"


def test_search_isbn_builds_isbn_query(monkeypatch):
    captured = {}

    class _Resp:
        ok = True
        status_code = 200
        def json(self):
            return {"docs": []}

    def _get(url, params=None, headers=None, timeout=None):
        captured["q"] = params["q"]
        return _Resp()

    monkeypatch.setattr(ol.requests, "get", _get)
    ol.openlibrary_search_with_status(title="x", isbn="978-0-7653-2982-0")
    assert captured["q"] == "isbn:9780765329820"
