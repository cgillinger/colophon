# Colophon – e-book metadata manager
"""Which book a KOSync document id belongs to.

A KOSync client never sends a book id we minted. It hashes its own copy of the
file, one of two ways (CrossPoint's ``lib/KOReaderSync/KOReaderDocumentId``):

- **binary** — KOReader's partial MD5: 1 KiB read at offsets 0, 1 KiB, 4 KiB,
  16 KiB, … 1 GiB (``1024 << 2i``), skipping those past the end of the file;
- **filename** — the MD5 of the file's name, without its folder.

CrossPoint defaults to filename matching. A book copied over USB keeps our
filename; one downloaded over OPDS is named by the device from the feed's
author and title (``src/util/OpdsFilename.cpp``), in one of three formats the
user picks. We therefore record, per file version, the binary hash, our own
filename and all three OPDS names. In smart sync the device asks for both of
its hashes, so either one matching is enough.

Rows outlive the file version they were computed from: after Colophon writes
metadata into a book, the device still holds the old bytes and keeps
reporting the old hash. A hash that maps to more than one book (two editions
named alike) is ambiguous and resolves to nothing rather than to a guess.
"""
import hashlib
import logging
import os
import re

from app.models import KosyncDocument, LibraryItem, db

logger = logging.getLogger(__name__)

_CHUNK = 1024
# CrossPoint's OpdsEntry bounds and StringUtils::sanitizeFilename's default.
_MAX_TITLE_BYTES = 160
_MAX_AUTHOR_BYTES = 120
_MAX_FILENAME_BYTES = 100
_ILLEGAL = set('/\\:*?"<>|')


def partial_md5(path: str) -> str | None:
    """KOReader's document id for the file at ``path``."""
    try:
        size = os.path.getsize(path)
        md5 = hashlib.md5()
        with open(path, "rb") as fh:
            for i in range(-1, 11):
                offset = 0 if i < 0 else _CHUNK << (2 * i)
                if offset >= size:
                    continue
                fh.seek(offset)
                md5.update(fh.read(_CHUNK))
        return md5.hexdigest()
    except OSError as exc:
        logger.debug("kosync: cannot hash %s (%s)", path, exc)
        return None


def filename_md5(name: str) -> str:
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def _bounded(text: str, max_bytes: int) -> str:
    raw = (text or "").encode("utf-8")[:max_bytes]
    return raw.decode("utf-8", "ignore")


def sanitize_filename(name: str, max_bytes: int = _MAX_FILENAME_BYTES) -> str:
    """CrossPoint's StringUtils::sanitizeFilename, byte for byte."""
    text = name.lstrip(" .")
    out = []
    used = 0
    for ch in text:
        cp = ord(ch)
        if ch in _ILLEGAL:
            piece = "_"
        elif cp >= 128 or 32 <= cp < 127:
            piece = ch
        else:
            continue
        size = len(piece.encode("utf-8"))
        if used + size > max_bytes:
            break
        out.append(piece)
        used += size
    result = "".join(out).rstrip(" .")
    return result or "book"


def opds_filenames(title: str, author: str) -> list[str]:
    """Every name CrossPoint may give an OPDS download of this entry."""
    title = _bounded(title, _MAX_TITLE_BYTES)
    author = _bounded(author, _MAX_AUTHOR_BYTES)
    bases = [
        f"{author} - {title}" if author else title,  # AuthorTitle (default)
        f"{title} - {author}" if author else title,  # TitleAuthor
        title,                                       # TitleOnly
    ]
    return [sanitize_filename(base) + ".epub" for base in dict.fromkeys(bases)]


def _fingerprint(path: str) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return f"{st.st_mtime_ns}:{st.st_size}"


def index_item(item: LibraryItem) -> bool:
    """Record the hashes of ``item``'s current file. Does NOT commit.

    Cheap when nothing changed: one ``stat`` and one indexed query. Returns
    True when it wrote anything.
    """
    path = item.file_path
    if not path or not path.lower().endswith(".epub"):
        return False
    fingerprint = _fingerprint(path)
    if fingerprint is None:
        return False
    if KosyncDocument.query.filter_by(item_id=item.id, fingerprint=fingerprint).first():
        return False

    hashes = []
    binary = partial_md5(path)
    if binary:
        hashes.append((binary, "binary"))
    names = [os.path.basename(path), *opds_filenames(item.title or "", item.author or "")]
    hashes.extend((filename_md5(name), "filename") for name in dict.fromkeys(names))

    existing = {
        row.doc_hash: row
        for row in KosyncDocument.query.filter_by(item_id=item.id).all()
    }
    for doc_hash, kind in hashes:
        row = existing.get(doc_hash)
        if row is not None:
            # Same hash, newer file version (a touched mtime): re-stamp it so
            # the next lookup doesn't hash this file again.
            row.fingerprint = fingerprint
            continue
        existing[doc_hash] = KosyncDocument(
            doc_hash=doc_hash, item_id=item.id, book_uid=item.book_uid,
            kind=kind, fingerprint=fingerprint,
        )
        db.session.add(existing[doc_hash])
    return True


def _lookup(doc_hash: str) -> LibraryItem | None:
    rows = KosyncDocument.query.filter_by(doc_hash=doc_hash).all()
    items = {}
    for row in rows:
        item = db.session.get(LibraryItem, row.item_id)
        if item is None or (row.book_uid and item.book_uid != row.book_uid):
            continue
        items[item.id] = item
    if len(items) > 1:
        logger.warning(
            "KOSync: document %s matches %d books (%s) — refusing to guess",
            doc_hash, len(items), ", ".join(str(i) for i in sorted(items)),
        )
        return None
    return next(iter(items.values()), None)


def resolve(doc_hash: str) -> LibraryItem | None:
    """The book a document id belongs to, or None.

    On a miss, bring the index up to date with every EPUB whose file changed
    since it was last hashed and look again — a book copied over USB, or one
    that was never offered over OPDS, is found this way.
    """
    doc_hash = (doc_hash or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", doc_hash):
        return None
    item = _lookup(doc_hash)
    if item is not None:
        return item
    changed = False
    for candidate in LibraryItem.query.filter(LibraryItem.file_path.ilike("%.epub")).all():
        if candidate.file_path.lower().endswith(".kepub.epub"):
            continue
        changed = index_item(candidate) or changed
    if changed:
        db.session.commit()
        return _lookup(doc_hash)
    return None
