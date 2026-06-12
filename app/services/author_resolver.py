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

from app.models import Author, AuthorAlias, LibraryItem

from app.services.author_authority import (
    author_signature,
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
