# Colophon – e-book metadata manager
"""Unit tests for app.services.scanner — no filesystem or DB required."""
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.scanner import (
    _assess_quality,
    _clean_title_from_filename,
    discover_ebook_files,
    extract_local_metadata,
    upsert_library_item,
    EBOOK_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# _clean_title_from_filename
# ---------------------------------------------------------------------------

class TestCleanTitleFromFilename:
    def test_replaces_underscores(self):
        assert _clean_title_from_filename("the_great_book")["title"] == "the great book"

    def test_replaces_hyphens(self):
        assert _clean_title_from_filename("the-great-book")["title"] == "the great book"

    def test_collapses_whitespace(self):
        assert _clean_title_from_filename("book  title")["title"] == "book title"

    def test_empty_string(self):
        result = _clean_title_from_filename("")
        assert result["title"] == ""
        assert result["series"] is None
        assert result["series_index"] is None

    def test_filename_series_pattern(self):
        result = _clean_title_from_filename(
            "The Disappearance03 - Birmingham, John - Angels of Vengeance"
        )
        assert result["title"] == "Angels of Vengeance"
        assert result["series"] == "The Disappearance"
        assert result["series_index"] == "03"

    def test_filename_series_with_space(self):
        result = _clean_title_from_filename(
            "Revelation Space 01 - Reynolds, Alastair - Revelation Space"
        )
        assert result["title"] == "Revelation Space"
        assert result["series"] == "Revelation Space"
        assert result["series_index"] == "01"

    def test_year_only_filename_does_not_match_series_pattern(self):
        result = _clean_title_from_filename("1968")
        assert result["title"] == "1968"
        assert result["series"] is None
        assert result["series_index"] is None


# ---------------------------------------------------------------------------
# _assess_quality
# ---------------------------------------------------------------------------

class TestAssessQuality:
    def test_good_when_title_author_and_rich_field(self):
        meta = {"title": "T", "author": "A", "description": "D"}
        assert _assess_quality(meta) == "good"

    def test_good_when_isbn_instead_of_description(self):
        meta = {"title": "T", "author": "A", "isbn": "9781234567890"}
        assert _assess_quality(meta) == "good"

    def test_partial_when_title_and_author_only(self):
        meta = {"title": "T", "author": "A"}
        assert _assess_quality(meta) == "partial"

    def test_partial_when_title_and_publisher(self):
        meta = {"title": "T", "publisher": "P"}
        assert _assess_quality(meta) == "partial"

    def test_minimal_when_only_title(self):
        meta = {"title": "T"}
        assert _assess_quality(meta) == "minimal"

    def test_minimal_when_empty(self):
        assert _assess_quality({}) == "minimal"


# ---------------------------------------------------------------------------
# discover_ebook_files
# ---------------------------------------------------------------------------

class TestDiscoverEbookFiles:
    def test_returns_list_not_generator(self, tmp_path):
        (tmp_path / "book.epub").touch()
        result = discover_ebook_files(tmp_path)
        assert isinstance(result, list)

    def test_finds_epub(self, tmp_path):
        (tmp_path / "book.epub").touch()
        result = discover_ebook_files(tmp_path)
        assert any(p.name == "book.epub" for p in result)

    def test_finds_mobi_and_azw3(self, tmp_path):
        (tmp_path / "book.mobi").touch()
        (tmp_path / "book.azw3").touch()
        names = {p.name for p in discover_ebook_files(tmp_path)}
        assert "book.mobi" in names
        assert "book.azw3" in names

    def test_ignores_non_ebook_files(self, tmp_path):
        (tmp_path / "readme.txt").touch()
        (tmp_path / "image.jpg").touch()
        result = discover_ebook_files(tmp_path)
        assert result == []

    def test_recurses_into_subdirectories(self, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "book.epub").touch()
        result = discover_ebook_files(tmp_path)
        assert any(p.name == "book.epub" for p in result)

    def test_missing_root_returns_empty_list(self, tmp_path):
        result = discover_ebook_files(tmp_path / "nonexistent")
        assert result == []

    def test_all_supported_extensions_found(self, tmp_path):
        for ext in EBOOK_EXTENSIONS:
            (tmp_path / f"file{ext}").touch()
        result = discover_ebook_files(tmp_path)
        assert len(result) == len(EBOOK_EXTENSIONS)


# ---------------------------------------------------------------------------
# extract_local_metadata
# ---------------------------------------------------------------------------

class TestExtractLocalMetadata:
    def _make_epub_file(self, tmp_path, name="book.epub"):
        p = tmp_path / name
        p.touch()
        return p

    def test_returns_normalized_shape(self, tmp_path):
        epub_path = self._make_epub_file(tmp_path)
        with patch("app.services.scanner.epub.read_epub") as mock_read:
            mock_book = MagicMock()
            mock_book.get_metadata.return_value = []
            mock_book.get_items_of_type.return_value = []
            mock_read.return_value = mock_book

            result = extract_local_metadata(epub_path)

        required_keys = {
            "title", "author", "description", "isbn", "publisher",
            "language", "series", "series_index", "cover_path",
            "source", "quality", "warnings",
        }
        assert required_keys.issubset(result.keys())

    def test_epub_uses_ebooklib_source(self, tmp_path):
        epub_path = self._make_epub_file(tmp_path)
        with patch("app.services.scanner.epub.read_epub") as mock_read:
            mock_book = MagicMock()
            mock_book.get_metadata.side_effect = lambda ns, k: (
                [("My Title", {})] if k == "title" else []
            )
            mock_book.get_items_of_type.return_value = []
            mock_read.return_value = mock_book

            result = extract_local_metadata(epub_path)

        assert result["source"] == "ebooklib"
        assert result["title"] == "My Title"

    def test_filename_fallback_when_no_title(self, tmp_path):
        epub_path = self._make_epub_file(tmp_path, "the_great_book.epub")
        with patch("app.services.scanner.epub.read_epub") as mock_read:
            mock_book = MagicMock()
            mock_book.get_metadata.return_value = []
            mock_book.get_items_of_type.return_value = []
            mock_read.return_value = mock_book

            result = extract_local_metadata(epub_path)

        assert result["title"] == "the great book"
        assert result["source"] == "filename"

    def test_exception_during_read_falls_back_to_filename(self, tmp_path):
        epub_path = self._make_epub_file(tmp_path, "fallback_book.epub")
        with patch("app.services.scanner.epub.read_epub", side_effect=Exception("broken")):
            result = extract_local_metadata(epub_path)

        assert result["title"] == "fallback book"
        assert result["source"] == "filename"
        assert result["warnings"]

    def test_non_epub_extension_uses_filename_source_without_ebook_meta(self, tmp_path):
        pdf_path = tmp_path / "my_book.pdf"
        pdf_path.touch()
        result = extract_local_metadata(pdf_path)
        assert result["title"] == "my book"
        assert result["source"] == "filename"

    def test_quality_field_set(self, tmp_path):
        epub_path = self._make_epub_file(tmp_path)
        with patch("app.services.scanner.epub.read_epub") as mock_read:
            mock_book = MagicMock()
            mock_book.get_metadata.side_effect = lambda ns, k: (
                [("Title", {})] if k == "title" else
                [("Author", {})] if k == "creator" else
                [("Desc", {})] if k == "description" else []
            )
            mock_book.get_items_of_type.return_value = []
            mock_read.return_value = mock_book

            result = extract_local_metadata(epub_path)

        assert result["quality"] == "good"


# ---------------------------------------------------------------------------
# upsert_library_item
# ---------------------------------------------------------------------------

class TestUpsertLibraryItem:
    def _meta(self, **kwargs):
        base = {
            "title": "Test Book", "author": "Test Author",
            "description": "Desc", "isbn": "9781234567890",
            "publisher": "Pub", "language": "en",
            "series": "", "series_index": "", "cover_path": None,
            "source": "ebooklib", "quality": "good", "warnings": [],
        }
        base.update(kwargs)
        return base

    def test_creates_new_item_when_no_existing(self, tmp_path):
        epub_path = tmp_path / "book.epub"
        epub_path.write_bytes(b"fake")

        mock_session = MagicMock()
        result = upsert_library_item(epub_path, self._meta(), db_session=mock_session)

        mock_session.add.assert_called_once_with(result)
        assert result.title == "Test Book"
        assert result.file_mtime is not None
        assert result.metadata_read_at is not None

    def test_updates_existing_item(self, tmp_path):
        epub_path = tmp_path / "book.epub"
        epub_path.write_bytes(b"fake")

        existing = MagicMock()
        existing.manual_metadata = False
        existing.cover_locked = False

        result = upsert_library_item(epub_path, self._meta(), existing=existing)

        assert result is existing
        assert existing.title == "Test Book"
        assert existing.file_mtime is not None

    def test_does_not_overwrite_manual_metadata(self, tmp_path):
        epub_path = tmp_path / "book.epub"
        epub_path.write_bytes(b"fake")

        existing = MagicMock()
        existing.manual_metadata = True
        existing.title = "Original Title"
        existing.cover_locked = False

        upsert_library_item(epub_path, self._meta(title="New Title"), existing=existing)

        # title should NOT be updated when manual_metadata is True
        assert existing.title == "Original Title"

    def test_does_not_overwrite_cover_when_locked(self, tmp_path):
        epub_path = tmp_path / "book.epub"
        epub_path.write_bytes(b"fake")

        existing = MagicMock()
        existing.manual_metadata = False
        existing.cover_locked = True
        existing.cover_path = "/original/cover.jpg"

        upsert_library_item(epub_path, self._meta(cover_path="/new/cover.jpg"), existing=existing)

        assert existing.cover_path == "/original/cover.jpg"

    def test_cover_updated_when_not_locked(self, tmp_path):
        epub_path = tmp_path / "book.epub"
        epub_path.write_bytes(b"fake")

        existing = MagicMock()
        existing.manual_metadata = False
        existing.cover_locked = False

        upsert_library_item(epub_path, self._meta(cover_path="/new/cover.jpg"), existing=existing)

        assert existing.cover_path == "/new/cover.jpg"
