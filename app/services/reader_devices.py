# Colophon – e-book metadata manager
"""Tokens for OPDS/KOSync e-readers (CrossPoint, KOReader).

Same scheme as the Kobo (services/kobo_auth.py): a 32-character hex token in
the URL path, only its SHA-256 hash stored, the first 8 characters kept so the
settings page can tell devices apart. One token covers both URLs a device
needs — ``/opds/<token>`` for the catalogue and ``/kosync/<token>`` for
reading position.
"""
from datetime import datetime

from app.models import ReaderDevice, db
from app.services.kobo_auth import generate_token, hash_token, is_valid_token_format


def create_device(name: str, language: str | None = None) -> tuple[ReaderDevice, str]:
    """Create a device and return ``(device, plaintext_token)``.

    The token is shown to the user once; only the hash is persisted.
    """
    token = generate_token()
    device = ReaderDevice(
        name=(name or "E-reader").strip()[:200],
        api_key_hash=hash_token(token),
        api_key_prefix=token[:8],
        language=language,
    )
    db.session.add(device)
    db.session.commit()
    return device, token


def find_device_by_token(token: str) -> ReaderDevice | None:
    if not is_valid_token_format(token):
        return None
    device = ReaderDevice.query.filter_by(api_key_hash=hash_token(token)).first()
    if device is None or device.revoked:
        return None
    return device


def touch_device(device: ReaderDevice, mark_sync: bool = False) -> None:
    now = datetime.utcnow()
    device.last_seen_at = now
    if mark_sync:
        device.last_sync_at = now
    db.session.commit()


def revoke_device(device_id: int) -> bool:
    device = ReaderDevice.query.get(device_id)
    if device is None:
        return False
    db.session.delete(device)
    db.session.commit()
    return True


def list_devices() -> list[ReaderDevice]:
    return ReaderDevice.query.order_by(ReaderDevice.created_at.desc()).all()
