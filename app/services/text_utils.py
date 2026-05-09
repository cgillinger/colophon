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

    title = title.strip()

    return {
        "cleaned_title": title,
        "extracted_series": extracted_series,
        "extracted_series_index": extracted_series_index,
        "was_modified": title != original,
    }
