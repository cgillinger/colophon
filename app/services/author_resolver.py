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
Fuzzy never *merges* anything — but since v2 (DESIGN-robust-author-links.md)
it no longer leaves the book unlinked either: an unmatched string becomes a
tentative entry the book links to, and the fuzzy hit is recorded as a merge
*proposal* between two registry entries (suggested_author_id, status
'review'). A book with a non-empty author string is always linked.

Multi-author policy: a comma-joined multi-author string ("John Smith,
Jane Doe") is treated as one opaque unit — it becomes its own registry
entry rather than being split. LibraryItem.author is a single string
everywhere in Colophon, so the registry mirrors that; per the matcher's
signature semantics the worst case is a redundant entry, never a false
merge. Splitting into person entities is a possible later refinement.

Resolution happens as a batched *pending pass* (resolve_pending_authors)
over items with author_status IS NULL or 'stale', called from
scan_directory and /upload after upserts. The before_flush listener in
models.py marks items 'stale' (keeping author_id as memory) whenever
item.author changes, so any author edit anywhere automatically re-enters
the queue — with context.
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
STATUS_REVIEW = "review"    # ⚠️ linked + open merge proposal (suggested_author_id)
STATUS_MISSING = "missing"  # ❓ no author in the file at all
STATUS_STALE = "stale"      # ⏳ author string changed; pending pass re-resolves


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

    def _forget(self, author_id):
        """Drop a GC'd entry from the in-memory indexes so later books in
        the same batch can't link to a deleted row."""
        for index in (self._exact, self._signatures):
            for key in [k for k, v in index.items() if v == author_id]:
                del index[key]
        self._candidates = [c for c in self._candidates if c[0] != author_id]

    def _gc_if_orphaned(self, author_id):
        """A tentative entry the batch just walked away from: if nothing
        links to it and no proposal references it, it is an auto-created
        leftover — remove it (invariant 4). Confirmed entries are never
        auto-removed; they keep the 'Inga böcker' badge instead."""
        if gc_orphaned_author(self.session, author_id):
            self._forget(author_id)

    def resolve_and_link(self, item):
        """Resolve one item's author string and stamp author_id +
        author_status. DB-only — never touches the file. Returns the
        status set.

        v2 invariant: a non-empty string always ends LINKED. When nothing
        matches deterministically, the literal string becomes/reuses a
        tentative entry the book links to, and any fuzzy hit — judged
        against the book's *previous* entry first (the memory a 'stale'
        item carries), then cold against the registry — is stored as a
        merge proposal in suggested_author_id (status 'review')."""
        prev_id = item.author_id if item.author_status == STATUS_STALE else None

        name = (item.author or "").strip()
        if not name:
            item.author_id = None
            item.author_status = STATUS_MISSING
            item.suggested_author_id = None
            if prev_id:
                self._gc_if_orphaned(prev_id)
            return STATUS_MISSING

        kind, payload = resolve_author(
            name, self._exact, self._signatures, self._candidates
        )

        if kind in ("exact", "signature"):
            item.author_id = payload
            item.author_status = STATUS_LINKED
            item.suggested_author_id = None
            if kind == "signature":
                self._record_alias(name, payload)
            if prev_id and prev_id != payload:
                self._gc_if_orphaned(prev_id)
            return STATUS_LINKED

        # No deterministic match: link the literal string (never limbo).
        author = self._create_tentative(name)
        item.author_id = author.id

        # Proposal: the remembered entry wins over cold fuzzy — the same
        # book's field changing spelling is near-certainly the same person.
        suggestion_id = None
        if prev_id and prev_id != author.id:
            prev = self.session.get(Author, prev_id)
            if prev and fuzzy_similarity(
                name, prev.canonical_name
            ) >= FUZZY_SUGGEST_THRESHOLD:
                suggestion_id = prev.id
        if suggestion_id is None and kind == "suggest":
            suggestion_id = payload[0][0]  # best cold candidate

        if suggestion_id:
            item.suggested_author_id = suggestion_id
            item.author_status = STATUS_REVIEW
        else:
            item.suggested_author_id = None
            item.author_status = STATUS_NEW

        if prev_id and prev_id != author.id and prev_id != suggestion_id:
            self._gc_if_orphaned(prev_id)
        return item.author_status


def resolve_pending_authors(session, items=None):
    """Resolve items whose author_status is NULL or 'stale'. Cheap:
    in-memory matching only, no file reads, no network. Caller commits.

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
            .filter(
                (LibraryItem.author_status.is_(None))
                | (LibraryItem.author_status == STATUS_STALE)
            )
            .all()
        )
    else:
        pending = [
            it for it in items
            if it.author_status is None or it.author_status == STATUS_STALE
        ]
    counts = {}
    if not pending:
        return counts

    registry = AuthorRegistry(session)
    for item in pending:
        status = registry.resolve_and_link(item)
        counts[status] = counts.get(status, 0) + 1
    return counts


def gc_orphaned_author(session, author_id):
    """Remove a *tentative* entry no book links to and no proposal
    references (invariant 4 of DESIGN-robust-author-links.md). Called
    when a resolution walks away from an entry and when a book is
    deleted. Confirmed/authority-linked entries are never auto-removed —
    they are curated knowledge and get the 'Inga böcker' badge instead.
    Returns True if the entry was removed. Caller commits."""
    if not author_id:
        return False
    author = session.get(Author, author_id)
    if author is None or author.source != "tentative":
        return False
    in_use = (
        session.query(LibraryItem.id)
        .filter(
            (LibraryItem.author_id == author_id)
            | (LibraryItem.suggested_author_id == author_id)
        )
        .first()
    )
    if in_use:
        return False
    session.query(AuthorAlias).filter_by(author_id=author_id).delete()
    session.delete(author)
    return True


def is_known_variant(session, author_id, name):
    """True when `name` is an already-recorded spelling of the linked
    entry (canonical or alias). The scanner's flip-flop guard: a re-scan
    seeing an older spelling of the same person in the file must not
    overwrite the DB's current form (the file catches up at the next
    metadata write)."""
    if not author_id:
        return False
    key = normalize_author_name(name or "")
    if not key:
        return False
    if session.query(AuthorAlias).filter_by(
        variant_key=key, author_id=author_id
    ).first():
        return True
    author = session.get(Author, author_id)
    return bool(
        author and normalize_author_name(author.canonical_name) == key
    )


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

    left_behind = {item.author_id, item.suggested_author_id} - {None, author.id}
    with keep_author_links(session):
        item.author = author.canonical_name
        item.author_id = author.id
        item.author_status = STATUS_LINKED
        item.suggested_author_id = None
    session.flush()
    for orphan_id in left_behind:
        gc_orphaned_author(session, orphan_id)
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
            item.suggested_author_id = None

    # Proposals pointing at the disappearing entry follow the merge; a
    # proposal that now points at the book's own entry is thereby settled.
    for item in session.query(LibraryItem).filter_by(
        suggested_author_id=source.id
    ).all():
        item.suggested_author_id = None if item.author_id == target.id else target.id
        if item.suggested_author_id is None and item.author_status == STATUS_REVIEW:
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
    known_ids = {a.id for a in authors}

    duplicate_ids = set()
    pairs = []
    seen_pairs = set()

    # Open merge proposals first — they carry memory context (the same
    # book's field changed spelling), so they outrank cold fuzzy pairs.
    proposals = (
        session.query(LibraryItem.author_id, LibraryItem.suggested_author_id)
        .filter(LibraryItem.suggested_author_id.isnot(None))
        .distinct()
        .all()
    )
    for a_id, b_id in proposals:
        if a_id not in known_ids or b_id not in known_ids:
            continue
        key = frozenset((a_id, b_id))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        pairs.append((a_id, b_id))
        duplicate_ids.update((a_id, b_id))

    for i, a in enumerate(authors):
        for b in authors[i + 1:]:
            if frozenset((a.id, b.id)) in seen_pairs:
                continue
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
