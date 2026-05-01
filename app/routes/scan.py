from flask import Blueprint, current_app, jsonify

from app.models import db
from app.services.scanner import scan_directory

scan_bp = Blueprint("scan", __name__)


@scan_bp.route("/scan", methods=["GET"])
def scan():
    summary = scan_directory(current_app.config["LIBRARY_DIR"], db.session)
    return jsonify(summary)
