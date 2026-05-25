# CLAUDE.md — Colophon

## What is this?

Colophon is a self-hosted e-book metadata manager. Flask + Gunicorn + SQLite, running in Docker. Single-user, hobby project. Version 1.0.0.

## Quick reference

```
Repo:           /mnt/docker/stacks/colophon/repo
Compose file:   /mnt/docker/stacks/colophon/docker-compose.yml
Container:      colophon
URL:            http://192.168.50.8:5055
Entry point:    wsgi.py → app.create_app()
DB:             SQLite at /data/colophon.db (inside container)
Books mount:    /books (host: configurable via COLOPHON_LIBRARY_HOST)
Data mount:     /data (host: configurable via COLOPHON_DATA_HOST)
```

## Rebuild after changes

Always run from `/mnt/docker/stacks/colophon/repo`:

```bash
git pull && cd .. && docker compose down && docker compose build --no-cache && docker compose up -d && docker logs colophon --tail 20
```

Use `--no-cache` every time. Docker layer cache has caused silent regressions before.

## Project structure

```
wsgi.py                         # Gunicorn entry: from app import create_app
app/
  __init__.py                   # create_app(), blueprint registration, Babel, DB init
  models.py                     # LibraryItem (single model, SQLite)
  version.py                    # __version__ = "1.0.0"
  paths.py                      # Central path constants
  config.py                     # Flask Config class (reads env vars)
  routes/
    __init__.py
    metadata.py                 # metadata_bp — bulk view, single-book modal, SSE streams
    scan.py                     # scan_bp — /scan endpoint (JSON + SSE)
    settings.py                 # settings_bp — API keys, AI config, upstream sync settings
    helpers.py                  # Shared route helpers
  services/
    __init__.py
    scanner.py                  # File discovery + ebooklib-based metadata extraction + upsert
    metadata_pipeline.py        # Orchestrates enrichment: build_search_input → sources → scoring
    metadata_sources.py         # Google Books search, scoring, deduplication
    metadata_calibre.py         # Calibre fetch-ebook-metadata subprocess wrapper
    metadata_writer.py          # Write metadata back to files (ebook-meta), group sync
    ai_metadata.py              # Provider-agnostic AI enrichment (series detection etc.)
    cover_search.py             # 5 sources: Open Library, Google Books, Hardcover, Wikidata, DDG
    app_settings.py             # DB+env hybrid settings (DB wins, env fallback)
    upstream_sync.py            # rsync-based pull/push to upstream library (e.g. Komga NFS)
    grouping.py                 # Format grouping: SHA256 of normalized title
    text_utils.py               # Title cleaning, series extraction from title strings
    language_detect.py          # langdetect-based language identification for EPUBs
    database.py                 # DB migrations (ensure_*_table, backfill_language)
  templates/
    bulk_metadata.html          # Main library view (large file, ~6000 lines, JS-heavy)
    metadata.html               # Single book detail (rarely used standalone)
    metadata_ai_preview.html    # AI suggestion review UI
    metadata_enrichment_preview.html  # Source enrichment review UI
    settings_api.html           # API keys + cover source toggles
    settings_ai.html            # AI config + usage stats + upstream library
  translations/
    sv/LC_MESSAGES/messages.po  # Swedish translation
  static/
    vendor/tabler-icons/        # Icon font
tests/
  test_metadata_pipeline.py
  test_calibre_metadata.py
  test_bookf.py
tools/
  install_calibre_plugins.sh    # Dockerfile build step: Goodreads, FF, FictionDB plugins
```

## Architecture decisions

### Blueprints

Only three: `metadata_bp`, `scan_bp`, `settings_bp`. No `library`, `bookstores`, or `reader` blueprints — those were removed during the fork from Bookstation.

### Metadata extraction

File scanning uses `ebooklib` directly (not subprocess `ebook-meta`). This was a critical fix — subprocess-based extraction caused Gunicorn sync worker timeouts at scale. `ebook-meta` is only used for *writing* metadata back to files.

### Metadata enrichment flow

1. `scan_file_local()` — reads embedded metadata via ebooklib
2. `build_search_input()` — picks best query (ISBN > title+author > filename)
3. `google_books_search_with_status()` + `fetch_calibre_metadata_with_status()`
4. `choose_best_metadata_explained()` — scoring + classification (auto_apply / review_needed / no_match)
5. `apply_metadata_to_item()` — writes to DB + optionally to file

### Settings model

Hybrid DB+env: `get_setting()` checks DB first, then `COLOPHON_<KEY>` env var, then legacy `COLOPHON_MISTRAL_*` env vars. UI values always win.

### Format grouping

Multiple formats of the same book (EPUB + MOBI + AZW3) share a `group_key` = SHA256 of normalized title (first 16 chars). Metadata operations apply to the whole group.

### SSE streaming

Both scan and bulk metadata use Server-Sent Events with background threads + `queue.SimpleQueue`. Single shared `_abort_event` for cancellation.

## Key model: LibraryItem

Single table `library_items`. Important fields:
- `manual_metadata` (bool) — locks text fields from auto-overwrite
- `cover_locked` (bool) — locks cover from auto-overwrite
- `group_key` — format grouping hash
- `pipeline_status` — scanned / enriched / polished
- `file_modified_by_colophon` / `upstream_synced_at` — upstream sync tracking

## Tech stack

- Python 3.12, Flask 3.0, Gunicorn (timeout 300s, 2 sync workers)
- SQLite via Flask-SQLAlchemy
- ebooklib 0.18, Calibre (CLI tools), BeautifulSoup, mutagen
- Flask-Babel (EN + SV), Flask-Session (filesystem)
- Playwright (installed but used sparingly)
- Docker: python:3.12-slim base

## i18n

All user-facing strings use `gettext()` / `_()`. Swedish translation in `app/translations/sv/`. After changing strings:

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d app/translations
# Edit .po file
pybabel compile -d app/translations
```

## Testing

```bash
python -m pytest tests/ -v
```

Tests mock external services (Google Books, Calibre subprocess). No integration tests requiring Docker.

## Common pitfalls

1. **Never spawn subprocesses per-file for reading metadata** — use ebooklib. Subprocesses + Gunicorn sync workers = timeouts.
2. **Docker cache** — always `--no-cache` on rebuild. Cached layers have hidden stale code.
3. **Blueprint references** — only `metadata.*`, `scan.*`, `settings.*` exist. Any `url_for('library.*')` etc. will crash.
4. **`bulk_metadata.html` is massive** (~6000 lines, inline JS). Be surgical with edits. The template contains a full i18n string map in JS.
5. **Settings priority**: DB value > `COLOPHON_*` env > legacy `COLOPHON_MISTRAL_*` env > default.
6. **Gunicorn timeout**: 300s. Long operations (bulk enrichment) use SSE streaming, not blocking requests.

## Git workflow

Push directly to `main`. No branches or PRs — single-developer project. If local edits conflict with remote changes: `git reset --hard origin/main`.

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`). The canonical version lives in `app/version.py`; templates render it via the `app_version` context processor in `app/__init__.py`.

### When to bump

Bump in the same commit as the change that triggers it, before pushing:

- **PATCH** (1.0.0 → 1.0.1) — bug fix, copy/i18n tweak, dependency bump, docs-only release. Routine fixes ship as patches.
- **MINOR** (1.0.0 → 1.1.0) — new user-visible feature, new setting, new integration, new metadata source, automatic schema migration.
- **MAJOR** (1.0.0 → 2.0.0) — breaking change the user has to act on: renamed/removed env var, changed config file format, schema migration that needs manual steps, removed feature, Kobo `.conf` lines that must be rewritten.

Don't bump for pure refactors, internal renames, test-only commits, or edits to `CLAUDE.md` / `docs/`. Multiple small commits between bumps is fine — version is per release, not per commit.

### Files to update on a bump

Three places, always together. They're the only hand-maintained copies:

1. `app/version.py` — `__version__ = "X.Y.Z"`
2. `README.md` — the `version-X.Y.Z` segment in the version badge URL
3. `CLAUDE.md` — the "Version X.Y.Z" line in the intro paragraph

Templates (`settings_api.html`, `settings_ai.html`) read from `app_version` and need no edit.

After bumping, tag the commit so the Releases page lines up with the badge:

```bash
git tag v1.0.1 && git push --tags
```

One-liner for the three-file bump (run from repo root, replace versions):

```bash
OLD=1.0.0 NEW=1.0.1 && sed -i "s/$OLD/$NEW/" app/version.py README.md CLAUDE.md
```

## Debugging

```bash
# Container logs
docker logs colophon --tail 50

# Shell into container
docker exec -it colophon bash

# Test API/backend in isolation (before touching UI)
docker exec colophon python -c "from app.services.cover_search import search_covers; print(search_covers(isbn='9780261103573'))"

# Check a route
curl -s http://192.168.50.8:5055/scan | python -m json.tool
```

## Playwright MCP (UI testing)

Playwright MCP is installed globally (`--scope user`) with headless Chromium bundled. The running Colophon instance lives at `http://192.168.50.8:5055` — point the browser there to verify UI changes after a rebuild.

**How to invoke**: say "Använd Playwright MCP" (or "Use Playwright MCP") in the first prompt of a session that needs UI verification. The MCP tools only load when explicitly requested.

**Key tools**:
- `browser_navigate` — go to a URL
- `browser_snapshot` — accessibility snapshot of the page (structured, fast, token-efficient — prefer this for "does element X exist / is it labelled correctly" checks)
- `browser_screenshot` — visual PNG; can be inspected with the Read tool to see what the user actually sees (use for layout/visual regressions, dark-mode rendering, etc.)
- `browser_click` — click an element by accessibility ref
- `browser_type` — type into an input by ref

**Snapshot vs screenshot**: accessibility snapshots are roughly an order of magnitude cheaper in tokens and faster to act on. Use snapshots to verify structure (aria-labels, headings, button states); use screenshots when the question is genuinely about pixels (alignment, color, badge styling, dark-mode contrast).

### ⚠️ Production safety

Colophon runs against the **real library** — every book and metadata field belongs to the user. Treat the running instance as production.

**Never do** without explicit per-action user authorization:
- Click "Radera" / "Delete" / trash icons on books, duplicates, or groups
- Save edits to metadata fields (the bulk modal's Save button writes to the DB and optionally the file)
- Run batch operations (the batch wizard mutates many rows at once)
- Toggle settings in the Settings pages
- Click "Fetch metadata" / "Ask AI" on real books (these mutate state and consume API quota)

**Safe to do** during verification:
- Navigate between views (Tabell / Hyllvy / Serie)
- Open modals and inspect their layout (closing without saving is fine)
- Use the search box, filters, pagination
- Hover, scroll, take screenshots
- Toggle theme, change language

When in doubt, **ask first**. A single misclick on "Radera permanent (inkl. fil)" deletes real ebook files from disk.
