# Colophon – e-book metadata manager
"""Delta-sync logic for the Kobo library/sync endpoint.

A sync token is opaque to the Kobo client — it just echoes it back on
the next request. Internally we use a small JSON document:

    {"v": 2, "since": "...", "hw": "...", "cur": 417, "full": false}

`since` is the watermark from the last *completed* round. `hw`
(high_water) is the ceiling of the round currently in flight — None
means no round is in flight. `cur` is the keyset cursor: the last
LibraryItem.id we walked past. `full` means this round ignores `since`
and sweeps everything below the ceiling.

Two properties are load-bearing, and both were bugs before v1.48.0:

**The cursor keys on `id`, not on `updated_at`.** The Kobo PUTs reading
state between page fetches, which bumps `updated_at` (it has `onupdate`)
and moves the row to the end of an `ORDER BY updated_at` sort. With
OFFSET everything after it slid one step and the row on the page
boundary was skipped — permanently, because `since` was then advanced
past it. `id` is immutable and no concurrent write can reorder it. The
`high_water` ceiling, set once when the round begins and carried in the
token, additionally makes the row set monotonically shrinking: a row can
leave the window but never enter it, so the walk terminates.

**The ledger, not the token's `since`, decides what we say about a
book.** Deriving "the content changed" from `since` means a device that
lost its token gets ChangedEntitlement for the entire library — the very
download storm the delta sync exists to prevent. We ask
`kobo_book_states` instead, so an interrupted or restarted walk never
costs more than what is actually missing.

Version 1 (`{"v":1,"since":...,"page":N}`) is spent: a device mid-walk
through an old round echoes it back after the upgrade, and it must be
rejected as "no token" rather than misread as round state.
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

# Max number of wrappers in one response.
SYNC_PAGE_SIZE = 100
# Max rows examined per request. Without a budget a round over an unchanged
# library returns one empty page per 100 rows; with it the whole thing is
# settled in a single request answering [] + done.
SYNC_SCAN_BUDGET = 2000
TOKEN_VERSION = 2


@dataclass
class SyncToken:
    since: datetime | None = None
    high_water: datetime | None = None
    cursor: int = 0
    full: bool = False

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
        if not isinstance(data, dict) or data.get("v") != TOKEN_VERSION:
            return cls()
        return cls(
            since=_parse_iso(data["since"]) if data.get("since") else None,
            high_water=_parse_iso(data["hw"]) if data.get("hw") else None,
            cursor=int(data.get("cur") or 0),
            full=bool(data.get("full")),
        )

    def encode(self) -> str:
        payload = {
            "v": TOKEN_VERSION,
            "since": _format_iso(self.since) if self.since else None,
            "hw": _format_iso(self.high_water) if self.high_water else None,
            "cur": int(self.cursor or 0),
            "full": bool(self.full),
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
    reading_state_items: list[LibraryItem] = field(default_factory=list)
    deleted_item_ids: list[int] = field(default_factory=list)
    # item id -> the UUID this device was told, so a withdrawal names the same
    # book the device actually holds even after its row is gone.
    deleted_revisions: dict[int, str] = field(default_factory=dict)
    next_token: SyncToken = field(default_factory=SyncToken)
    has_more: bool = False
    # True when the mass-delete guard suppressed a delete signal. Surfaced so
    # the caller can tell the operator there is something to unblock — without
    # it the guard is a silent one-way trap: the stale KoboBookState rows are
    # never cleared, so every later sync recomputes and re-suppresses the same
    # oversized delete, forever.
    blocked_mass_delete: bool = False
    # Rows examined this request. Diagnostic only — an unchanged library
    # scans many rows and emits nothing, and that should be visible in logs.
    scanned: int = 0


def compute_delta(
    device_id: int,
    incoming_token: SyncToken,
    epub_items_query,
    page_size: int = SYNC_PAGE_SIZE,
    scan_budget: int = SYNC_SCAN_BUDGET,
    allow_mass_delete: bool = False,
) -> SyncDelta:
    """Return the entitlements that should be sent to one device for
    one sync request.

    `epub_items_query` is a callable returning a base SQLAlchemy query
    over the EPUB LibraryItems (injected so this stays unit-testable).
    """
    # Which items has this device already seen, under which UUID, and in
    # what shape? The revision is what we must quote back when withdrawing a
    # book: by then the row may be gone, so it cannot be recomputed from the
    # item. The two timestamps are what the classifier compares against.
    ledger = {
        row.library_item_id: row
        for row in KoboBookState.query.filter_by(device_id=device_id).all()
    }
    seen_ids = set(ledger)

    # A new round sets the ceiling once; a continuing one carries it.
    if incoming_token.high_water is None:
        high_water = datetime.utcnow()
        cursor = 0
    else:
        high_water = incoming_token.high_water
        cursor = int(incoming_token.cursor or 0)

    since = incoming_token.since
    # An empty ledger means we have no record of having sent this device
    # anything — it may still hold a token from a sync we've since lost track
    # of (operator cleared kobo_book_states, row dropped). Sweep everything;
    # the ledger decides what is actually said about each book, so a full
    # sweep over an already-synced library emits nothing, it just costs a scan.
    full = bool(incoming_token.full) or not seen_ids

    # Channel-aware sync: never offer a cloud entitlement for a book this
    # device already holds as a USB-transferred file. The Kobo can't tell the
    # two apart (a sideload's ContentID is a path, an entitlement's is a UUID),
    # so it would simply show the book twice.
    #
    # Only books it has NOT already been sent wirelessly are withheld. One it
    # already has as a cloud book must keep receiving updates — dropping it
    # from the delta wouldn't remove it from the device, it would just freeze
    # its reading state. And `current_ids` below is deliberately left
    # unfiltered, so withholding a book never reads as "deleted".
    #
    # Fails open: a broken ledger should degrade to a possible duplicate, not
    # to an empty library.
    try:
        from app.services.device_transfers import transferred_item_ids

        excluded = transferred_item_ids(device_id) - seen_ids
    except Exception:
        logger.debug("kobo_sync: USB ledger lookup failed", exc_info=True)
        excluded = set()
    if excluded:
        logger.info(
            "kobo_sync: withholding %d book(s) from device %s — already there via USB",
            len(excluded), device_id,
        )

    # Deletion detection only on the first page of a round — otherwise we'd
    # emit deletes once per page.
    deleted_ids: list[int] = []
    blocked_mass_delete = False
    if cursor == 0 and seen_ids:
        current_ids = {
            row.id
            for row in epub_items_query().with_entities(LibraryItem.id).all()
        }
        proposed_deletes = sorted(seen_ids - current_ids)

        # Safety net: refuse to emit a mass-delete that looks like a glitch
        # rather than user intent. Anything above MASS_DELETE_THRESHOLD of
        # the device's known set is treated as suspicious — we skip the
        # delete signal entirely and log it so an operator can investigate.
        # Without this, a transient DB-read failure mid-sync could tell the
        # Kobo "every book is gone" → device withdraws downloaded copies.
        MASS_DELETE_THRESHOLD = 0.20  # 20 %
        oversized = proposed_deletes and len(proposed_deletes) > max(
            5, int(len(seen_ids) * MASS_DELETE_THRESHOLD)
        )
        if oversized and not allow_mass_delete:
            logger.warning(
                "kobo_sync: refusing mass-delete signal (%d of %d seen items "
                "would be marked deleted; >%.0f%% threshold). Treating as a "
                "glitch. If the library really did shrink this much, set "
                "KOBO_ALLOW_MASS_DELETE to unblock the next sync.",
                len(proposed_deletes), len(seen_ids), MASS_DELETE_THRESHOLD * 100,
            )
            deleted_ids = []
            blocked_mass_delete = True
        else:
            if oversized:
                logger.warning(
                    "kobo_sync: emitting an oversized delete signal (%d of %d "
                    "seen items) because the operator unblocked it.",
                    len(proposed_deletes), len(seen_ids),
                )
            deleted_ids = proposed_deletes

        # Completeness repair: if the library holds something the ledger
        # doesn't know about, `since` cannot be trusted this round. The
        # ledger decides what is said about each book anyway, so an extra
        # sweep only costs scan time.
        if current_ids - seen_ids - excluded:
            full = True

    new_items: list[LibraryItem] = []
    changed_items: list[LibraryItem] = []
    reading_state_items: list[LibraryItem] = []
    scanned = 0
    has_more = False

    base_q = epub_items_query()
    if excluded:
        base_q = base_q.filter(~LibraryItem.id.in_(excluded))
    base_q = base_q.filter(LibraryItem.updated_at <= high_water)
    if not full and since is not None:
        base_q = base_q.filter(LibraryItem.updated_at > since)
    base_q = base_q.order_by(LibraryItem.id.asc())

    while True:
        chunk = base_q.filter(LibraryItem.id > cursor).limit(page_size).all()
        if not chunk:
            break
        for item in chunk:
            cursor = item.id
            scanned += 1
            sent = ledger.get(item.id)
            if sent is None:
                new_items.append(item)
            else:
                # Already on the device. Distinguish a content change (must
                # re-ship the whole entitlement, device may re-download) from
                # a reading-progress-only change (must NOT, or the Kobo
                # archives the local file and re-downloads on next open).
                content_at = item.content_updated_at or item.updated_at
                if _newer(content_at, sent.sent_content_at):
                    changed_items.append(item)
                elif _newer(item.updated_at, sent.sent_updated_at):
                    reading_state_items.append(item)
            emitted = len(new_items) + len(changed_items) + len(reading_state_items)
            if emitted >= page_size:
                break
        emitted = len(new_items) + len(changed_items) + len(reading_state_items)
        if emitted >= page_size or scanned >= scan_budget:
            has_more = bool(
                base_q.filter(LibraryItem.id > cursor).limit(1).all()
            )
            break

    if has_more:
        next_token = SyncToken(
            since=since, high_water=high_water, cursor=cursor, full=full
        )
    else:
        # Round complete. `since` becomes the ceiling, NOT max(updated_at):
        # anything that failed to be reported has, by construction,
        # updated_at > high_water and is caught by the next round.
        next_token = SyncToken(since=high_water, high_water=None, cursor=0, full=False)

    return SyncDelta(
        new_items=new_items,
        changed_items=changed_items,
        reading_state_items=reading_state_items,
        deleted_item_ids=deleted_ids,
        deleted_revisions={
            i: ledger[i].revision_id
            for i in deleted_ids
            if i in ledger and ledger[i].revision_id
        },
        next_token=next_token,
        has_more=has_more,
        blocked_mass_delete=blocked_mass_delete,
        scanned=scanned,
    )


def _newer(value: datetime | None, reference: datetime | None) -> bool:
    """value > reference, where a missing reference means "yes".

    A ledger row without timestamps predates the columns and is re-emitted
    once; the backfill in services/database.py exists so that never happens
    to a whole library at upgrade time.
    """
    if value is None:
        return False
    if reference is None:
        return True
    return value > reference


def record_sync(device_id: int, items: Iterable[LibraryItem], revision_fn) -> None:
    """Upsert a KoboBookState row for every item we're sending.

    `revision_fn` maps a LibraryItem.id → the RevisionId UUID we emit
    (so we have it for change-detection later).
    """
    if not items:
        return
    now = datetime.utcnow()
    for item in items:
        # Capture the shape we are shipping, so the next round can tell a
        # content change from a page turn without consulting the token.
        sent_updated = item.updated_at
        sent_content = item.content_updated_at or item.updated_at
        existing = KoboBookState.query.filter_by(
            device_id=device_id, library_item_id=item.id
        ).first()
        if existing is None:
            db.session.add(KoboBookState(
                device_id=device_id,
                library_item_id=item.id,
                last_synced_at=now,
                revision_id=revision_fn(item),
                sent_updated_at=sent_updated,
                sent_content_at=sent_content,
            ))
        else:
            existing.last_synced_at = now
            existing.revision_id = revision_fn(item)
            existing.sent_updated_at = sent_updated
            existing.sent_content_at = sent_content
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


def clear_ledger(device_id: int) -> int:
    """Forget everything we've told this device. The next sync delivers the
    whole library again.

    The operator escape hatch behind "Force full resync". Needed because the
    protocol has no "just refresh the cover" signal: the device only fetches
    a cover when it ingests an entitlement, so a library that already has
    wrong covers out on a device can only be repaired by re-shipping.
    """
    count = KoboBookState.query.filter(
        KoboBookState.device_id == device_id
    ).delete(synchronize_session=False)
    db.session.commit()
    return count or 0
