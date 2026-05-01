import mimetypes

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from app.services.epub_extractor import (
    clean_epub_internal_path,
    get_epub_cache_dir,
    prepare_epub,
)
from app.routes.helpers import get_item_or_404


reader_bp = Blueprint("reader", __name__)


@reader_bp.route("/read/<int:item_id>")
def read_item(item_id):
    item = get_item_or_404(item_id)

    if item.media_type != "ebook":
        flash("Detta är inte en e-bok.", "error")
        return redirect(url_for("library.index"))

    reader_type = "unsupported"
    text_content = ""
    epub_error = None
    epub_pages = []
    epub_page_index = 0
    epub_current_page = None

    if item.extension == ".epub":
        reader_type = "epub"

        epub_result = prepare_epub(
            item,
            current_app.config["EPUB_CACHE_DIR"],
        )

        if epub_result["ok"]:
            epub_pages = epub_result["pages"]
            epub_page_index = request.args.get("page", 0, type=int)

            if epub_page_index < 0:
                epub_page_index = 0

            if epub_page_index >= len(epub_pages):
                epub_page_index = len(epub_pages) - 1

            epub_current_page = epub_pages[epub_page_index]
        else:
            epub_error = epub_result["error"]

    elif item.extension == ".pdf":
        reader_type = "pdf"

    elif item.extension == ".txt":
        reader_type = "txt"

        try:
            with open(item.file_path, "r", encoding="utf-8", errors="replace") as text_file:
                text_content = text_file.read()
        except Exception as error:
            text_content = f"Kunde inte läsa textfilen: {error}"

    return render_template(
        "reader.html",
        item=item,
        reader_type=reader_type,
        text_content=text_content,
        epub_error=epub_error,
        epub_pages=epub_pages,
        epub_page_index=epub_page_index,
        epub_current_page=epub_current_page,
    )


@reader_bp.route("/epub_content/<int:item_id>/<path:filename>")
def epub_content(item_id, filename):
    item = get_item_or_404(item_id)

    if item.extension.lower() != ".epub":
        abort(404)

    epub_result = prepare_epub(
        item,
        current_app.config["EPUB_CACHE_DIR"],
    )

    if not epub_result["ok"]:
        abort(404)

    safe_filename = clean_epub_internal_path(filename)

    if not safe_filename:
        abort(404)

    cache_dir = get_epub_cache_dir(
        current_app.config["EPUB_CACHE_DIR"],
        item.id,
    )

    full_path = (cache_dir / safe_filename).resolve()

    if not str(full_path).startswith(str(cache_dir.resolve())):
        abort(404)

    if not full_path.exists():
        abort(404)

    guessed_mimetype, _ = mimetypes.guess_type(str(full_path))

    lower_name = safe_filename.lower()

    if lower_name.endswith((".xhtml", ".xht", ".html", ".htm")):
        guessed_mimetype = "text/html; charset=utf-8"
    elif lower_name.endswith(".css"):
        guessed_mimetype = "text/css; charset=utf-8"
    elif lower_name.endswith(".svg"):
        guessed_mimetype = "image/svg+xml"

    return send_from_directory(
        cache_dir,
        safe_filename,
        mimetype=guessed_mimetype,
        conditional=True,
    )


@reader_bp.route("/listen/<int:item_id>")
def listen_item(item_id):
    item = get_item_or_404(item_id)

    if item.media_type != "audiobook":
        flash("Detta är inte en ljudbok.", "error")
        return redirect(url_for("library.index"))

    return render_template("audio.html", item=item)
