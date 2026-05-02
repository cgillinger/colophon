"""Tests for app.services.metadata_calibre — all unit tests, no Calibre required."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.metadata_calibre import (
    CalibreError,
    _parse_opf,
    _read_ebook_meta,
    fetch_calibre_metadata,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_OPF = """\
<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Great Book</dc:title>
    <dc:creator opf:role="aut">Jane Author</dc:creator>
    <dc:description>A compelling description of the book.</dc:description>
    <dc:publisher>Cool Publisher</dc:publisher>
    <dc:language>en</dc:language>
    <dc:date>2022-06-15</dc:date>
    <dc:identifier opf:scheme="ISBN">9781234567890</dc:identifier>
    <dc:subject>Fiction</dc:subject>
    <dc:subject>Thriller</dc:subject>
    <meta name="calibre:series" content="Great Series"/>
    <meta name="calibre:series_index" content="2"/>
  </metadata>
</package>
"""

SAMPLE_EBOOK_META_OUTPUT = """\
Title               : The Great Book
Author(s)           : Jane Author
Publisher           : Cool Publisher
Tags                : Fiction, Thriller
Published           : 2022-06-15
Languages           : en
Identifiers         : isbn:9781234567890
Comments            : A compelling description of the book.
"""


# ---------------------------------------------------------------------------
# _parse_opf tests
# ---------------------------------------------------------------------------

class TestParseOpf:
    def test_title(self):
        assert _parse_opf(SAMPLE_OPF)["title"] == "The Great Book"

    def test_author(self):
        assert _parse_opf(SAMPLE_OPF)["author"] == "Jane Author"

    def test_description(self):
        result = _parse_opf(SAMPLE_OPF)
        assert result["description"] == "A compelling description of the book."

    def test_publisher(self):
        assert _parse_opf(SAMPLE_OPF)["publisher"] == "Cool Publisher"

    def test_language(self):
        assert _parse_opf(SAMPLE_OPF)["language"] == "en"

    def test_date(self):
        assert _parse_opf(SAMPLE_OPF)["date"] == "2022-06-15"

    def test_isbn(self):
        assert _parse_opf(SAMPLE_OPF)["isbn"] == "9781234567890"

    def test_series(self):
        assert _parse_opf(SAMPLE_OPF)["series"] == "Great Series"

    def test_series_index(self):
        assert _parse_opf(SAMPLE_OPF)["series_index"] == "2"

    def test_tags_list(self):
        tags = _parse_opf(SAMPLE_OPF)["tags"]
        assert isinstance(tags, list)
        assert "Fiction" in tags
        assert "Thriller" in tags

    def test_cover_url_missing(self):
        assert _parse_opf(SAMPLE_OPF)["cover_url"] is None

    def test_cover_url_present(self):
        opf = SAMPLE_OPF.replace(
            "</metadata>",
            '  <meta name="cover-url" content="https://example.com/cover.jpg"/>\n  </metadata>',
        )
        assert _parse_opf(opf)["cover_url"] == "https://example.com/cover.jpg"

    def test_missing_metadata_element_returns_empty_dict(self):
        minimal = "<?xml version='1.0'?><package xmlns='http://www.idpf.org/2007/opf'/>"
        result = _parse_opf(minimal)
        assert result["description"] is None
        assert result["tags"] == []

    def test_invalid_xml_raises_calibre_error(self):
        with pytest.raises(CalibreError, match="OPF-XML"):
            _parse_opf("this is not xml <<<")


# ---------------------------------------------------------------------------
# _read_ebook_meta tests
# ---------------------------------------------------------------------------

class TestReadEbookMeta:
    def _run(self, stdout):
        mock_result = MagicMock()
        mock_result.stdout = stdout
        mock_result.returncode = 0
        with patch("app.services.metadata_calibre.subprocess.run", return_value=mock_result):
            return _read_ebook_meta("dummy.epub")

    def test_parses_title(self):
        title, _ = self._run(SAMPLE_EBOOK_META_OUTPUT)
        assert title == "The Great Book"

    def test_parses_author(self):
        _, author = self._run(SAMPLE_EBOOK_META_OUTPUT)
        assert author == "Jane Author"

    def test_missing_fields_return_none(self):
        title, author = self._run("No relevant fields here.\n")
        assert title is None
        assert author is None


# ---------------------------------------------------------------------------
# fetch_calibre_metadata tests
# ---------------------------------------------------------------------------

class TestFetchCalibreMetadata:
    def test_returns_empty_when_calibre_missing(self):
        with patch("app.services.metadata_calibre.shutil.which", return_value=None):
            assert fetch_calibre_metadata(title="X", author="Y") == []

    def test_returns_empty_without_title_and_author(self):
        with patch(
            "app.services.metadata_calibre.shutil.which",
            return_value="/usr/bin/fake",
        ):
            assert fetch_calibre_metadata() == []

    def test_returns_result_dict_in_standard_format(self):
        fetch_result = MagicMock(stdout=SAMPLE_OPF, stderr="", returncode=0)

        with patch(
            "app.services.metadata_calibre.shutil.which",
            return_value="/usr/bin/fake",
        ), patch(
            "app.services.metadata_calibre.subprocess.run",
            return_value=fetch_result,
        ):
            results = fetch_calibre_metadata(title="The Great Book", author="Jane Author")

        assert len(results) == 1
        result = results[0]
        assert result["source"].startswith("Calibre")
        assert result["title"] == "The Great Book"
        assert result["author"] == "Jane Author"
        assert result["description"] == "A compelling description of the book."
        assert result["publisher"] == "Cool Publisher"
        assert result["language"] == "en"
        assert result["isbn"] == "9781234567890"
        assert result["series"] == "Great Series"
        assert result["series_index"] == "2"
        # Standardized schema keys are present:
        for key in [
            "source", "title", "author", "description", "isbn", "publisher",
            "language", "series", "series_index", "cover_url",
        ]:
            assert key in result

    def test_empty_opf_returns_empty_list(self):
        fetch_result = MagicMock(stdout="", stderr="ingen", returncode=1)
        with patch(
            "app.services.metadata_calibre.shutil.which",
            return_value="/usr/bin/fake",
        ), patch(
            "app.services.metadata_calibre.subprocess.run",
            return_value=fetch_result,
        ):
            assert fetch_calibre_metadata(title="X", author="Y") == []

    def test_source_label_includes_plugin_name(self):
        fetch_result = MagicMock(
            stdout=SAMPLE_OPF,
            stderr="Source: Goodreads\nSomething else\nSource: Goodreads\n",
            returncode=0,
        )
        with patch(
            "app.services.metadata_calibre.shutil.which",
            return_value="/usr/bin/fake",
        ), patch(
            "app.services.metadata_calibre.subprocess.run",
            return_value=fetch_result,
        ):
            results = fetch_calibre_metadata(title="X", author="Y")
        assert "Goodreads" in results[0]["source"]
