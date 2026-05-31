# Colophon – e-book metadata manager
"""Field-level metadata merge.

The enrichment pipeline used to be a *row-winner*: it scored every candidate
from every source and kept the single highest-scoring one, throwing the rest
away. That discards the union of fields — e.g. Google has the synopsis and
cover but never the series, while the embedded file or Calibre has the series.
With row-winner you only ever got one of them.

This module builds the final record **field by field** instead, taking the
best available value for each field across all *trusted* candidates:

    anchor      — the highest-scoring candidate decides the book's identity
                  (title/author) and is always trusted.
    trust-gate  — a candidate only contributes fields if it plausibly describes
                  the same book (shares the anchor's ISBN, title similarity
                  >= 0.6, or identity score >= 45). The embedded file is always
                  trusted — it *is* the book.
    per-field   — each field is coalesced with a strategy:
                    description       -> longest non-empty (richest synopsis)
                    genres            -> union of unique tags (cap 12)
                    series+index      -> coupled, taken together from the first
                                         source that names a series (so the name
                                         and number never come from different
                                         books)
                    everything else   -> first non-empty in per-field precedence

`merge_candidates()` returns the merged payload plus a `provenance` map
{field: source_label} so the UI can show "Series ✓ (Calibre)".
"""
from app.services.metadata_sources import (
    normalize_isbn,
    score_metadata_result,
    similarity,
)


# Canonical source keys used in the precedence tables. Candidate "source"
# labels vary ("Google Books API", "Calibre: Goodreads, FictionDB",
# "Wikipedia", "Embedded file"), so we bucket them.
def _source_key(label):
    s = (label or "").lower()
    if "embedded" in s or "inbäddad" in s or "inbaddad" in s:
        return "embedded"
    if "calibre" in s:
        return "calibre"
    if "wikidata" in s:
        return "wikidata"
    if "hardcover" in s:
        return "hardcover"
    if "libris" in s:
        return "libris"
    if "open library" in s or "openlibrary" in s:
        return "openlibrary"
    if "google" in s:
        return "google"
    if "wikipedia" in s:
        return "wikipedia"
    return "other"


# Per-field precedence (canonical source keys, highest priority first). The
# special token "anchor" means the anchor candidate specifically. Only sources
# that exist in the current pipeline are listed; unknown sources ("other") are
# always considered last via DEFAULT_PRECEDENCE.
# Wikidata gives the cleanest *structured* series (name + ordinal P1545), so it
# ranks highest after the embedded file; Hardcover next (series name, no index).
SERIES_PRECEDENCE = ["embedded", "wikidata", "hardcover", "calibre", "google", "wikipedia"]

# LIBRIS is the authoritative Swedish national bibliography — it ranks high for
# publisher/date/language/isbn (even above the embedded file for publisher,
# whose OPF value is often junk, e.g. the author's name). It returns nothing for
# non-Swedish books, so it simply doesn't contribute there.
FIELD_PRECEDENCE = {
    "title":          ["anchor", "embedded", "libris", "calibre", "hardcover", "wikidata", "google", "openlibrary", "wikipedia"],
    "author":         ["anchor", "embedded", "libris", "calibre", "hardcover", "wikidata", "google", "openlibrary", "wikipedia"],
    "publisher":      ["libris", "embedded", "calibre", "google", "openlibrary", "hardcover", "wikipedia"],
    "published_date": ["libris", "embedded", "google", "calibre", "openlibrary", "hardcover", "wikidata", "wikipedia"],
    "language":       ["embedded", "libris", "google", "calibre", "wikipedia"],
    "isbn":           ["embedded", "libris", "google", "calibre", "hardcover", "openlibrary", "wikipedia"],
    "cover_url":      ["google", "hardcover", "openlibrary", "wikidata", "calibre", "wikipedia", "embedded"],
}

DEFAULT_PRECEDENCE = ["anchor", "embedded", "wikidata", "hardcover", "libris", "calibre", "google", "openlibrary", "wikipedia", "other"]

# Fields filled by the generic first-by-precedence pass (series, description and
# genres have their own strategies and are handled separately).
_FIRST_FIELDS = ["title", "author", "publisher", "published_date", "language", "isbn", "cover_url"]


def _is_embedded(candidate):
    return _source_key(candidate.get("source")) == "embedded"


def _trusted_candidates(item, candidates, anchor):
    """Return the non-anchor candidates allowed to contribute fields.

    Keeps a candidate when it plausibly describes the same book as the anchor:
    shared ISBN, title similarity >= 0.6, or identity score >= 45. The embedded
    file is always trusted (it is the file itself).
    """
    out = []
    anchor = anchor or {}
    anchor_isbn = normalize_isbn(anchor.get("isbn", ""))
    anchor_title = anchor.get("title", "") or ""

    for c in candidates:
        if c is anchor:
            continue
        if _is_embedded(c):
            out.append(c)
            continue
        c_isbn = normalize_isbn(c.get("isbn", ""))
        if anchor_isbn and c_isbn and anchor_isbn == c_isbn:
            out.append(c)
            continue
        if anchor_title and similarity(anchor_title, c.get("title", "")) >= 0.6:
            out.append(c)
            continue
        if score_metadata_result(item, c) >= 45:
            out.append(c)
            continue
    return out


def _ordered_pool(candidates, source_key, anchor):
    """Candidates matching a precedence token, anchor preferred when present."""
    if source_key == "anchor":
        return [anchor] if anchor else []
    pool = []
    for c in candidates:
        if _source_key(c.get("source")) == source_key:
            pool.append(c)
    return pool


def _coalesce_first(field, precedence, anchor, trusted):
    """First non-empty value walking the precedence order."""
    for key in precedence:
        for c in _ordered_pool(trusted, key, anchor):
            v = (c.get(field) or "")
            v = v.strip() if isinstance(v, str) else str(v).strip()
            if v:
                return v, c.get("source", "")
    return "", ""


def _coalesce_series(anchor, trusted):
    """Series name + index, coupled so the index never comes from a different book.

    The name is taken from the first source (by precedence) that names a series,
    together with that source's own index. If that source gave a name but no
    index, the index is borrowed only from another trusted source naming the
    *same* series (e.g. Wikidata's structured ordinal) — never from an unrelated
    series. Returns (name, index, name_source, index_source).
    """
    name, idx, name_src, idx_src = "", "", "", ""
    for key in SERIES_PRECEDENCE:
        for c in _ordered_pool(trusted, key, anchor):
            s = (c.get("series") or "").strip()
            if s:
                name, name_src = s, c.get("source", "")
                idx = (c.get("series_index") or "").strip()
                idx_src = name_src if idx else ""
                break
        if name:
            break

    if name and not idx:
        for c in trusted:
            if (c.get("series") or "").strip().lower() == name.lower():
                candidate_idx = (c.get("series_index") or "").strip()
                if candidate_idx:
                    idx, idx_src = candidate_idx, c.get("source", "")
                    break

    return name, idx, name_src, idx_src


def _coalesce_longest(field, anchor, trusted):
    """Longest non-empty value (used for description)."""
    best_v, best_src = "", ""
    for c in trusted:
        v = (c.get(field) or "").strip()
        if len(v) > len(best_v):
            best_v, best_src = v, c.get("source", "")
    return best_v, best_src


def _coalesce_union(field, trusted, cap=12):
    """Union of unique comma-separated tags (used for genres)."""
    seen, out, first_src = set(), [], ""
    for c in trusted:
        raw = c.get(field) or ""
        for tok in (t.strip() for t in raw.split(",")):
            if not tok:
                continue
            key = tok.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(tok)
            if not first_src:
                first_src = c.get("source", "")
            if len(out) >= cap:
                break
        if len(out) >= cap:
            break
    return ", ".join(out), first_src


def merge_candidates(item, candidates, anchor=None):
    """Merge candidate records field by field.

    Returns (payload, provenance) where payload is a dict of merged field
    values (only non-empty fields are present) and provenance maps each filled
    field to the source label that supplied it.
    """
    candidates = [c for c in (candidates or []) if c]
    if not candidates:
        return {}, {}
    if anchor is None:
        anchor = candidates[0]

    # Anchor first, then the gated contributors — this ordering also makes the
    # anchor win ties in the longest/union strategies.
    trusted = [anchor] + _trusted_candidates(item, candidates, anchor)

    payload, provenance = {}, {}

    name, idx, name_src, idx_src = _coalesce_series(anchor, trusted)
    if name:
        payload["series"] = name
        provenance["series"] = name_src
        if idx:
            payload["series_index"] = idx
            provenance["series_index"] = idx_src or name_src

    desc, d_src = _coalesce_longest("description", anchor, trusted)
    if desc:
        payload["description"] = desc
        provenance["description"] = d_src

    genres, g_src = _coalesce_union("genres", trusted)
    if genres:
        payload["genres"] = genres
        provenance["genres"] = g_src

    for field in _FIRST_FIELDS:
        precedence = FIELD_PRECEDENCE.get(field, DEFAULT_PRECEDENCE)
        value, src = _coalesce_first(field, precedence, anchor, trusted)
        if value:
            payload[field] = value
            provenance[field] = src

    return payload, provenance
