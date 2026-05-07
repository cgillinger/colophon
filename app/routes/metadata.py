import json
import logging
import os
import queue
import shutil
import threading
from pathlib import Path

from app.services.ai_metadata import fetch_ai_suggestions

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
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
    choose_best_metadata_explained,
    classify_enrichment_result,
    clean_text,
    download_cover_to_file,
    search_all_sources,
    search_all_sources_with_status,
    search_cover_candidates,
)
from app.services.metadata_writer import (
    FILE_WRITE_ERROR_MESSAGES,
    apply_metadata_to_item,
    item_has_good_metadata,
    write_metadata_to_file,
)
from app.services.grouping import compute_group_key
from app.services.metadata_pipeline import (
    apply_enrichment_result as _pipeline_apply,
    build_search_input,
    run_metadata_enrichment,
)
from app.routes.helpers import get_item_or_404, save_uploaded_cover, get_int_form_value


metadata_bp = Blueprint("metadata", __name__)


# Single-user app — one shared abort flag across SSE streams.
_abort_event = threading.Event()


@metadata_bp.route("/metadata/abort", methods=["POST"])
def abort_metadata():
    """Signal any running metadata SSE stream to stop."""
    _abort_event.set()
    return jsonify({"ok": True})


def _pick_search_representative(group_items):
    """Pick the item with the richest embedded metadata for searching."""
    def _richness(item):
        score = 0
        if item.isbn:
            score += 3
        if item.author and '[' not in (item.author or ''):
            score += 2
        if item.description:
            score += 1
        if item.title and item.title != item.file_name:
            score += 1
        if (item.extension or '').lower() in ('.epub', 'epub'):
            score += 1
        return score
    return max(group_items, key=_richness)


def _format_label(item):
    """Return a normalized format label like 'EPUB' for an item."""
    ext = (item.extension or '').lstrip('.').upper()
    return ext or 'OKÄNT'


def _file_write_warning(error_code):
    """Return a Swedish warning string for a file-write error code, or None."""
    if not error_code:
        return None
    label = FILE_WRITE_ERROR_MESSAGES.get(error_code, error_code)
    return f"Metadata sparades i biblioteket, men kunde inte skrivas till e-boksfilen ({label})."


@metadata_bp.route("/")
def index():
    return redirect(url_for("metadata.bulk_metadata"))


@metadata_bp.route("/cover/<int:item_id>")
def cover_item(item_id):
    item = get_item_or_404(item_id)
    if item.cover_path and os.path.exists(item.cover_path):
        return send_file(item.cover_path)
    # Group fallback: gruppmedlemmar delar omslag men cover-filen kan saknas
    # på enskilda format. Återanvänd en siblings cover-fil om den finns.
    if item.group_key:
        siblings = (
            LibraryItem.query
            .filter(LibraryItem.group_key == item.group_key)
            .filter(LibraryItem.id != item.id)
            .all()
        )
        for sibling in siblings:
            if sibling.cover_path and os.path.exists(sibling.cover_path):
                return send_file(sibling.cover_path)
    return ("", 404)


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
    return f"pending_enrichment_{item_id}"


def _enrichment_preview_key(item_id):
    return f"enrichment_preview_{item_id}"


def _ai_preview_key(item_id):
    return f"ai_preview_{item_id}"


_ENRICHMENT_FIELDS = [
    ("title", "Titel"),
    ("author", "Författare"),
    ("description", "Synopsis"),
    ("publisher", "Förlag"),
    ("isbn", "ISBN"),
    ("language", "Språk"),
    ("series", "Serie"),
    ("series_index", "Del"),
    ("genres", "Genre"),
    ("published_date", "Publiceringsdatum"),
]


def _build_enrichment_diff(item, fetched):
    rows = []
    for key, label in _ENRICHMENT_FIELDS:
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
        description = clean_text(request.form.get("description", ""))
        genres = request.form.get("genres", "").strip()
        published_date = request.form.get("published_date", "").strip()[:20]

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
        item.genres = genres or None
        item.published_date = published_date or None
        item.group_key = compute_group_key(item.title or "", item.author or "")

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
        if genres:
            written_text["genres"] = genres
        if published_date:
            written_text["published_date"] = published_date
        write_result = write_metadata_to_file(item, written_text, cover_to_embed)

        db.session.commit()

        flash("Metadata sparad.", "success")
        warning = _file_write_warning(write_result.get("error") if not write_result["ok"] else None)
        if warning:
            flash(warning, "warning")
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

    write_result = write_metadata_to_file(item, {}, cover_path)

    db.session.commit()

    if source:
        flash(f"Omslag hämtat från {source}.", "success")
    else:
        flash("Omslag hämtat och sparat.", "success")
    warning = _file_write_warning(write_result.get("error") if not write_result["ok"] else None)
    if warning:
        flash(warning, "warning")

    return redirect(url_for("metadata.metadata_item", item_id=item.id))


@metadata_bp.route("/metadata/bulk", methods=["GET", "POST"])
def bulk_metadata():
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
        action = request.form.get("action", "search")

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
            "review_needed": [],
            "no_match": [],
            "source_errors": 0,
            "file_write_failed": 0,
            "skipped": [],
            "limited": False,
            "processed": 0,
        }

        if action == "ai":
            if not os.environ.get("COLOPHON_MISTRAL_API_KEY"):
                flash(
                    "Mistral är inte konfigurerat. Lägg till COLOPHON_MISTRAL_API_KEY i .env.",
                    "error",
                )
            else:
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

                    result = fetch_ai_suggestions(item)
                    if not result["ok"]:
                        summary["no_match"].append({"title": item.title, "score": 0})
                        continue

                    high_fields = {
                        k: v["value"]
                        for k, v in result["suggestions"].items()
                        if v.get("confidence") == "high"
                        and v.get("value")
                        and k not in _AI_DISPLAY_ONLY
                    }
                    if not high_fields:
                        summary["no_match"].append({"title": item.title, "score": 0})
                        continue

                    ai_apply = apply_metadata_to_item(
                        item=item,
                        result=high_fields,
                        cover_dir=current_app.config["COVER_DIR"],
                        overwrite=overwrite,
                        write_to_file=True,
                        selected_fields=set(high_fields.keys()),
                    )
                    if not ai_apply["file_updated"] and ai_apply.get("file_write_error"):
                        summary["file_write_failed"] += 1
                    summary["updated"].append(
                        {
                            "title": item.title,
                            "source": "Mistral AI",
                            "score": len(high_fields),
                            "file_write_error": ai_apply.get("file_write_error"),
                        }
                    )

                db.session.commit()
                ai_parts = [f"Uppdaterade: {len(summary['updated'])}"]
                if summary["file_write_failed"]:
                    ai_parts.append(f"filskrivning misslyckades: {summary['file_write_failed']}")
                ai_parts += [
                    f"inga högsäkra förslag: {len(summary['no_match'])}",
                    f"hoppade över: {len(summary['skipped'])}",
                ]
                flash("AI-körning klar. " + ", ".join(ai_parts) + ".", "success")
        else:
            from collections import OrderedDict
            sync_groups = OrderedDict()
            for item in selected_items:
                key = item.group_key or f"_solo_{item.id}"
                sync_groups.setdefault(key, []).append(item)

            processed_count = 0

            for group_key, group_items in sync_groups.items():
                if processed_count >= max_items:
                    summary["limited"] = True
                    break

                processed_count += 1
                summary["processed"] = processed_count

                representative = _pick_search_representative(group_items)
                formats = [_format_label(it) for it in group_items]
                title_label = representative.title
                if len(group_items) > 1:
                    title_label = f"{representative.title} ({', '.join(formats)})"

                # Use the priority-based search input (Phase 4)
                search_inp = build_search_input(representative)

                search_outcome = search_all_sources_with_status(
                    title=search_inp["title"],
                    author=search_inp["author"],
                    isbn=search_inp["isbn"],
                    query_text=search_inp["query_text"],
                    include_calibre=True,
                )
                candidates = search_outcome["candidates"]
                source_results = search_outcome["source_results"]

                # If all sources errored (not just "no result"), count separately
                all_errored = all(
                    not sr.get("ok") and sr.get("status") not in ("no_result",)
                    for sr in source_results
                )
                if not candidates and all_errored:
                    summary["source_errors"] += 1
                    continue

                scoring = choose_best_metadata_explained(representative, candidates)
                best = scoring["best"]
                classification = scoring["classification"]

                if not best or classification == "no_match":
                    summary["no_match"].append(
                        {
                            "title": title_label,
                            "score": scoring["score"],
                        }
                    )
                    continue

                if classification in ("review_needed", "manual_only"):
                    # Medium-confidence match — flag for manual review, do not apply
                    summary["review_needed"].append(
                        {
                            "title": title_label,
                            "source": best.get("source", "Okänd källa"),
                            "score": scoring["score"],
                        }
                    )
                    continue

                # classification == "auto_apply" — high confidence, apply to all
                # group members so every format gets the same metadata.
                file_write_error = None
                for member in group_items:
                    apply_result = apply_metadata_to_item(
                        item=member,
                        result=best,
                        cover_dir=current_app.config["COVER_DIR"],
                        overwrite=overwrite,
                        write_to_file=True,
                    )
                    if not apply_result["file_updated"] and apply_result.get("file_write_error"):
                        summary["file_write_failed"] += 1
                        if member.id == representative.id:
                            file_write_error = apply_result.get("file_write_error")

                summary["updated"].append(
                    {
                        "title": title_label,
                        "source": best.get("source", "Okänd källa"),
                        "score": scoring["score"],
                        "file_write_error": file_write_error,
                    }
                )

            db.session.commit()
            parts = [f"Sparade: {len(summary['updated'])}"]
            if summary["review_needed"]:
                parts.append(f"granskning rekommenderas: {len(summary['review_needed'])}")
            if summary["no_match"]:
                parts.append(f"ingen säker träff: {len(summary['no_match'])}")
            if summary["source_errors"]:
                parts.append(f"källfel: {summary['source_errors']}")
            if summary["file_write_failed"]:
                parts.append(f"filskrivning misslyckades: {summary['file_write_failed']}")
            if summary["skipped"]:
                parts.append(f"hoppade över: {len(summary['skipped'])}")
            flash("Massuppdatering klar. " + ", ".join(parts) + ".", "success")

        items = (
            LibraryItem.query
            .order_by(LibraryItem.title.asc())
            .all()
        )

    from collections import OrderedDict
    groups = OrderedDict()
    for it in items:
        key = it.group_key or f"_ungrouped_{it.id}"
        groups.setdefault(key, []).append(it)

    total_count = LibraryItem.query.count()
    missing_count = LibraryItem.query.filter(
        db.or_(
            LibraryItem.author.is_(None),
            LibraryItem.author == "",
            LibraryItem.description.is_(None),
            LibraryItem.description == "",
            LibraryItem.cover_path.is_(None),
            LibraryItem.cover_path == "",
        )
    ).count()

    from sqlalchemy import func
    raw_counts = (
        db.session.query(
            func.lower(LibraryItem.extension),
            func.count(),
        )
        .group_by(func.lower(LibraryItem.extension))
        .all()
    )
    format_counts = {}
    for ext, count in raw_counts:
        if not ext:
            continue
        label = ext.lstrip(".").upper() or "OKÄNT"
        format_counts[label] = format_counts.get(label, 0) + count
    format_counts = dict(sorted(format_counts.items()))

    missing_cover_count = LibraryItem.query.filter(
        db.or_(
            LibraryItem.cover_path.is_(None),
            LibraryItem.cover_path == "",
        )
    ).count()

    return render_template(
        "bulk_metadata.html",
        items=items,
        groups=groups,
        summary=summary,
        total_count=total_count,
        missing_count=missing_count,
        format_counts=format_counts,
        missing_cover_count=missing_cover_count,
    )


@metadata_bp.route("/metadata/bulk/stream")
def bulk_stream():
    """SSE endpoint: run bulk metadata search with per-book, per-stage progress."""
    def _parse_int(val, default, lo, hi):
        try:
            v = int(val)
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    raw_ids = request.args.get("item_ids", "")
    overwrite = request.args.get("overwrite", "0") == "1"
    max_items = _parse_int(request.args.get("max_items"), 25, 1, 100)

    smart_replace_raw = request.args.get("smart_replace", "")
    smart_replace_fields = {
        f.strip() for f in smart_replace_raw.split(",") if f.strip()
    }

    item_ids = []
    for part in raw_ids.split(","):
        part = part.strip()
        if part.isdigit():
            item_ids.append(int(part))

    selected_items = [LibraryItem.query.get(iid) for iid in item_ids]
    selected_items = [it for it in selected_items if it is not None]

    def _error_stream(message):
        def _gen():
            yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
        return Response(_gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if not selected_items:
        return _error_stream("Inga giltiga böcker valda.")

    app = current_app._get_current_object()
    cover_dir = app.config["COVER_DIR"]
    ev_queue = queue.SimpleQueue()

    _abort_event.clear()

    def _run():
        with app.app_context():
            from app.models import LibraryItem as _Item, db as _db
            from app.services.metadata_pipeline import run_metadata_enrichment as _enrich
            from app.services.metadata_writer import (
                apply_metadata_to_item as _apply,
            )

            summary = {
                "updated": 0,
                "review_needed": 0,
                "no_match": 0,
                "source_errors": 0,
                "skipped": 0,
                "file_write_failed": 0,
                "limited": False,
            }

            # Group selected items by group_key — books that exist in multiple
            # formats are searched once and the result applied to all formats.
            from collections import OrderedDict
            groups = OrderedDict()
            for item in selected_items:
                fresh = _db.session.get(_Item, item.id)
                if not fresh:
                    continue
                key = fresh.group_key or f"_solo_{fresh.id}"
                groups.setdefault(key, []).append(fresh)

            total_groups = len(groups)
            index = 0
            processed = 0

            for group_key, group_items in groups.items():
                if _abort_event.is_set():
                    break

                index += 1

                if processed >= max_items:
                    summary["limited"] = True
                    break

                processed += 1

                representative = _pick_search_representative(group_items)
                formats = [_format_label(it) for it in group_items]
                item_ids = [it.id for it in group_items]

                ev_queue.put({
                    "type": "book_start",
                    "item_id": representative.id,
                    "item_ids": item_ids,
                    "title": representative.title or "",
                    "formats": formats,
                    "group_size": len(group_items),
                    "index": index,
                    "total": total_groups,
                })

                def _snapshot(it):
                    return {
                        "title": it.title or "",
                        "author": it.author or "",
                        "series": it.series or "",
                        "series_index": it.series_index or "",
                        "isbn": it.isbn or "",
                        "publisher": it.publisher or "",
                        "language": it.language or "",
                        "genres": it.genres or "",
                        "description": it.description or "",
                        "published_date": it.published_date or "",
                        "cover_path": it.cover_path or "",
                    }

                before_snapshots = {it.id: _snapshot(it) for it in group_items}

                all_source_details = []

                def _progress_cb(event, _bucket=all_source_details):
                    if event.get("type") == "progress" and event.get("source_details"):
                        _bucket.extend(event["source_details"])
                    ev_queue.put(event)

                try:
                    result = _enrich(
                        representative,
                        cover_dir=cover_dir,
                        on_progress=_progress_cb,
                        abort_check=_abort_event.is_set,
                    )
                except Exception:
                    app.logger.exception(
                        "bulk_stream enrichment failed for group %s (rep item %s)",
                        group_key, representative.id,
                    )
                    rep_before = before_snapshots.get(representative.id, {})
                    ev_queue.put({
                        "type": "book_done",
                        "item_id": representative.id,
                        "item_ids": item_ids,
                        "title": representative.title or "",
                        "formats": formats,
                        "group_size": len(group_items),
                        "index": index,
                        "total": total_groups,
                        "classification": "source_error",
                        "score": None,
                        "source": None,
                        "before": rep_before,
                        "candidate": {},
                        "warnings": [],
                        "has_cover_before": bool(rep_before.get("cover_path")),
                        "cover_url_fetched": "",
                        "has_cover_fetched": False,
                        "google_ok": False,
                        "google_candidates": 0,
                        "calibre_ok": False,
                        "calibre_candidates": 0,
                        "source_details": all_source_details,
                        "file_write_error": None,
                    })
                    summary["source_errors"] += 1
                    continue

                google_ok = None
                google_candidates = None
                calibre_ok = None
                calibre_candidates = None
                for sr in result.get("source_results", []):
                    if sr.get("source") == "google_books":
                        google_ok = sr.get("ok", False)
                        google_candidates = len(sr.get("candidates", []))
                    elif sr.get("source") == "calibre":
                        calibre_ok = sr.get("ok", False)
                        calibre_candidates = len(sr.get("candidates", []))

                score = result.get("score")
                classification = result.get("classification", "no_match")
                best = result.get("best")
                source = (best or {}).get("source") if best else None
                file_write_error = None
                rep_apply_result = None

                # Detect source_error: all sources errored (not just no results)
                source_results = result.get("source_results", [])
                all_errored = bool(source_results) and all(
                    not sr.get("ok") and sr.get("status") not in ("no_result",)
                    for sr in source_results
                )

                if not result.get("ok") and all_errored:
                    classification = "source_error"
                    summary["source_errors"] += 1
                elif not result.get("ok") or classification == "no_match":
                    classification = "no_match"
                    summary["no_match"] += 1
                elif classification in ("review_needed", "manual_only"):
                    classification = "review_needed"
                    summary["review_needed"] += 1
                else:
                    # auto_apply: apply same metadata to every group member
                    classification = "auto_apply"
                    for member in group_items:
                        apply_result = _apply(
                            item=member,
                            result=best,
                            cover_dir=cover_dir,
                            overwrite=overwrite,
                            write_to_file=True,
                            smart_replace_fields=smart_replace_fields,
                        )
                        if member.id == representative.id:
                            rep_apply_result = apply_result
                        if not apply_result.get("file_updated") and apply_result.get("file_write_error"):
                            if member.id == representative.id:
                                file_write_error = apply_result.get("file_write_error")
                            summary["file_write_failed"] += 1
                    summary["updated"] += 1

                fetched_payload = result.get("fetched_payload") or {}
                warnings = result.get("warnings") or []
                rep_before = before_snapshots.get(representative.id, {})

                # Per-field quality notes ("why is the fetched value better?")
                # — shown beneath each row in the comparison modal.
                quality_notes = {}
                if fetched_payload:
                    from app.services.quality import evaluate_quality
                    rep_author = rep_before.get("author", "")
                    for field_name in (
                        "title", "author", "isbn", "publisher", "genres", "description",
                        "published_date",
                    ):
                        existing = rep_before.get(field_name, "")
                        fetched_val = fetched_payload.get(field_name, "")
                        if not existing or not fetched_val:
                            continue
                        is_better, reason = evaluate_quality(
                            field_name, existing, fetched_val, author=rep_author,
                        )
                        if is_better and reason:
                            quality_notes[field_name] = reason

                apply_details = None
                if rep_apply_result is not None:
                    apply_details = {
                        "fields_added": rep_apply_result.get("fields_added", []),
                        "fields_replaced": rep_apply_result.get("fields_replaced", []),
                        "fields_skipped": rep_apply_result.get("fields_skipped", []),
                    }

                # Per-field confidence: highlight fields the user should
                # double-check on review_needed candidates. Fields without an
                # entry are implicitly "ok".
                field_confidence = {}
                signals = result.get("signals") or {}
                if signals.get("title_similarity", 1) < 0.8:
                    field_confidence["title"] = "low"
                if signals.get("author_similarity", 1) < 0.7:
                    field_confidence["author"] = "low"
                if not signals.get("isbn_exact_match"):
                    field_confidence["isbn"] = "low"
                if any("språk" in (w or "").lower() for w in warnings):
                    field_confidence["language"] = "low"

                ev_queue.put({
                    "type": "book_done",
                    "item_id": representative.id,
                    "item_ids": item_ids,
                    "title": representative.title or "",
                    "formats": formats,
                    "group_size": len(group_items),
                    "index": index,
                    "total": total_groups,
                    "classification": classification,
                    "score": score,
                    "source": source or "",
                    "before": rep_before,
                    "candidate": fetched_payload,
                    "warnings": warnings,
                    "quality_notes": quality_notes,
                    "has_cover_before": bool(rep_before.get("cover_path")),
                    "cover_url_fetched": fetched_payload.get("cover_url", "") or "",
                    "has_cover_fetched": bool(result.get("cover_path")),
                    "google_ok": google_ok,
                    "google_candidates": google_candidates,
                    "calibre_ok": calibre_ok,
                    "calibre_candidates": calibre_candidates,
                    "source_details": all_source_details,
                    "file_write_error": file_write_error,
                    "apply_details": apply_details,
                    "field_confidence": field_confidence,
                })

            try:
                _db.session.commit()
            except Exception:
                app.logger.exception("bulk_stream db commit failed")
                _db.session.rollback()

            if _abort_event.is_set():
                ev_queue.put({
                    "type": "aborted",
                    "processed": processed,
                    "summary": summary,
                })
            else:
                ev_queue.put({"type": "done", "summary": summary})
            ev_queue.put(None)

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


# ---------------------------------------------------------------------------
# Ephemeral result store for the SSE enrichment flow
# (single-user app — key is item_id, value is the preview dict)
# ---------------------------------------------------------------------------
_enrichment_cache: dict = {}


@metadata_bp.route("/metadata/<int:item_id>/enrich/stream")
def enrich_stream(item_id):
    """SSE endpoint: run metadata enrichment and stream stage-level progress.

    The frontend opens this URL with EventSource, shows each progress message,
    then redirects to the enrichment_preview route when "done" is received.
    The enrichment result is stored in _enrichment_cache so enrichment_preview
    can read it without needing the Flask session from within the thread.
    """
    item = get_item_or_404(item_id)

    def _error_stream(message):
        def _gen():
            yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
        return Response(_gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if not item.file_path or not Path(item.file_path).exists():
        return _error_stream("Bokfilen hittades inte på disk.")
    if Path(item.file_path).suffix.lower() not in {".epub", ".mobi", ".azw3", ".kepub"}:
        return _error_stream("Metadatahämtning stöder bara EPUB, MOBI, AZW3 och KEPUB.")

    app = current_app._get_current_object()
    ev_queue = queue.SimpleQueue()
    _abort_event.clear()

    def _run():
        with app.app_context():
            from app.models import LibraryItem, db as _db
            from app.services.metadata_pipeline import run_metadata_enrichment as _enrich
            fresh_item = _db.session.get(LibraryItem, item_id)
            if not fresh_item:
                ev_queue.put({"type": "error", "message": "Boken hittades inte."})
                ev_queue.put(None)
                return
            try:
                result = _enrich(
                    fresh_item,
                    cover_dir=app.config["COVER_DIR"],
                    on_progress=ev_queue.put,
                    abort_check=_abort_event.is_set,
                )
                if result["ok"]:
                    _enrichment_cache[item_id] = {
                        "fetched": result["fetched_payload"],
                        "sources_used": result["sources_used"],
                        "validation_warning": result["validation_warning"],
                        "score": result["score"],
                    }
                    ev_queue.put({"type": "done", "ok": True})
                else:
                    ev_queue.put({"type": "done", "ok": False, "message": result["error"]})
            except Exception as exc:
                app.logger.exception("enrich_stream failed for item %s", item_id)
                ev_queue.put({"type": "error", "message": str(exc)})
            finally:
                ev_queue.put(None)

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


@metadata_bp.route("/metadata/<int:item_id>/enrich", methods=["POST"])
def enrich_item_metadata(item_id):
    item = get_item_or_404(item_id)

    source_path = Path(item.file_path)

    if not source_path.exists():
        flash("Bokfilen hittades inte på disk.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    if source_path.suffix.lower() not in {".epub", ".mobi", ".azw3", ".kepub"}:
        flash("Metadatahämtning stöder bara EPUB, MOBI, AZW3 och KEPUB.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    lock_path = Path("/tmp") / f"colophon_enrichment_{item.id}.lock"

    if lock_path.exists():
        flash("Metadatahämtning körs redan på denna bok. Vänta tills den är klar.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    try:
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
        cover_dir = current_app.config["COVER_DIR"]

        result = run_metadata_enrichment(item, cover_dir=cover_dir)

        if not result["ok"]:
            flash(result["error"], "error")
            return redirect(url_for("metadata.metadata_item", item_id=item.id))

        # Clean up any previous preview cover that is being replaced
        old_preview = session.get(_enrichment_preview_key(item.id))
        old_cover = (old_preview or {}).get("fetched", {}).get("cover_path")
        new_cover = result["fetched_payload"].get("cover_path")
        if old_cover and old_cover != new_cover:
            try:
                os.unlink(old_cover)
            except OSError:
                pass

        session[_enrichment_preview_key(item.id)] = {
            "fetched": result["fetched_payload"],
            "sources_used": result["sources_used"],
            "validation_warning": result["validation_warning"],
            "score": result["score"],
        }

        return redirect(url_for("metadata.enrichment_preview", item_id=item.id))

    except Exception as error:
        db.session.rollback()
        flash(f"Kunde inte hämta metadata: {error}", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    finally:
        try:
            lock_path.unlink()
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)


@metadata_bp.route("/metadata/<int:item_id>/enrich/preview", methods=["GET"])
def enrichment_preview(item_id):
    item = get_item_or_404(item_id)
    preview = session.get(_enrichment_preview_key(item.id))

    # SSE flow stores the result in the module-level cache because Flask session
    # is not writable from background threads. Move it into session now.
    if not preview and item_id in _enrichment_cache:
        preview = _enrichment_cache.pop(item_id)
        session[_enrichment_preview_key(item.id)] = preview

    if not preview:
        flash("Ingen hämtad metadata att granska. Kör hämtningen först.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    fetched = preview.get("fetched") or {}
    rows = _build_enrichment_diff(item, fetched)

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
        "metadata_enrichment_preview.html",
        item=item,
        rows=rows,
        cover_status=cover_status,
        cover_default_check=cover_default_check,
        has_fetched_cover=has_fetched_cover,
        sources_used=preview.get("sources_used") or [],
        validation_warning=preview.get("validation_warning"),
    )


@metadata_bp.route("/metadata/<int:item_id>/enrich/preview-cover")
def enrichment_preview_cover(item_id):
    preview = session.get(_enrichment_preview_key(item_id))
    cover_path = (preview or {}).get("fetched", {}).get("cover_path")
    if not cover_path or not os.path.exists(cover_path):
        return ("", 404)
    return send_file(cover_path)


@metadata_bp.route("/metadata/<int:item_id>/enrich/apply", methods=["POST"])
def enrichment_apply(item_id):
    item = get_item_or_404(item_id)
    preview = session.get(_enrichment_preview_key(item.id))
    if not preview:
        flash("Förhandsgranskningen har gått ut. Kör hämtningen igen.", "error")
        return redirect(url_for("metadata.metadata_item", item_id=item.id))

    fetched = preview.get("fetched") or {}
    selected = set(request.form.getlist("fields"))

    apply_result = _pipeline_apply(
        item=item,
        fetched=fetched,
        selected_fields=selected,
        cover_dir=current_app.config["COVER_DIR"],
        write_to_file=True,
    )

    db.session.commit()

    cover_src = fetched.get("cover_path")
    if cover_src and os.path.exists(cover_src):
        try:
            os.unlink(cover_src)
        except OSError:
            pass
    session.pop(_enrichment_preview_key(item.id), None)

    db_updated = apply_result.get("db_updated", 0)
    cover_saved = apply_result.get("cover_saved", False)
    file_updated = apply_result.get("file_updated", False)
    file_write_error = apply_result.get("file_write_error")

    total = db_updated + (1 if cover_saved else 0)
    if total:
        parts = [f"{db_updated} fält uppdaterade"]
        if cover_saved:
            parts.append("omslag bytt")
        if file_updated:
            parts.append("filen uppdaterad")
        flash("Metadata sparad (" + ", ".join(parts) + ").", "success")
        warning = _file_write_warning(file_write_error)
        if warning:
            flash(warning, "warning")
    else:
        flash("Inga fält valdes — inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))


@metadata_bp.route("/metadata/<int:item_id>/enrich/cancel", methods=["POST"])
def enrichment_cancel(item_id):
    item = get_item_or_404(item_id)
    preview = session.pop(_enrichment_preview_key(item.id), None)
    cover_src = (preview or {}).get("fetched", {}).get("cover_path")
    if cover_src and os.path.exists(cover_src):
        try:
            os.unlink(cover_src)
        except OSError:
            pass
    flash("Förhandsgranskning avbruten. Inget sparades.", "success")
    return redirect(url_for("metadata.metadata_item", item_id=item.id))


# ---------------------------------------------------------------------------
# Backward-compatible aliases for old /bookf/* URL paths
# ---------------------------------------------------------------------------

@metadata_bp.route("/metadata/<int:item_id>/bookf", methods=["POST"])
def run_bookf_for_item(item_id):
    return enrich_item_metadata(item_id)


@metadata_bp.route("/metadata/<int:item_id>/bookf/preview", methods=["GET"])
def bookf_preview(item_id):
    return redirect(url_for("metadata.enrichment_preview", item_id=item_id))


@metadata_bp.route("/metadata/<int:item_id>/bookf/preview-cover")
def bookf_preview_cover(item_id):
    return enrichment_preview_cover(item_id)


@metadata_bp.route("/metadata/<int:item_id>/bookf/apply", methods=["POST"])
def bookf_apply(item_id):
    return enrichment_apply(item_id)


@metadata_bp.route("/metadata/<int:item_id>/bookf/cancel", methods=["POST"])
def bookf_cancel(item_id):
    return enrichment_cancel(item_id)


# Fields shown in the AI preview table (display order)
_AI_PREVIEW_FIELDS = [
    ("series", "Serie"),
    ("series_index", "Del"),
    ("title", "Titel"),
    ("author", "Författare"),
    ("language", "Språk"),
    ("publisher", "Förlag"),
    ("genres", "Genre"),
    ("description", "Synopsis"),
    ("published_date", "Publiceringsdatum"),
]

_AI_DISPLAY_ONLY: set = set()


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

    return render_template(
        "metadata_ai_preview.html",
        item=item,
        rows=rows,
        subjects_display=None,
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


@metadata_bp.route("/metadata/<int:item_id>/json")
def metadata_json(item_id):
    item = get_item_or_404(item_id)
    return jsonify({
        "id": item.id,
        "title": item.title or "",
        "author": item.author or "",
        "series": item.series or "",
        "series_index": item.series_index or "",
        "isbn": item.isbn or "",
        "publisher": item.publisher or "",
        "language": item.language or "",
        "description": item.description or "",
        "genres": item.genres or "",
        "published_date": item.published_date or "",
        "file_name": item.file_name,
        "extension": item.extension,
        "size_bytes": item.size_bytes,
        "cover_path": bool(item.cover_path),
        "manual_metadata": bool(item.manual_metadata),
        "ai_configured": bool(os.environ.get("COLOPHON_MISTRAL_API_KEY")),
    })


@metadata_bp.route("/metadata/<int:item_id>/save-json", methods=["POST"])
def save_metadata_json(item_id):
    item = get_item_or_404(item_id)
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "no_data"}), 400

    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title_required"}), 400

    item.title = title
    item.author = (data.get("author") or "").strip() or None
    item.series = (data.get("series") or "").strip() or None
    item.series_index = (data.get("series_index") or "").strip() or None
    item.isbn = (data.get("isbn") or "").strip() or None
    item.publisher = (data.get("publisher") or "").strip() or None
    item.language = (data.get("language") or "").strip() or None
    item.description = clean_text(data.get("description") or "") or None
    item.genres = (data.get("genres") or "").strip() or None
    item.published_date = (data.get("published_date") or "").strip()[:20] or None
    item.manual_metadata = True
    item.group_key = compute_group_key(item.title or "", item.author or "")

    written_text = {}
    for field in (
        "title", "author", "series", "series_index", "isbn", "publisher",
        "language", "description", "genres", "published_date",
    ):
        val = getattr(item, field)
        if val:
            written_text[field] = val

    write_result = write_metadata_to_file(item, written_text, None)
    db.session.commit()

    resp = {"ok": True}
    if not write_result["ok"] and write_result.get("error") not in ("no_fields", "not_installed", "unsupported_format"):
        resp["file_write_warning"] = write_result.get("error")
    return jsonify(resp)


@metadata_bp.route("/metadata/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    """Delete a book from the library, optionally including the file on disk."""
    item = get_item_or_404(item_id)
    delete_file = request.form.get("delete_file") == "1"

    title = item.title
    file_path = item.file_path
    cover_path = item.cover_path

    if cover_path:
        try:
            os.unlink(cover_path)
        except OSError:
            pass

    file_deleted = False
    file_error = None
    if delete_file and file_path and os.path.exists(file_path):
        try:
            os.unlink(file_path)
            file_deleted = True
        except OSError as exc:
            file_error = str(exc)
            logger.warning("Kunde inte radera fil %s: %s", file_path, exc)

    db.session.delete(item)
    db.session.commit()

    return jsonify({
        "ok": True,
        "title": title,
        "file_deleted": file_deleted,
        "file_error": file_error,
    })


@metadata_bp.route("/metadata/bulk/delete", methods=["POST"])
def bulk_delete():
    """Delete multiple books. Expects JSON: {item_ids: [...], delete_files: bool}"""
    data = request.get_json(silent=True) or {}

    item_ids = data.get("item_ids") or []
    delete_files = bool(data.get("delete_files"))

    if not item_ids:
        return jsonify({"ok": False, "error": "Inga böcker valda."}), 400

    deleted = 0
    file_errors = 0

    for raw_id in item_ids:
        try:
            iid = int(raw_id)
        except (TypeError, ValueError):
            continue

        item = LibraryItem.query.get(iid)
        if not item:
            continue

        if item.cover_path:
            try:
                os.unlink(item.cover_path)
            except OSError:
                pass

        if delete_files and item.file_path and os.path.exists(item.file_path):
            try:
                os.unlink(item.file_path)
            except OSError:
                file_errors += 1

        db.session.delete(item)
        deleted += 1

    db.session.commit()

    return jsonify({
        "ok": True,
        "deleted": deleted,
        "file_errors": file_errors,
    })


@metadata_bp.route("/metadata/<int:item_id>/fetch-json", methods=["POST"])
def fetch_metadata_json(item_id):
    item = get_item_or_404(item_id)

    query_text = item.isbn or " ".join(
        part for part in [item.title, item.author] if part
    ).strip()

    try:
        results = search_all_sources(
            title=item.title or "",
            author=item.author or "",
            isbn=item.isbn or "",
            query_text=query_text,
            include_calibre=True,
        )
        best, best_score = choose_best_metadata(item, results)

        if not best:
            return jsonify({"ok": False, "error": "no_match"})

        def _txt(v):
            return str(v).strip() if v is not None else ""

        return jsonify({
            "ok": True,
            "fetched": {
                "title": _txt(best.get("title")),
                "author": _txt(best.get("author")),
                "description": clean_text(_txt(best.get("description"))),
                "publisher": _txt(best.get("publisher")),
                "isbn": _txt(best.get("isbn")),
                "language": _txt(best.get("language")),
                "series": _txt(best.get("series")),
                "series_index": _txt(best.get("series_index")),
                "genres": _txt(best.get("genres")),
                "published_date": _txt(best.get("published_date"))[:20],
            },
            "score": best_score,
            "source": best.get("source", ""),
        })
    except Exception as error:
        logger.error("fetch_metadata_json error: %s", error)
        return jsonify({"ok": False, "error": str(error)}), 500


@metadata_bp.route("/metadata/<int:item_id>/ai-json", methods=["POST"])
def ai_metadata_json(item_id):
    item = get_item_or_404(item_id)

    if not os.environ.get("COLOPHON_MISTRAL_API_KEY"):
        return jsonify({"ok": False, "error": "not_configured"}), 400

    requested_fields = [
        f.strip()
        for f in request.args.get("fields", "").split(",")
        if f.strip()
    ]

    result = fetch_ai_suggestions(item, fields=requested_fields or None)

    if not result["ok"]:
        return jsonify({"ok": False, "error": result["error"]}), 500

    flat = {
        k: v["value"]
        for k, v in result["suggestions"].items()
        if k not in _AI_DISPLAY_ONLY and v.get("confidence") != "low" and v.get("value")
    }

    return jsonify({"ok": True, "suggestions": flat})
