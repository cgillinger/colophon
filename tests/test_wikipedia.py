# Colophon – e-book metadata manager
"""Tests for the Wikipedia metadata provider.

No real network: requests.get is mocked at module scope.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.metadata_wikipedia import (
    search_wikipedia,
    search_wikipedia_with_status,
)


_RESULT_KEYS = {"source", "ok", "status", "duration_ms", "message", "candidates", "raw_debug"}


def _summary_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


SAMPLE_SUMMARY = {
    "type": "standard",
    "title": "Dune (novel)",
    "lang": "en",
    "extract": "Dune is a 1965 epic science fiction novel by American author Frank Herbert.",
    "thumbnail": {
        "source": "https://upload.wikimedia.org/.../Dune-Frontcover.jpg",
    },
    "wikibase_item": "Q43545",
    "content_urls": {
        "desktop": {"page": "https://en.wikipedia.org/wiki/Dune_(novel)"},
    },
}


# ---------------------------------------------------------------------------
# search_wikipedia
# ---------------------------------------------------------------------------

class TestSearchWikipedia:
    def test_returns_candidate_on_200(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response(SAMPLE_SUMMARY),
        ):
            candidates = search_wikipedia(title="Dune", lang="en")
        assert len(candidates) == 1
        c = candidates[0]
        assert c["source"] == "Wikipedia"
        assert c["title"] == "Dune (novel)"
        assert "Frank Herbert" in c["description"]
        assert c["cover_url"].startswith("https://")
        assert c["wikidata_id"] == "Q43545"
        assert "description" in c["fields_found"]
        assert "cover" in c["fields_found"]
        assert "wikidata_id" in c["fields_found"]

    def test_empty_title_returns_empty(self):
        candidates = search_wikipedia(title="   ")
        assert candidates == []

    def test_404_then_novel_suffix_succeeds(self):
        responses = [
            _summary_response({}, status_code=404),
            _summary_response(SAMPLE_SUMMARY, status_code=200),
        ]
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            side_effect=responses,
        ) as fetch:
            candidates = search_wikipedia(title="Dune")
        assert len(candidates) == 1
        # Second call should use the "(novel)" slug.
        assert fetch.call_count == 2
        second_args = fetch.call_args_list[1].args
        assert second_args[0].endswith("_(novel)")

    def test_404_on_both_returns_empty(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response({}, status_code=404),
        ):
            candidates = search_wikipedia(title="Nonexistent Book Title 12345")
        assert candidates == []

    def test_disambiguation_returns_empty(self):
        data = dict(SAMPLE_SUMMARY, type="disambiguation")
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response(data),
        ):
            candidates = search_wikipedia(title="Dune")
        assert candidates == []

    def test_non_200_non_404_returns_empty(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response({}, status_code=500),
        ):
            candidates = search_wikipedia(title="Dune")
        assert candidates == []

    def test_slug_replaces_spaces(self):
        captured = {}

        def fake_fetch(slug, lang):
            captured["slug"] = slug
            return _summary_response(SAMPLE_SUMMARY)

        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            side_effect=fake_fetch,
        ):
            search_wikipedia(title="The Left Hand of Darkness")
        assert captured["slug"] == "The_Left_Hand_of_Darkness"

    def test_request_exception_propagates(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            side_effect=requests.ConnectionError("boom"),
        ):
            with pytest.raises(requests.ConnectionError):
                search_wikipedia(title="Dune")

    def test_missing_thumbnail_field(self):
        data = dict(SAMPLE_SUMMARY)
        data.pop("thumbnail")
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response(data),
        ):
            candidates = search_wikipedia(title="Dune")
        assert len(candidates) == 1
        assert candidates[0]["cover_url"] == ""
        assert "cover" not in candidates[0]["fields_found"]


# ---------------------------------------------------------------------------
# search_wikipedia_with_status
# ---------------------------------------------------------------------------

class TestSearchWikipediaWithStatus:
    def test_returns_ok_when_results_found(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response(SAMPLE_SUMMARY),
        ):
            result = search_wikipedia_with_status(title="Dune")
        assert result["ok"] is True
        assert result["status"] == "ok"
        assert len(result["candidates"]) == 1
        assert _RESULT_KEYS.issubset(result.keys())
        assert result["source"] == "wikipedia"

    def test_returns_no_result_on_empty_title(self):
        result = search_wikipedia_with_status(title="")
        assert result["ok"] is False
        assert result["status"] == "no_result"
        assert result["candidates"] == []

    def test_returns_no_result_on_404(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response({}, status_code=404),
        ):
            result = search_wikipedia_with_status(title="No Such Book Title")
        assert result["ok"] is False
        assert result["status"] == "no_result"

    def test_returns_network_error_on_request_exception(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            result = search_wikipedia_with_status(title="Dune")
        assert result["ok"] is False
        assert result["status"] == "network_or_plugin_error"

    def test_includes_duration(self):
        with patch(
            "app.services.metadata_wikipedia._fetch_summary",
            return_value=_summary_response(SAMPLE_SUMMARY),
        ):
            result = search_wikipedia_with_status(title="Dune")
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0
