"""Field-level quality heuristics for metadata comparison.

Each heuristic returns (is_better, reason). The reason is a Swedish string
shown to the user in the bulk comparison modal so they can see *why* the
fetched value was preferred.
"""
import re


def is_better_synopsis(existing, fetched):
    """Fetched is better if it's at least 50% longer."""
    if not fetched:
        return False, ""
    if not existing:
        return True, "Befintlig var tom"
    if len(fetched) > len(existing) * 1.5:
        return True, f"Längre ({len(fetched)} vs {len(existing)} tecken)"
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
            return True, "ISBN-13 ersätter ISBN-10"
        return True, "ISBN-13 ersätter ogiltigt"
    return False, ""


def is_better_genre(existing, fetched):
    """Fetched is better if it lists more genres."""
    if not fetched:
        return False, ""
    if not existing:
        return True, "Befintlig var tom"
    existing_count = len([g for g in existing.split(",") if g.strip()])
    fetched_count = len([g for g in fetched.split(",") if g.strip()])
    if fetched_count > existing_count:
        return True, f"Mer specifik ({fetched_count} vs {existing_count} genrer)"
    return False, ""


def is_better_author(existing, fetched):
    """Fetched is better if existing has bracket-style inversions."""
    if not fetched:
        return False, ""
    if not existing:
        return True, "Befintlig var tom"
    if "[" in existing and "[" not in fetched:
        return True, "Renare format (inga hakparenteser)"
    return False, ""


def is_better_publisher(existing, fetched, author=""):
    """Fetched is better if existing publisher field actually contains the author."""
    if not fetched:
        return False, ""
    if not existing:
        return True, "Befintlig var tom"
    if author and existing.strip().lower() in author.strip().lower():
        return True, "Befintlig var samma som författarnamn"
    return False, ""


def is_better_published_date(existing, fetched):
    """Fetched is better if it's more precise than existing."""
    if not fetched:
        return False, ""
    if not existing:
        return True, "Befintlig var tom"
    if len(fetched) > len(existing):
        return True, f"Mer precist ({fetched} vs {existing})"
    return False, ""


def is_better_title(existing, fetched):
    """Fetched is better if existing has parenthetical noise that we'd strip."""
    if not fetched:
        return False, ""
    if not existing:
        return True, "Befintlig var tom"
    from app.services.text_utils import clean_title

    existing_info = clean_title(existing)
    fetched_info = clean_title(fetched)
    if existing_info["was_modified"] and not fetched_info["was_modified"]:
        return True, "Renare titel (serie/marknadsföring borttaget)"
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
