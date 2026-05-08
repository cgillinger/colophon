import logging
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_DC = "http://purl.org/dc/elements/1.1/"
_OPF = "http://www.idpf.org/2007/opf"


class CalibreError(Exception):
    pass


def _parse_opf(xml_string: str) -> dict:
    """Parse OPF XML from fetch-ebook-metadata --opf output."""
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as exc:
        raise CalibreError(f"Kunde inte tolka OPF-XML: {exc}") from exc

    meta = (
        root.find(f"{{{_OPF}}}metadata")
        or root.find("metadata")
    )
    if meta is None:
        return {
            "title": None, "author": None, "description": None,
            "publisher": None, "language": None, "date": None,
            "isbn": None, "series": None, "series_index": None,
            "tags": [], "cover_url": None,
        }

    def _dc(tag):
        el = meta.find(f"{{{_DC}}}{tag}")
        return (el.text or "").strip() or None if el is not None else None

    def _meta_attr(name):
        for el in meta:
            if el.get("name") == name:
                return (el.get("content") or "").strip() or None
        return None

    creators = []
    for el in meta.findall(f"{{{_DC}}}creator"):
        text = (el.text or "").strip()
        if text:
            creators.append(text)
    author = ", ".join(creators) if creators else None

    isbn = None
    for el in meta.findall(f"{{{_DC}}}identifier"):
        scheme = (
            el.get(f"{{{_OPF}}}scheme", "")
            or el.get("scheme", "")
        )
        if "isbn" in scheme.lower():
            isbn = (el.text or "").strip() or None
            break

    tags = []
    for el in meta.findall(f"{{{_DC}}}subject"):
        t = (el.text or "").strip()
        if t:
            tags.append(t)

    cover_url = _meta_attr("cover-url") or _meta_attr("cover_url")
    if not cover_url:
        guide = root.find(f"{{{_OPF}}}guide") or root.find("guide")
        if guide is not None:
            for ref in guide:
                if ref.get("type") == "cover":
                    href = ref.get("href", "")
                    if href.startswith("http"):
                        cover_url = href
                        break

    return {
        "title": _dc("title"),
        "author": author,
        "description": _dc("description"),
        "publisher": _dc("publisher"),
        "language": _dc("language"),
        "date": _dc("date"),
        "isbn": isbn,
        "series": _meta_attr("calibre:series"),
        "series_index": _meta_attr("calibre:series_index"),
        "tags": tags,
        "cover_url": cover_url,
    }


def _read_ebook_meta(file_path) -> tuple[str | None, str | None]:
    """Return (title, author) read via ebook-meta."""
    result = subprocess.run(
        ["ebook-meta", str(file_path)],
        capture_output=True,
        text=True,
    )
    title = None
    author = None
    for line in result.stdout.splitlines():
        if line.startswith("Title") and ":" in line:
            title = line.split(":", 1)[1].strip() or None
        elif line.startswith("Author(s)") and ":" in line:
            author = line.split(":", 1)[1].strip() or None
    return title, author


def read_all_ebook_meta_fields(file_path) -> dict[str, str]:
    """Read all metadata fields from ebook-meta output."""
    try:
        result = subprocess.run(
            ["ebook-meta", str(file_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        logger.debug("ebook-meta inte funnet i PATH")
        return {}
    except subprocess.TimeoutExpired:
        logger.warning("ebook-meta timeout för %s", file_path)
        return {}
    fields: dict[str, str] = {}
    current_key: str | None = None
    current_parts: list[str] = []

    for line in result.stdout.splitlines():
        if line and not line[0].isspace() and ":" in line:
            if current_key is not None:
                fields[current_key] = " ".join(current_parts).strip()
            key, _, value = line.partition(":")
            current_key = key.strip().lower()
            current_parts = [value.strip()]
        elif current_key is not None and line.startswith(" "):
            current_parts.append(line.strip())

    if current_key is not None:
        fields[current_key] = " ".join(current_parts).strip()

    return fields


def _parse_calibre_sources(stderr: str) -> list[str]:
    """Extract plugin names from Calibre verbose stderr output (three-method fallback)."""
    sources_used: list[str] = []
    lines = stderr.splitlines()

    # Method 1: verbose plugin section headers  ****** PluginName (version) ******
    plugin_pattern = re.compile(r'\*{6,}\s+(.+?)\s+\(\d+.*?\)\s+\*{6,}')
    found_pattern = re.compile(r'Found\s+(\d+)\s+results?', re.IGNORECASE)
    for i, line in enumerate(lines):
        match = plugin_pattern.search(line)
        if match:
            plugin_name = match.group(1).strip()
            found_count = 0
            for j in range(i + 1, min(i + 5, len(lines))):
                found_match = found_pattern.search(lines[j])
                if found_match:
                    found_count = int(found_match.group(1))
                    break
            if found_count > 0 and plugin_name not in sources_used:
                sources_used.append(plugin_name)

    if sources_used:
        return sources_used

    # Method 2: "Using plugins:" line
    for line in lines:
        if line.strip().lower().startswith("using plugins:"):
            plugins_str = line.split(":", 1)[1].strip()
            for part in plugins_str.split("),"):
                name = part.split("(")[0].strip().rstrip(",").strip()
                if name:
                    sources_used.append(name)
            break

    if sources_used:
        return sources_used

    # Method 3: legacy "source:" lines
    for line in lines:
        s = line.strip()
        if s.lower().startswith("source:"):
            src = s.split(":", 1)[1].strip()
            if src and src not in sources_used:
                sources_used.append(src)

    return sources_used


def fetch_calibre_metadata_with_status(
    title: str = "",
    author: str = "",
    sources: str = "all",
) -> dict:
    """Fetch metadata via Calibre and return a structured source result.

    Unlike fetch_calibre_metadata(), this function never collapses distinct
    failure modes into an empty list.  The returned dict always contains:
        source         "calibre"
        ok             bool
        status         one of: ok | no_result | not_installed | timeout |
                               bad_xml | command_error | network_or_plugin_error
        duration_ms    int
        message        str   — human-readable summary
        candidates     list[dict]
        raw_debug      {returncode, stderr_excerpt}
    """
    t0 = time.monotonic()

    def _result(ok, status, message, candidates=None, returncode=None, stderr=""):
        return {
            "source": "calibre",
            "ok": ok,
            "status": status,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": message,
            "candidates": candidates or [],
            "raw_debug": {
                "returncode": returncode,
                "stderr_excerpt": (stderr or "")[:500],
            },
        }

    if not shutil.which("fetch-ebook-metadata"):
        return _result(False, "not_installed", "fetch-ebook-metadata är inte installerat.")

    title = (title or "").strip()
    author = (author or "").strip()

    if not title and not author:
        return _result(False, "no_result", "Ingen söktitel eller -författare angiven.")

    cmd = ["fetch-ebook-metadata", "--opf", "--verbose"]
    if title:
        cmd += ["--title", title]
    if author:
        cmd += ["--authors", author]
    if sources and sources != "all":
        cmd += ["--allowed-plugin", sources]

    logger.debug("Kör: %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return _result(False, "timeout", "Calibre tog för lång tid (>120 sekunder).")
    except Exception as exc:
        return _result(False, "command_error", f"Calibre-kommandot misslyckades: {exc}")

    stderr = proc.stderr or ""
    opf_xml = (proc.stdout or "").strip()

    if proc.returncode != 0 and not opf_xml:
        return _result(
            False, "command_error",
            f"fetch-ebook-metadata returnerade kod {proc.returncode}.",
            returncode=proc.returncode, stderr=stderr,
        )

    if not opf_xml or not opf_xml.startswith("<"):
        return _result(
            False, "no_result",
            "Calibre hittade inga matchande böcker.",
            returncode=proc.returncode, stderr=stderr,
        )

    try:
        parsed = _parse_opf(opf_xml)
    except CalibreError as exc:
        return _result(
            False, "bad_xml",
            f"Calibre returnerade ogiltig XML: {exc}",
            returncode=proc.returncode, stderr=stderr,
        )

    sources_used: list[str] = _parse_calibre_sources(stderr)

    source_label = f"Calibre: {', '.join(sources_used)}" if sources_used else "Calibre"
    series_index = parsed.get("series_index")

    tags = parsed.get("tags") or []
    genres = ", ".join(t for t in tags if t) if isinstance(tags, list) else str(tags)

    pubdate = (parsed.get("date") or "").strip()[:10]

    candidate = {
        "source": source_label,
        "title": parsed.get("title") or title or "",
        "author": parsed.get("author") or author or "",
        "description": parsed.get("description") or "",
        "isbn": parsed.get("isbn") or "",
        "publisher": parsed.get("publisher") or "",
        "language": parsed.get("language") or "",
        "series": parsed.get("series") or "",
        "series_index": str(series_index) if series_index else "",
        "cover_url": parsed.get("cover_url") or "",
        "genres": genres,
        "published_date": pubdate,
    }

    fields_found = []
    if parsed.get("title"): fields_found.append("title")
    if parsed.get("author"): fields_found.append("author")
    if parsed.get("description"): fields_found.append("description")
    if parsed.get("isbn"): fields_found.append("isbn")
    if parsed.get("publisher"): fields_found.append("publisher")
    if parsed.get("series"): fields_found.append("series")
    if genres: fields_found.append("genres")
    if parsed.get("cover_url"): fields_found.append("cover")
    if pubdate: fields_found.append("published_date")
    candidate["fields_found"] = fields_found
    candidate["plugins_used"] = list(sources_used)

    return _result(
        True, "ok",
        f"Calibre: 1 träff ({source_label}).",
        candidates=[candidate],
        returncode=proc.returncode, stderr=stderr,
    )


def list_available_sources() -> list[str]:
    """Return metadata source names reported by fetch-ebook-metadata."""
    try:
        result = subprocess.run(
            ["fetch-ebook-metadata", "--help"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    output = result.stdout + result.stderr
    for line in output.splitlines():
        if "all plugin names" in line.lower():
            _, _, names_part = line.partition(":")
            return [n.strip() for n in names_part.split(",") if n.strip()]
    return []


def fetch_calibre_metadata(
    title: str = "",
    author: str = "",
    sources: str = "all",
) -> list[dict]:
    """Fetch metadata via Calibre's fetch-ebook-metadata CLI.

    Returns a list with one result-dict (or empty list on failure or if
    Calibre is not installed). The returned dict matches the standard format
    used by all metadata sources.
    """
    if not shutil.which("fetch-ebook-metadata"):
        return []

    title = (title or "").strip()
    author = (author or "").strip()

    if not title and not author:
        return []

    cmd = ["fetch-ebook-metadata", "--opf", "--verbose"]
    if title:
        cmd += ["--title", title]
    if author:
        cmd += ["--authors", author]
    if sources and sources != "all":
        cmd += ["--allowed-plugin", sources]

    logger.debug("Kör: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []

    opf_xml = (result.stdout or "").strip()
    if not opf_xml or not opf_xml.startswith("<"):
        return []

    try:
        parsed = _parse_opf(opf_xml)
    except CalibreError:
        return []

    sources_used: list[str] = _parse_calibre_sources(result.stderr or "")

    source_label = (
        f"Calibre: {', '.join(sources_used)}" if sources_used else "Calibre"
    )

    series_index = parsed.get("series_index")
    series_index_str = str(series_index) if series_index else ""

    tags = parsed.get("tags") or []
    genres = ", ".join(t for t in tags if t) if isinstance(tags, list) else str(tags)

    fields_found = []
    if parsed.get("title"): fields_found.append("title")
    if parsed.get("author"): fields_found.append("author")
    if parsed.get("description"): fields_found.append("description")
    if parsed.get("isbn"): fields_found.append("isbn")
    if parsed.get("publisher"): fields_found.append("publisher")
    if parsed.get("series"): fields_found.append("series")
    if genres: fields_found.append("genres")
    if parsed.get("cover_url"): fields_found.append("cover")

    return [
        {
            "source": source_label,
            "title": parsed.get("title") or title or "",
            "author": parsed.get("author") or author or "",
            "description": parsed.get("description") or "",
            "isbn": parsed.get("isbn") or "",
            "publisher": parsed.get("publisher") or "",
            "language": parsed.get("language") or "",
            "series": parsed.get("series") or "",
            "series_index": series_index_str,
            "cover_url": parsed.get("cover_url") or "",
            "genres": genres,
            "fields_found": fields_found,
            "plugins_used": list(sources_used),
        }
    ]
