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
    def test_returns_error_when_no_results(self):
        item = _item(title="Book", author="Author")
        with patch("app.services.metadata_pipeline.build_search_input") as mock_si, \
             patch("app.services.metadata_sources.search_all_sources", return_value=[]), \
             patch("app.services.metadata_sources.choose_best_metadata", return_value=(None, 0)):
            mock_si.return_value = {
                "query_text": "Book Author",
                "title": "Book",
                "author": "Author",
                "isbn": "",
                "source": "db_title_author",
                "warnings": [],
            }
            result = run_metadata_enrichment(item)
        assert result["ok"] is False
        assert result["error"]

    def test_returns_ok_with_best_candidate(self):
        item = _item(title="Book", author="Author")
        best_candidate = {
            "source": "Google Books API",
            "title": "Book",
            "author": "Author",
            "description": "A book",
            "isbn": "9781234567890",
            "publisher": "Publisher",
            "language": "en",
            "series": "",
            "series_index": "",
            "cover_url": "",
        }
        with patch("app.services.metadata_pipeline.build_search_input") as mock_si, \
             patch("app.services.metadata_sources.search_all_sources", return_value=[best_candidate]), \
             patch("app.services.metadata_sources.choose_best_metadata", return_value=(best_candidate, 85)):
            mock_si.return_value = {
                "query_text": "Book Author",
                "title": "Book",
                "author": "Author",
                "isbn": "",
                "source": "db_title_author",
                "warnings": [],
            }
            result = run_metadata_enrichment(item)
        assert result["ok"] is True
        assert result["score"] == 85
        assert result["fetched_payload"]["title"] == "Book"
        assert result["sources_used"] == ["Google Books API"]


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
