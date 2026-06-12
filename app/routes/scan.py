# Colophon – e-book metadata manager
import json
import os
import queue
import re
import threading
import unicodedata
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, Response

from app.models import db, LibraryItem
from app.services.author_resolver import resolve_pending_authors
from app.services.scanner import (
    scan_directory,
    extract_local_metadata,
    upsert_library_item,
    EBOOK_EXTENSIONS,
)

scan_bp = Blueprint("scan", __name__)


def sanitize_upload_filename(name: str) -> str:
    """Reduce an uploaded filename to a safe basename inside LIBRARY_DIR.

    Keeps unicode letters (so Swedish titles survive) but strips any path
    components, control characters and the handful of bytes that are unsafe
    or awkward in a filename. Never returns an empty stem.
    """
    # Drop any directory part the browser may have sent (path traversal guard).
    # Normalise Windows separators to '/' first so basename keeps only the leaf.
    name = os.path.basename((name or "").replace("\\", "/"))
    # Normalise and remove control chars.
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    # Disallow the filesystem-hostile set; collapse whitespace.
    name = re.sub(r'[<>:"|?*\x00]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        name = "upload"
    return name


@scan_bp.route("/scan", methods=["GET"])
def scan():
    if request.args.get("progress") == "1":
        return _scan_sse()

    try:
        summary = scan_directory(
            current_app.config["LIBRARY_DIR"],
            db.session,
            cover_dir=current_app.config["COVER_DIR"],
        )
        return jsonify(summary)
    except Exception as exc:
        current_app.logger.exception("scan_directory failed")
        return jsonify({"error": str(exc)}), 500


@scan_bp.route("/upload", methods=["POST"])
def upload():
    """Ingest one or more uploaded ebook files straight into the library.

    Files are written into LIBRARY_DIR and ingested via the same path the
    scanner uses (extract_local_metadata + upsert_library_item), so the user
    never has to run "Find new books" afterwards. New rows get their
    created_at stamped, which drives the "Nytillagt" badge.

    Returns a JSON summary plus a per-file result list. The client uploads
    files one request at a time for live progress, but this also accepts a
    multi-file form for robustness.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files"}), 400

    library_dir = Path(current_app.config["LIBRARY_DIR"])
    cover_dir = current_app.config["COVER_DIR"]
    library_dir.mkdir(parents=True, exist_ok=True)

    results = []
    ingested = []  # (result entry, LibraryItem) for post-loop author resolution
    added = updated = skipped = errors = 0

    for storage in files:
        original = storage.filename or ""
        safe_name = sanitize_upload_filename(original)
        ext = Path(safe_name).suffix.lower()

        if ext not in EBOOK_EXTENSIONS:
            errors += 1
            results.append({"name": original, "status": "error",
                            "reason": "unsupported"})
            continue

        dest = library_dir / safe_name

        # Never overwrite an existing library file or silently create a
        # duplicate: a same-named file already on disk is reported as skipped.
        if dest.exists():
            skipped += 1
            results.append({"name": safe_name, "status": "skipped",
                            "reason": "exists"})
            continue

        try:
            storage.save(str(dest))
        except Exception as exc:
            current_app.logger.exception("upload save failed for %s", safe_name)
            errors += 1
            results.append({"name": safe_name, "status": "error",
                            "reason": str(exc)})
            continue

        try:
            absolute_path = str(dest.resolve())
            existing = LibraryItem.query.filter_by(file_path=absolute_path).first()
            metadata = extract_local_metadata(str(dest), cover_dir=cover_dir)
            item = upsert_library_item(
                str(dest), metadata, existing=existing, db_session=db.session
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("upload ingest failed for %s", safe_name)
            # The bytes are on disk; a later scan can still pick them up.
            errors += 1
            results.append({"name": safe_name, "status": "error",
                            "reason": str(exc)})
            continue

        if existing:
            updated += 1
            status = "updated"
        else:
            added += 1
            status = "added"
        results.append({
            "name": safe_name,
            "status": status,
            "item_id": item.id,
            "title": item.title or safe_name,
            "author": item.author or "",
        })
        ingested.append((results[-1], item))

    # Author resolution — one batched pass over everything this request
    # ingested (DB-only linking; never blocks the upload, never touches
    # files). Drives the panel's "X authors known · Y to review" summary.
    author_counts = {}
    if ingested:
        try:
            author_counts = resolve_pending_authors(
                db.session, [item for _, item in ingested]
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("author resolution failed after upload")
        else:
            for entry, item in ingested:
                entry["author_status"] = item.author_status

    return jsonify({
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "authors": author_counts,
        "results": results,
    })


def _scan_sse():
    """Stream scan progress events as Server-Sent Events.

    Runs the scan in a daemon thread so the generator can yield events
    in real time rather than buffering them until the scan completes.
    """
    app = current_app._get_current_object()
    library_dir = app.config["LIBRARY_DIR"]
    cover_dir = app.config["COVER_DIR"]

    ev_queue = queue.SimpleQueue()

    def _run():
        with app.app_context():
            from app.models import db as _db
            from app.services.scanner import scan_directory as _scan
            from app.services.upstream_sync import upstream_configured, pull_from_upstream
            try:
                if upstream_configured():
                    for ev in pull_from_upstream():
                        ev["type"] = "upstream_pull"
                        ev_queue.put(ev)

                summary = _scan(
                    library_dir,
                    _db.session,
                    on_progress=ev_queue.put,
                    cover_dir=cover_dir,
                )
                ev_queue.put({
                    "type": "done",
                    "added": summary["added"],
                    "updated": summary["updated"],
                    "skipped": summary.get("skipped", 0),
                    "removed": summary.get("removed", 0),
                })
            except Exception as exc:
                app.logger.exception("scan_directory SSE failed")
                ev_queue.put({"type": "error", "message": str(exc)})
            finally:
                ev_queue.put(None)  # sentinel — tells generator to stop

    threading.Thread(target=_run, daemon=True).start()

    def generate():
        while True:
            ev = ev_queue.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
