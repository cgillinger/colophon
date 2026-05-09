# Colophon – e-book metadata manager
import hashlib
import re
import unicodedata


def compute_group_key(title, author=""):
    """Compute a stable grouping key from title.

    Two files of the same book in different formats (EPUB + MOBI + AZW3)
    typically share an identical title but may have differently formatted
    author names. The key is therefore based on the normalised title only.
    """
    def _normalize(s):
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

    norm_title = _normalize(title)
    if not norm_title:
        return ""

    return hashlib.sha256(norm_title.encode("utf-8")).hexdigest()[:16]
