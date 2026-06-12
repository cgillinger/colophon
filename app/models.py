# Colophon – e-book metadata manager
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class LibraryItem(db.Model):
    __tablename__ = "library_items"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(500), nullable=True)
    # FK into authors (authority control). Relational convenience only —
    # the canonical name itself lives in `author`, mirroring the file.
    # NULL = not yet resolved against the registry. Deliberately NOT in
    # _DEVICE_CONTENT_COLUMNS: linking alone must not re-ship Kobo
    # entitlements. See docs/author-authority-design.md.
    author_id = db.Column(db.Integer, db.ForeignKey("authors.id"), nullable=True, index=True)
    # Outcome of the last registry resolution (author_resolver.py):
    # 'linked' (✅ known), 'new' (➕ tentative canonical created),
    # 'review' (⚠️ fuzzy suggestion awaits the user), 'missing' (❓ no
    # author). NULL = not yet resolved — picked up by the pending pass on
    # the next scan/upload. Reset by _reset_author_resolution below
    # whenever `author` changes without an explicit author_id.
    author_status = db.Column(db.String(16), nullable=True)
    description = db.Column(db.Text, nullable=True)

    series = db.Column(db.String(500), nullable=True)
    series_index = db.Column(db.String(100), nullable=True)
    isbn = db.Column(db.String(100), nullable=True)
    publisher = db.Column(db.String(500), nullable=True)
    language = db.Column(db.String(100), nullable=True)
    genres = db.Column(db.Text, nullable=True)
    published_date = db.Column(db.String(20), nullable=True)

    file_path = db.Column(db.String(2000), nullable=False, unique=True)
    file_name = db.Column(db.String(500), nullable=False)
    extension = db.Column(db.String(50), nullable=False)

    cover_path = db.Column(db.String(2000), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    file_mtime = db.Column(db.Float, nullable=True)

    # Deprecated 2026-05-24 — formerly gated scan-overwrite of text fields.
    # No code reads or writes this anymore; kept in the schema to avoid an
    # SQLite ALTER TABLE DROP migration. See docs/future-idea-per-field-locks.md
    # for the replacement design (currently unimplemented).
    manual_metadata = db.Column(db.Boolean, default=False)
    cover_locked = db.Column(db.Boolean, default=False)

    group_key = db.Column(db.String(64), nullable=True, index=True)

    pipeline_status = db.Column(db.String(50), default="scanned", nullable=False)
    scanned_at = db.Column(db.DateTime, nullable=True)
    enriched_at = db.Column(db.DateTime, nullable=True)
    polished_at = db.Column(db.DateTime, nullable=True)
    metadata_read_at = db.Column(db.DateTime, nullable=True)

    file_modified_by_colophon = db.Column(db.DateTime, nullable=True)
    upstream_synced_at = db.Column(db.DateTime, nullable=True)

    completeness_score = db.Column(db.Integer, nullable=True)

    # Reading state — shared across devices, last-write-wins with monotonic
    # status (ReadyToRead < Reading < Finished). Updated by Kobo PUTs to
    # /v1/library/<uuid>/state, and by the manual buttons in the book modal.
    read_status = db.Column(db.String(20), default="ReadyToRead", nullable=False)
    read_progress = db.Column(db.Float, nullable=True)
    read_location = db.Column(db.Text, nullable=True)
    read_last_modified = db.Column(db.DateTime, nullable=True)
    read_started_at = db.Column(db.DateTime, nullable=True)
    read_finished_at = db.Column(db.DateTime, nullable=True)
    times_started = db.Column(db.Integer, default=0, nullable=False)
    # Set when the user dismisses an "Återuppta?" card for a stale Reading
    # book. Re-shown only if read_last_modified moves past this timestamp
    # (i.e. user picks the book up again).
    forgot_dismissed_at = db.Column(db.DateTime, nullable=True)
    # User's own 1-5 rating. 0/NULL = unrated. No external/aggregate
    # rating stored — Goodreads is closed and other sources are sparse.
    user_rating = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Advances only when device-visible content/metadata or the file
    # changes — NOT on reading-progress writes. The Kobo sync delta keys
    # on this (not updated_at) to decide ChangedEntitlement vs
    # ChangedReadingState: re-shipping a full entitlement on every page
    # turn makes the Kobo archive the local file and re-download on next
    # open. Stamped by the before_flush listener below; kept <= updated_at.
    content_updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def size_text(self):
        if not self.size_bytes:
            return "0 MB"

        size_mb = self.size_bytes / 1024 / 1024

        if size_mb >= 1024:
            return f"{size_mb / 1024:.2f} GB"

        return f"{size_mb:.1f} MB"

    def short_description(self):
        if not self.description:
            return "Ingen synopsis hittades ännu. Klicka på Metadata för att lägga till en egen synopsis."

        text = " ".join(self.description.split())

        if len(text) > 450:
            return text[:450] + "..."

        return text


class Author(db.Model):
    """Canonical author entity (authority control).

    canonical_name is the display form that eventually gets written into
    files — but only once the entry has earned it: source != 'tentative'.
    See docs/author-authority-design.md ("earning the right to be written").
    """
    __tablename__ = "authors"

    id = db.Column(db.Integer, primary_key=True)
    canonical_name = db.Column(db.String(500), nullable=False)
    # The opf:file-as sort form, e.g. "Tolkien, J. R. R.".
    sort_name = db.Column(db.String(500), nullable=True)

    # Authority ids — populated by the escalation layer (step 5).
    wikidata_qid = db.Column(db.String(32), nullable=True)
    libris_id = db.Column(db.String(64), nullable=True)
    viaf_id = db.Column(db.String(64), nullable=True)

    # 'tentative' (free-text first occurrence — never written to files),
    # 'user_confirmed', 'authority_linked'. Gates file writes.
    source = db.Column(db.String(20), nullable=False, default="tentative")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuthorAlias(db.Model):
    """Variant spelling → canonical author.

    variant_key holds the layer-1 normalised form of an observed spelling
    (author_authority.normalize_author_name), so repeat occurrences of a
    known variant resolve with one indexed lookup.
    """
    __tablename__ = "author_aliases"

    id = db.Column(db.Integer, primary_key=True)
    variant_key = db.Column(db.String(500), nullable=False, unique=True, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("authors.id"), nullable=False, index=True)


class KoboDevice(db.Model):
    __tablename__ = "kobo_devices"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    api_key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    api_key_prefix = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    last_sync_at = db.Column(db.DateTime, nullable=True)
    sync_count = db.Column(db.Integer, default=0)
    revoked = db.Column(db.Boolean, default=False)


class KoboBookState(db.Model):
    """Per-device tracking of which LibraryItems a Kobo has been told about.

    Phase 2 uses last_synced_at + revision_id for delta computation and
    deletion detection. Phase 3 fills in the reading-state fields when
    we start accepting PUT /v1/library/<id>/state from the device.
    """
    __tablename__ = "kobo_book_states"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("kobo_devices.id"), nullable=False, index=True)
    library_item_id = db.Column(db.Integer, db.ForeignKey("library_items.id"), nullable=False, index=True)
    last_synced_at = db.Column(db.DateTime, default=datetime.utcnow)
    revision_id = db.Column(db.String(64), nullable=True)

    # Phase 3 fields (populated by reading-state writes from the device):
    status = db.Column(db.String(50), nullable=True)
    current_bookmark = db.Column(db.Text, nullable=True)  # JSON blob
    statistics = db.Column(db.Text, nullable=True)        # JSON blob
    state_modified_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("device_id", "library_item_id", name="uq_kobo_book_state_device_item"),
    )


# ---------------------------------------------------------------------------
# content_updated_at stamping
# ---------------------------------------------------------------------------
#
# A synced Kobo treats a ChangedEntitlement (which carries DownloadUrls) as
# "the book's content changed on the server" and archives + re-downloads its
# local copy. We must therefore only emit ChangedEntitlement when the file or
# device-visible metadata actually changed — reading-progress writes (which
# happen on every page turn) must NOT. content_updated_at is the timestamp the
# sync delta keys on; the listener below advances it only when a content
# column changes, and keeps it == updated_at for those writes so the invariant
# content_updated_at <= updated_at always holds (the delta logic relies on it).

from sqlalchemy import event as _sa_event, inspect as _sa_inspect  # noqa: E402
from sqlalchemy.orm import Session as _SASession  # noqa: E402

_DEVICE_CONTENT_COLUMNS = frozenset({
    "title", "author", "description", "series", "series_index", "isbn",
    "publisher", "language", "genres", "published_date",
    "file_path", "file_name", "extension", "cover_path", "size_bytes",
})


@_sa_event.listens_for(_SASession, "before_flush")
def _stamp_content_updated_at(session, flush_context, instances):
    # New rows: seed content_updated_at so it never exceeds updated_at.
    for obj in session.new:
        if isinstance(obj, LibraryItem) and obj.content_updated_at is None:
            obj.content_updated_at = obj.updated_at or datetime.utcnow()

    # Updates: only stamp when a device-visible content column changed.
    for obj in session.dirty:
        if not isinstance(obj, LibraryItem):
            continue
        state = _sa_inspect(obj)
        if any(
            state.attrs[col].history.has_changes()
            for col in _DEVICE_CONTENT_COLUMNS
        ):
            now = datetime.utcnow()
            obj.content_updated_at = now
            obj.updated_at = now


@_sa_event.listens_for(_SASession, "before_flush")
def _reset_author_resolution(session, flush_context, instances):
    """Invalidate the registry link whenever `author` changes hands.

    Any code path that rewrites item.author (scan re-read, enrichment,
    modal save, group sync) silently invalidates a previous resolution.
    Resetting here — instead of at every call site — guarantees a stale
    author_id can never survive an author edit. The pending pass on the
    next scan/upload re-resolves.

    Exception: when author_id or author_status changed in the same flush,
    the writer is the resolver itself or a deliberate user confirmation
    (step-4 combobox sets both) — leave it alone. Registry cascades
    (rename/merge relabel items to the same author_id, so no FK change
    registers) suppress via session.info — see keep_author_links() in
    app/services/author_resolver.py.
    """
    if session.info.get("suppress_author_reset"):
        return
    for obj in session.dirty:
        if not isinstance(obj, LibraryItem):
            continue
        state = _sa_inspect(obj)
        if not state.attrs["author"].history.has_changes():
            continue
        if (state.attrs["author_id"].history.has_changes()
                or state.attrs["author_status"].history.has_changes()):
            continue
        obj.author_id = None
        obj.author_status = None
