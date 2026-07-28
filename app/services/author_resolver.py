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

Multi-author policy (v1.36.0): '&' is the canonical separator
(author_authority.AUTHOR_SEPARATOR) — the resolver splits on it and
resolves each person individually, storing ordered links in book_authors
(position 0 mirrored in item.author_id for single-author call sites).
Strings fused with any *other* separator ("A och B", "A, B") stay one
opaque unit — comma is ambiguous with the sort form, so splitting them is
a manual act: the /authors split flow records an AuthorSplitRule mapping
the fused string to its person entities, which this resolver consults so
re-scans of the still-fused file honour the user's decision instead of
recreating the fused entry. Per the matcher's signature semantics the
worst case for an unsplit fused string is a redundant entry, never a
false merge.

Resolution happens as a batched *pending pass* (resolve_pending_authors)
over items with author_status IS NULL or 'stale', called from
scan_directory and /upload after upserts. The before_flush listener in
models.py marks items 'stale' (keeping author_id as memory) whenever
item.author changes, so any author edit anywhere automatically re-enters
the queue — with context.
"""
import json
import re
from contextlib import contextmanager

from app.models import (
    Author,
    AuthorAlias,
    AuthorSplitRule,
    BookAuthor,
    LibraryItem,
)

from app.services.author_authority import (
    AUTHOR_SEPARATOR,
    FUZZY_SUGGEST_THRESHOLD,
    author_signature,
    fuzzy_similarity,
    normalize_author_name,
    resolve_author,
    split_author_string,
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
        self._split_rules = {}  # normalize_author_name(fused) -> [author_id, ...]

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
        for rule in session.query(AuthorSplitRule).all():
            try:
                ids = [int(x) for x in json.loads(rule.author_ids)]
            except (ValueError, TypeError):
                continue
            if ids:
                self._split_rules[rule.source_key] = ids

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

    def _expand_parts(self, name):
        """'&'-split a string and expand split rules. Returns a list of
        ('id', author_id) / ('name', part) tuples in display order. Rules
        whose authors have all been deleted fall back to the literal part."""
        out = []
        for part in split_author_string(name):
            rule_ids = self._split_rules.get(normalize_author_name(part))
            if rule_ids:
                valid = [
                    aid for aid in rule_ids
                    if self.session.get(Author, aid) is not None
                ]
                if valid:
                    out.extend(("id", aid) for aid in valid)
                    continue
            out.append(("name", part))
        return out

    def _set_links(self, item, author_ids):
        """Replace the item's book_authors rows with `author_ids` in order."""
        if item.id is None:
            self.session.flush()
        self.session.query(BookAuthor).filter_by(item_id=item.id).delete()
        self.session.flush()  # clear UNIQUE(item_id, position) before re-insert
        for pos, author_id in enumerate(author_ids):
            self.session.add(BookAuthor(
                item_id=item.id, author_id=author_id, position=pos
            ))

    def resolve_and_link(self, item):
        """Resolve one item's author string and stamp the book_authors
        links + author_id (primary mirror) + author_status. DB-only —
        never touches the file. Returns the status set.

        The string is '&'-split (plus split-rule expansion) and each part
        resolves individually. v2 invariant per part: a non-empty part
        always ends LINKED — unmatched parts become/reuse tentative
        entries, and any fuzzy hit — judged against the book's *previous*
        entries first (the memory a 'stale' item carries), then cold
        against the registry — is stored as a merge proposal in
        suggested_author_id. Book-level status is the worst part outcome:
        review > new > linked."""
        old_ids = [
            row.author_id
            for row in self.session.query(BookAuthor)
            .filter_by(item_id=item.id)
            .order_by(BookAuthor.position)
            .all()
        ] if item.id is not None else []
        memory_ids = list(old_ids) if item.author_status == STATUS_STALE else []
        if (item.author_status == STATUS_STALE and item.author_id
                and item.author_id not in memory_ids):
            memory_ids.insert(0, item.author_id)

        name = (item.author or "").strip()
        if not name:
            item.author_id = None
            item.author_status = STATUS_MISSING
            item.suggested_author_id = None
            self._set_links(item, [])
            for author_id in set(old_ids):
                self._gc_if_orphaned(author_id)
            return STATUS_MISSING

        resolved = []       # author ids, display order
        status = STATUS_LINKED
        suggestion_id = None
        for kind_tag, value in self._expand_parts(name):
            if kind_tag == "id":
                resolved.append(value)
                continue

            part = value
            kind, payload = resolve_author(
                part, self._exact, self._signatures, self._candidates
            )
            if kind in ("exact", "signature"):
                resolved.append(payload)
                if kind == "signature":
                    self._record_alias(part, payload)
                continue

            # No deterministic match: link the literal part (never limbo).
            author = self._create_tentative(part)
            resolved.append(author.id)

            # Proposal: a remembered entry wins over cold fuzzy — the same
            # book's field changing spelling is near-certainly the same person.
            part_suggestion = None
            best_score = 0.0
            for prev_id in memory_ids:
                if prev_id == author.id:
                    continue
                prev = self.session.get(Author, prev_id)
                if not prev:
                    continue
                score = fuzzy_similarity(part, prev.canonical_name)
                if score >= FUZZY_SUGGEST_THRESHOLD and score > best_score:
                    part_suggestion, best_score = prev.id, score
            if part_suggestion is None and kind == "suggest":
                part_suggestion = payload[0][0]  # best cold candidate

            if part_suggestion:
                if suggestion_id is None:
                    suggestion_id = part_suggestion
                status = STATUS_REVIEW
            elif status != STATUS_REVIEW:
                status = STATUS_NEW

        # Dedupe while preserving order ("X & X" — or a rule that expands
        # to an author already present).
        seen = set()
        ordered = [a for a in resolved if not (a in seen or seen.add(a))]

        self._set_links(item, ordered)
        item.author_id = ordered[0] if ordered else None
        item.suggested_author_id = suggestion_id
        item.author_status = status if ordered else STATUS_MISSING

        for author_id in set(old_ids) - set(ordered) - {suggestion_id}:
            self._gc_if_orphaned(author_id)
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
    ) or (
        session.query(BookAuthor.id).filter_by(author_id=author_id).first()
    )
    # Split rules never reference tentative entries (split/merge promote
    # their parts), so no rule check is needed here.
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


def _ordered_link_ids(session, item):
    """The item's linked author ids in display order (book_authors)."""
    return [
        row.author_id
        for row in session.query(BookAuthor)
        .filter_by(item_id=item.id)
        .order_by(BookAuthor.position)
        .all()
    ]


def _relink_item(session, item, author_ids):
    """Rewrite an item's links, primary mirror and display string from an
    ordered author-id list (deduped here). Sets status LINKED. Does not
    touch suggested_author_id — callers decide. Caller wraps the batch in
    keep_author_links() and commits."""
    seen = set()
    ordered = [a for a in author_ids if not (a in seen or seen.add(a))]
    session.query(BookAuthor).filter_by(item_id=item.id).delete()
    session.flush()  # clear UNIQUE(item_id, position) before re-insert
    names = []
    for pos, author_id in enumerate(ordered):
        session.add(BookAuthor(
            item_id=item.id, author_id=author_id, position=pos
        ))
        author = session.get(Author, author_id)
        if author:
            names.append(author.canonical_name)
    item.author = AUTHOR_SEPARATOR.join(names) or None
    item.author_id = ordered[0] if ordered else None
    item.author_status = STATUS_LINKED if ordered else STATUS_MISSING
    return ordered


def _items_linked_to(session, author_id):
    """Every LibraryItem holding a link (or the legacy primary mirror) to
    this author."""
    from sqlalchemy import or_

    return (
        session.query(LibraryItem)
        .filter(or_(
            LibraryItem.id.in_(
                session.query(BookAuthor.item_id).filter_by(author_id=author_id)
            ),
            LibraryItem.author_id == author_id,
        ))
        .all()
    )


def _rewrite_split_rules(session, old_id, new_id=None):
    """Keep split rules valid across merges/deletes: replace old_id with
    new_id (or drop it when new_id is None). A rule left with fewer than
    two distinct authors no longer describes a split and is deleted. The
    replacement is promoted out of 'tentative' so the invariant 'rules
    never reference tentative entries' (the GC relies on it) holds."""
    for rule in session.query(AuthorSplitRule).all():
        try:
            ids = [int(x) for x in json.loads(rule.author_ids)]
        except (ValueError, TypeError):
            session.delete(rule)
            continue
        if old_id not in ids:
            continue
        out = []
        for author_id in ids:
            mapped = new_id if author_id == old_id else author_id
            if mapped is not None and mapped not in out:
                out.append(mapped)
        if len(out) >= 2:
            rule.author_ids = json.dumps(out)
            if new_id is not None:
                replacement = session.get(Author, new_id)
                if replacement and replacement.source == "tentative":
                    replacement.source = "user_confirmed"
        else:
            session.delete(rule)


def remove_item_links(session, item_id):
    """Drop an item's book_authors rows (call before deleting the item).
    Returns the author ids that were linked, for the caller's GC pass."""
    ids = [
        row.author_id
        for row in session.query(BookAuthor).filter_by(item_id=item_id).all()
    ]
    session.query(BookAuthor).filter_by(item_id=item_id).delete()
    return ids


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

    left_behind = (
        {item.author_id, item.suggested_author_id}
        | set(_ordered_link_ids(session, item))
    ) - {None, author.id}
    with keep_author_links(session):
        _relink_item(session, item, [author.id])
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

    items = _items_linked_to(session, author.id)
    with keep_author_links(session):
        for item in items:
            # Links are unchanged by a rename — rebuild the display string
            # from them so co-authors keep their place.
            ids = _ordered_link_ids(session, item) or [author.id]
            _relink_item(session, item, ids)
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

    items = _items_linked_to(session, source.id)
    with keep_author_links(session):
        for item in items:
            # Repoint the source link in place; if the item already links
            # the target too, _relink_item's dedupe collapses them.
            ids = _ordered_link_ids(session, item) or [source.id]
            _relink_item(
                session, item,
                [target.id if a == source.id else a for a in ids],
            )
            item.suggested_author_id = None

    # Proposals pointing at the disappearing entry follow the merge; a
    # proposal that now points at one of the book's own entries is
    # thereby settled.
    for item in session.query(LibraryItem).filter_by(
        suggested_author_id=source.id
    ).all():
        linked = set(_ordered_link_ids(session, item)) | {item.author_id}
        item.suggested_author_id = None if target.id in linked else target.id
        if item.suggested_author_id is None and item.author_status == STATUS_REVIEW:
            item.author_status = STATUS_LINKED

    _rewrite_split_rules(session, source.id, target.id)
    session.delete(source)
    return len(items)


def author_from_selection(session, selection):
    """One UI author field → an Author entity.

    selection: {'author_id': int} for a registry pick (promoted out of
    'tentative' — an active choice confirms the spelling), or
    {'name': str} for a typed entry, which reuses an existing entry when
    layers 1-2 match and otherwise creates a user_confirmed one (the
    caller has already run the fuzzy create-guard). Returns None for an
    empty selection or a dangling id."""
    author = None
    if selection.get("author_id"):
        author = session.get(Author, selection["author_id"])
    if author is None:
        name = (selection.get("name") or "").strip()
        if not name:
            return None
        author = find_existing_author(session, name)
        if author is None:
            author = Author(
                canonical_name=_display_form(name),
                source="user_confirmed",
            )
            session.add(author)
            session.flush()
            key = normalize_author_name(author.canonical_name)
            if key and not session.query(AuthorAlias).filter_by(
                variant_key=key
            ).first():
                session.add(AuthorAlias(variant_key=key, author_id=author.id))
    if author.source == "tentative":
        author.source = "user_confirmed"
    return author


def remove_author_from_split_rules(session, author_id):
    """Author deleted from the registry: drop it from every split rule
    (rules left with fewer than two authors are deleted)."""
    _rewrite_split_rules(session, author_id, None)


def set_item_authors(session, item, selections):
    """User confirmation from the modal's multi-field author UI: link the
    book to exactly these authors, in this order.

    selections: [{'author_id': int|None, 'name': str}, ...] — see
    author_from_selection. Rebuilds the display string with the canonical
    separator. Caller commits."""
    authors = []
    for sel in selections:
        author = author_from_selection(session, sel)
        if author and all(a.id != author.id for a in authors):
            authors.append(author)

    # Single-author correction: remember the book's previous spelling as
    # an alias (the same memory assign_author_to_item keeps), so that
    # variant resolves by itself next time. A fused previous string can't
    # be aliased to one person — multi selections skip this.
    if len(authors) == 1 and "&" not in (item.author or ""):
        old_variant = normalize_author_name(item.author or "")
        if old_variant:
            alias = session.query(AuthorAlias).filter_by(
                variant_key=old_variant
            ).first()
            if alias is None:
                session.add(
                    AuthorAlias(variant_key=old_variant, author_id=authors[0].id)
                )
            elif (alias.author_id == item.author_id
                    and alias.author_id != authors[0].id):
                owner = session.get(Author, alias.author_id)
                if owner is not None and owner.source == "tentative":
                    # The book's own tentative entry is about to be
                    # orphaned/GC'd — keep the observed spelling as
                    # memory on the entry the user chose instead.
                    alias.author_id = authors[0].id

    left_behind = (
        {item.author_id, item.suggested_author_id}
        | set(_ordered_link_ids(session, item))
    ) - {None} - {a.id for a in authors}
    with keep_author_links(session):
        _relink_item(session, item, [a.id for a in authors])
        item.suggested_author_id = None
    session.flush()
    for orphan_id in left_behind:
        gc_orphaned_author(session, orphan_id)
    return authors


def split_author_entity(session, fused, part_authors):
    """Split a fused registry entry ("Sören Karlsson och Deanne Rauscher")
    into its person entities — the manual counterpart of merge_authors.

    Every book linked to the fused entry gets the parts at that position
    (order preserved), display strings are rebuilt with the canonical
    separator, and the fused canonical + each of its alias spellings
    become AuthorSplitRules so re-scans of still-fused files resolve to
    the persons instead of recreating the fused entry. The fused entry is
    then deleted. Parts are promoted out of 'tentative' (rules must never
    reference tentative entries — the GC relies on it). Caller commits.
    Returns the number of items relinked."""
    seen = set()
    parts = [p for p in part_authors if not (p.id in seen or seen.add(p.id))]
    if len(parts) < 2:
        raise ValueError("need_two_parts")
    if any(p.id == fused.id for p in parts):
        raise ValueError("part_is_fused")

    for part in parts:
        if part.source == "tentative":
            part.source = "user_confirmed"
    part_ids = [p.id for p in parts]

    keys = {normalize_author_name(fused.canonical_name)}
    keys.update(
        alias.variant_key
        for alias in session.query(AuthorAlias).filter_by(author_id=fused.id)
    )
    for key in keys:
        if not key:
            continue
        rule = session.query(AuthorSplitRule).filter_by(source_key=key).first()
        if rule:
            rule.author_ids = json.dumps(part_ids)
        else:
            session.add(
                AuthorSplitRule(source_key=key, author_ids=json.dumps(part_ids))
            )

    items = _items_linked_to(session, fused.id)
    with keep_author_links(session):
        for item in items:
            ids = _ordered_link_ids(session, item) or [fused.id]
            new_ids = []
            for author_id in ids:
                new_ids.extend(part_ids if author_id == fused.id else [author_id])
            _relink_item(session, item, new_ids)
            item.suggested_author_id = None

    # Proposals pointing at the disappearing fused entry are moot — the
    # split IS the verdict on what that string meant.
    for item in session.query(LibraryItem).filter_by(
        suggested_author_id=fused.id
    ).all():
        item.suggested_author_id = None
        if item.author_status == STATUS_REVIEW:
            item.author_status = STATUS_LINKED

    session.query(AuthorAlias).filter_by(author_id=fused.id).delete()
    session.delete(fused)
    return len(items)


def authors_overview(session):
    """Manage-authors data: every canonical entry with its book count,
    plus proactively flagged likely duplicates (design guard 3 — a 1-book
    entry beside a near-identical 30-book entry screams typo)."""
    from sqlalchemy import func

    from app.services.author_authority import looks_like_multiple_authors

    # Count through book_authors so co-author links count too; the legacy
    # author_id mirror is folded in for any not-yet-resolved stragglers.
    counts = dict(
        session.query(
            BookAuthor.author_id, func.count(func.distinct(BookAuthor.item_id))
        )
        .group_by(BookAuthor.author_id)
        .all()
    )
    for author_id, count in (
        session.query(LibraryItem.author_id, func.count(LibraryItem.id))
        .filter(
            LibraryItem.author_id.isnot(None),
            ~LibraryItem.id.in_(session.query(BookAuthor.item_id)),
        )
        .group_by(LibraryItem.author_id)
        .all()
    ):
        counts[author_id] = counts.get(author_id, 0) + count
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
            "looks_multi": looks_like_multiple_authors(author.canonical_name),
        }
        for author in authors
    ]
    return rows, pairs
