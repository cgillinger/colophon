import json

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from app.services.scanner import scan_library
from app.services.drm_acsm_handler import (
    ADOBE_DOWNLOAD_URL,
    copy_ade_books_to_library,
    get_ade_status,
    list_pending_acsm_files,
    process_pending_acsm_files,
    read_drm_status,
)


drm_bp = Blueprint("drm", __name__)


@drm_bp.route("/drm", methods=["GET"])
def drm_page():
    status = read_drm_status()

    return render_template(
        "drm.html",
        ade_status=get_ade_status(),
        pending_acsm_files=list_pending_acsm_files(),
        adobe_download_url=ADOBE_DOWNLOAD_URL,
        drm_status=status,
        drm_status_text=json.dumps(status, ensure_ascii=False, indent=2) if status else "",
    )


@drm_bp.route("/drm/process-pending", methods=["POST"])
def drm_process_pending():
    results = process_pending_acsm_files(current_app.config["LIBRARY_DIR"])

    imported = 0
    missing = False

    for row in results:
        state = row.get("result", {}).get("state")

        if state == "ade_missing":
            missing = True

        imported += len(row.get("result", {}).get("copied", []))

    if missing:
        flash("Adobe Digital Editions hittades inte. Installera ADE och försök igen.", "error")
    elif not results:
        flash("Inga ACSM-filer hittades.", "error")
    elif imported:
        scan_result = scan_library(
            current_app.config["LIBRARY_DIR"],
            current_app.config["COVER_DIR"],
        )

        flash(
            f"Importerade {imported} fil(er). Skanning: nya {scan_result['added']}, uppdaterade {scan_result['updated']}.",
            "success",
        )
    else:
        flash("ADE startades. Om boken inte syns ännu: vänta lite och tryck Importera senaste ADE-böcker.", "success")

    return redirect(url_for("drm.drm_page"))


@drm_bp.route("/drm/import-ade", methods=["POST"])
def drm_import_ade():
    copied = copy_ade_books_to_library(current_app.config["LIBRARY_DIR"])

    if copied:
        scan_result = scan_library(
            current_app.config["LIBRARY_DIR"],
            current_app.config["COVER_DIR"],
        )

        flash(
            f"Importerade {len(copied)} fil(er) från ADE. Skanning: nya {scan_result['added']}, uppdaterade {scan_result['updated']}.",
            "success",
        )
    else:
        flash("Hittade inga nya EPUB/PDF-filer i Adobe Digital Editions-mapparna.", "error")

    return redirect(url_for("drm.drm_page"))
