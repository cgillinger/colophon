# Colophon – e-book metadata manager
"""API-key generation and lookup for Kobo devices.

A device's URL contains a 32-character hex token (e.g.
http://host:5055/kobo/<token>/...). The token itself is never stored;
only its SHA-256 hash lives in the kobo_devices table. The first 8
characters are stored in plaintext so the settings UI can identify
a device without needing the full key.
"""
import hashlib
import re
import secrets
from datetime import datetime

from app.models import KoboDevice, db

TOKEN_BYTES = 16  # 32 hex chars
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def generate_token() -> str:
    """Return a fresh 32-char hex token suitable for use in a Kobo URL."""
    return secrets.token_hex(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def is_valid_token_format(token: str) -> bool:
    return bool(token) and bool(_TOKEN_RE.match(token))


def create_device(name: str) -> tuple[KoboDevice, str]:
    """Create a new device row and return (device, plaintext_token).

    The plaintext token is shown to the user exactly once; only the
    hash is persisted.
    """
    token = generate_token()
    device = KoboDevice(
        name=(name or "Unnamed device").strip()[:200],
        api_key_hash=hash_token(token),
        api_key_prefix=token[:8],
    )
    db.session.add(device)
    db.session.commit()
    return device, token


def find_device_by_token(token: str) -> KoboDevice | None:
    if not is_valid_token_format(token):
        return None
    device = KoboDevice.query.filter_by(api_key_hash=hash_token(token)).first()
    if device is None or device.revoked:
        return None
    return device


def touch_device(device: KoboDevice, mark_sync: bool = False) -> None:
    """Update last-seen timestamps. Cheap, called on every request."""
    now = datetime.utcnow()
    device.last_seen_at = now
    if mark_sync:
        device.last_sync_at = now
        device.sync_count = (device.sync_count or 0) + 1
    db.session.commit()


def revoke_device(device_id: int) -> bool:
    device = KoboDevice.query.get(device_id)
    if device is None:
        return False
    db.session.delete(device)
    db.session.commit()
    return True


def list_devices() -> list[KoboDevice]:
    return KoboDevice.query.order_by(KoboDevice.created_at.desc()).all()
