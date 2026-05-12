# Colophon – e-book metadata manager
"""Text-cleaning utilities shared across scanner and metadata pipeline."""
import re


# Patterns stripped from titles. Some capture series + index for promotion to
# the dedicated series fields when those are empty on the item/candidate.
_TITLE_NOISE_PATTERNS = [
    # "(Series Name Book 3)", "(Series #3)", "(Series, Book 3)",
    # "(Series Vol. 3)", "(Series Bok 3)", etc.
    r"\s*\((?P<series>[^)]+?)[, ]+(?:Book|#|Vol\.?|Volume|Part|Bok|Del|Libro)\s*(?P<index>\d+(?:\.\d+)?)\)",
    # "(Series Name Series)" — series with no number
    r"\s*\((?P<series>[^)]+?)\s+[Ss]eries\)",
    # Marketing tags: "(Now a major Netflix series)", "(A ... novel)",
    # "(The bestselling thriller)", "(An unputdownable ...)"
    r"\s*\((?:Now a |A |The |An )[^)]*\)",
]
_COMPILED_PATTERNS = [re.compile(p) for p in _TITLE_NOISE_PATTERNS]

# "Lastname, Firstname - " or "Lastname, Firstname Middlename - " or
# "Lastname, F. - ". Strips an author prefix some publishers/scanners
# prepend to the title field.
_AUTHOR_PREFIX_PATTERN = re.compile(
    r"^[A-ZÅÄÖ][a-zåäöéèêë]+,\s+"
    r"[A-ZÅÄÖ][a-zåäöéèêë.]+(?:\s+[A-ZÅÄÖ][a-zåäöéèêë.]*\.?)*"
    r"\s*[-–—]\s*"
)


def clean_title(title):
    """Strip series info and marketing text from a title.

    Returns:
        {
            "cleaned_title": str,
            "extracted_series": str | None,
            "extracted_series_index": str | None,
            "was_modified": bool,
        }
    """
    if not title:
        return {
            "cleaned_title": "",
            "extracted_series": None,
            "extracted_series_index": None,
            "was_modified": False,
        }

    original = title
    extracted_series = None
    extracted_series_index = None

    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(title)
        if not match:
            continue
        groups = match.groupdict()
        if groups.get("series") and not extracted_series:
            extracted_series = groups["series"].strip()
        if groups.get("index") and not extracted_series_index:
            extracted_series_index = groups["index"].strip()
        title = pattern.sub("", title)

    author_match = _AUTHOR_PREFIX_PATTERN.match(title)
    if author_match:
        title = title[author_match.end():]

    title = title.strip()

    return {
        "cleaned_title": title,
        "extracted_series": extracted_series,
        "extracted_series_index": extracted_series_index,
        "was_modified": title != original,
    }


def normalize_series_index(value):
    """Normalize a series_index value to a clean string.

    Strips trailing ".0" but preserves real decimals:
        "1.0"   -> "1"
        "3.0"   -> "3"
        "1.5"   -> "1.5"
        "  2  " -> "2"
        ""      -> ""
        None    -> ""
        "II"    -> "II"   (non-numeric passes through, trimmed)
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        return ("%f" % f).rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return s
