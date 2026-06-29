# Colophon – e-book metadata manager
"""Best-effort DRM detection for EPUB files.

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
