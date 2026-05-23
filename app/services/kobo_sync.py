# Colophon – e-book metadata manager
"""Delta-sync logic for the Kobo library/sync endpoint.

A sync token is opaque to the Kobo client — it just echoes it back on
the next request. Internally we use a small JSON document:

    {"v": 1, "since": "2026-05-22T10:14:33.000Z", "page": 0}

`since` is the highest `updated_at` we've already returned to this
device. `page` lets us paginate within a single sync run.

The protocol bumps `v` if we ever change the shape; an unknown
version is treated as "no token" (= full re-sync).
"""
import base64
import binascii
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from app.models import KoboBookState, LibraryItem, db

logger = logging.getLogger(__name__)

SYNC_PAGE_SIZE = 200
TOKEN_VERSION = 1


@dataclass
class SyncToken:
    since: datetime | None = None
    page: int = 0

    @classmethod
    def parse(cls, header_value: str | None) -> "SyncToken":
        if not header_value:
            return cls()
        try:
            raw = base64.urlsafe_b64decode(header_value.encode("ascii"))
            data = json.loads(raw.decode("utf-8"))
        except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
            logger.info("Kobo sync: unparseable token, treating as full sync: %s", exc)
            return cls()
        if data.get("v") != TOKEN_VERSION:
            return cls()
        since_str = data.get("since")
        since = _parse_iso(since_str) if since_str else None
        page = int(data.get("page") or 0)
        return cls(since=since, page=page)

    def encode(self) -> str:
        payload = {
            "v": TOKEN_VERSION,
            "since": _format_iso(self.since) if self.since else None,
            "page": self.page,
        }
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")


def _format_iso(dt: datetime) -> str:
    # Full microsecond precision — this is the internal token, not a
    # field the Kobo client reads. We need it to round-trip exactly so
    # `updated_at > since` excludes items already sent.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_iso(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1]
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass
class SyncDelta:
    """Result of one page of delta computation."""
    new_items: list[LibraryItem] = field(default_factory=list)
    changed_items: list[LibraryItem] = field(default_factory=list)
    deleted_item_ids: list[int] = field(default_factory=list)
    next_token: SyncToken = field(default_factory=SyncToken)
    has_more: bool = False


def compute_delta(
    device_id: int,
    incoming_token: SyncToken,
    epub_items_query,
    page_size: int = SYNC_PAGE_SIZE,
) -> SyncDelta:
    """Return the entitlements that should be sent to one device for
    one sync request.

    `epub_items_query` is a callable returning a base SQLAlchemy query
    over the EPUB LibraryItems (injected so this stays unit-testable).
    """
    base_q = epub_items_query()

    # Which items has this device already seen?
    seen_ids = {
        row.library_item_id
        for row in KoboBookState.query.filter_by(device_id=device_id).all()
    }

    # If we have no record of having sent anything to this device,
    # ignore the incoming token's `since` and re-send everything. The
    # device may still be holding a token from a previous sync that
    # we've since lost track of (eg. operator cleared kobo_book_states
    # manually, or the row got dropped). Without this, every sync would
    # come back empty because the filter `updated_at > since` matches
    # nothing for an unchanged library.
    effective_since = incoming_token.since if seen_ids else None

    if effective_since is not None:
        base_q = base_q.filter(LibraryItem.updated_at > effective_since)
    base_q = base_q.order_by(LibraryItem.updated_at.asc(), LibraryItem.id.asc())

    offset = incoming_token.page * page_size
    fetched = base_q.offset(offset).limit(page_size + 1).all()
    has_more = len(fetched) > page_size
    items_this_page = fetched[:page_size]

    new_items: list[LibraryItem] = []
    changed_items: list[LibraryItem] = []
    for item in items_this_page:
        if item.id in seen_ids:
            changed_items.append(item)
        else:
            new_items.append(item)

    # Deletion detection only on the first page of a paginated sync —
    # otherwise we'd emit deletes once per page.
    deleted_ids: list[int] = []
    if incoming_token.page == 0 and seen_ids:
        current_ids = {
            row.id
            for row in epub_items_query().with_entities(LibraryItem.id).all()
        }
        deleted_ids = sorted(seen_ids - current_ids)

    # Compute outgoing token
    if has_more:
        next_token = SyncToken(since=effective_since, page=incoming_token.page + 1)
    else:
        # Done. Advance `since` to the latest updated_at we've seen,
        # falling back to the effective_since value if we sent nothing.
        max_seen = max(
            (i.updated_at for i in items_this_page if i.updated_at is not None),
            default=None,
        )
        if max_seen is None:
            new_since = effective_since
        elif effective_since is None or max_seen > effective_since:
            new_since = max_seen
        else:
            new_since = effective_since
        next_token = SyncToken(since=new_since, page=0)

    return SyncDelta(
        new_items=new_items,
        changed_items=changed_items,
        deleted_item_ids=deleted_ids,
        next_token=next_token,
        has_more=has_more,
    )


def record_sync(device_id: int, items: Iterable[LibraryItem], revision_fn) -> None:
    """Upsert a KoboBookState row for every item we're sending.

    `revision_fn` maps a LibraryItem.id → the RevisionId UUID we emit
    (so we have it for change-detection later).
    """
    if not items:
        return
    now = datetime.utcnow()
    for item in items:
        existing = KoboBookState.query.filter_by(
            device_id=device_id, library_item_id=item.id
        ).first()
        if existing is None:
            db.session.add(KoboBookState(
                device_id=device_id,
                library_item_id=item.id,
                last_synced_at=now,
                revision_id=revision_fn(item.id),
            ))
        else:
            existing.last_synced_at = now
            existing.revision_id = revision_fn(item.id)
    db.session.commit()


def forget_items(device_id: int, item_ids: Iterable[int]) -> None:
    """Remove KoboBookState rows for items we just told the device
    about as deletions. Otherwise we'd emit the same deletion forever."""
    ids = list(item_ids)
    if not ids:
        return
    KoboBookState.query.filter(
        KoboBookState.device_id == device_id,
        KoboBookState.library_item_id.in_(ids),
    ).delete(synchronize_session=False)
    db.session.commit()
