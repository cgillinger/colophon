import os
import shutil
import subprocess
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app.models import db, LibraryItem
from app.services.scanner import scan_library
from app.routes.helpers import get_item_or_404, get_mimetype


library_bp = Blueprint("library", __name__)


ALLOWED_IMPORT_EXTENSIONS = {
    ".epub",
    ".pdf",
    ".txt",
    ".cbz",
    ".cbr",
}


def safe_browse_path(raw_path=None):
    home = Path.home().resolve()

    if not raw_path:
        return home

    try:
        wanted = Path(raw_path).expanduser().resolve()
    except Exception:
        return home

    if wanted == home or str(wanted).startswith(str(home) + os.sep):
        return wanted

    return home


@library_bp.route("/")
def index():
    media_type = request.args.get("typ", "all")

    query = LibraryItem.query

    if media_type == "ebook":
        query = query.filter_by(media_type="ebook")
    elif media_type == "audiobook":
        query = query.filter_by(media_type="audiobook")

    items = query.order_by(LibraryItem.title.asc()).all()

    total_count = LibraryItem.query.count()
    ebook_count = LibraryItem.query.filter_by(media_type="ebook").count()
    audiobook_count = LibraryItem.query.filter_by(media_type="audiobook").count()

    return render_template(
        "index.html",
        items=items,
        media_type=media_type,
        total_count=total_count,
        ebook_count=ebook_count,
        audiobook_count=audiobook_count,
        library_dir=current_app.config["LIBRARY_DIR"],
    )


@library_bp.route("/scan", methods=["POST"])
def scan():
    result = scan_library(
        current_app.config["LIBRARY_DIR"],
        current_app.config["COVER_DIR"],
    )

    if result["missing_folder"]:
        flash("Biblioteksmappen kunde inte hittas.", "error")
    else:
        flash(
            f"Skanning klar. Nya: {result['added']}, uppdaterade: {result['updated']}, hoppade över: {result['skipped']}.",
            "success",
        )

    return redirect(url_for("library.index"))


@library_bp.route("/file/<int:item_id>")
def file_item(item_id):
    item = get_item_or_404(item_id)

    if not os.path.exists(item.file_path):
        flash("Filen finns inte längre på disken.", "error")
        return redirect(url_for("library.index"))

    return send_file(
        item.file_path,
        mimetype=get_mimetype(item),
        as_attachment=False,
        conditional=True,
        download_name=item.file_name,
    )


@library_bp.route("/cover/<int:item_id>")
def cover_item(item_id):
    item = get_item_or_404(item_id)

    if not item.cover_path:
        flash("Boken har inget omslag.", "error")
        return redirect(url_for("library.index"))

    if not os.path.exists(item.cover_path):
        flash("Omslagsfilen finns inte längre.", "error")
        return redirect(url_for("library.index"))

    return send_file(item.cover_path)


@library_bp.route("/series")
def series_page():
    items = (
        LibraryItem.query
        .filter(LibraryItem.series.isnot(None))
        .filter(LibraryItem.series != "")
        .filter(LibraryItem.series != "")
        .order_by(LibraryItem.series.asc(), LibraryItem.series_index.asc(), LibraryItem.title.asc())
        .all()
    )

    groups = {}

    for item in items:
        key = item.series.strip() if item.series else "Okänd serie"
        groups.setdefault(key, []).append(item)

    series_groups = []

    for name, books in sorted(groups.items(), key=lambda x: x[0].lower()):
        def sort_key(book):
            try:
                return float(book.series_index or 9999)
            except Exception:
                return 9999

        books = sorted(books, key=sort_key)
        series_groups.append({
            "name": name,
            "books": books,
            "count": len(books),
            "first_cover": books[0].id if books else None,
        })

    return render_template(
        "series.html",
        series_groups=series_groups,
        total_series=len(series_groups),
        total_books=len(items),
    )


@library_bp.route("/series/<path:series_name>")
def series_detail_page(series_name):
    items = (
        LibraryItem.query
        .filter(LibraryItem.series == series_name)
        .order_by(LibraryItem.series_index.asc(), LibraryItem.title.asc())
        .all()
    )

    def sort_key(book):
        try:
            return float(book.series_index or 9999)
        except Exception:
            return 9999

    items = sorted(items, key=sort_key)

    return render_template(
        "series_detail.html",
        series_name=series_name,
        items=items,
        total_books=len(items),
    )


@library_bp.route("/book/<int:item_id>")
def book_detail_page(item_id):
    item = get_item_or_404(item_id)

    series_items = []

    if item.series:
        series_items = (
            LibraryItem.query
            .filter(LibraryItem.series == item.series)
            .order_by(LibraryItem.series_index.asc(), LibraryItem.title.asc())
            .all()
        )

        def sort_key(book):
            try:
                return float(book.series_index or 9999)
            except Exception:
                return 9999

        series_items = sorted(series_items, key=sort_key)

    return render_template(
        "book_detail.html",
        item=item,
        series_items=series_items,
    )


@library_bp.route("/want-read")
def want_read_page():
    items = (
        LibraryItem.query
        .filter(LibraryItem.want_read == True)
        .order_by(LibraryItem.title.asc())
        .all()
    )

    return render_template(
        "want_read.html",
        items=items,
        total_books=len(items),
    )


@library_bp.route("/item/<int:item_id>/want-read", methods=["POST"])
def toggle_want_read(item_id):
    item = get_item_or_404(item_id)
    item.want_read = not bool(item.want_read)
    db.session.commit()

    if item.want_read:
        flash(f"Lades till i Vill läsa: {item.title}", "success")
    else:
        flash(f"Togs bort från Vill läsa: {item.title}", "success")

    return redirect(request.referrer or url_for("library.index"))


@library_bp.route("/item/<int:item_id>/open-folder")
def open_item_folder(item_id):
    item = get_item_or_404(item_id)
    file_path = Path(item.file_path)

    if not file_path.exists():
        flash("Filen finns inte längre på disk.", "error")
        return redirect(request.referrer or url_for("library.index"))

    try:
        subprocess.Popen(["xdg-open", str(file_path.parent)])
        flash(f"Öppnade biblioteksmappen: {file_path.parent}", "success")
    except Exception as error:
        flash(f"Kunde inte öppna mappen: {error}", "error")

    return redirect(request.referrer or url_for("library.index"))


@library_bp.route("/item/<int:item_id>/delete", methods=["POST"])
def delete_library_item(item_id):
    item = get_item_or_404(item_id)
    file_path = Path(item.file_path)
    title = item.title or item.file_name or "Bok"

    try:
        if file_path.exists():
            file_path.unlink()

        db.session.delete(item)
        db.session.commit()

        flash(f"Boken raderades från biblioteket: {title}", "success")
    except Exception as error:
        db.session.rollback()
        flash(f"Kunde inte radera boken: {error}", "error")

    return redirect(url_for("library.index"))


@library_bp.route("/add-ebook")
def add_ebook_page():
    current_path = safe_browse_path(request.args.get("path"))

    if not current_path.exists() or not current_path.is_dir():
        current_path = Path.home().resolve()

    folders = []
    files = []

    try:
        for entry in sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.name.startswith("."):
                continue

            if entry.is_dir():
                folders.append(entry)
            elif entry.is_file() and entry.suffix.lower() in ALLOWED_IMPORT_EXTENSIONS:
                files.append(entry)
    except Exception as error:
        flash(f"Kunde inte läsa mappen: {error}", "error")

    parent_path = None

    if current_path != Path.home().resolve():
        parent_path = current_path.parent

    return render_template(
        "add_ebook.html",
        current_path=current_path,
        parent_path=parent_path,
        folders=folders,
        files=files,
        library_dir=current_app.config["LIBRARY_DIR"],
    )


@library_bp.route("/add-ebook/import", methods=["POST"])
def import_ebook_from_disk():
    source_raw = request.form.get("source_path", "").strip()
    source_path = safe_browse_path(source_raw)

    if not source_path.exists() or not source_path.is_file():
        flash("Filen kunde inte hittas.", "error")
        return redirect(url_for("library.add_ebook_page"))

    if source_path.suffix.lower() not in ALLOWED_IMPORT_EXTENSIONS:
        flash("Detta filformat stöds inte som e-bok.", "error")
        return redirect(url_for("library.add_ebook_page", path=str(source_path.parent)))

    library_dir = Path(current_app.config["LIBRARY_DIR"])
    library_dir.mkdir(parents=True, exist_ok=True)

    target_path = library_dir / source_path.name

    if target_path.exists():
        flash(f"Boken finns redan i biblioteket: {target_path.name}", "error")
        return redirect(url_for("library.add_ebook_page", path=str(source_path.parent)))

    try:
        shutil.copy2(source_path, target_path)
    except Exception as error:
        flash(f"Kunde inte kopiera boken: {error}", "error")
        return redirect(url_for("library.add_ebook_page", path=str(source_path.parent)))

    scan_result = scan_library(
        current_app.config["LIBRARY_DIR"],
        current_app.config["COVER_DIR"],
    )

    flash(
        f"E-boken importerades: {target_path.name}. Skanning klar. Nya: {scan_result['added']}, uppdaterade: {scan_result['updated']}.",
        "success",
    )

    return redirect(url_for("library.index"))


@library_bp.route("/about")
def about_page():
    return render_template("about.html")
