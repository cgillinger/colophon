# Colophon – e-book metadata manager
"""Best-effort DRM detection for EPUB and MOBI/AZW3 files.

Used to gate the reader's "share book" affordance: we never hand someone a
copy-protected file they couldn't open anyway, and we explain *why* instead of
failing silently. This is a clarity/correctness guard, **not** hard
enforcement — the raw bytes are still served to the owner's own reader at
``/reader/<id>/file``; this just stops the share button from passing along a
useless, locked file.

EPUB is a zip; DRM leaves traces under ``META-INF/``:

  * ``rights.xml``      → Adobe ADEPT (and Barnes & Noble) DRM — unambiguous.
  * ``encryption.xml``  → encrypted resources. BUT this file is *also* the
    standard home of lawful **font obfuscation**, which is not DRM. So we treat
    it as DRM only when an ``EncryptedData`` entry uses an algorithm that isn't
    one of the two known obfuscation schemes (foliate-js de-obfuscates those
    transparently — see ``static/vendor/foliate-js/epub.js``).
"""
import logging
import xml.etree.ElementTree as ET
import zipfile

logger = logging.getLogger(__name__)

# Algorithms in META-INF/encryption.xml that mean *font obfuscation*, not DRM.
# A book using only these is freely readable.
_OBFUSCATION_ALGORITHMS = {
    "http://www.idpf.org/2008/embedding",   # IDPF/EPUB font obfuscation
    "http://ns.adobe.com/pdf/enc#rc",       # Adobe font obfuscation (lower-cased)
}


def _strip_ns(tag):
    """Local element name without its XML namespace ('{ns}Foo' → 'Foo')."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else tag


def epub_has_drm(file_path) -> bool:
    """Return True if this EPUB appears to carry copy-protection (DRM).

    Conservative by construction: anything we can't open or parse as a zip
    returns False (a corrupt/non-zip file isn't "protected" — the reader
    surfaces its own open error for those). The one exception is an
    ``encryption.xml`` that exists but is unreadable/empty, which we treat as
    protected to stay on the safe side.
    """
    try:
        with zipfile.ZipFile(str(file_path)) as zf:
            names = set(zf.namelist())
            # A rights file is an unambiguous DRM marker (ADEPT / B&N).
            if "META-INF/rights.xml" in names:
                return True
            if "META-INF/encryption.xml" not in names:
                return False
            raw = zf.read("META-INF/encryption.xml")
    except (zipfile.BadZipFile, OSError, KeyError):
        return False

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # encryption.xml present but unparseable → assume protected.
        logger.debug("Unparseable encryption.xml in %s; treating as DRM", file_path)
        return True

    found_method = False
    for el in root.iter():
        if _strip_ns(el.tag) != "EncryptionMethod":
            continue
        found_method = True
        algo = (el.get("Algorithm") or "").strip().lower()
        if algo not in _OBFUSCATION_ALGORITHMS:
            # Some other algorithm encrypts real content → DRM.
            return True

    # Only obfuscation algorithms → just fonts, shareable. An encryption.xml
    # with no EncryptionMethod at all is anomalous → treat as protected.
    return not found_method


def mobi_has_drm(file_path) -> bool:
    """Return True if this MOBI/AZW3 carries Mobipocket DRM.

    MOBI and AZW3 are PalmDB containers: a 78-byte header, then an 8-byte
    record-info entry per record, then the record data. Record 0 opens with the
    PalmDOC header, whose 'Encryption Type' field (a big-endian uint16 at offset
    12 of the record) is 0 = none, 1 = old scheme, 2 = Mobipocket DRM. We read
    only those few header bytes — no full parse.

    Conservative like epub_has_drm: anything we can't read as a PalmDB returns
    False (a truncated/corrupt file isn't 'protected' — the reader surfaces its
    own open error for those)."""
    try:
        with open(str(file_path), "rb") as f:
            header = f.read(82)
            if len(header) < 82:
                return False
            num_records = int.from_bytes(header[76:78], "big")
            if num_records < 1:
                return False
            rec0_offset = int.from_bytes(header[78:82], "big")
            f.seek(rec0_offset + 12)
            enc = f.read(2)
            if len(enc) < 2:
                return False
            return int.from_bytes(enc, "big") != 0
    except OSError:
        return False


def file_has_drm(file_path, extension) -> bool:
    """Dispatch DRM detection by format, for the reader's share gate.

    EPUB and MOBI/AZW3 each have their own detector; an unrecognised format
    returns False (we don't block sharing on a format we can't vet — and the
    share button only ever appears for formats the reader can open anyway).
    PDF detection lands with PDF reading."""
    ext = (extension or "").lower()
    if ext == ".epub":
        return epub_has_drm(file_path)
    if ext in (".mobi", ".azw", ".azw3"):
        return mobi_has_drm(file_path)
    return False
