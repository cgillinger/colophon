import logging
import shutil
import subprocess
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


def _read_all_ebook_meta_fields(file_path) -> dict[str, str]:
    """Read all metadata fields from ebook-meta output."""
    try:
        result = subprocess.run(
            ["ebook-meta", str(file_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
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

    cmd = ["fetch-ebook-metadata", "--opf"]
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

    sources_used: list[str] = []
    for line in (result.stderr or "").splitlines():
        s = line.strip()
        if s.lower().startswith("source:"):
            src = s.split(":", 1)[1].strip()
            if src and src not in sources_used:
                sources_used.append(src)

    source_label = (
        f"Calibre: {', '.join(sources_used)}" if sources_used else "Calibre"
    )

    series_index = parsed.get("series_index")
    series_index_str = str(series_index) if series_index else ""

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
        }
    ]
