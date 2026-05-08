import json
import queue
import threading

from flask import Blueprint, current_app, jsonify, request, Response

from app.models import db
from app.services.scanner import scan_directory

scan_bp = Blueprint("scan", __name__)


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
