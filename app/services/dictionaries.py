# Colophon – e-book metadata manager
"""On-demand dictionaries for the in-browser reader.

Downloads pinned open-source StarDict dictionaries the first time a word is
looked up in a language, normalises them to plain .ifo/.idx/.dict under
DATA_DIR/dictionaries/<pair>/, and serves lookups server-side from an
in-memory index (see docs/reader-dictionary-lookup.md for the full design).

The manifest pins URL + checksum so a moved or changed upstream file fails
loudly instead of installing something unverified. Updating a dictionary
version = edit the manifest, commit.
"""
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import struct
import tarfile
import tempfile
import threading
from datetime import datetime

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Manifest — pinned sources
# --------------------------------------------------------------------------
MANIFEST = {
    "eng-eng": {
        "label": "English (GCIDE/Webster)",
        "kind": "definition",
        "url": ("https://archive.org/download/"
                "stardict-dictd_www.dict.org_gcide-2.4.2.tar/"
                "stardict-dictd_www.dict.org_gcide-2.4.2.tar.bz2"),
        "checksum_algo": "sha256",
        "checksum": "7ce3072763a896897f2c4d23db88619ddf11f043b1f4ae58e764f1a861690537",
        "archive_mb": 34,
        "license": "GPL (GCIDE)",
    },
    "eng-swe": {
        "label": "Engelska → Svenska (FreeDict/WikDict)",
        "kind": "translation",
        "url": ("https://download.freedict.org/dictionaries/eng-swe/2025.11.23/"
                "freedict-eng-swe-2025.11.23.stardict.tar.xz"),
        "checksum_algo": "sha512",
        "checksum": ("2c545616e9d346d58fcd405fc7e297e580c869cc7a43eb401f672d01242ea02c"
                     "44b562c97dcf389f6e43e5525574f1a04720200cae2576d9355595c84b6a4275"),
        "archive_mb": 3,
        "license": "CC BY-SA 3.0",
    },
}

# Book language (normalised) → pairs to query, in display order
# (definition first, then translation).
LANGUAGE_PAIRS = {
    "en": ["eng-eng", "eng-swe"],
}

# Members worth keeping from a dictionary archive, by suffix.
_WANTED_SUFFIXES = (".ifo", ".idx", ".idx.gz", ".dict", ".dict.dz", ".syn")

_MAX_ARCHIVE_BYTES = 200 * 1024 * 1024   # sanity cap for the streamed download
_MAX_ENTRIES_PER_PAIR = 3
_MAX_ENTRY_BYTES = 16 * 1024

_download_lock = threading.Lock()
_index_lock = threading.Lock()
# pair → {"index": {word_lower: [(offset, size), ...]}, "type": "m"|"h"|...}
_index_cache = {}


# --------------------------------------------------------------------------
# Paths / status
# --------------------------------------------------------------------------
def _dict_root():
    data_dir = current_app.config.get("DATA_DIR", "/data")
    return os.path.join(data_dir, "dictionaries")


def _pair_dir(pair):
    return os.path.join(_dict_root(), pair)


def _pair_files(pair):
    d = _pair_dir(pair)
    return {ext: os.path.join(d, f"{pair}.{ext}") for ext in ("ifo", "idx", "dict")}


def is_downloaded(pair):
    return all(os.path.exists(p) for p in _pair_files(pair).values())


def normalize_language(code):
    """'en-GB' / 'EN_us' / 'en' → 'en'; None → ''. """
    return (code or "").strip().lower().replace("_", "-").split("-")[0]


def pairs_for_language(code):
    return LANGUAGE_PAIRS.get(normalize_language(code), [])


# --------------------------------------------------------------------------
# Download + normalisation
# --------------------------------------------------------------------------
def _download_archive(url, dest_path, algo, expected):
    """Stream url to dest_path, hashing on the fly; raise on mismatch."""
    hasher = hashlib.new(algo)
    total = 0
    with requests.get(url, stream=True, timeout=(15, 120)) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                total += len(chunk)
                if total > _MAX_ARCHIVE_BYTES:
                    raise ValueError("archive larger than the sanity cap")
                hasher.update(chunk)
                fh.write(chunk)
    digest = hasher.hexdigest()
    if digest != expected:
        raise ValueError(
            f"checksum mismatch ({algo}): got {digest[:16]}…, "
            f"expected {expected[:16]}… — upstream file changed?"
        )


def _extract_wanted(archive_path, out_dir):
    """Extract only dictionary members, by basename — tar paths are never
    trusted (no directories, no absolute paths, no traversal)."""
    found = {}
    with tarfile.open(archive_path, "r:*") as tar:
        for member in tar:
            if not member.isfile():
                continue
            base = os.path.basename(member.name)
            suffix = next((s for s in _WANTED_SUFFIXES if base.endswith(s)), None)
            if not suffix:
                continue
            src = tar.extractfile(member)
            if src is None:
                continue
            dest = os.path.join(out_dir, base)
            with open(dest, "wb") as fh:
                shutil.copyfileobj(src, fh)
            found[suffix] = dest
    return found


def _gunzip_to(src_path, dest_path):
    with gzip.open(src_path, "rb") as src, open(dest_path, "wb") as dest:
        shutil.copyfileobj(src, dest)


def ensure_downloaded(pair):
    """Download + normalise one dictionary pair. Idempotent; raises on any
    failure (network, checksum, malformed archive) with a loggable message."""
    spec = MANIFEST.get(pair)
    if not spec:
        raise KeyError(f"unknown dictionary pair: {pair}")
    if is_downloaded(pair):
        return

    with _download_lock:
        if is_downloaded(pair):   # someone else finished while we waited
            return
        pair_dir = _pair_dir(pair)
        os.makedirs(pair_dir, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=_dict_root()) as tmp:
            archive = os.path.join(tmp, "archive")
            logger.info("Downloading dictionary %s from %s", pair, spec["url"])
            _download_archive(spec["url"], archive,
                              spec["checksum_algo"], spec["checksum"])
            found = _extract_wanted(archive, tmp)

            targets = _pair_files(pair)
            # .ifo — always plain
            if ".ifo" not in found:
                raise ValueError("archive contains no .ifo file")
            shutil.move(found[".ifo"], targets["ifo"])
            # .idx — may arrive gzipped (FreeDict does this)
            if ".idx.gz" in found:
                _gunzip_to(found[".idx.gz"], targets["idx"])
            elif ".idx" in found:
                shutil.move(found[".idx"], targets["idx"])
            else:
                raise ValueError("archive contains no .idx file")
            # .dict — DictZip (.dict.dz) is valid gzip; store uncompressed so
            # lookups can seek() straight to an entry.
            if ".dict.dz" in found:
                _gunzip_to(found[".dict.dz"], targets["dict"])
            elif ".dict" in found:
                shutil.move(found[".dict"], targets["dict"])
            else:
                raise ValueError("archive contains no .dict file")

        ifo = _parse_ifo(targets["ifo"])
        meta = {
            "pair": pair,
            "source_url": spec["url"],
            "license": spec["license"],
            "bookname": ifo.get("bookname", ""),
            "wordcount": ifo.get("wordcount", ""),
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
        }
        with open(os.path.join(pair_dir, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        with _index_lock:
            _index_cache.pop(pair, None)
        logger.info("Dictionary %s installed (%s headwords)",
                    pair, meta["wordcount"] or "?")


def download_for_language(code):
    """Download every missing pair for a language. Returns the pair list."""
    pairs = pairs_for_language(code)
    for pair in pairs:
        ensure_downloaded(pair)
    return pairs


# --------------------------------------------------------------------------
# Index + lookup
# --------------------------------------------------------------------------
def _parse_ifo(path):
    out = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "=" in line:
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip()
    return out


def _parse_idx(path):
    """StarDict .idx: repeated (word\\0 + u32 offset + u32 size, big-endian).
    Returns {word_lower: [(offset, size), ...]} preserving file order."""
    with open(path, "rb") as fh:
        raw = fh.read()
    index = {}
    pos = 0
    n = len(raw)
    while pos < n:
        nul = raw.find(b"\x00", pos)
        if nul < 0 or nul + 9 > n:
            break
        word = raw[pos:nul].decode("utf-8", errors="replace").lower()
        offset, size = struct.unpack(">II", raw[nul + 1:nul + 9])
        index.setdefault(word, []).append((offset, size))
        pos = nul + 9
    return index


def _load_pair(pair):
    """Load (and cache) a pair's index + entry type. Raises if not on disk."""
    with _index_lock:
        cached = _index_cache.get(pair)
        if cached:
            return cached
    files = _pair_files(pair)
    ifo = _parse_ifo(files["ifo"])
    index = _parse_idx(files["idx"])
    loaded = {
        "index": index,
        "type": (ifo.get("sametypesequence") or "m")[:1],
        "dict_path": files["dict"],
    }
    with _index_lock:
        _index_cache[pair] = loaded
    return loaded


_STRIP_CHARS = "\"'‘’“”“”‘’.,;:!?()[]{}«»…—–"


def _candidates(word):
    """Lookup candidates in priority order: as-selected, lowercase,
    possessive-stripped, then light English suffix heuristics (with silent-e
    restoration and doubled-consonant undoing). Misses are the AI button's job."""
    seen = []

    def add(w):
        if w and len(w) >= 2 and w not in seen:
            seen.append(w)

    base = word.strip().strip(_STRIP_CHARS)
    add(base)
    low = base.lower()
    add(low)
    for poss in ("'s", "’s"):
        if low.endswith(poss):
            add(low[: -len(poss)])
            low = low[: -len(poss)]

    def stemmed(stem):
        add(stem)
        add(stem + "e")                       # lov-ed → love
        if len(stem) > 2 and stem[-1] == stem[-2]:
            add(stem[:-1])                    # runn-ing → run

    if low.endswith("ies"):
        add(low[:-3] + "y")                   # carries → carry
    for suffix in ("ing", "est", "ed", "er", "es", "ly", "s"):
        if low.endswith(suffix) and len(low) - len(suffix) >= 2:
            stemmed(low[: -len(suffix)])
    return seen


def _read_entries(loaded, hits):
    """Read entry texts for [(offset, size), ...] from the .dict file."""
    texts = []
    with open(loaded["dict_path"], "rb") as fh:
        for offset, size in hits[:_MAX_ENTRIES_PER_PAIR]:
            fh.seek(offset)
            data = fh.read(min(size, _MAX_ENTRY_BYTES))
            texts.append(data.decode("utf-8", errors="replace"))
    return texts


def lookup_word(language, word):
    """The lookup API the reader route exposes. Returns a JSON-ready dict —
    one of status: ok | needs_download | unsupported_language."""
    pairs = pairs_for_language(language)
    if not pairs:
        return {"status": "unsupported_language"}

    missing = [p for p in pairs if not is_downloaded(p)]
    if missing:
        return {
            "status": "needs_download",
            "language": normalize_language(language),
            "download_mb": sum(MANIFEST[p]["archive_mb"] for p in missing),
            "pairs": missing,
        }

    matches = []
    candidates = _candidates(word)
    for pair in pairs:
        loaded = _load_pair(pair)
        for cand in candidates:
            hits = loaded["index"].get(cand)
            if not hits:
                continue
            for text in _read_entries(loaded, hits):
                matches.append({
                    "pair": pair,
                    "kind": MANIFEST[pair]["kind"],
                    "label": MANIFEST[pair]["label"],
                    "headword": cand,
                    "type": loaded["type"],
                    "text": text,
                })
            break   # first matching candidate wins for this pair
    return {"status": "ok", "word": word, "matches": matches}
