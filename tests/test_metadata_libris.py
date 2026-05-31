# Colophon – e-book metadata manager
"""Tests for the LIBRIS (Swedish national bibliography) source. No network."""
import app.services.metadata_libris as lb
from app.services.metadata_libris import (
    _reformat_creator, _clean_publisher, _clean_date, _clean_title, _record_to_candidate,
)


def test_reformat_creator():
    assert _reformat_creator("Tamas, Gellert, 1963-") == "Gellert Tamas"
    assert _reformat_creator("Moberg, Åsa, 1947-") == "Åsa Moberg"
    assert _reformat_creator(["Snickars, Pelle"]) == "Pelle Snickars"
    assert _reformat_creator("") == ""


def test_clean_publisher():
    assert _clean_publisher(["Stockholm : Natur & kultur", "Lettland"]) == "Natur & kultur"
    assert _clean_publisher(["Mondial"]) == "Mondial"
    assert _clean_publisher([]) == ""


def test_clean_date():
    assert _clean_date("2016") == "2016"
    assert _clean_date(["2017", "[2017-02-02]"]) == "2017"
    assert _clean_date("nnnn") == ""
    assert _clean_date("") == ""


def test_clean_title_strips_resource_marker():
    assert _clean_title("Det svenska hatet [Elektronisk resurs] en berättelse") == "Det svenska hatet en berättelse"


def test_record_to_candidate():
    rec = {
        "title": "Det svenska hatet : en berättelse om vår tid",
        "creator": "Tamas, Gellert, 1963-",
        "isbn": "9789127148963",
        "publisher": ["Stockholm : Natur & kultur", "Lettland"],
        "date": "2016",
        "language": "swe",
        "subject": ["Sverige", "rasism"],
    }
    c = _record_to_candidate(rec)
    assert c["source"] == "LIBRIS"
    assert c["author"] == "Gellert Tamas"
    assert c["publisher"] == "Natur & kultur"
    assert c["language"] == "sv"
    assert c["isbn"] == "9789127148963"
    assert c["published_date"] == "2016"
    assert c["genres"] == "Sverige, rasism"
    assert c["description"] == ""        # catalogue noise is intentionally dropped
    assert c["series"] == ""
    assert "publisher" in c["fields_found"]


def test_record_requires_title():
    assert _record_to_candidate({"creator": "X"}) is None


def test_marc_language_unknown_blank():
    c = _record_to_candidate({"title": "T", "language": "zxx"})
    assert c["language"] == ""


def test_search_with_status(monkeypatch):
    class _Resp:
        ok = True
        status_code = 200
        def json(self):
            return {"xsearch": {"list": [{
                "title": "Den svenska enhörningen : storyn om Spotify",
                "creator": "Fleischer, Rasmus",
                "isbn": "9789188671257",
                "publisher": ["Stockholm : Mondial"],
                "date": "2018", "language": "swe",
            }]}}

    monkeypatch.setattr(lb.requests, "get", lambda *a, **k: _Resp())
    sr = lb.libris_search_with_status(title="Den svenska enhörningen", author="Pelle Snickars")
    assert sr["ok"] is True
    assert sr["source"] == "libris"
    assert sr["candidates"][0]["publisher"] == "Mondial"


def test_search_isbn_builds_isbn_query(monkeypatch):
    captured = {}

    class _Resp:
        ok = True
        status_code = 200
        def json(self):
            return {"xsearch": {"list": []}}

    def _get(url, params=None, headers=None, timeout=None):
        captured["query"] = params["query"]
        return _Resp()

    monkeypatch.setattr(lb.requests, "get", _get)
    lb.libris_search_with_status(title="x", author="y", isbn="978-91-27-14896-3")
    assert captured["query"] == "isbn:(9789127148963)"
