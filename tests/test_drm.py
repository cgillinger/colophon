# Colophon – e-book metadata manager
"""Tests for best-effort EPUB DRM detection (app/services/drm.py)."""
import zipfile

import pytest

from app.services.drm import epub_has_drm

CONTAINER = (
    '<?xml version="1.0"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)

ENC_HEADER = '<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'


def _encryption_xml(*algorithms):
    body = "".join(
        '<EncryptedData xmlns="http://www.w3.org/2001/04/xmlenc#">'
        f'<EncryptionMethod Algorithm="{algo}"/>'
        "<CipherData><CipherReference URI=\"OEBPS/fonts/x.otf\"/></CipherData>"
        "</EncryptedData>"
        for algo in algorithms
    )
    return ENC_HEADER + body + "</encryption>"


def _make_epub(path, extra=None):
    """Write a minimal EPUB zip; `extra` maps archive names → bytes/str."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", "<package/>")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return str(path)


def test_plain_epub_is_not_drm(tmp_path):
    assert epub_has_drm(_make_epub(tmp_path / "plain.epub")) is False


def test_rights_xml_means_drm(tmp_path):
    path = _make_epub(tmp_path / "adept.epub", {"META-INF/rights.xml": "<rights/>"})
    assert epub_has_drm(path) is True


def test_idpf_font_obfuscation_is_not_drm(tmp_path):
    enc = _encryption_xml("http://www.idpf.org/2008/embedding")
    path = _make_epub(tmp_path / "fonts.epub", {"META-INF/encryption.xml": enc})
    assert epub_has_drm(path) is False


def test_adobe_font_obfuscation_is_not_drm(tmp_path):
    # Adobe's obfuscation algorithm, including a casing variant.
    enc = _encryption_xml("http://ns.adobe.com/pdf/enc#RC")
    path = _make_epub(tmp_path / "adobefonts.epub", {"META-INF/encryption.xml": enc})
    assert epub_has_drm(path) is False


def test_real_content_encryption_is_drm(tmp_path):
    enc = _encryption_xml("http://www.w3.org/2001/04/xmlenc#aes256-cbc")
    path = _make_epub(tmp_path / "encrypted.epub", {"META-INF/encryption.xml": enc})
    assert epub_has_drm(path) is True


def test_mixed_obfuscation_and_encryption_is_drm(tmp_path):
    enc = _encryption_xml(
        "http://www.idpf.org/2008/embedding",
        "http://www.w3.org/2001/04/xmlenc#aes128-cbc",
    )
    path = _make_epub(tmp_path / "mixed.epub", {"META-INF/encryption.xml": enc})
    assert epub_has_drm(path) is True


def test_unparseable_encryption_xml_is_treated_as_drm(tmp_path):
    path = _make_epub(tmp_path / "broken.epub", {"META-INF/encryption.xml": "not xml <<<"})
    assert epub_has_drm(path) is True


def test_encryption_xml_without_method_is_treated_as_drm(tmp_path):
    path = _make_epub(tmp_path / "empty-enc.epub", {"META-INF/encryption.xml": ENC_HEADER + "</encryption>"})
    assert epub_has_drm(path) is True


def test_non_zip_file_is_not_drm(tmp_path):
    p = tmp_path / "notazip.epub"
    p.write_bytes(b"this is not a zip archive")
    assert epub_has_drm(str(p)) is False


def test_missing_file_is_not_drm(tmp_path):
    assert epub_has_drm(str(tmp_path / "does-not-exist.epub")) is False
