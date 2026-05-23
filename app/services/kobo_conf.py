# Colophon – e-book metadata manager
"""Patch a Kobo eReader.conf for a given Colophon device URL.

The Kobo's ``[OneStoreServices]`` section is the only thing we touch:

  - ``api_endpoint=...`` is replaced with the Colophon URL for this device.
  - ``image_host=``, ``image_url_template=``, ``image_url_quality_template=``
    are deleted if present (stale values from a previous Komga/Calibre-Web
    setup silently override the ones Colophon sends in ``/v1/initialization``,
    which is the #1 cause of "books sync but covers are blank").

Everything else — comments, ordering, unknown keys, other sections — is
preserved byte-for-byte. We never normalise via configparser because some
firmware versions tolerate quirks (duplicate keys, trailing spaces) that
configparser would silently rewrite.
"""
from __future__ import annotations

_LINES_TO_REMOVE_PREFIXES = (
    "image_host=",
    "image_url_template=",
    "image_url_quality_template=",
)

_TARGET_SECTION = "[OneStoreServices]"

# Cap to keep DoS surface small. A real .conf is ~10–30 KB.
MAX_CONF_BYTES = 200_000


class KoboConfError(ValueError):
    """Raised when the uploaded file isn't a parseable Kobo conf."""


def decode_conf(raw: bytes) -> tuple[str, str]:
    """Decode bytes from a Kobo conf upload, returning (text, encoding).

    Kobo firmware writes UTF-8 in practice. Some users may save through an
    editor that re-encodes to UTF-16 (with BOM) or adds a UTF-8 BOM. We
    detect and round-trip the encoding so the written-back file matches
    what the device expects.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as exc:
        raise KoboConfError(f"Could not decode file as UTF-8 or UTF-16: {exc}")


def encode_conf(text: str, encoding: str) -> bytes:
    """Round-trip back to bytes in the same encoding decode_conf detected."""
    if encoding == "utf-16":
        # codecs adds the BOM automatically for utf-16 (vs utf-16-le/be).
        return text.encode("utf-16")
    if encoding == "utf-8-sig":
        return text.encode("utf-8-sig")
    return text.encode("utf-8")


def patch_conf_text(text: str, new_api_endpoint: str) -> str:
    """Apply the Colophon patch and return the modified text.

    Preserves line endings per-line, so a mixed-newline file round-trips
    correctly. If the file is missing an ``api_endpoint`` line inside
    ``[OneStoreServices]``, the new one is appended at the end of that
    section so the device still picks it up.
    """
    if _TARGET_SECTION not in text:
        raise KoboConfError(
            f"This does not look like a Kobo eReader.conf — "
            f"the {_TARGET_SECTION} section is missing."
        )

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_target = False
    api_endpoint_written = False

    for raw_line in lines:
        body = raw_line.rstrip("\r\n").strip()

        # Section transition?
        if body.startswith("[") and body.endswith("]"):
            if in_target and not api_endpoint_written:
                # We're leaving [OneStoreServices] without having seen an
                # api_endpoint line — append one before moving on.
                out.append(f"api_endpoint={new_api_endpoint}{_line_newline(raw_line)}")
                api_endpoint_written = True
            in_target = body == _TARGET_SECTION
            out.append(raw_line)
            continue

        if in_target:
            if body.startswith("api_endpoint="):
                out.append(f"api_endpoint={new_api_endpoint}{_line_newline(raw_line)}")
                api_endpoint_written = True
                continue
            if any(body.startswith(prefix) for prefix in _LINES_TO_REMOVE_PREFIXES):
                # Drop the line entirely.
                continue

        out.append(raw_line)

    # File ended while still inside [OneStoreServices] without an
    # api_endpoint line. Add one.
    if in_target and not api_endpoint_written:
        nl = _line_newline(out[-1]) if out else "\n"
        if not nl:
            nl = "\n"
        # Ensure the previous line ends in a newline so our new line starts
        # on its own.
        if out and not out[-1].endswith(("\n", "\r")):
            out.append(nl)
        out.append(f"api_endpoint={new_api_endpoint}{nl}")

    return "".join(out)


def _line_newline(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""
