"""Unit tests for app.services.metadata_pipeline — no network, no DB required."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.metadata_pipeline import (
    build_search_input,
    run_metadata_enrichment,
    apply_enrichment_result,
    _build_validation_warning,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(**kwargs):
    item = MagicMock()
    item.id = kwargs.get("id", 1)
    item.isbn = kwargs.get("isbn", "")
    item.title = kwargs.get("title", "")
    item.author = kwargs.get("author", "")
    item.file_path = kwargs.get("file_path", "/books/test.epub")
    return item


# ---------------------------------------------------------------------------
# build_search_input
# ---------------------------------------------------------------------------

class TestBuildSearchInput:
    def test_file_isbn_takes_priority(self):
        item = _item(isbn="1111111111", title="DB Title", author="DB Author")
        local = {"isbn": "9999999999", "title": "File Title", "author": "File Author"}
        result = build_search_input(item, local)
        assert result["isbn"] == "9999999999"
        assert result["source"] == "file_isbn"
        assert result["query_text"] == "9999999999"

    def test_db_isbn_used_when_no_file_isbn(self):
        item = _item(isbn="1234567890", title="Book", author="Author")
        result = build_search_input(item)
        assert result["isbn"] == "1234567890"
        assert result["source"] == "db_isbn"

    def test_file_title_author_used_when_no_isbn(self):
        item = _item(title="DB Title", author="DB Author")
        local = {"isbn": "", "title": "File Title", "author": "File Author"}
        result = build_search_input(item, local)
        assert result["title"] == "File Title"
        assert result["source"] == "file_title_author"

    def test_db_title_author_fallback(self):
        item = _item(title="Book Title", author="Writer")
        result = build_search_input(item)
        assert result["title"] == "Book Title"
        assert result["source"] == "db_title_author"

    def test_filename_fallback(self):
        item = _item(file_path="/books/some_book.epub")
        result = build_search_input(item)
        assert result["source"] == "filename"
        assert result["query_text"] == "some_book"
        assert result["warnings"]

    def test_no_file_path_fallback(self):
        item = _item(file_path="")
        result = build_search_input(item)
        assert result["source"] == "filename"
        assert result["query_text"] == ""


# ---------------------------------------------------------------------------
# _build_validation_warning
# ---------------------------------------------------------------------------

class TestBuildValidationWarning:
    def test_no_warning_when_titles_match(self):
        item = _item(title="Great Book", author="Some Author")
        fetched = {"title": "Great Book", "author": "Some Author"}
        assert _build_validation_warning(item, fetched) is None

    def test_warning_when_both_title_and_author_diverge(self):
        item = _item(title="Great Book", author="Jane Writer")
        fetched = {"title": "Completely Different", "author": "John Other"}
        warning = _build_validation_warning(item, fetched)
        assert warning is not None
        assert "avvika" in warning

    def test_no_warning_when_item_has_no_existing_title(self):
        item = _item(title="", author="")
        fetched = {"title": "New Title", "author": "New Author"}
        assert _build_validation_warning(item, fetched) is None


# ---------------------------------------------------------------------------
# run_metadata_enrichment
# ---------------------------------------------------------------------------

class TestRunMetadataEnrichment:
    def _google_outcome(self, candidates):
        """Return a google_books_search_with_status()-compatible per-source dict."""
        return {
            "source": "google_books",
            "ok": bool(candidates),
            "status": "ok" if candidates else "no_result",
            "duration_ms": 10,
            "message": "",
            "candidates": list(candidates),
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    def _scoring(self, best, score, classification="review_needed"):
        """Return a choose_best_metadata_explained()-compatible dict."""
        return {
            "best": best, "score": score,
            "signals": {"isbn_exact_match": False, "title_similarity": 0.9,
                        "author_similarity": 0.9, "has_description": True, "has_cover": False},
            "warnings": [], "classification": classification,
            "all_scored": [{"candidate": best, "score": score, "signals": {},
                            "warnings": [], "classification": classification}] if best else [],
        }

    def test_returns_error_when_no_results(self):
        item = _item(title="Book", author="Author")
        with patch("app.services.metadata_pipeline.build_search_input") as mock_si, \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([])), \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(None, 0, "no_match")):
            mock_si.return_value = {
                "query_text": "Book Author", "title": "Book", "author": "Author",
                "isbn": "", "source": "db_title_author", "warnings": [],
            }
            result = run_metadata_enrichment(item, include_calibre=False)
        assert result["ok"] is False
        assert result["error"]
        assert "source_results" in result
        assert "signals" in result
        assert "classification" in result

    def test_returns_ok_with_best_candidate(self):
        item = _item(title="Book", author="Author")
        best_candidate = {
            "source": "Google Books API", "title": "Book", "author": "Author",
            "description": "A book", "isbn": "9781234567890", "publisher": "Publisher",
            "language": "en", "series": "", "series_index": "", "cover_url": "",
        }
        with patch("app.services.metadata_pipeline.build_search_input") as mock_si, \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([best_candidate])), \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(best_candidate, 85)):
            mock_si.return_value = {
                "query_text": "Book Author", "title": "Book", "author": "Author",
                "isbn": "", "source": "db_title_author", "warnings": [],
            }
            result = run_metadata_enrichment(item, include_calibre=False)
        assert result["ok"] is True
        assert result["score"] == 85
        assert result["fetched_payload"]["title"] == "Book"
        assert result["sources_used"] == ["Google Books API"]
        assert "source_results" in result
        assert "signals" in result
        assert "classification" in result
        assert "all_scored" in result

    def test_result_includes_search_input_and_local_metadata(self):
        item = _item(title="Book", author="Author")
        best_candidate = {
            "source": "Google Books API", "title": "Book", "author": "Author",
            "description": "", "isbn": "", "publisher": "", "language": "",
            "series": "", "series_index": "", "cover_url": "",
        }
        file_meta = {"isbn": "9780000000001", "title": "Book", "author": "Author",
                     "source": "ebooklib", "quality": "good", "warnings": []}
        with patch("app.services.metadata_pipeline.scan_file_local", return_value=file_meta), \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([best_candidate])), \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(best_candidate, 80)):
            result = run_metadata_enrichment(item, include_calibre=False)
        assert "search_input" in result
        assert "local_metadata" in result
        assert result["local_metadata"] is file_meta

    def test_auto_reads_file_metadata_when_not_supplied(self):
        """File metadata is read automatically and used by build_search_input."""
        item = _item(isbn="", title="Bad Filename Title", author="",
                     file_path="/books/some_file.epub")
        file_meta = {"isbn": "9781234567890", "title": "Real Title", "author": "Real Author",
                     "source": "ebooklib", "quality": "good", "warnings": []}
        best_candidate = {
            "source": "Google Books API", "title": "Real Title", "author": "Real Author",
            "description": "A real book", "isbn": "9781234567890", "publisher": "",
            "language": "", "series": "", "series_index": "", "cover_url": "",
        }
        captured = {}
        real_build = __import__(
            "app.services.metadata_pipeline", fromlist=["build_search_input"]
        ).build_search_input

        def capturing_build(item, local_metadata=None):
            captured["local_metadata"] = local_metadata
            return real_build(item, local_metadata)

        with patch("app.services.metadata_pipeline.scan_file_local", return_value=file_meta), \
             patch("app.services.metadata_pipeline.build_search_input", side_effect=capturing_build), \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([best_candidate])), \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(best_candidate, 91)):
            run_metadata_enrichment(item, include_calibre=False)

        assert captured["local_metadata"] is file_meta

    def test_file_isbn_used_over_weak_db_title(self):
        """When file has ISBN and DB only has a poor title, search uses file ISBN."""
        item = _item(isbn="", title="untitled_book_2", author="")
        file_meta = {"isbn": "9789876543210", "title": "", "author": "",
                     "source": "ebooklib", "quality": "partial", "warnings": []}
        best_candidate = {
            "source": "Calibre", "title": "Real Book", "author": "Real Author",
            "description": "", "isbn": "9789876543210", "publisher": "",
            "language": "", "series": "", "series_index": "", "cover_url": "",
        }
        with patch("app.services.metadata_pipeline.scan_file_local", return_value=file_meta), \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([best_candidate])) as mock_google, \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(best_candidate, 80)):
            run_metadata_enrichment(item, include_calibre=False)

        call_kwargs = mock_google.call_args.kwargs
        assert call_kwargs.get("isbn") == "9789876543210"
        assert call_kwargs.get("query_text") == "9789876543210"

    def test_scan_file_local_failure_falls_back_to_db(self):
        """If file reading fails, build_search_input falls back to DB data."""
        item = _item(title="DB Title", author="DB Author", isbn="")
        best_candidate = {
            "source": "Google Books API", "title": "DB Title", "author": "DB Author",
            "description": "", "isbn": "", "publisher": "", "language": "",
            "series": "", "series_index": "", "cover_url": "",
        }
        with patch("app.services.metadata_pipeline.scan_file_local",
                   side_effect=Exception("file not found")), \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([best_candidate])) as mock_google, \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(best_candidate, 70)):
            result = run_metadata_enrichment(item, include_calibre=False)

        assert result["ok"] is True
        assert result["local_metadata"] is None
        call_kwargs = mock_google.call_args.kwargs
        assert call_kwargs.get("title") == "DB Title"

    def test_explicit_local_metadata_not_overridden(self):
        """Caller-supplied local_metadata must not be replaced by auto-read."""
        item = _item(title="Book", author="Author")
        explicit_meta = {"isbn": "0000000001", "title": "Explicit", "author": "Explicit",
                         "source": "ebooklib", "quality": "good", "warnings": []}
        best_candidate = {
            "source": "Google Books API", "title": "Book", "author": "Author",
            "description": "", "isbn": "", "publisher": "", "language": "",
            "series": "", "series_index": "", "cover_url": "",
        }
        with patch("app.services.metadata_pipeline.scan_file_local") as mock_scan, \
             patch("app.services.metadata_sources.google_books_search_with_status",
                   return_value=self._google_outcome([best_candidate])), \
             patch("app.services.metadata_sources.choose_best_metadata_explained",
                   return_value=self._scoring(best_candidate, 70)):
            run_metadata_enrichment(item, local_metadata=explicit_meta, include_calibre=False)

        mock_scan.assert_not_called()


# ---------------------------------------------------------------------------
# apply_enrichment_result
# ---------------------------------------------------------------------------

class TestApplyEnrichmentResult:
    def test_delegates_to_writer(self):
        item = _item()
        fetched = {"title": "Book", "author": "Author", "cover_path": None}
        expected = {"db_updated": 1, "file_updated": False, "cover_saved": False, "cover_attempted": False}

        with patch("app.services.metadata_writer.apply_metadata_to_item", return_value=expected) as mock_apply:
            result = apply_enrichment_result(
                item=item,
                fetched=fetched,
                selected_fields={"title"},
                cover_dir="/covers",
            )

        assert result == expected
        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args.kwargs
        assert call_kwargs["selected_fields"] == {"title"}
        assert call_kwargs["write_to_file"] is True
