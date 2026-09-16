# Colophon – e-book metadata manager
import hashlib
import re
import unicodedata


def normalize_title_key(s):
    """Comparison form of a title: ASCII-folded, lowercased, bracketed
    asides and punctuation removed, whitespace collapsed.

    Lifted out of `compute_group_key` so anything else comparing two
    titles ("is this Wikidata work one of the books we hold?") uses the
    same notion of sameness instead of a second, slightly different one.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compute_group_key(title, author=""):
    """Compute a stable grouping key from title.

    Two files of the same book in different formats (EPUB + MOBI + AZW3)
    typically share an identical title but may have differently formatted
    author names. The key is therefore based on the normalised title only.
    """
    norm_title = normalize_title_key(title)
    if not norm_title:
        return ""

    return hashlib.sha256(norm_title.encode("utf-8")).hexdigest()[:16]
