# Colophon – e-book metadata manager
"""Shared metadata pipeline for single-book and batch enrichment flows.

Orchestration lives here; routes stay thin (receive → call → render/redirect).
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from flask_babel import gettext as _

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Completeness score
# ---------------------------------------------------------------------------

# Weights are heuristic: cover and description dominate the visual experience,
# the rest are "nice to have". Max score = 9.
FIELD_WEIGHTS = {
    "cover":          3,
    "description":    3,
    "genres":         1,
    "published_date": 1,
    "publisher":      1,
}

# A field with a value can still count as "missing" if the value looks like
# a placeholder. Each entry is a predicate(value) -> bool ("treat as missing").
QUALITY_THRESHOLDS = {
    "description": lambda v: len((v or "").strip()) < 50,
    "genres":      lambda v: (v or "").strip().lower() in {"fiction", "unknown", ""},
}


def _cover_is_placeholder(item):
    """Treat very small cover files as placeholders (e.g. 1px tracking pixels)."""
    cover_path = getattr(item, "cover_path", None)
    if not cover_path:
        return True
    try:
        return os.path.getsize(cover_path) < 5_000
    except OSError:
        return True


def completeness_score(item):
    """Return 0..9. 0 = complete, 9 = entirely missing.

    Higher score means the item would benefit more from a fresh fetch. The
    score is a rough heuristic — used for prioritising prefetch, not for
    user-facing quality grading.
    """
    score = 0
    for field, weight in FIELD_WEIGHTS.items():
        if field == "cover":
            if _cover_is_placeholder(item):
                score += weight
            continue
        value = getattr(item, field, "") or ""
        threshold = QUALITY_THRESHOLDS.get(field)
        if not str(value).strip() or (threshold and threshold(value)):
            score += weight
    return score


# ---------------------------------------------------------------------------
# Search input construction
# ---------------------------------------------------------------------------

def build_search_input(item, local_metadata=None):
    """Return the best available search input for external metadata lookup.

    Priority order:
      1. ISBN from local_metadata (file)
      2. ISBN from DB item
      3. title + author from local_metadata (file)
      4. title + author from DB item
      5. cleaned filename

    local_metadata should come from scan_file_local() so that metadata
    embedded in the ebook file (often richer than DB) is used first.

    Returns a dict with keys:
        query_text, title, author, isbn, source, warnings
    """
    warnings = []

    file_isbn = (local_metadata or {}).get("isbn", "").strip()
    db_isbn = (item.isbn or "").strip()

    file_title = (local_metadata or {}).get("title", "").strip()
    file_author = (local_metadata or {}).get("author", "").strip()
    db_title = (item.title or "").strip()
    db_author = (item.author or "").strip()

    if file_isbn:
        return {
            "query_text": file_isbn,
            "title": file_title or db_title,
            "author": file_author or db_author,
            "isbn": file_isbn,
            "source": "file_isbn",
            "warnings": warnings,
        }

    if db_isbn:
        return {
            "query_text": db_isbn,
            "title": db_title,
            "author": db_author,
            "isbn": db_isbn,
            "source": "db_isbn",
            "warnings": warnings,
        }

    if file_title or file_author:
        query_text = " ".join(p for p in [file_title, file_author] if p)
        return {
            "query_text": query_text,
            "title": file_title,
            "author": file_author,
            "isbn": "",
            "source": "file_title_author",
            "warnings": warnings,
        }

    if db_title or db_author:
        query_text = " ".join(p for p in [db_title, db_author] if p)
        return {
            "query_text": query_text,
            "title": db_title,
            "author": db_author,
            "isbn": "",
            "source": "db_title_author",
            "warnings": warnings,
        }

    # Fallback: use the filename stem
    file_path = getattr(item, "file_path", "") or ""
    filename_stem = Path(file_path).stem if file_path else ""
    warnings.append(_("Searching by filename — metadata is missing in the database."))
    return {
        "query_text": filename_stem,
        "title": filename_stem,
        "author": "",
        "isbn": "",
        "source": "filename",
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Main enrichment orchestration
# ---------------------------------------------------------------------------

def run_metadata_enrichment(
    item,
    cover_dir=None,
    include_google=True,
    include_calibre=True,
    include_wikipedia=True,
    local_metadata=None,
    on_progress=None,
    abort_check=None,
):
    """Search external sources for the best metadata candidate.

    Emits stage-level progress events via on_progress when provided.

    Progressive stages (new flow):
        read_file_metadata
        fast_sources       — Wikipedia + Google Books started in parallel
        google_books       — Google Books finished (per-source detail)
        wikipedia          — Wikipedia finished (per-source detail)
        fast_preview       — best candidate from fast sources (~1s)
        calibre            — Calibre finished
        final_preview      — best candidate after Calibre
        scoring            — legacy alias, kept for back-compat
        preview_ready      — legacy alias, kept for back-compat

    Always reads fresh metadata from the ebook file before building the
    search input, so ISBN or title/author embedded in the file takes
    priority over potentially weak DB data (e.g. from a filename-only
    initial scan).  Pass local_metadata explicitly to override.

    Returns a result dict:
        ok                 bool
        best               dict | None  — best raw candidate from sources
        score              float
        signals            dict
        warnings           list[str]
        classification     str
        all_scored         list[dict]
        sources_used       list[str]
        source_results     list[dict]   — per-source status objects
        search_input       dict         — what was sent to external sources
        local_metadata     dict | None  — metadata read from file
        validation_warning str | None
        fetched_payload    dict         — cleaned payload ready for preview
        cover_path         str | None   — local path to downloaded cover
        error              str | None   — human-readable error when ok=False
    """
    from app.services.metadata_sources import (
        choose_best_metadata_explained,
        download_cover_to_file,
        google_books_search_with_status,
        deduplicate_results,
    )
    from app.services.metadata_calibre import fetch_calibre_metadata_with_status
    from app.services.metadata_wikipedia import search_wikipedia_with_status

    item_id = getattr(item, "id", None)
    item_title = getattr(item, "title", "") or ""

    def _emit(stage, **kwargs):
        if on_progress:
            on_progress({
                "type": "progress",
                "stage": stage,
                "item_id": item_id,
                "title": item_title,
                **kwargs,
            })

    def _aborted():
        return abort_check is not None and abort_check()

    # Stage 1: read file metadata
    _emit(
        "read_file_metadata",
        status="reading",
        message=_("Reading existing metadata from file..."),
        warnings=[],
    )

    if local_metadata is None and getattr(item, "file_path", None):
        try:
            local_metadata = scan_file_local(item.file_path)
        except Exception as exc:
            logger.debug("scan_file_local failed for %s: %s", item.file_path, exc)
            local_metadata = None

    search_input = build_search_input(item, local_metadata)

    source_results = []
    all_candidates = []

    # Stage 2: fast sources (Wikipedia + Google Books in parallel)
    fast_jobs = {}
    if include_wikipedia:
        fast_jobs["wikipedia"] = lambda: search_wikipedia_with_status(
            title=search_input["title"],
            author=search_input["author"],
            lang=(search_input.get("language") or "en")[:2] or "en",
        )
    if include_google:
        fast_jobs["google_books"] = lambda: google_books_search_with_status(
            query_text=search_input["query_text"],
            title=search_input["title"],
            author=search_input["author"],
            isbn=search_input["isbn"],
        )

    if fast_jobs:
        _emit(
            "fast_sources",
            status="searching",
            message=_("Searching fast sources (Wikipedia + Google Books)..."),
            sources=list(fast_jobs.keys()),
            warnings=[],
        )

    fast_results = _run_fast_sources(fast_jobs)

    # Emit per-source completion events in a stable order so UIs that
    # listen for stage="google_books" (existing batch UI) keep working.
    if "google_books" in fast_results:
        google_sr = fast_results["google_books"]
        source_results.append(google_sr)
        google_candidates_list = google_sr.get("candidates", [])
        all_candidates.extend(google_candidates_list)
        google_source_details = [{
            "source": "Google Books",
            "fields_found": (
                google_candidates_list[0].get("fields_found", [])
                if google_candidates_list else []
            ),
            "ok": bool(google_sr["ok"]),
        }]
        _emit(
            "google_books",
            source="google_books",
            status="ok" if google_sr["ok"] else google_sr["status"],
            message=google_sr["message"],
            candidates_found=len(google_candidates_list),
            source_details=google_source_details,
            warnings=[],
        )

    if "wikipedia" in fast_results:
        wiki_sr = fast_results["wikipedia"]
        source_results.append(wiki_sr)
        wiki_candidates_list = wiki_sr.get("candidates", [])
        all_candidates.extend(wiki_candidates_list)
        wiki_source_details = [{
            "source": "Wikipedia",
            "fields_found": (
                wiki_candidates_list[0].get("fields_found", [])
                if wiki_candidates_list else []
            ),
            "ok": bool(wiki_sr["ok"]),
        }]
        _emit(
            "wikipedia",
            source="wikipedia",
            status="ok" if wiki_sr["ok"] else wiki_sr["status"],
            message=wiki_sr["message"],
            candidates_found=len(wiki_candidates_list),
            source_details=wiki_source_details,
            warnings=[],
        )

    # Emit fast_preview with the best candidate so far so the UI can fill
    # fields before Calibre finishes.
    if all_candidates:
        fast_scoring = choose_best_metadata_explained(item, list(all_candidates))
        fast_best = fast_scoring.get("best")
        fast_payload = _build_fetched_payload(fast_best) if fast_best else {}
        _emit(
            "fast_preview",
            status="ok" if fast_best else "no_match",
            message=_("Fast sources done."),
            candidates_found=len(fast_scoring.get("all_scored") or []),
            score=fast_scoring.get("score"),
            payload=fast_payload,
            source=(fast_best or {}).get("source", "") if fast_best else "",
            warnings=[],
        )

    # Stage 3: Calibre (skipped on abort to bail out faster)
    if _aborted():
        include_calibre = False

    if include_calibre:
        _emit(
            "calibre",
            source="calibre",
            status="searching",
            message=_("Searching Calibre sources..."),
            candidates_found=0,
            warnings=[],
        )
        calibre_sr = fetch_calibre_metadata_with_status(
            title=search_input["title"],
            author=search_input["author"],
        )
        source_results.append(calibre_sr)
        calibre_candidates_list = calibre_sr.get("candidates", [])
        all_candidates.extend(calibre_candidates_list)

        # One source_details entry per Calibre plugin (Goodreads, Fantastic
        # Fiction, etc.) so the UI can show per-plugin coverage. All plugins
        # share the same fields_found because Calibre returns merged data.
        calibre_source_details = []
        for c in calibre_candidates_list:
            plugins = c.get("plugins_used") or []
            fields = c.get("fields_found", [])
            if plugins:
                for plugin in plugins:
                    calibre_source_details.append({
                        "source": plugin,
                        "fields_found": list(fields),
                        "ok": True,
                    })
            else:
                calibre_source_details.append({
                    "source": c.get("source", "Calibre"),
                    "fields_found": list(fields),
                    "ok": True,
                })
        if not calibre_source_details:
            calibre_source_details = [{
                "source": "Calibre",
                "fields_found": [],
                "ok": bool(calibre_sr["ok"]),
            }]

        _emit(
            "calibre",
            source="calibre",
            status="ok" if calibre_sr["ok"] else calibre_sr["status"],
            message=calibre_sr["message"],
            candidates_found=len(calibre_candidates_list),
            source_details=calibre_source_details,
            warnings=[],
        )

    all_candidates = deduplicate_results(all_candidates)

    # Stage 4: scoring
    _emit(
        "scoring",
        status="scoring",
        message=_("Comparing candidates..."),
        candidates_found=len(all_candidates),
        warnings=[],
    )

    scoring = choose_best_metadata_explained(item, all_candidates)
    best = scoring["best"]
    best_score = scoring["score"]

    # Stage 5: preview_ready
    n_candidates = len(scoring["all_scored"])
    if best:
        best_source = best.get("source", "")
        _emit(
            "preview_ready",
            status="ok",
            message=_(
                "Found %(count)d possible matches. Best match: %(score)d points, %(source)s.",
                count=n_candidates, score=round(best_score), source=best_source,
            ),
            candidates_found=n_candidates,
            warnings=scoring["warnings"],
        )
    else:
        _emit(
            "preview_ready",
            status="no_match",
            message=_("No secure matches found."),
            candidates_found=n_candidates,
            warnings=[],
        )

    if not best:
        return {
            "ok": False,
            "best": None,
            "score": best_score,
            "signals": scoring["signals"],
            "warnings": scoring["warnings"],
            "classification": scoring["classification"],
            "all_scored": scoring["all_scored"],
            "sources_used": [],
            "source_results": source_results,
            "search_input": search_input,
            "local_metadata": local_metadata,
            "validation_warning": None,
            "fetched_payload": {},
            "cover_path": None,
            "error": _("No secure metadata matches were found from Google Books or Calibre."),
        }

    cover_path_for_preview = None
    if cover_dir and best.get("cover_url"):
        os.makedirs(cover_dir, exist_ok=True)
        downloaded = download_cover_to_file(
            cover_url=best["cover_url"],
            cover_dir=cover_dir,
            item_id=item.id,
        )
        if downloaded:
            ext = os.path.splitext(downloaded)[1] or ".jpg"
            preview_path = os.path.join(cover_dir, f"preview_{item.id}{ext}")
            try:
                os.replace(downloaded, preview_path)
                cover_path_for_preview = preview_path
            except OSError:
                cover_path_for_preview = downloaded

    fetched_payload = _build_fetched_payload(best, cover_path=cover_path_for_preview)

    validation_warning = _build_validation_warning(item, fetched_payload)

    # Emit final_preview after scoring + cover download so the UI can replace
    # any placeholder values shown after fast_preview with the final ones.
    _emit(
        "final_preview",
        status="ok",
        message=_("Final metadata ready."),
        candidates_found=len(scoring["all_scored"]),
        score=best_score,
        payload=fetched_payload,
        source=best.get("source", "") if best else "",
        warnings=scoring["warnings"],
    )

    return {
        "ok": True,
        "best": best,
        "score": best_score,
        "signals": scoring["signals"],
        "warnings": scoring["warnings"],
        "classification": scoring["classification"],
        "all_scored": scoring["all_scored"],
        "sources_used": [best["source"]] if best.get("source") else [],
        "source_results": source_results,
        "search_input": search_input,
        "local_metadata": local_metadata,
        "validation_warning": validation_warning,
        "fetched_payload": fetched_payload,
        "cover_path": cover_path_for_preview,
        "error": None,
    }


def _run_fast_sources(jobs):
    """Run zero-arg callables in parallel and collect their results.

    `jobs` is a {name: callable} mapping. Returns {name: result_or_error_dict}.
    Each callable is expected to never raise — on exception we synthesise the
    same shape as a `network_or_plugin_error` result.
    """
    if not jobs:
        return {}

    results = {}
    with ThreadPoolExecutor(max_workers=max(2, len(jobs))) as pool:
        future_to_name = {pool.submit(fn): name for name, fn in jobs.items()}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                logger.debug("Fast source %s raised: %s", name, exc, exc_info=True)
                results[name] = {
                    "source": name,
                    "ok": False,
                    "status": "network_or_plugin_error",
                    "duration_ms": 0,
                    "message": str(exc),
                    "candidates": [],
                    "raw_debug": {"returncode": None, "stderr_excerpt": ""},
                }
    return results


def _build_fetched_payload(best, cover_path=None):
    """Produce the standard fetched_payload dict from a candidate."""
    if not best:
        return {}

    from app.services.metadata_sources import clean_text as _clean
    from app.services.text_utils import clean_title as _clean_title

    def _txt(value):
        return str(value).strip() if value not in (None, "") else ""

    raw_title = _txt(best.get("title"))
    title_info = _clean_title(raw_title) if raw_title else {
        "cleaned_title": "",
        "extracted_series": None,
        "extracted_series_index": None,
        "was_modified": False,
    }
    candidate_series = _txt(best.get("series")) or (title_info["extracted_series"] or "")
    candidate_series_index = _txt(best.get("series_index")) or (
        title_info["extracted_series_index"] or ""
    )

    return {
        "title": title_info["cleaned_title"] or raw_title,
        "author": _txt(best.get("author")),
        "description": _clean(_txt(best.get("description"))),
        "publisher": _txt(best.get("publisher")),
        "isbn": _txt(best.get("isbn")),
        "language": _txt(best.get("language")),
        "series": candidate_series,
        "series_index": candidate_series_index,
        "genres": _txt(best.get("genres")),
        "published_date": _txt(best.get("published_date"))[:10],
        "cover_url": _txt(best.get("cover_url")),
        "cover_path": cover_path,
    }


def _build_validation_warning(item, fetched_payload):
    def _normalize(value):
        return (value or "").lower().replace(":", " ").replace("-", " ").strip()

    old_title = _normalize(item.title)
    old_author = _normalize(item.author)
    if not (old_title or old_author):
        return None
    new_title = _normalize(fetched_payload.get("title"))
    new_author = _normalize(fetched_payload.get("author"))

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

    if (new_title or new_author) and title_score < 0.55 and author_score < 0.60:
        return (
            f"Hämtad metadata verkar avvika från bokens titel/författare "
            f"(titel: {fetched_payload.get('title') or 'okänd'}, "
            f"författare: {fetched_payload.get('author') or 'okänd'}). "
            f"Granska noggrant innan du sparar."
        )
    return None


# ---------------------------------------------------------------------------
# Apply enrichment result
# ---------------------------------------------------------------------------

def apply_enrichment_result(
    item,
    fetched,
    selected_fields,
    cover_dir,
    write_to_file=True,
):
    """Apply a fetched metadata payload to the DB item and optionally to file.

    Wraps metadata_writer.apply_metadata_to_item so routes stay thin.

    Returns the apply_result dict from the writer:
        db_updated, file_updated, cover_saved, cover_attempted
    """
    from app.services.metadata_writer import apply_metadata_to_item

    return apply_metadata_to_item(
        item=item,
        result=dict(fetched),
        cover_dir=cover_dir,
        overwrite=True,
        write_to_file=write_to_file,
        selected_fields=selected_fields,
    )


# ---------------------------------------------------------------------------
# Local file scan
# ---------------------------------------------------------------------------

def scan_file_local(file_path, cover_dir=None):
    """Extract local metadata from a single ebook file.

    Delegates to scanner.extract_local_metadata and returns the normalized
    dict (title, author, …, source, quality, warnings).
    """
    from app.services.scanner import extract_local_metadata
    return extract_local_metadata(file_path, cover_dir=cover_dir)
