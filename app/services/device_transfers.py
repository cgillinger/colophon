# Colophon – e-book metadata manager
"""Channel-aware sync — the ledger of books Colophon put on a device by USB.

The Kobo's firmware cannot tell that a sideloaded file (ContentID = a path) and
a cloud entitlement (ContentID = a UUID) are the same book. Send a book both
ways and it appears twice on the device — the failure mode that duplicated
~1900 books on a Bookstation user's reader, which is where this design comes
from.

The rule is **one channel per book and device**, enforced server-side: every
USB transfer Colophon makes is recorded here, and the wireless sync skips those
books for that device. The ledger is therefore not an optional extra — a USB
transfer feature without it *is* the duplicate bug. Build them together.

Identity of a mounted device, in order of confidence:

1. **The wireless token in its own config.** Colophon writes
   ``api_endpoint=<base>/kobo/<token>`` into ``Kobo eReader.conf`` during
   wireless setup, so the token can be read straight off the mount. We store
   only its hash, so the lookup is hash-and-match — exact, no fuzzy fallback.
2. **The serial number** from ``.kobo/version``, for a device that has never
   been configured wirelessly. Kept as a secondary key so bookkeeping written
   before a device was paired still matches afterwards.

Books copied to a device outside Colophon have no ledger row. They can't be
prevented, only detected — the compare view flags them, and "adopt" writes the
row retroactively so the wireless sync starts skipping them.
"""
import logging
import os
import re

from app.models import DeviceTransfer, KoboDevice, db
from app.services.kobo_auth import hash_token, is_valid_token_format
from app.services.kobo_conf import decode_conf

logger = logging.getLogger(__name__)

# Where the Kobo keeps the two files that identify it.
CONF_RELPATH = os.path.join(".kobo", "Kobo", "Kobo eReader.conf")
VERSION_RELPATH = os.path.join(".kobo", "version")

# api_endpoint=http://host:5055/kobo/<token>. Colophon's tokens are 32 hex
# chars; the class stays generous so a future token format still matches.
_CONF_TOKEN_RE = re.compile(
    r"^\s*api_endpoint\s*=\s*\S*/kobo/([A-Za-z0-9._~-]+)\s*$", re.MULTILINE
)

# A conf is ~10–30 KB; refuse to slurp something absurd off a mount.
MAX_CONF_BYTES = 200_000


def read_device_serial(mount_path) -> str | None:
    """Serial number from ``.kobo/version`` (first CSV field)."""
    try:
        with open(os.path.join(mount_path, VERSION_RELPATH), "rb") as fh:
            first = fh.readline(4096).decode("utf-8", "replace").strip()
    except OSError:
        return None
    serial = first.split(",")[0].strip()
    return serial or None


def read_device_token(mount_path) -> str | None:
    """The wireless token from the device's own config, or ``None``.

    Decoded through :func:`kobo_conf.decode_conf` rather than a plain UTF-8
    read: confs turn up as UTF-16-with-BOM, and reading one as UTF-8 with
    replacement characters makes the regex miss — the device would then look
    unconfigured instead of merely differently encoded.
    """
    try:
        with open(os.path.join(mount_path, CONF_RELPATH), "rb") as fh:
            raw = fh.read(MAX_CONF_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_CONF_BYTES:
        logger.warning("device_transfers: %s conf is implausibly large, ignoring", mount_path)
        return None
    try:
        text, _encoding = decode_conf(raw)
    except Exception:
        return None
    match = _CONF_TOKEN_RE.search(text)
    if not match:
        return None
    token = match.group(1)
    # A stock device points at storeapi.kobo.com and has no /kobo/<token> at
    # all; anything that doesn't look like one of ours isn't one of ours.
    return token if is_valid_token_format(token) else None


def device_for_mount(mount_path) -> tuple[KoboDevice | None, str | None]:
    """``(device, serial)`` for a mounted Kobo.

    ``device`` is the registered KoboDevice when the mount carries a token we
    issued, else ``None``. ``serial`` is returned regardless, because it is the
    only handle we have on a device that was never paired wirelessly.
    """
    serial = read_device_serial(mount_path)
    token = read_device_token(mount_path)
    device = None
    if token:
        device = KoboDevice.query.filter_by(api_key_hash=hash_token(token)).first()
        if device is not None and device.revoked:
            device = None
    if device is not None and serial and not device.device_serial:
        # Learn the serial the first time we see the device over USB, so the
        # two identities are joined from then on.
        device.device_serial = serial
    return device, serial


def record_transfer(session, item_id, device=None, serial=None,
                    label=None, method="usb") -> bool:
    """Record that a book was put on a device. Idempotent per book+device.

    Returns ``True`` when a new row was written, ``False`` when an existing one
    was found (and enriched with anything newer we now know). An existing row
    is *completed* rather than duplicated, so a transfer booked against a bare
    serial converges onto the device once it is paired.

    The caller commits.
    """
    device_id = getattr(device, "id", device)
    if device_id is None and not serial:
        return False

    query = DeviceTransfer.query.filter_by(item_id=item_id)
    conditions = []
    if device_id is not None:
        conditions.append(DeviceTransfer.device_id == device_id)
    if serial:
        conditions.append(DeviceTransfer.device_serial == serial)
    existing = query.filter(db.or_(*conditions)).first()

    if existing is not None:
        if device_id is not None:
            existing.device_id = device_id
        if serial:
            existing.device_serial = serial
        if label:
            existing.device_label = label
        existing.method = method or existing.method
        return False

    session.add(DeviceTransfer(
        item_id=item_id,
        device_id=device_id,
        device_serial=serial,
        device_label=label,
        method=method or "usb",
    ))
    return True


def remove_transfer(session, item_id, device=None, serial=None) -> int:
    """Forget a transfer — the book left the device, or should go back to WiFi.

    Returns the number of rows removed. The caller commits.
    """
    device_id = getattr(device, "id", device)
    if device_id is None and not serial:
        return 0
    conditions = []
    if device_id is not None:
        conditions.append(DeviceTransfer.device_id == device_id)
    if serial:
        conditions.append(DeviceTransfer.device_serial == serial)
    rows = DeviceTransfer.query.filter(
        DeviceTransfer.item_id == item_id, db.or_(*conditions)
    ).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def transferred_item_ids(device=None, serial=None) -> set[int]:
    """Books already on this device via USB — the set the WiFi sync skips.

    Pass the device; its stored serial is picked up automatically so rows
    booked before it was paired still match.
    """
    device_id = getattr(device, "id", device)
    if device_id is not None and not serial:
        row = KoboDevice.query.get(device_id) if not hasattr(device, "device_serial") else device
        serial = getattr(row, "device_serial", None)
    if device_id is None and not serial:
        return set()

    conditions = []
    if device_id is not None:
        conditions.append(DeviceTransfer.device_id == device_id)
    if serial:
        conditions.append(DeviceTransfer.device_serial == serial)
    rows = (
        DeviceTransfer.query
        .with_entities(DeviceTransfer.item_id)
        .filter(db.or_(*conditions))
        .distinct()
        .all()
    )
    return {r.item_id for r in rows}
