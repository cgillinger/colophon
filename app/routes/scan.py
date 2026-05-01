import json

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
    library_dir = current_app.config["LIBRARY_DIR"]
    cover_dir = current_app.config["COVER_DIR"]
    session = db.session

    def generate():
        events = []

        def collect(event):
            events.append(event)

        try:
            summary = scan_directory(library_dir, session, on_progress=collect, cover_dir=cover_dir)
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'added': summary['added'], 'updated': summary['updated'], 'removed': summary['removed']})}\n\n"
        except Exception as exc:
            current_app.logger.exception("scan_directory SSE failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
