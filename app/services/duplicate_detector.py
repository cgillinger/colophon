# Colophon – e-book metadata manager
"""Find potential duplicate books in the library.

Three detection layers:
  1. Same ISBN (confidence 1.0)
  2. Same group_key + same file extension (confidence 0.95)
  3. Fuzzy title match >= 0.85, with author cross-check (confidence = ratio)

Items already grouped by an earlier (higher-priority) layer are excluded
from later layers. Same group_key + DIFFERENT extension is format grouping
(intentional) and is NEVER flagged as a duplicate.
"""
import os
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from app.models import LibraryItem


_FUZZY_THRESHOLD = 0.85
_AUTHOR_THRESHOLD = 0.5


def _normalize_for_fuzzy(title):
    if not title:
        return ""
    s = unicodedata.normalize("NFKD", title)
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"\[.*?\]|\(.*?\)", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _serialize_item(item):
    ext = (item.extension or "").lstrip(".").lower()
    if not ext and item.file_name:
        ext = os.path.splitext(item.file_name)[1].lstrip(".").lower()
    return {
        "id": item.id,
        "title": item.title or "",
        "author": item.author or "",
        "filename": item.file_name or "",
        "filepath": item.file_path or "",
        "file_size": item.size_bytes or 0,
        "file_ext": ext,
        "isbn": item.isbn or "",
        "series": item.series or "",
        "series_index": item.series_index or "",
        "cover_url": f"/cover/{item.id}" if item.cover_path else "",
        "published_date": item.published_date or "",
        "publisher": item.publisher or "",
    }


def find_duplicates():
    """Return a list of duplicate groups.

    Each group: {
        'match_type': 'isbn' | 'exact_title' | 'fuzzy_title',
        'confidence': float (0-1),
        'match_detail': str,
        'items': [serialized_item, ...]
    }
    """
    all_items = LibraryItem.query.all()
    claimed = set()
    groups = []

    # --- Layer 1: ISBN ---
    isbn_buckets = defaultdict(list)
    for item in all_items:
        isbn = (item.isbn or "").strip().replace("-", "").replace(" ", "")
        if isbn and len(isbn) >= 10:
            isbn_buckets[isbn].append(item)
    for isbn, members in isbn_buckets.items():
        if len(members) < 2:
            continue
        for m in members:
            claimed.add(m.id)
        groups.append({
            "match_type": "isbn",
            "confidence": 1.0,
            "match_detail": f"ISBN {isbn}",
            "items": [_serialize_item(m) for m in members],
        })

    # --- Layer 2: same group_key + same extension ---
    key_ext_buckets = defaultdict(list)
    for item in all_items:
        if item.id in claimed:
            continue
        if not item.group_key:
            continue
        ext = (item.extension or "").lower()
        if not ext and item.file_name:
            ext = os.path.splitext(item.file_name)[1].lower()
        key_ext_buckets[(item.group_key, ext)].append(item)
    for (gkey, ext), members in key_ext_buckets.items():
        if len(members) < 2:
            continue
        for m in members:
            claimed.add(m.id)
        sample_title = members[0].title or ""
        groups.append({
            "match_type": "exact_title",
            "confidence": 0.95,
            "match_detail": sample_title,
            "items": [_serialize_item(m) for m in members],
        })

    # --- Layer 3: fuzzy title (+ author cross-check) ---
    candidates = [
        (item, _normalize_for_fuzzy(item.title), (item.author or "").lower().strip())
        for item in all_items
        if item.id not in claimed
    ]
    candidates = [c for c in candidates if c[1]]
    used = set()
    for i, (a, norm_a, author_a) in enumerate(candidates):
        if a.id in used:
            continue
        members = [a]
        best_ratio = 0.0
        for j in range(i + 1, len(candidates)):
            b, norm_b, author_b = candidates[j]
            if b.id in used:
                continue
            ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
            if ratio < _FUZZY_THRESHOLD:
                continue
            if author_a and author_b:
                ar = SequenceMatcher(None, author_a, author_b).ratio()
                if ar < _AUTHOR_THRESHOLD:
                    continue
            members.append(b)
            used.add(b.id)
            if ratio > best_ratio:
                best_ratio = ratio
        if len(members) > 1:
            used.add(a.id)
            groups.append({
                "match_type": "fuzzy_title",
                "confidence": best_ratio or _FUZZY_THRESHOLD,
                "match_detail": a.title or "",
                "items": [_serialize_item(m) for m in members],
            })

    return groups
