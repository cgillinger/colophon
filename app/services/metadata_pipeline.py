"""Shared metadata pipeline for single-book and batch enrichment flows.

Orchestration lives here; routes stay thin (receive → call → render/redirect).
"""
import logging
import os
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search input construction
# ---------------------------------------------------------------------------

def build_search_input(item, local_metadata=None):
    """Return the best available search input for external metadata lookup.

    Priority order (Phase 4 will extend with file-level metadata):
      1. ISBN from local_metadata (file)
      2. ISBN from DB item
      3. title + author from local_metadata (file)
      4. title + author from DB item
      5. cleaned filename

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
    warnings.append("Söker på filnamn – metadata saknas i databasen.")
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
    local_metadata=None,
):
    """Search external sources for the best metadata candidate.

    Returns a result dict:
        ok               bool
        best             dict | None      — best raw candidate from sources
        score            float
        sources_used     list[str]
        validation_warning  str | None
        fetched_payload  dict             — cleaned payload ready for preview
        cover_path       str | None       — local path to downloaded cover
        error            str | None       — human-readable error when ok=False
    """
    from app.services.metadata_sources import (
        choose_best_metadata,
        download_cover_to_file,
        search_all_sources,
    )

    search_input = build_search_input(item, local_metadata)

    results = search_all_sources(
        title=search_input["title"],
        author=search_input["author"],
        isbn=search_input["isbn"],
        query_text=search_input["query_text"],
        include_calibre=include_calibre,
    )

    best, best_score = choose_best_metadata(item, results)

    if not best:
        return {
            "ok": False,
            "best": None,
            "score": best_score,
            "sources_used": [],
            "validation_warning": None,
            "fetched_payload": {},
            "cover_path": None,
            "error": "Inga säkra metadata-träffar hittades från Google Books eller Calibre.",
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

    def _txt(value):
        return str(value).strip() if value not in (None, "") else ""

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

    validation_warning = _build_validation_warning(item, fetched_payload)

    return {
        "ok": True,
        "best": best,
        "score": best_score,
        "sources_used": [best["source"]] if best.get("source") else [],
        "validation_warning": validation_warning,
        "fetched_payload": fetched_payload,
        "cover_path": cover_path_for_preview,
        "error": None,
    }


def _build_validation_warning(item, fetched_payload):
    def _normalize(value):
        return (value or "").lower().replace(":", " ").replace("-", " ").strip()

    old_title = _normalize(item.title)
    old_author = _normalize(item.author)
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
