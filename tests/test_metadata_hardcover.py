# Colophon – e-book metadata manager
"""Tests for the Hardcover metadata source. No network."""
from unittest.mock import MagicMock

import app.services.metadata_hardcover as hc
from app.services.metadata_hardcover import _candidate_from_document, _pick_isbn


_DOC = {
    "title": "A Fire Upon the Deep",
    "author_names": ["Vernor Vinge"],
    "description": "A galaxy-spanning space opera about the Zones of Thought.",
    "series_names": ["Zones of Thought"],
    "genres": ["Science Fiction", "Space Opera"],
    "isbns": ["0812515285", "9780812515282"],
    "release_year": 1992,
    "image": {"url": "https://hardcover.app/covers/fire.jpg", "width": 300, "height": 450},
    "rating": 4.1,
}


def test_pick_isbn_prefers_13():
    assert _pick_isbn(["0812515285", "9780812515282"]) == "9780812515282"
    assert _pick_isbn(["0812515285"]) == "0812515285"
    assert _pick_isbn([]) == ""
    assert _pick_isbn("9780812515282") == "9780812515282"


def test_candidate_parses_all_fields():
    c = _candidate_from_document(_DOC)
    assert c["source"] == "Hardcover"
    assert c["title"] == "A Fire Upon the Deep"
    assert c["author"] == "Vernor Vinge"
    assert c["series"] == "Zones of Thought"
    assert c["series_index"] == ""           # search doc carries no reliable position
    assert c["genres"] == "Science Fiction, Space Opera"
    assert c["isbn"] == "9780812515282"
    assert c["published_date"] == "1992"
    assert c["cover_url"].endswith("fire.jpg")
    assert "series" in c["fields_found"]
    assert "cover" in c["fields_found"]


def test_candidate_requires_title():
    assert _candidate_from_document({"author_names": ["X"]}) is None
    assert _candidate_from_document({}) is None
    assert _candidate_from_document(None) is None


def test_candidate_handles_missing_optionals():
    c = _candidate_from_document({"title": "Lonely Book"})
    assert c["title"] == "Lonely Book"
    assert c["author"] == ""
    assert c["series"] == ""
    assert c["genres"] == ""
    assert c["cover_url"] == ""
    assert c["fields_found"] == ["title"]


def test_search_with_status_ok(monkeypatch):
    import app.services.app_settings as app_settings
    monkeypatch.setattr(app_settings, "get_setting", lambda *a, **k: "")

    class _Resp:
        status_code = 200
        ok = True
        def json(self):
            return {"data": {"search": {"results": {"hits": [{"document": _DOC}]}}}}

    monkeypatch.setattr(hc.requests, "post", lambda *a, **k: _Resp())
    sr = hc.hardcover_search_with_status(title="A Fire Upon the Deep", author="Vernor Vinge")
    assert sr["ok"] is True
    assert sr["status"] == "ok"
    assert sr["source"] == "hardcover"
    assert len(sr["candidates"]) == 1
    assert sr["candidates"][0]["series"] == "Zones of Thought"


def test_query_prefers_title_author_over_isbn(monkeypatch):
    """Hardcover search is keyword-based; a raw ISBN matches nothing."""
    import app.services.app_settings as app_settings
    monkeypatch.setattr(app_settings, "get_setting", lambda *a, **k: "")
    captured = {}

    class _Resp:
        status_code = 200
        ok = True
        def json(self):
            return {"data": {"search": {"results": {"hits": []}}}}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["query"] = json["variables"]["query"]
        return _Resp()

    monkeypatch.setattr(hc.requests, "post", _fake_post)
    hc.hardcover_search_with_status(title="A Fire Upon the Deep", author="Vernor Vinge", isbn="9780575128811")
    assert captured["query"] == "A Fire Upon the Deep Vernor Vinge"


def test_search_with_status_no_hits(monkeypatch):
    import app.services.app_settings as app_settings
    monkeypatch.setattr(app_settings, "get_setting", lambda *a, **k: "")

    class _Resp:
        status_code = 200
        ok = True
        def json(self):
            return {"data": {"search": {"results": {"hits": []}}}}

    monkeypatch.setattr(hc.requests, "post", lambda *a, **k: _Resp())
    sr = hc.hardcover_search_with_status(isbn="9780000000000")
    assert sr["ok"] is False
    assert sr["status"] == "no_result"


def test_search_with_status_rate_limited(monkeypatch):
    import app.services.app_settings as app_settings
    monkeypatch.setattr(app_settings, "get_setting", lambda *a, **k: "")

    class _Resp:
        status_code = 429
        ok = False

    monkeypatch.setattr(hc.requests, "post", lambda *a, **k: _Resp())
    sr = hc.hardcover_search_with_status(title="x")
    assert sr["status"] == "rate_limited"
