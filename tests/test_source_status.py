# Colophon – e-book metadata manager
"""Tests for structured source result functions (Phase 5).

No network, no Calibre install required.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.metadata_calibre import fetch_calibre_metadata_with_status
from app.services.metadata_sources import (
    google_books_search_with_status,
    search_all_sources_with_status,
)

SAMPLE_OPF = """\
<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Great Book</dc:title>
    <dc:creator opf:role="aut">Jane Author</dc:creator>
    <dc:identifier opf:scheme="ISBN">9781234567890</dc:identifier>
  </metadata>
</package>
"""

_RESULT_KEYS = {"source", "ok", "status", "duration_ms", "message", "candidates", "raw_debug"}


# ---------------------------------------------------------------------------
# fetch_calibre_metadata_with_status
# ---------------------------------------------------------------------------

class TestFetchCalibreMetadataWithStatus:
    def test_returns_not_installed_when_missing(self):
        with patch("app.services.metadata_calibre.shutil.which", return_value=None):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert result["ok"] is False
        assert result["status"] == "not_installed"
        assert result["candidates"] == []
        assert _RESULT_KEYS.issubset(result.keys())

    def test_returns_no_result_without_title_and_author(self):
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"):
            result = fetch_calibre_metadata_with_status()
        assert result["status"] == "no_result"

    def test_returns_timeout_on_timeout(self):
        import subprocess
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="fetch-ebook-metadata", timeout=120)):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert result["status"] == "timeout"
        assert result["ok"] is False

    def test_returns_command_error_on_nonzero_returncode(self):
        proc = MagicMock(stdout="", stderr="some error", returncode=1)
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run", return_value=proc):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert result["status"] == "command_error"
        assert result["ok"] is False

    def test_returns_no_result_on_empty_stdout(self):
        proc = MagicMock(stdout="", stderr="", returncode=0)
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run", return_value=proc):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert result["status"] == "no_result"
        assert result["candidates"] == []

    def test_returns_bad_xml_on_invalid_opf(self):
        proc = MagicMock(stdout="<this is not valid xml <<<", stderr="", returncode=0)
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run", return_value=proc):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert result["status"] == "bad_xml"
        assert result["ok"] is False

    def test_returns_ok_with_candidate_on_valid_opf(self):
        proc = MagicMock(stdout=SAMPLE_OPF, stderr="", returncode=0)
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run", return_value=proc):
            result = fetch_calibre_metadata_with_status(title="The Great Book", author="Jane Author")
        assert result["ok"] is True
        assert result["status"] == "ok"
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["title"] == "The Great Book"
        assert result["candidates"][0]["isbn"] == "9781234567890"

    def test_source_label_includes_plugin_name(self):
        proc = MagicMock(
            stdout=SAMPLE_OPF,
            stderr="Source: Goodreads\n",
            returncode=0,
        )
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run", return_value=proc):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert "Goodreads" in result["candidates"][0]["source"]

    def test_duration_ms_is_non_negative_int(self):
        with patch("app.services.metadata_calibre.shutil.which", return_value=None):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0

    def test_raw_debug_present(self):
        proc = MagicMock(stdout="", stderr="err", returncode=1)
        with patch("app.services.metadata_calibre.shutil.which", return_value="/usr/bin/fake"), \
             patch("app.services.metadata_calibre.subprocess.run", return_value=proc):
            result = fetch_calibre_metadata_with_status(title="X", author="Y")
        assert "returncode" in result["raw_debug"]
        assert "stderr_excerpt" in result["raw_debug"]


# ---------------------------------------------------------------------------
# google_books_search_with_status
# ---------------------------------------------------------------------------

class TestGoogleBooksSearchWithStatus:
    def test_returns_ok_when_results_found(self):
        candidates = [{"source": "Google Books API", "title": "Book", "author": "Author",
                       "description": "", "isbn": "", "publisher": "", "language": "",
                       "series": "", "series_index": "", "cover_url": ""}]
        with patch("app.services.metadata_sources.google_books_search", return_value=candidates):
            result = google_books_search_with_status(title="Book", author="Author")
        assert result["ok"] is True
        assert result["status"] == "ok"
        assert result["candidates"] == candidates
        assert _RESULT_KEYS.issubset(result.keys())

    def test_returns_no_result_on_empty_list(self):
        with patch("app.services.metadata_sources.google_books_search", return_value=[]):
            result = google_books_search_with_status(title="Unknown Book")
        assert result["ok"] is False
        assert result["status"] == "no_result"
        assert result["candidates"] == []

    def test_returns_network_error_on_exception(self):
        with patch("app.services.metadata_sources.google_books_search",
                   side_effect=Exception("connection refused")):
            result = google_books_search_with_status(title="Book")
        assert result["ok"] is False
        assert result["status"] == "network_or_plugin_error"

    def test_message_contains_count(self):
        candidates = [
            {"source": "Google Books API", "title": f"Book {i}", "author": "",
             "description": "", "isbn": "", "publisher": "", "language": "",
             "series": "", "series_index": "", "cover_url": ""}
            for i in range(3)
        ]
        with patch("app.services.metadata_sources.google_books_search", return_value=candidates):
            result = google_books_search_with_status(title="Book")
        assert "3" in result["message"]


# ---------------------------------------------------------------------------
# search_all_sources_with_status
# ---------------------------------------------------------------------------

class TestSearchAllSourcesWithStatus:
    def _google_ok(self, n=2):
        return {
            "source": "google_books", "ok": True, "status": "ok",
            "duration_ms": 100, "message": f"Google Books: {n} träffar.",
            "candidates": [
                {"source": "Google Books API", "title": f"Book {i}", "author": "Author",
                 "description": "", "isbn": str(i), "publisher": "", "language": "",
                 "series": "", "series_index": "", "cover_url": ""}
                for i in range(n)
            ],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    def _calibre_fail(self, status="not_installed"):
        return {
            "source": "calibre", "ok": False, "status": status,
            "duration_ms": 0, "message": "Calibre ej tillgängligt.",
            "candidates": [], "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    def test_returns_candidates_and_source_results(self):
        with patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_ok(2)), \
             patch("app.services.metadata_calibre.fetch_calibre_metadata_with_status",
                   return_value=self._calibre_fail()):
            result = search_all_sources_with_status(title="Book", author="Author")

        assert "candidates" in result
        assert "source_results" in result
        assert len(result["source_results"]) == 2

    def test_calibre_failure_does_not_hide_google_results(self):
        with patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_ok(2)), \
             patch("app.services.metadata_calibre.fetch_calibre_metadata_with_status",
                   return_value=self._calibre_fail("timeout")):
            result = search_all_sources_with_status(title="Book", author="Author",
                                                     include_calibre=True)

        # Google candidates must still appear despite Calibre failing
        assert len(result["candidates"]) == 2
        google_sr = next(sr for sr in result["source_results"] if sr["source"] == "google_books")
        calibre_sr = next(sr for sr in result["source_results"] if sr["source"] == "calibre")
        assert google_sr["ok"] is True
        assert calibre_sr["ok"] is False
        assert calibre_sr["status"] == "timeout"

    def test_no_calibre_when_include_calibre_false(self):
        with patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_ok(1)):
            result = search_all_sources_with_status(title="Book", include_calibre=False)

        sources = [sr["source"] for sr in result["source_results"]]
        assert "calibre" not in sources

    def test_empty_candidates_when_all_sources_fail(self):
        google_fail = {**self._google_ok(0), "ok": False, "status": "no_result",
                       "candidates": []}
        with patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=google_fail), \
             patch("app.services.metadata_calibre.fetch_calibre_metadata_with_status",
                   return_value=self._calibre_fail("not_installed")):
            result = search_all_sources_with_status(title="Book", include_calibre=True)

        assert result["candidates"] == []
        assert all(not sr["ok"] for sr in result["source_results"])

    def test_source_results_expose_individual_statuses(self):
        calibre_ok = {
            "source": "calibre", "ok": True, "status": "ok",
            "duration_ms": 800, "message": "Calibre: 1 träff.",
            "candidates": [{"source": "Calibre: Goodreads", "title": "Book", "author": "Author",
                            "description": "", "isbn": "9780000000000", "publisher": "",
                            "language": "", "series": "", "series_index": "", "cover_url": ""}],
            "raw_debug": {"returncode": 0, "stderr_excerpt": "Source: Goodreads"},
        }
        with patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_ok(1)), \
             patch("app.services.metadata_calibre.fetch_calibre_metadata_with_status",
                   return_value=calibre_ok):
            result = search_all_sources_with_status(title="Book", include_calibre=True)

        statuses = {sr["source"]: sr["status"] for sr in result["source_results"]}
        assert statuses["google_books"] == "ok"
        assert statuses["calibre"] == "ok"
        assert len(result["candidates"]) >= 1
