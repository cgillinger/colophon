# Colophon – e-book metadata manager
"""In-browser EPUB reader.

Step 1 is online-only: it renders a book in the browser (foliate-js) and
syncs reading progress through the *same* canonical LibraryItem fields the
Kobo sync uses (see services/reading_state.py), so reading in the app and on
a Kobo stay in lock-step for free. Offline caching of book content is
deliberately deferred (see docs/TODO.md).

Routes:
  GET  /reader/<id>         — the reader page
  GET  /reader/<id>/file    — the raw EPUB bytes (a stable, token-free URL so
                              a future "download for offline" step can cache it)
  POST /reader/<id>/progress — persist reading progress (percent + status)
"""
import logging
import os
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
from app.services.reading_state import apply_reading_state

logger = logging.getLogger(__name__)

reader_bp = Blueprint("reader", __name__, url_prefix="/reader")

# Formats the in-browser reader can render. EPUB is the tested path in step 1;
# the file route is gated to this set so we never hand the reader a format it
# can't open.
READABLE_EXTENSIONS = {".epub"}


def _is_readable(item):
    return (item.extension or "").lower() in READABLE_EXTENSIONS


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
    )


@reader_bp.route("/<int:item_id>/file")
def book_file(item_id):
    """Serve the raw EPUB bytes to the browser reader.

    Mirrors the cover_item guard in routes/metadata.py: 404 if the file has
    gone missing on disk rather than letting send_file raise. We serve the
    *raw* EPUB (not the kepubified variant the Kobo download path produces) —
    browsers and foliate-js read plain EPUB.
    """
    item = get_item_or_404(item_id)
    if not _is_readable(item):
        abort(404)
    if not item.file_path or not os.path.exists(item.file_path):
        logger.warning("Reader: file missing on disk for item %s: %s", item.id, item.file_path)
        abort(404)
    return send_file(
        item.file_path,
        mimetype="application/epub+zip",
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
