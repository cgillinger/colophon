# Colophon – e-book metadata manager
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class LibraryItem(db.Model):
    __tablename__ = "library_items"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(500), nullable=False)
    author = db.Column(db.String(500), nullable=True)
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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
