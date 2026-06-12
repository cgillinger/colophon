# Colophon – e-book metadata manager
"""Author resolution against the registry — step 3 of
docs/author-authority-design.md (resolve-on-upload, DB-only).

This is the DB-aware layer on top of the pure matcher in
author_authority.py. It links library items to canonical authors,
records observed variant spellings as aliases, and grows the registry
with *tentative* entries for genuinely new authors. It NEVER writes to
ebook files — tentative canonicals have not earned that (design guard 1);
file writes stay with the existing metadata-write moment.

Iron rule (enforced here): auto-link only layers 1–2 (exact / signature).
A fuzzy hit sets author_status='review' and links nothing.

Multi-author policy: a comma-joined multi-author string ("John Smith,
Jane Doe") is treated as one opaque unit — it becomes its own registry
entry rather than being split. LibraryItem.author is a single string
everywhere in Colophon, so the registry mirrors that; per the matcher's
signature semantics the worst case is a redundant entry, never a false
merge. Splitting into person entities is a possible later refinement.

Resolution happens as a batched *pending pass* (resolve_pending_authors)
over items with author_status IS NULL, called from scan_directory and
/upload after upserts. The before_flush listener in models.py resets
author_id/author_status to NULL whenever item.author changes, so any
author edit anywhere automatically re-enters the queue.
"""
import re
from contextlib import contextmanager

from app.models import Author, AuthorAlias, LibraryItem

from app.services.author_authority import (
    FUZZY_SUGGEST_THRESHOLD,
    author_signature,
    fuzzy_similarity,
    normalize_author_name,
    resolve_author,
)

# author_status values (LibraryItem.author_status)
STATUS_LINKED = "linked"    # ✅ matched the registry via layer 1–2
STATUS_NEW = "new"          # ➕ created a tentative canonical entry
STATUS_REVIEW = "review"    # ⚠️ fuzzy suggestion only — user must confirm
STATUS_MISSING = "missing"  # ❓ no author in the file at all


def _display_form(name):
    """The form stored as canonical_name for a new tentative entry:
    the observed spelling, case preserved, whitespace tidied."""
    return re.sub(r"\s+", " ", name.strip())


class AuthorRegistry:
    """In-memory view of the registry for one scan/upload batch.

    Builds the three lookup structures the pure matcher needs once,
    then keeps them current as the batch links aliases and creates
    tentative entries — so the second book by a new author in the same
    batch resolves as an exact hit.
    """

    def __init__(self, session):
        self.session = session
        self._exact = {}        # normalize_author_name(form) -> author_id
        self._signatures = {}   # author_signature(form) -> author_id
        self._candidates = []   # (author_id, canonical_name) for fuzzy

        for author in session.query(Author).all():
            self._index_form(author.canonical_name, author.id)
            self._candidates.append((author.id, author.canonical_name))
        for alias in session.query(AuthorAlias).all():
            # variant_key is already normalized; both indexes accept it
            # (normalization is idempotent under the signature).
            self._exact.setdefault(alias.variant_key, alias.author_id)
            sig = author_signature(alias.variant_key)
            if sig:
                self._signatures.setdefault(sig, alias.author_id)

    def _index_form(self, form, author_id):
        key = normalize_author_name(form)
        if key:
            self._exact.setdefault(key, author_id)
        sig = author_signature(form)
        if sig:
            self._signatures.setdefault(sig, author_id)

    def _record_alias(self, observed_name, author_id):
        """Persist an observed variant so the next occurrence is a
        layer-1 exact hit instead of re-deriving the signature."""
        key = normalize_author_name(observed_name)
        if not key or key in self._exact:
            self._index_form(observed_name, author_id)
            return
        self.session.add(AuthorAlias(variant_key=key, author_id=author_id))
        self._index_form(observed_name, author_id)

    def _create_tentative(self, observed_name):
        """Grow the registry with a tentative canonical (design: the
        registry grows itself). source='tentative' gates file writes —
        this entry is DB-only until it earns confirmation."""
        author = Author(
            canonical_name=_display_form(observed_name),
            source="tentative",
        )
        self.session.add(author)
        self.session.flush()  # need author.id for the FK + indexes
        self._record_alias(observed_name, author.id)
        self._candidates.append((author.id, author.canonical_name))
        return author

    def resolve_and_link(self, item):
        """Resolve one item's author string and stamp author_id +
        author_status. DB-only — never touches the file. Returns the
        status set."""
        name = (item.author or "").strip()
        if not name:
            item.author_id = None
            item.author_status = STATUS_MISSING
            return STATUS_MISSING

        kind, payload = resolve_author(
            name, self._exact, self._signatures, self._candidates
        )

        if kind in ("exact", "signature"):
            item.author_id = payload
            item.author_status = STATUS_LINKED
            if kind == "signature":
                self._record_alias(name, payload)
            return STATUS_LINKED

        if kind == "suggest":
            # Iron rule: fuzzy proposes, never links. Suggestions are
            # recomputed on demand by the review UI (step 4) — the
            # registry may have changed by the time the user looks.
            item.author_id = None
            item.author_status = STATUS_REVIEW
            return STATUS_REVIEW

        author = self._create_tentative(name)
        item.author_id = author.id
        item.author_status = STATUS_NEW
        return STATUS_NEW


def resolve_pending_authors(session, items=None):
    """Resolve items whose author_status is NULL. Cheap: in-memory
    matching only, no file reads, no network. Caller commits.

    With items=None, sweeps the whole table — new rows, rows whose
    author changed, and the entire pre-upgrade library on the first scan
    after the migration. Pass an explicit list to bound the work to one
    request's worth (the /upload route does, so the first upload after
    upgrade doesn't drag the full backlog into a synchronous request —
    the backlog belongs to the next scan, which runs in the SSE thread).

    Returns a status -> count dict for progress/summary reporting.
    """
    if items is None:
        pending = (
            session.query(LibraryItem)
            .filter(LibraryItem.author_status.is_(None))
            .all()
        )
    else:
        pending = [it for it in items if it.author_status is None]
    counts = {}
    if not pending:
        return counts

    registry = AuthorRegistry(session)
    for item in pending:
        status = registry.resolve_and_link(item)
        counts[status] = counts.get(status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Curation — user-driven registry operations (step 4)
# ---------------------------------------------------------------------------

@contextmanager
def keep_author_links(session):
    """Deliberate relabeling: setting item.author to its canonical form
    must not trip the reset listener in models.py (rename/merge keep the
    same author_id, so no FK change registers as history). Flushes inside
    the suppression window so the listener actually sees the flag."""
    session.info["suppress_author_reset"] = True
    try:
        yield
        session.flush()
    finally:
        session.info.pop("suppress_author_reset", None)


def find_existing_author(session, name):
    """Layer 1–2 lookup of a typed name against the registry (canonicals
    + aliases). Returns the Author or None. Used to stop the combobox /
    rename from creating a duplicate of an existing entry."""
    key = normalize_author_name(name)
    if not key:
        return None
    alias = session.query(AuthorAlias).filter_by(variant_key=key).first()
    if alias:
        return session.get(Author, alias.author_id)
    sig = author_signature(name)
    for author in session.query(Author).all():
        if normalize_author_name(author.canonical_name) == key:
            return author
        if sig and author_signature(author.canonical_name) == sig:
            return author
    return None


def suggest_similar_authors(session, name, limit=5, exclude_id=None):
    """Fuzzy near-matches for a name — (Author, score) best first, all at
    or above FUZZY_SUGGEST_THRESHOLD. Powers the review combobox and the
    create-time "1 character from Tolkien — sure?" guard (design guard 2).
    """
    scored = []
    for author in session.query(Author).all():
        if author.id == exclude_id:
            continue
        score = fuzzy_similarity(name, author.canonical_name)
        if score >= FUZZY_SUGGEST_THRESHOLD:
            scored.append((author, score))
    scored.sort(key=lambda entry: entry[1], reverse=True)
    return scored[:limit]


def assign_author_to_item(session, item, author=None, name=None):
    """User confirmation: link item to an existing Author, or create a
    user_confirmed entry from a typed name (caller has already run the
    duplicate/fuzzy guards). Sets the canonical name on the item and
    records the item's previous spelling as an alias, so the same variant
    (typo included — that is what authority cross-references are) resolves
    by itself next time. Caller commits."""
    if author is None:
        author = Author(
            canonical_name=_display_form(name),
            source="user_confirmed",
        )
        session.add(author)
        session.flush()
        key = normalize_author_name(author.canonical_name)
        if key and not session.query(AuthorAlias).filter_by(variant_key=key).first():
            session.add(AuthorAlias(variant_key=key, author_id=author.id))
    elif author.source == "tentative":
        # The user actively chose this entry — it has earned confirmation.
        author.source = "user_confirmed"

    old_variant = normalize_author_name(item.author or "")
    if old_variant and not session.query(AuthorAlias).filter_by(
        variant_key=old_variant
    ).first():
        session.add(AuthorAlias(variant_key=old_variant, author_id=author.id))

    with keep_author_links(session):
        item.author = author.canonical_name
        item.author_id = author.id
        item.author_status = STATUS_LINKED
    return author


def rename_author(session, author, new_name):
    """Cascade rename: one action relabels every linked book (the whole
    point of authority control — a registry typo is one fix, not N).
    The old canonical survives as an alias so files still carrying it
    keep resolving. DB-only: files pick the canonical up at the next
    metadata-write moment (design: file-write timing). Caller commits.

    Returns the number of items relabelled. Raises ValueError if the new
    name already belongs to another entry (merge instead)."""
    clash = find_existing_author(session, new_name)
    if clash and clash.id != author.id:
        raise ValueError("name_taken")

    old_key = normalize_author_name(author.canonical_name)
    author.canonical_name = _display_form(new_name)
    if author.source == "tentative":
        author.source = "user_confirmed"
    new_key = normalize_author_name(author.canonical_name)
    for key in (old_key, new_key):
        if key and not session.query(AuthorAlias).filter_by(variant_key=key).first():
            session.add(AuthorAlias(variant_key=key, author_id=author.id))

    items = session.query(LibraryItem).filter_by(author_id=author.id).all()
    with keep_author_links(session):
        for item in items:
            item.author = author.canonical_name
            item.author_status = STATUS_LINKED
    return len(items)


def merge_authors(session, source, target):
    """Cascade merge: every book and alias of `source` moves to `target`,
    then `source` is deleted. Authority ids fill empty slots on the
    target. Caller commits. Returns the number of items relabelled."""
    if source.id == target.id:
        raise ValueError("same_author")

    for alias in session.query(AuthorAlias).filter_by(author_id=source.id).all():
        alias.author_id = target.id
    source_key = normalize_author_name(source.canonical_name)
    if source_key and not session.query(AuthorAlias).filter_by(
        variant_key=source_key
    ).first():
        session.add(AuthorAlias(variant_key=source_key, author_id=target.id))

    for field in ("wikidata_qid", "libris_id", "viaf_id"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))

    items = session.query(LibraryItem).filter_by(author_id=source.id).all()
    with keep_author_links(session):
        for item in items:
            item.author = target.canonical_name
            item.author_id = target.id
            item.author_status = STATUS_LINKED

    session.delete(source)
    return len(items)


def authors_overview(session):
    """Manage-authors data: every canonical entry with its book count,
    plus proactively flagged likely duplicates (design guard 3 — a 1-book
    entry beside a near-identical 30-book entry screams typo)."""
    from sqlalchemy import func

    counts = dict(
        session.query(LibraryItem.author_id, func.count(LibraryItem.id))
        .filter(LibraryItem.author_id.isnot(None))
        .group_by(LibraryItem.author_id)
        .all()
    )
    authors = session.query(Author).order_by(Author.canonical_name).all()

    duplicate_ids = set()
    pairs = []
    for i, a in enumerate(authors):
        for b in authors[i + 1:]:
            if fuzzy_similarity(a.canonical_name, b.canonical_name) >= FUZZY_SUGGEST_THRESHOLD:
                pairs.append((a.id, b.id))
                duplicate_ids.update((a.id, b.id))

    rows = [
        {
            "author": author,
            "book_count": counts.get(author.id, 0),
            "likely_duplicate": author.id in duplicate_ids,
        }
        for author in authors
    ]
    return rows, pairs
