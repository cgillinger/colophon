"""Field-level quality heuristics for metadata comparison.

Each heuristic returns (is_better, reason). The reason is a translated
string shown to the user in the bulk comparison modal so they can see
*why* the fetched value was preferred.
"""
import re

from flask_babel import gettext as _


def is_better_synopsis(existing, fetched):
    """Fetched is better if it's at least 50% longer."""
    if not fetched:
        return False, ""
    if not existing:
        return True, _("Existing was empty")
    if len(fetched) > len(existing) * 1.5:
        return True, _("Longer (%(new)d vs %(old)d chars)", new=len(fetched), old=len(existing))
    return False, ""


def is_better_isbn(existing, fetched):
    """Fetched is better if it's a valid ISBN-13 and existing is not."""
    if not fetched:
        return False, ""
    fetched_clean = re.sub(r"[-\s]", "", fetched)
    existing_clean = re.sub(r"[-\s]", "", existing) if existing else ""

    fetched_is_isbn13 = len(fetched_clean) == 13 and fetched_clean.isdigit()
    existing_is_isbn13 = len(existing_clean) == 13 and existing_clean.isdigit()

    if fetched_is_isbn13 and not existing_is_isbn13:
        if len(existing_clean) == 10:
            return True, _("ISBN-13 replaces ISBN-10")
        return True, _("ISBN-13 replaces invalid")
    return False, ""


def is_better_genre(existing, fetched):
    """Fetched is better if it lists more genres."""
    if not fetched:
        return False, ""
    if not existing:
        return True, _("Existing was empty")
    existing_count = len([g for g in existing.split(",") if g.strip()])
    fetched_count = len([g for g in fetched.split(",") if g.strip()])
    if fetched_count > existing_count:
        return True, _("More specific (%(new)d vs %(old)d genres)", new=fetched_count, old=existing_count)
    return False, ""


def is_better_author(existing, fetched):
    """Fetched is better if existing has bracket-style inversions."""
    if not fetched:
        return False, ""
    if not existing:
        return True, _("Existing was empty")
    if "[" in existing and "[" not in fetched:
        return True, _("Cleaner format (no brackets)")
    return False, ""


def is_better_publisher(existing, fetched, author=""):
    """Fetched is better if existing publisher field actually contains the author."""
    if not fetched:
        return False, ""
    if not existing:
        return True, _("Existing was empty")
    if author and existing.strip().lower() in author.strip().lower():
        return True, _("Existing was the same as the author name")
    return False, ""


def is_better_published_date(existing, fetched):
    """Fetched is better if it's more precise than existing."""
    if not fetched:
        return False, ""
    if not existing:
        return True, _("Existing was empty")
    if len(fetched) > len(existing):
        return True, _("More precise (%(new)s vs %(old)s)", new=fetched, old=existing)
    return False, ""


def is_better_title(existing, fetched):
    """Fetched is better if existing has parenthetical noise that we'd strip."""
    if not fetched:
        return False, ""
    if not existing:
        return True, _("Existing was empty")
    from app.services.text_utils import clean_title

    existing_info = clean_title(existing)
    fetched_info = clean_title(fetched)
    if existing_info["was_modified"] and not fetched_info["was_modified"]:
        return True, _("Cleaner title (series/marketing removed)")
    return False, ""


# Registry of heuristics keyed by field name. The publisher heuristic also
# accepts an author kwarg — callers handle that branch explicitly.
QUALITY_HEURISTICS = {
    "title": is_better_title,
    "author": is_better_author,
    "isbn": is_better_isbn,
    "publisher": is_better_publisher,
    "genres": is_better_genre,
    "description": is_better_synopsis,
    "published_date": is_better_published_date,
}


def evaluate_quality(field_name, existing, fetched, author=""):
    """Run the heuristic for a field. Returns (is_better, reason).

    Returns (False, "") for fields without a registered heuristic.
    """
    heuristic = QUALITY_HEURISTICS.get(field_name)
    if not heuristic:
        return False, ""
    if field_name == "publisher":
        return heuristic(existing, fetched, author)
    return heuristic(existing, fetched)
