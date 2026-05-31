# Colophon – e-book metadata manager
"""Tests for completeness-driven tier escalation + fetch modes.

Calibre (the slow tier-2 subprocess) must run only when the fetch mode allows
it AND the fast tier left an essential field uncovered:

    fast  — never
    more  — only when essentials are missing
    deep  — always

No network: the source functions are monkeypatched.
"""
from unittest.mock import MagicMock

import app.services.metadata_sources as sources
import app.services.metadata_calibre as calibre
from app.services import metadata_pipeline as pipeline


def _item(**kwargs):
    item = MagicMock()
    item.id = 1
    item.file_path = ""          # so the pipeline skips scan_file_local
    item.cover_path = None
    item.isbn = kwargs.get("isbn", "")
    item.title = kwargs.get("title", "Dune")
    item.author = kwargs.get("author", "Frank Herbert")
    item.language = kwargs.get("language", "")
    return item


def _google_status(candidate):
    return {
        "source": "google_books", "ok": True, "status": "ok",
        "duration_ms": 1, "message": "ok", "candidates": [candidate],
        "raw_debug": {"returncode": None, "stderr_excerpt": ""},
    }


_COMPLETE = {
    "source": "Google Books API",
    "title": "Dune", "author": "Frank Herbert",
    "description": "A rich, long synopsis of Dune that clears the threshold easily.",
    "isbn": "", "publisher": "Ace", "language": "en",
    "series": "Dune", "series_index": "1", "genres": "Science Fiction",
    "published_date": "1965-08-01", "cover_url": "http://x/cover.jpg",
}

_SPARSE = {
    "source": "Google Books API",
    "title": "Dune", "author": "Frank Herbert",
    "description": "", "isbn": "", "publisher": "", "language": "",
    "series": "", "series_index": "", "genres": "",
    "published_date": "", "cover_url": "",
}


def _patch_sources(monkeypatch, google_candidate):
    monkeypatch.setattr(
        sources, "google_books_search_with_status",
        lambda **kw: _google_status(google_candidate),
    )
    calls = {"calibre": 0}

    def _fake_calibre(**kw):
        calls["calibre"] += 1
        return {
            "source": "calibre", "ok": False, "status": "no_result",
            "duration_ms": 1, "message": "no hits", "candidates": [],
            "raw_debug": {"returncode": None, "stderr_excerpt": ""},
        }

    monkeypatch.setattr(calibre, "fetch_calibre_metadata_with_status", _fake_calibre)
    return calls


def _run(mode, google_candidate, monkeypatch):
    calls = _patch_sources(monkeypatch, google_candidate)
    result = pipeline.run_metadata_enrichment(
        _item(),
        cover_dir=None,
        include_google=True,
        include_wikipedia=False,
        include_calibre=True,
        include_file=False,
        mode=mode,
    )
    return result, calls


def test_more_skips_calibre_when_essentials_covered(monkeypatch):
    result, calls = _run("more", _COMPLETE, monkeypatch)
    assert calls["calibre"] == 0
    assert result["fetch_mode"] == "more"
    # The skipped Calibre is still reported as a source_result.
    statuses = {sr["source"]: sr["status"] for sr in result["source_results"]}
    assert statuses.get("calibre") == "skipped"


def test_more_runs_calibre_when_essentials_missing(monkeypatch):
    result, calls = _run("more", _SPARSE, monkeypatch)
    assert calls["calibre"] == 1


def test_fast_never_runs_calibre_even_when_incomplete(monkeypatch):
    result, calls = _run("fast", _SPARSE, monkeypatch)
    assert calls["calibre"] == 0


def test_deep_always_runs_calibre_even_when_complete(monkeypatch):
    result, calls = _run("deep", _COMPLETE, monkeypatch)
    assert calls["calibre"] == 1


def test_disabled_calibre_is_never_run(monkeypatch):
    calls = _patch_sources(monkeypatch, _SPARSE)
    pipeline.run_metadata_enrichment(
        _item(), cover_dir=None,
        include_google=True, include_wikipedia=False,
        include_calibre=False, include_file=False, mode="deep",
    )
    assert calls["calibre"] == 0


def test_invalid_mode_falls_back_to_more(monkeypatch):
    result, _ = _run("nonsense", _COMPLETE, monkeypatch)
    assert result["fetch_mode"] == "more"
