# Colophon – e-book metadata manager
"""Shared metadata pipeline for single-book and batch enrichment flows.

Orchestration lives here; routes stay thin (receive → call → render/redirect).

Sources are merged **field by field** (see services/metadata_merge.py) rather
than picking a single winning row, and run in cost tiers with completeness-
driven escalation:

    Tier 1 (fast)   — embedded file (OPF) + Google Books + Wikipedia, run in
                      parallel. ~1s, no expensive subprocess.
    Tier 2 (deep)   — Calibre's fetch-ebook-metadata (a slow subprocess that
                      queries many plugins). Only run when needed.

The fetch mode caps the escalation:
    fast  — tier 1 only, never Calibre.
    more  — tier 1, then Calibre only if essential fields are still missing
            (the default; cheap books stay fast, hard books get help).
    deep  — tier 1, then Calibre always.
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

# Essential fields used by the escalation gate: if the merged payload is missing
# any of these after the fast tier, "more" mode escalates to Calibre.
ESSENTIAL_FIELDS = ("title", "author", "description", "cover", "series")

# Valid fetch modes and their human order. Stored as METADATA_FETCH_MODE.
FETCH_MODES = ("fast", "more", "deep")
DEFAULT_FETCH_MODE = "more"


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


def _missing_essentials(payload):
    """Return the essential fields the merged payload does not yet cover."""
    missing = []
    for field in ESSENTIAL_FIELDS:
        if field == "cover":
            if not (payload.get("cover_url") or "").strip():
                missing.append("cover")
        elif not str(payload.get(field) or "").strip():
            missing.append(field)
    return missing


# ---------------------------------------------------------------------------
# Settings resolution (DB > env > default), overridable per call
# ---------------------------------------------------------------------------

def _resolve_flag(explicit, setting_key, default=True):
    """Return explicit when given, else the DB/env setting, else default."""
    if explicit is not None:
        return bool(explicit)
    from app.services.app_settings import get_setting
    raw = get_setting(setting_key, "true" if default else "false")
    return (raw or "").strip().lower() == "true"


def resolve_fetch_mode(explicit=None):
    """Return the active fetch mode (fast|more|deep)."""
    if explicit:
        mode = str(explicit).strip().lower()
    else:
        from app.services.app_settings import get_setting
        mode = (get_setting("METADATA_FETCH_MODE", DEFAULT_FETCH_MODE) or "").strip().lower()
    return mode if mode in FETCH_MODES else DEFAULT_FETCH_MODE


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


def _file_candidate(local_metadata):
    """Build a merge candidate from the ebook file's own embedded metadata.

    The embedded file is the single most trustworthy source for series, and is
    free (no network). It only earns a candidate when it carries something
    beyond title/author — those merely seed the search query and add nothing to
    the merge on their own.
    """
    if not local_metadata:
        return None

    contributing = (
        "description", "isbn", "publisher", "language",
        "series", "series_index", "genres", "published_date",
    )
    candidate = {"source": _("Embedded file"), "cover_url": ""}
    for field in ("title", "author", *contributing):
        value = local_metadata.get(field) or ""
        candidate[field] = value.strip() if isinstance(value, str) else str(value)

    if not any(candidate.get(f) for f in contributing):
        return None

    candidate["fields_found"] = [f for f in candidate if f not in ("source", "fields_found") and candidate.get(f)]
    return candidate


# ---------------------------------------------------------------------------
# Main enrichment orchestration
# ---------------------------------------------------------------------------

def run_metadata_enrichment(
    item,
    cover_dir=None,
    include_google=None,
    include_calibre=None,
    include_wikipedia=None,
    include_hardcover=None,
    include_wikidata=None,
    include_libris=None,
    include_file=None,
    mode=None,
    local_metadata=None,
    on_progress=None,
    abort_check=None,
):
    """Search external sources for the best metadata and merge them field by field.

    Emits stage-level progress events via on_progress when provided.

    Stages:
        read_file_metadata
        fast_sources       — tier 1 (Google + Wikipedia) started in parallel
        google_books       — Google Books finished
        wikipedia          — Wikipedia finished
        fast_preview       — merged candidate from tier 1 (~1s)
        calibre            — tier 2 finished, skipped, or disabled
        scoring            — comparing candidates
        final_preview      — merged candidate after escalation
        preview_ready      — terminal summary

    include_* and mode default to the saved settings (METADATA_SOURCE_*_ENABLED,
    METADATA_FETCH_MODE) when not passed explicitly.

    Returns a result dict (see keys assembled at the end).
    """
    from app.services.metadata_sources import (
        choose_best_metadata_explained,
        download_cover_to_file,
        google_books_search_with_status,
        deduplicate_results,
    )
    from app.services.metadata_calibre import fetch_calibre_metadata_with_status
    from app.services.metadata_wikipedia import search_wikipedia_with_status
    from app.services.metadata_hardcover import hardcover_search_with_status
    from app.services.metadata_wikidata import wikidata_search_with_status
    from app.services.metadata_libris import libris_search_with_status
    from app.services.metadata_merge import merge_candidates

    include_google = _resolve_flag(include_google, "METADATA_SOURCE_GOOGLE_ENABLED")
    include_wikipedia = _resolve_flag(include_wikipedia, "METADATA_SOURCE_WIKIPEDIA_ENABLED")
    include_hardcover = _resolve_flag(include_hardcover, "METADATA_SOURCE_HARDCOVER_ENABLED")
    include_wikidata = _resolve_flag(include_wikidata, "METADATA_SOURCE_WIKIDATA_ENABLED")
    include_libris = _resolve_flag(include_libris, "METADATA_SOURCE_LIBRIS_ENABLED")
    include_calibre = _resolve_flag(include_calibre, "METADATA_SOURCE_CALIBRE_ENABLED")
    include_file = _resolve_flag(include_file, "METADATA_SOURCE_FILE_ENABLED")
    mode = resolve_fetch_mode(mode)

    # Fast sources run in worker threads, which don't inherit the Flask app
    # context — so get_setting()'s DB read fails there and falls back to env,
    # silently blanking DB-stored keys (e.g. the Hardcover token, the Google
    # key). Capture the app here (main thread) and push its context inside each
    # worker. None when there's no context (e.g. unit tests).
    try:
        from flask import current_app
        _flask_app = current_app._get_current_object()
    except RuntimeError:
        _flask_app = None

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
    all_candidates = []          # everything, incl. the embedded file
    external_candidates = []     # only network sources — used for identity scoring

    # Embedded file becomes a high-trust candidate (best source for series).
    file_candidate = _file_candidate(local_metadata) if include_file else None
    if file_candidate:
        all_candidates.append(file_candidate)

    def _merge_now(anchor):
        merged, provenance = merge_candidates(item, all_candidates, anchor)
        return merged, provenance

    # -- Tier 1: fast sources (Wikipedia + Google Books in parallel) ---------
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
    if include_hardcover:
        fast_jobs["hardcover"] = lambda: hardcover_search_with_status(
            query_text=search_input["query_text"],
            title=search_input["title"],
            author=search_input["author"],
            isbn=search_input["isbn"],
        )
    if include_libris:
        fast_jobs["libris"] = lambda: libris_search_with_status(
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

    fast_results = _run_fast_sources(fast_jobs, app=_flask_app)

    if "google_books" in fast_results:
        google_sr = fast_results["google_books"]
        source_results.append(google_sr)
        google_candidates_list = google_sr.get("candidates", [])
        all_candidates.extend(google_candidates_list)
        external_candidates.extend(google_candidates_list)
        google_source_details = [{
            "source": "Google Books",
            "fields_found": (
                google_candidates_list[0].get("fields_found", [])
                if google_candidates_list else []
            ),
            "ok": bool(google_sr["ok"]),
            "status": google_sr.get("status", ""),
            "message": google_sr.get("message", ""),
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
        external_candidates.extend(wiki_candidates_list)
        wiki_source_details = [{
            "source": "Wikipedia",
            "fields_found": (
                wiki_candidates_list[0].get("fields_found", [])
                if wiki_candidates_list else []
            ),
            "ok": bool(wiki_sr["ok"]),
            "status": wiki_sr.get("status", ""),
            "message": wiki_sr.get("message", ""),
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

    if "hardcover" in fast_results:
        hc_sr = fast_results["hardcover"]
        source_results.append(hc_sr)
        hc_candidates_list = hc_sr.get("candidates", [])
        all_candidates.extend(hc_candidates_list)
        external_candidates.extend(hc_candidates_list)
        hc_source_details = [{
            "source": "Hardcover",
            "fields_found": (
                hc_candidates_list[0].get("fields_found", [])
                if hc_candidates_list else []
            ),
            "ok": bool(hc_sr["ok"]),
            "status": hc_sr.get("status", ""),
            "message": hc_sr.get("message", ""),
        }]
        _emit(
            "hardcover",
            source="hardcover",
            status="ok" if hc_sr["ok"] else hc_sr["status"],
            message=hc_sr["message"],
            candidates_found=len(hc_candidates_list),
            source_details=hc_source_details,
            warnings=[],
        )

    if "libris" in fast_results:
        lb_sr = fast_results["libris"]
        source_results.append(lb_sr)
        lb_candidates_list = lb_sr.get("candidates", [])
        all_candidates.extend(lb_candidates_list)
        external_candidates.extend(lb_candidates_list)
        lb_source_details = [{
            "source": "LIBRIS",
            "fields_found": (
                lb_candidates_list[0].get("fields_found", [])
                if lb_candidates_list else []
            ),
            "ok": bool(lb_sr["ok"]),
            "status": lb_sr.get("status", ""),
            "message": lb_sr.get("message", ""),
        }]
        _emit(
            "libris",
            source="libris",
            status="ok" if lb_sr["ok"] else lb_sr["status"],
            message=lb_sr["message"],
            candidates_found=len(lb_candidates_list),
            source_details=lb_source_details,
            warnings=[],
        )

    # Merged preview after tier 1 so the UI fills before Calibre runs.
    fast_scoring = choose_best_metadata_explained(item, list(external_candidates))
    fast_anchor = fast_scoring.get("best")
    fast_merged, fast_provenance = _merge_now(fast_anchor)
    fast_payload = _build_fetched_payload(fast_merged) if fast_merged else {}
    missing = _missing_essentials(fast_merged)
    _emit(
        "fast_preview",
        status="ok" if fast_merged else "no_match",
        message=_("Fast sources done."),
        candidates_found=len(fast_scoring.get("all_scored") or []),
        score=fast_scoring.get("score"),
        payload=fast_payload,
        provenance=fast_provenance,
        missing_essentials=missing,
        source=(fast_anchor or {}).get("source", "") if fast_anchor else "",
        warnings=[],
    )

    # -- Tier 1.5: Wikidata — targeted escalation for structured series + ordinal.
    # Only run when the fast tier left the series name or its index unfilled, so
    # complete books pay nothing for it. Runs in the main thread (no key needed).
    need_series = (
        include_wikidata
        and not _aborted()
        and mode in ("more", "deep")
        and (
            not (fast_merged.get("series") or "").strip()
            or not (fast_merged.get("series_index") or "").strip()
        )
    )
    if need_series:
        _emit(
            "wikidata", source="wikidata", status="searching",
            message=_("Searching Wikidata for series..."),
            candidates_found=0, warnings=[],
        )
        wd_sr = wikidata_search_with_status(
            query_text=search_input["query_text"],
            title=search_input["title"],
            author=search_input["author"],
            isbn=search_input["isbn"],
        )
        source_results.append(wd_sr)
        wd_candidates_list = wd_sr.get("candidates", [])
        all_candidates.extend(wd_candidates_list)
        external_candidates.extend(wd_candidates_list)
        wd_source_details = [{
            "source": "Wikidata",
            "fields_found": (
                wd_candidates_list[0].get("fields_found", [])
                if wd_candidates_list else []
            ),
            "ok": bool(wd_sr["ok"]),
            "status": wd_sr.get("status", ""),
            "message": wd_sr.get("message", ""),
        }]
        _emit(
            "wikidata", source="wikidata",
            status="ok" if wd_sr["ok"] else wd_sr["status"],
            message=wd_sr["message"],
            candidates_found=len(wd_candidates_list),
            source_details=wd_source_details,
            warnings=[],
        )
        # Re-merge so the Calibre decision and final preview see Wikidata's data.
        fast_scoring = choose_best_metadata_explained(item, list(external_candidates))
        fast_anchor = fast_scoring.get("best")
        fast_merged, fast_provenance = _merge_now(fast_anchor)
        missing = _missing_essentials(fast_merged)

    # -- Tier 2: Calibre, gated by mode + completeness -----------------------
    if _aborted():
        include_calibre = False

    run_calibre = include_calibre and (
        mode == "deep" or (mode == "more" and bool(missing))
    )

    if run_calibre:
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
        external_candidates.extend(calibre_candidates_list)

        # One source_details entry per Calibre plugin so the UI can show
        # per-plugin coverage. Plugins share fields_found (Calibre merges).
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
    else:
        # Emit a terminal calibre event so the UI's spinner resolves, and record
        # a skipped source_result so downstream consumers see a stable shape.
        if not include_calibre:
            skip_msg = _("Calibre is turned off in settings.")
        elif mode == "fast":
            skip_msg = _("Calibre skipped (Fast mode).")
        else:
            skip_msg = _("Calibre skipped — fast sources already covered the essentials.")
        source_results.append({
            "source": "calibre", "ok": False, "status": "skipped",
            "duration_ms": 0, "message": skip_msg, "candidates": [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        })
        _emit(
            "calibre",
            source="calibre",
            status="skipped",
            message=skip_msg,
            candidates_found=0,
            source_details=[],
            warnings=[],
        )

    all_candidates = deduplicate_results(all_candidates)
    external_candidates = deduplicate_results(external_candidates)

    # Stage: scoring (identity/classification over external candidates only —
    # the embedded file is always trusted in the merge but should not decide
    # the match confidence on its own).
    _emit(
        "scoring",
        status="scoring",
        message=_("Comparing candidates..."),
        candidates_found=len(external_candidates),
        warnings=[],
    )

    scoring = choose_best_metadata_explained(item, external_candidates)
    best = scoring["best"]
    best_score = scoring["score"]

    n_candidates = len(scoring["all_scored"])
    if best:
        _emit(
            "preview_ready",
            status="ok",
            message=_(
                "Found %(count)d possible matches. Best match: %(score)d points, %(source)s.",
                count=n_candidates, score=round(best_score), source=best.get("source", ""),
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
            "provenance": {},
            "fetch_mode": mode,
            "cover_path": None,
            "error": _("No secure metadata matches were found."),
        }

    # Field-level merge over every trusted candidate (external + embedded file).
    merged, provenance = merge_candidates(item, all_candidates, best)

    cover_path_for_preview = None
    cover_url = merged.get("cover_url")
    if cover_dir and cover_url:
        os.makedirs(cover_dir, exist_ok=True)
        downloaded = download_cover_to_file(
            cover_url=cover_url,
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

    fetched_payload = _build_fetched_payload(merged, cover_path=cover_path_for_preview)

    validation_warning = _build_validation_warning(item, fetched_payload)

    # Sources that actually contributed at least one field (for the UI summary).
    sources_used = list(dict.fromkeys(v for v in provenance.values() if v))

    _emit(
        "final_preview",
        status="ok",
        message=_("Final metadata ready."),
        candidates_found=len(scoring["all_scored"]),
        score=best_score,
        payload=fetched_payload,
        provenance=provenance,
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
        "sources_used": sources_used,
        "source_results": source_results,
        "search_input": search_input,
        "local_metadata": local_metadata,
        "validation_warning": validation_warning,
        "fetched_payload": fetched_payload,
        "provenance": provenance,
        "fetch_mode": mode,
        "cover_path": cover_path_for_preview,
        "error": None,
    }


def _run_fast_sources(jobs, app=None):
    """Run zero-arg callables in parallel and collect their results.

    `jobs` is a {name: callable} mapping. Returns {name: result_or_error_dict}.
    Each callable is expected to never raise — on exception we synthesise the
    same shape as a `network_or_plugin_error` result.

    When `app` is given, each callable runs inside a pushed Flask app context so
    that get_setting()'s DB reads work from the worker thread (otherwise
    DB-stored API keys read as empty).
    """
    if not jobs:
        return {}

    def _wrap(fn):
        if app is None:
            return fn
        def _run_in_ctx():
            with app.app_context():
                return fn()
        return _run_in_ctx

    results = {}
    with ThreadPoolExecutor(max_workers=max(2, len(jobs))) as pool:
        future_to_name = {pool.submit(_wrap(fn)): name for name, fn in jobs.items()}
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
    """Produce the standard fetched_payload dict from a (merged) candidate."""
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
