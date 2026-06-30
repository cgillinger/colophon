# Colophon – e-book metadata manager
"""In-browser e-book reader.

Renders a book in the browser (foliate-js) and syncs reading progress through
the *same* canonical LibraryItem fields the Kobo sync uses (see
services/reading_state.py), so reading in the app and on a Kobo stay in
lock-step for free.

Formats: EPUB (incl. fixed-layout) plus MOBI/AZW3 — foliate-js carries the
parsers for all three and dispatches on the file's magic bytes, so we just hand
it the raw bytes. PDF is not yet supported (its parser isn't vendored). DRM'd
MOBI/AZW3 fail to open and surface the generic load-error overlay.

Offline reading is supported (v1.26.0): the reader's "save for offline" button
caches the book file + reader shell into a persistent Cache Storage bucket via
the service worker (app/templates/sw.js), and reading progress is mirrored to
localStorage so a saved book resumes — and later re-syncs — with no connection.
Requires a secure context (HTTPS), e.g. via Tailscale Serve.

Routes:
  GET  /reader/<id>         — the reader page
  GET  /reader/<id>/file    — the raw EPUB bytes (a stable, token-free URL the
                              service worker caches for offline reading)
  POST /reader/<id>/progress — persist reading progress (percent + status)
"""
import logging
import os
import re
from datetime import datetime

from flask import (
    Blueprint,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from app.models import db
from app.routes.helpers import get_item_or_404
from app.services.drm import file_has_drm
from app.services.reading_state import apply_reading_state

logger = logging.getLogger(__name__)

reader_bp = Blueprint("reader", __name__, url_prefix="/reader")

# Formats the in-browser reader can render, mapped to the Content-Type we serve
# the raw bytes with. foliate-js sniffs the actual format from the file's magic
# bytes, so these mimetypes are cosmetic correctness rather than load-bearing;
# the key set is the real gate — the file route 404s anything outside it so we
# never hand the reader a format it can't open. (.azw is old MOBI-in-disguise.)
READER_MIMETYPES = {
    ".epub": "application/epub+zip",
    ".mobi": "application/x-mobipocket-ebook",
    ".azw": "application/x-mobipocket-ebook",
    ".azw3": "application/vnd.amazon.ebook",
}
READABLE_EXTENSIONS = set(READER_MIMETYPES)


def _is_readable(item):
    return (item.extension or "").lower() in READABLE_EXTENSIONS


def _share_extension(item):
    """The file's real extension, dot-prefixed and lower-cased (e.g. '.mobi'),
    falling back to the on-disk suffix and finally '.epub'."""
    ext = (item.extension or "").lower() or os.path.splitext(item.file_path or "")[1].lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return ext or ".epub"


def _share_filename(item):
    """A human-friendly download name for the share sheet, keeping the file's
    real extension so the recipient gets a correctly-typed file.

    Prefer 'Title - Author.<ext>' (what a recipient wants to see in their
    library), sanitised for cross-platform filenames; fall back to the real
    on-disk basename when there's no usable title.
    """
    ext = _share_extension(item)
    title = (item.title or "").strip()
    author = (item.author or "").strip()
    if title:
        stem = f"{title} - {author}" if author else title
        stem = re.sub(r'[\\/:*?"<>|]+', " ", stem)   # illegal on Win/macOS
        stem = re.sub(r"\s+", " ", stem).strip()[:120]
        if stem:
            return f"{stem}{ext}"
    return os.path.basename(item.file_path or "") or f"book{ext}"


def _can_share(item):
    """A book is shareable from the reader when it's a readable format whose
    file exists and carries no DRM. DRM detection is on-demand (per-format, see
    services/drm.py) rather than a stored flag, so it can never go stale.

    Covers EPUB and MOBI/AZW3 — handing a recipient the raw file means vouching
    it's DRM-free, and file_has_drm() understands all three. PDF share lands
    with PDF reading (it can't reach the in-reader share button until then)."""
    if not _is_readable(item) or not item.file_path or not os.path.exists(item.file_path):
        return False
    return not file_has_drm(item.file_path, item.extension)


@reader_bp.route("/<int:item_id>")
def read_book(item_id):
    item = get_item_or_404(item_id)
    if not _is_readable(item):
        abort(404)
    return render_template(
        "reader.html",
        item=item,
        file_url=url_for("reader.book_file", item_id=item.id),
        progress_url=url_for("reader.update_progress", item_id=item.id),
        initial_progress=item.read_progress or 0,
        read_status=item.read_status or "ReadyToRead",
        can_share=_can_share(item),
        share_filename=_share_filename(item),
        share_mimetype=READER_MIMETYPES.get(_share_extension(item), "application/octet-stream"),
    )


@reader_bp.route("/<int:item_id>/file")
def book_file(item_id):
    """Serve the raw book bytes to the browser reader.

    Mirrors the cover_item guard in routes/metadata.py: 404 if the file has
    gone missing on disk rather than letting send_file raise. We serve the
    *raw* file (for EPUB, not the kepubified variant the Kobo download path
    produces) — foliate-js reads plain EPUB/MOBI/AZW3 and sniffs the format
    from the bytes regardless of the Content-Type we declare.
    """
    item = get_item_or_404(item_id)
    if not _is_readable(item):
        abort(404)
    if not item.file_path or not os.path.exists(item.file_path):
        logger.warning("Reader: file missing on disk for item %s: %s", item.id, item.file_path)
        abort(404)
    ext = (item.extension or "").lower()
    return send_file(
        item.file_path,
        mimetype=READER_MIMETYPES.get(ext, "application/octet-stream"),
        download_name=os.path.basename(item.file_path),
        conditional=True,
    )


@reader_bp.route("/<int:item_id>/progress", methods=["POST"])
def update_progress(item_id):
    """Persist reading progress from the browser reader.

    Goes through the shared apply_reading_state() so the monotonic /
    last-write-wins rules are identical to the Kobo PUT path, and bumps
    read_last_modified so the next Kobo sync delta carries the change to the
    device. We never pass a location: the browser resumes by percent, and not
    writing read_location avoids clobbering the Kobo's (incompatible) location.
    """
    item = get_item_or_404(item_id)
    payload = request.get_json(silent=True) or {}

    status = payload.get("status") or "Reading"
    if status not in ("Reading", "Finished"):
        status = "Reading"

    percent = payload.get("percent")
    if percent is not None:
        try:
            percent = max(0.0, min(100.0, float(percent)))
        except (TypeError, ValueError):
            percent = None

    applied = apply_reading_state(
        item,
        status,
        progress=percent,
        modified_at=datetime.utcnow(),
    )
    if applied:
        db.session.commit()

    return jsonify(
        {
            "ok": True,
            "applied": applied,
            "read_status": item.read_status,
            "read_progress": item.read_progress,
        }
    )
