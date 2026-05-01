import logging
import os
import shutil
from difflib import SequenceMatcher
from pathlib import Path

from app.services.ai_metadata import fetch_ai_suggestions
from app.services.scanner import scan_directory

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

logger = logging.getLogger(__name__)

from app.models import db, LibraryItem
from app.services.metadata_sources import (
    choose_best_metadata,
    download_cover_to_file,
    search_all_sources,
    search_cover_candidates,
)
from app.services.metadata_writer import (
    apply_metadata_to_item,
    item_has_good_metadata,
    write_metadata_to_file,
)
from app.routes.helpers import get_item_or_404, save_uploaded_cover, get_int_form_value


metadata_bp = Blueprint("metadata", __name__)


@metadata_bp.route("/")
def index():
    return redirect(url_for("metadata.bulk_metadata"))


@metadata_bp.route("/cover/<int:item_id>")
def cover_item(item_id):
    item = get_item_or_404(item_id)
    if not item.cover_path or not os.path.exists(item.cover_path):
        return ("", 404)
    return send_file(item.cover_path)


SUPPORTED_LANGUAGES = [
    ("en", "English"),
    ("sv", "Svenska"),
    ("no", "Norsk"),
    ("da", "Dansk"),
    ("fi", "Suomi"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
]


def _pending_session_key(item_id):
    return f"pending_bookf_{item_id}"


def _bookf_preview_key(item_id):
    return f"bookf_preview_{item_id}"


def _ai_preview_key(item_id):
    return f"ai_preview_{item_id}"


_BOOKF_FIELDS = [
    ("title", "Titel"),
    ("author", "Författare"),
    ("description", "Synopsis"),
    ("publisher", "Förlag"),
    ("isbn", "ISBN"),
    ("language", "Språk"),
    ("series", "Serie"),
    ("series_index", "Del"),
]


def _build_bookf_diff(item, fetched):
    rows = []
    for key, label in _BOOKF_FIELDS:
        current_raw = getattr(item, key, None)
        current = (str(current_raw).strip() if current_raw not in (None, "") else "")
        fetched_raw = fetched.get(key)
        fetched_val = (str(fetched_raw).strip() if fetched_raw not in (None, "") else "")

        if not fetched_val:
            status = "missing"
            default_check = False
        elif key == "language":
            # Språk är aldrig auto-förbockat – användaren måste välja aktivt.
            status = "changed" if current and current != fetched_val else "new"
            default_check = False
        elif not current:
            status = "new"
            default_check = True
        elif current == fetched_val:
            status = "same"
            default_check = False
        else:
            status = "changed"
            default_check = False

        rows.append({
            "key": key,
            "label": label,
            "current": current,
            "fetched": fetched_val,
            "status": status,
            "default_check": default_check,
            "disabled": status == "missing" or status == "same",
        })
    return rows


@metadata_bp.route("/metadata/<int:item_id>", methods=["GET", "POST"])
def metadata_item(item_id):
    item = get_item_or_404(item_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        series = request.form.get("series", "").strip()
        series_index = request.form.get("series_index", "").strip()
        isbn = request.form.get("isbn", "").strip()
        publisher = request.form.get("publisher", "").strip()
        language = request.form.get("language", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            flash("Titel får inte vara tom.", "error")
            return redirect(url_for("metadata.metadata_item", item_id=item.id))

        item.title = title
        item.author = author or None
        item.series = series or None
        item.series_index = series_index or None
        item.isbn = isbn or None
        item.publisher = publisher or None
        item.language = language or None
        item.description = description or None

        uploaded_cover = request.files.get("cover")
        new_cover_path = save_uploaded_cover(item, uploaded_cover)

        if uploaded_cover and uploaded_cover.filename and not new_cover_path:
            flash("Omslaget sparades inte. Använd JPG, PNG eller WEBP.", "error")
        elif new_cover_path:
            item.cover_path = new_cover_path
            item.cover_locked = True

        item.manual_metadata = True

        cover_to_embed = new_cover_path

        pending = session.pop(_pending_session_key(item.id), None)
        if pending and pending.get("cover_path") and not new_cover_path and not item.cover_locked:
            cover_src = pending["cover_path"]
            if os.path.exists(cover_src):
                cover_dir = current_app.config["COVER_DIR"]
                os.makedirs(cover_dir, exist_ok=True)
                ext = os.path.splitext(cover_src)[1] or ".jpg"
                dest = os.path.join(cover_dir, f"cover_{item.id}{ext}")
                shutil.copy2(cover_src, dest)
                item.cover_path = dest
                cover_to_embed = dest
                try:
                    os.unlink(cover_src)
                except OSError:
                    pass

        written_text = {}
        if title:
            written_text["title"] = title
        if author:
            written_text["author"] = author
        if series:
            written_text["series"] = series
        if series_index:
            written_text["series_index"] = series_index
        if isbn:
            written_text["isbn"] = isbn
        if publisher:
            written_text["publisher"] = publisher
        if language:
            written_text["language"] = language
        if description:
            written_text["description"] = description
        write_metadata_to_file(item, written_text, cover_to_embed)

        db.session.commit()

        flash("Metadata sparad.", "success")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    pending = session.get(_pending_session_key(item.id))
    current_lang = (item.language or "en").strip() or "en"
    return render_template(
        "metadata.html",
        item=item,
        pending=pending,
        languages=SUPPORTED_LANGUAGES,
        current_lang=current_lang,
        ai_configured=bool(os.environ.get("COLOPHON_MISTRAL_API_KEY")),
    )


@metadata_bp.route("/metadata/<int:item_id>/cancel-preview", methods=["POST"])
def cancel_preview(item_id):
    item = get_item_or_404(item_id)
    pending = session.pop(_pending_session_key(item.id), None)
    if pending and pending.get("cover_path"):
        try:
            os.unlink(pending["cover_path"])
        except OSError:
            pass
    flash("Förhandsgranskning avbruten. Inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))


@metadata_bp.route("/metadata/<int:item_id>/preview-cover")
def preview_cover(item_id):
    pending = session.get(_pending_session_key(item_id))
    if not pending or not pending.get("cover_path") or not os.path.exists(pending["cover_path"]):
        return ("", 404)
    return send_file(pending["cover_path"])


@metadata_bp.route("/metadata/<int:item_id>/covers")
def lookup_covers(item_id):
    item = get_item_or_404(item_id)

    candidates = search_cover_candidates(item)

    return render_template(
        "cover_lookup.html",
        item=item,
        candidates=candidates,
    )


@metadata_bp.route("/metadata/<int:item_id>/cover/apply", methods=["POST"])
def apply_cover(item_id):
    item = get_item_or_404(item_id)

    cover_url = request.form.get("cover_url", "").strip()
    source = request.form.get("source", "").strip()

    if not cover_url:
        flash("Inget omslag valdes.", "error")
        return redirect(url_for("metadata.lookup_covers", item_id=item.id))

    cover_path = download_cover_to_file(
        cover_url=cover_url,
        cover_dir=current_app.config["COVER_DIR"],
        item_id=item.id,
    )

    if not cover_path:
        flash("Omslaget kunde inte laddas ner.", "error")
        return redirect(url_for("metadata.lookup_covers", item_id=item.id))

    item.cover_path = cover_path
    item.cover_locked = True
    item.manual_metadata = True

    write_metadata_to_file(item, {}, cover_path)

    db.session.commit()

    if source:
        flash(f"Omslag hämtat från {source}.", "success")
    else:
        flash("Omslag hämtat och sparat.", "success")

    return redirect(url_for("metadata.metadata_item", item_id=item.id))


@metadata_bp.route("/metadata/bulk", methods=["GET", "POST"])
def bulk_metadata():
    if request.method == "GET":
        scan_directory(
            current_app.config["LIBRARY_DIR"],
            db.session,
            cover_dir=current_app.config["COVER_DIR"],
        )

    items = (
        LibraryItem.query
        .order_by(LibraryItem.title.asc())
        .all()
    )

    summary = None

    if request.method == "POST":
        selected_ids = request.form.getlist("item_ids")
        overwrite = request.form.get("overwrite") == "1"
        only_missing = request.form.get("only_missing") == "1"
        max_items = get_int_form_value("max_items", 25, 1, 100)

        selected_items = []

        for selected_id in selected_ids:
            try:
                item_id = int(selected_id)
            except Exception:
                continue

            item = LibraryItem.query.get(item_id)

            if item:
                selected_items.append(item)

        summary = {
            "updated": [],
            "no_match": [],
            "skipped": [],
            "limited": False,
            "processed": 0,
        }

        processed_count = 0

        for item in selected_items:
            if processed_count >= max_items:
                summary["limited"] = True
                break

            if only_missing and item_has_good_metadata(item):
                summary["skipped"].append(
                    {
                        "title": item.title,
                        "reason": "Har redan författare, synopsis och omslag.",
                    }
                )
                continue

            processed_count += 1
            summary["processed"] = processed_count

            query_text = ""

            if item.isbn:
                query_text = item.isbn
            else:
                query_text = " ".join(
                    [part for part in [item.title, item.author] if part]
                ).strip()

            results = search_all_sources(
                title=item.title or "",
                author=item.author or "",
                isbn=item.isbn or "",
                query_text=query_text,
                include_calibre=True,
            )

            best_result, best_score = choose_best_metadata(item, results)

            if not best_result:
                summary["no_match"].append(
                    {
                        "title": item.title,
                        "score": best_score,
                    }
                )
                continue

            apply_metadata_to_item(
                item=item,
                result=best_result,
                cover_dir=current_app.config["COVER_DIR"],
                overwrite=overwrite,
                write_to_file=True,
            )

            summary["updated"].append(
                {
                    "title": item.title,
                    "source": best_result.get("source", "Okänd källa"),
                    "score": best_score,
                }
            )

        db.session.commit()

        flash(
            f"Massuppdatering klar. Uppdaterade: {len(summary['updated'])}, utan säker träff: {len(summary['no_match'])}, hoppade över: {len(summary['skipped'])}.",
            "success",
        )

        items = (
            LibraryItem.query
            .order_by(LibraryItem.title.asc())
            .all()
        )

    return render_template(
        "bulk_metadata.html",
        items=items,
        summary=summary,
    )


@metadata_bp.route("/metadata/<int:item_id>/bookf", methods=["POST"])
def run_bookf_for_item(item_id):
    item = get_item_or_404(item_id)

    source_path = Path(item.file_path)

    if not source_path.exists():
        flash("Bokfilen hittades inte på disk.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    if source_path.suffix.lower() not in {".epub", ".mobi", ".azw3", ".kepub"}:
        flash("Metadatahämtning stöder bara EPUB, MOBI, AZW3 och KEPUB.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    lock_path = Path("/tmp") / f"colophon_bookf_{item.id}.lock"

    if lock_path.exists():
        flash("Metadatahämtning körs redan på denna bok. Vänta tills den är klar.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    try:
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

        query_text = ""
        if item.isbn:
            query_text = item.isbn
        else:
            query_text = " ".join(
                [part for part in [item.title, item.author] if part]
            ).strip()

        results = search_all_sources(
            title=item.title or "",
            author=item.author or "",
            isbn=item.isbn or "",
            query_text=query_text,
            include_calibre=True,
        )

        best, best_score = choose_best_metadata(item, results)

        if not best:
            flash(
                "Inga säkra metadata-träffar hittades från Google Books eller Calibre.",
                "error",
            )
            return redirect(url_for("metadata.metadata_item", item_id=item.id))

        cover_path_for_preview = None
        if best.get("cover_url"):
            cover_dir = current_app.config["COVER_DIR"]
            os.makedirs(cover_dir, exist_ok=True)
            downloaded = download_cover_to_file(
                cover_url=best.get("cover_url"),
                cover_dir=cover_dir,
                item_id=item.id,
            )
            if downloaded:
                ext = os.path.splitext(downloaded)[1] or ".jpg"
                preview_path = os.path.join(
                    cover_dir, f"preview_{item.id}{ext}"
                )
                try:
                    os.replace(downloaded, preview_path)
                    cover_path_for_preview = preview_path
                except OSError:
                    cover_path_for_preview = downloaded

        old_preview = session.get(_bookf_preview_key(item.id))
        if (
            old_preview
            and old_preview.get("fetched", {}).get("cover_path")
            and old_preview["fetched"]["cover_path"] != cover_path_for_preview
        ):
            try:
                os.unlink(old_preview["fetched"]["cover_path"])
            except OSError:
                pass

        def _txt(value):
            if value is None:
                return ""
            return str(value).strip()

        fetched_payload = {
            "title": _txt(best.get("title")),
            "author": _txt(best.get("author")),
            "description": _txt(best.get("description")),
            "publisher": _txt(best.get("publisher")),
            "isbn": _txt(best.get("isbn")),
            "language": _txt(best.get("language")),
            "series": _txt(best.get("series")),
            "series_index": _txt(best.get("series_index")),
            "cover_url": _txt(best.get("cover_url")),
            "cover_path": cover_path_for_preview,
        }

        def _normalize(value):
            return (value or "").lower().replace(":", " ").replace("-", " ").strip()

        old_title = _normalize(item.title)
        old_author = _normalize(item.author)
        new_title = _normalize(fetched_payload["title"])
        new_author = _normalize(fetched_payload["author"])

        title_score = (
            SequenceMatcher(None, old_title, new_title).ratio()
            if old_title and new_title
            else 0
        )
        author_score = (
            SequenceMatcher(None, old_author, new_author).ratio()
            if old_author and new_author
            else 0
        )

        validation_warning = None
        if (
            (new_title or new_author)
            and title_score < 0.55
            and author_score < 0.60
        ):
            validation_warning = (
                f"Hämtad metadata verkar avvika från bokens titel/författare "
                f"(titel: {fetched_payload['title'] or 'okänd'}, "
                f"författare: {fetched_payload['author'] or 'okänd'}). "
                f"Granska noggrant innan du sparar."
            )

        session[_bookf_preview_key(item.id)] = {
            "fetched": fetched_payload,
            "sources_used": [best.get("source", "")] if best.get("source") else [],
            "validation_warning": validation_warning,
            "score": best_score,
        }

        return redirect(url_for("metadata.bookf_preview", item_id=item.id))

    except Exception as error:
        db.session.rollback()
        flash(f"Kunde inte hämta metadata: {error}", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    finally:
        try:
            lock_path.unlink()
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)


@metadata_bp.route("/metadata/<int:item_id>/bookf/preview", methods=["GET"])
def bookf_preview(item_id):
    item = get_item_or_404(item_id)
    preview = session.get(_bookf_preview_key(item.id))
    if not preview:
        flash("Ingen hämtad metadata att granska. Kör hämtningen först.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    fetched = preview.get("fetched") or {}
    rows = _build_bookf_diff(item, fetched)

    cover_path = fetched.get("cover_path") or ""
    has_fetched_cover = bool(cover_path) and os.path.exists(cover_path)
    cover_status = "missing"
    cover_default_check = False
    if has_fetched_cover:
        if item.cover_locked:
            cover_status = "same"
        elif item.cover_path:
            cover_status = "changed"
        else:
            cover_status = "new"
            cover_default_check = True

    return render_template(
        "metadata_bookf_preview.html",
        item=item,
        rows=rows,
        cover_status=cover_status,
        cover_default_check=cover_default_check,
        has_fetched_cover=has_fetched_cover,
        sources_used=preview.get("sources_used") or [],
        validation_warning=preview.get("validation_warning"),
    )


@metadata_bp.route("/metadata/<int:item_id>/bookf/preview-cover")
def bookf_preview_cover(item_id):
    preview = session.get(_bookf_preview_key(item_id))
    cover_path = (preview or {}).get("fetched", {}).get("cover_path")
    if not cover_path or not os.path.exists(cover_path):
        return ("", 404)
    return send_file(cover_path)


@metadata_bp.route("/metadata/<int:item_id>/bookf/apply", methods=["POST"])
def bookf_apply(item_id):
    item = get_item_or_404(item_id)
    preview = session.get(_bookf_preview_key(item.id))
    if not preview:
        flash("Förhandsgranskningen har gått ut. Kör hämtningen igen.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    fetched = preview.get("fetched") or {}
    selected = set(request.form.getlist("fields"))

    result_for_apply = dict(fetched)

    apply_result = apply_metadata_to_item(
        item=item,
        result=result_for_apply,
        cover_dir=current_app.config["COVER_DIR"],
        overwrite=True,
        write_to_file=True,
        selected_fields=selected,
    )

    db.session.commit()

    cover_src = fetched.get("cover_path")
    if cover_src and os.path.exists(cover_src):
        try:
            os.unlink(cover_src)
        except OSError:
            pass
    session.pop(_bookf_preview_key(item.id), None)

    db_updated = apply_result.get("db_updated", 0)
    cover_saved = apply_result.get("cover_saved", False)
    file_updated = apply_result.get("file_updated", False)

    total = db_updated + (1 if cover_saved else 0)
    if total:
        parts = [f"{db_updated} fält uppdaterade"]
        if cover_saved:
            parts.append("omslag bytt")
        if file_updated:
            parts.append("filen uppdaterad")
        flash("Metadata sparad (" + ", ".join(parts) + ").", "success")
    else:
        flash("Inga fält valdes — inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))


@metadata_bp.route("/metadata/<int:item_id>/bookf/cancel", methods=["POST"])
def bookf_cancel(item_id):
    item = get_item_or_404(item_id)
    preview = session.pop(_bookf_preview_key(item.id), None)
    cover_src = (preview or {}).get("fetched", {}).get("cover_path")
    if cover_src and os.path.exists(cover_src):
        try:
            os.unlink(cover_src)
        except OSError:
            pass
    flash("Förhandsgranskning avbruten. Inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))


# Fields shown in the AI preview table (display order)
_AI_PREVIEW_FIELDS = [
    ("series", "Serie"),
    ("series_index", "Del"),
    ("title", "Titel"),
    ("author", "Författare"),
    ("language", "Språk"),
    ("publisher", "Förlag"),
    ("description", "Synopsis"),
]

# subjects is display-only — not yet a LibraryItem column
_AI_DISPLAY_ONLY = {"subjects"}


@metadata_bp.route("/metadata/<int:item_id>/ai", methods=["POST"])
def run_ai_for_item(item_id):
    item = get_item_or_404(item_id)

    if not os.environ.get("COLOPHON_MISTRAL_API_KEY"):
        flash(
            "Mistral är inte konfigurerat. Lägg till COLOPHON_MISTRAL_API_KEY i .env.",
            "error",
        )
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    result = fetch_ai_suggestions(item)

    if not result["ok"]:
        error = result["error"]
        if error == "auth":
            flash("Mistral nekade anropet. Kontrollera API-nyckeln.", "error")
        elif error == "timeout":
            flash("Mistral-anropet tog för lång tid. Försök igen.", "error")
        elif error == "rate_limit":
            flash("Gränsen för Mistral-anrop verkar vara nådd. Försök igen senare.", "error")
        elif error == "invalid_json":
            flash("Mistral returnerade ett svar som inte kunde tolkas.", "error")
        else:
            flash(f"Mistral-anropet misslyckades ({error}).", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    suggestions = result["suggestions"]
    applicable = {k: v for k, v in suggestions.items() if k not in _AI_DISPLAY_ONLY}
    if not applicable:
        flash("AI:n hittade inga förbättringar att föreslå.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    session[_ai_preview_key(item.id)] = {"suggestions": suggestions}
    return redirect(url_for("metadata.ai_preview", item_id=item.id))


@metadata_bp.route("/metadata/<int:item_id>/ai/preview", methods=["GET"])
def ai_preview(item_id):
    item = get_item_or_404(item_id)
    preview = session.get(_ai_preview_key(item.id))
    if not preview:
        flash("Inga AI-förslag att granska. Kör hämtningen först.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    suggestions = preview.get("suggestions", {})
    rows = []
    for key, label in _AI_PREVIEW_FIELDS:
        suggestion = suggestions.get(key)
        if not suggestion:
            continue
        confidence = suggestion["confidence"]
        if confidence == "low":
            continue
        current_raw = getattr(item, key, None)
        current = (str(current_raw).strip() if current_raw not in (None, "") else "")
        rows.append({
            "key": key,
            "label": label,
            "current": current,
            "value": suggestion["value"],
            "confidence": confidence,
            "reason": suggestion["reason"],
            "default_check": confidence == "high",
        })

    subjects_display = None
    subjects_suggestion = suggestions.get("subjects")
    if subjects_suggestion and subjects_suggestion["confidence"] != "low":
        subjects_display = subjects_suggestion

    return render_template(
        "metadata_ai_preview.html",
        item=item,
        rows=rows,
        subjects_display=subjects_display,
    )


@metadata_bp.route("/metadata/<int:item_id>/ai/apply", methods=["POST"])
def ai_apply(item_id):
    item = get_item_or_404(item_id)
    preview = session.get(_ai_preview_key(item.id))
    if not preview:
        flash("Förhandsgranskningen har gått ut. Kör hämtningen igen.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    suggestions = preview.get("suggestions", {})
    selected = set(request.form.getlist("fields")) - _AI_DISPLAY_ONLY

    result = {k: v["value"] for k, v in suggestions.items() if k not in _AI_DISPLAY_ONLY}

    apply_result = apply_metadata_to_item(
        item=item,
        result=result,
        cover_dir=current_app.config["COVER_DIR"],
        overwrite=True,
        write_to_file=True,
        selected_fields=selected,
    )

    db.session.commit()
    session.pop(_ai_preview_key(item.id), None)

    db_updated = apply_result.get("db_updated", 0)
    if db_updated:
        flash(f"Metadata sparad ({db_updated} fält uppdaterade).", "success")
    else:
        flash("Inga fält valdes — inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))


@metadata_bp.route("/metadata/<int:item_id>/ai/cancel", methods=["POST"])
def ai_cancel(item_id):
    item = get_item_or_404(item_id)
    session.pop(_ai_preview_key(item.id), None)
    flash("Förhandsgranskning avbruten. Inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))
