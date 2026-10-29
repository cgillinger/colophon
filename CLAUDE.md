<!-- md optimerad 2026:10:29 -->
# CLAUDE.md — Colophon

## What is this?

Colophon is a self-hosted e-book metadata manager. Flask + Gunicorn + SQLite, running in Docker. Single-user, hobby project. Version 1.64.1.

The reasoning behind the rules in this file lives in `docs/design-decisions.md` (per feature, per version). Read the relevant section there before changing one of the areas listed under "Load-bearing invariants".

## Quick reference

```
Repo:           /mnt/docker/stacks/colophon/repo
Compose file:   /mnt/docker/stacks/colophon/docker-compose.yml
Container:      colophon
URL:            http://192.168.1.100:5055
Entry point:    wsgi.py → app.create_app()
DB:             SQLite at /data/colophon.db (inside container)
Books mount:    /books (host: COLOPHON_LIBRARY_HOST)
Data mount:     /data (host: COLOPHON_DATA_HOST)
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
  models.py                     # LibraryItem, Author/AuthorAlias, BookAuthor/AuthorSplitRule, KoboDevice, KoboBookState, ReaderDevice, KosyncDocument
  version.py                    # __version__ (single source)
  paths.py / config.py          # Path constants / Flask Config (env vars)
  routes/                       # metadata, authors, scan, settings, kobo, reader, opds, kosync, helpers
  services/
    scanner.py                  # File discovery + ebooklib metadata extraction + upsert
    metadata_pipeline.py        # Enrichment: tiers + completeness escalation + fetch modes
    metadata_merge.py           # Field-level merge: anchor + trust-gate + precedence + provenance
    metadata_{sources,calibre,wikipedia,hardcover,wikidata,libris,openlibrary}.py  # Sources
    metadata_writer.py          # Write back to files (ebook-meta), group sync
    ai_metadata.py              # Provider-agnostic AI enrichment, library context, series proposals
    cover_search.py             # 5 cover sources; cover_thumbs.py shared downscaler
    quality.py                  # is_better_* heuristics
    author_authority.py         # Matching layers 1–3 (pure); author_resolver.py = DB layer; author_authority_lookup.py = Wikidata
    author_folders.py           # "Move to author folder" + upstream cleanup
    series_batch.py             # Series-order scenario (AI + Wikidata → reviewable proposal)
    language_detect.py / language_check.py   # langdetect; language scenario
    duplicate_detector.py, grouping.py, text_utils.py, app_settings.py, upstream_sync.py, database.py
    kobo_auth.py, kobo_sync.py, kobo_kepub.py, kobo_location.py, kobo_conf.py, kobo_usb.py, device_transfers.py
    reading_state.py            # Shared monotonic reading-state writer (Kobo + reader + KOSync)
    page_map.py                 # Virtual page map (1500 dense chars/page) + print page-list labels
    koreader_xpath.py, kosync_documents.py, reader_devices.py   # OPDS/KOSync e-readers
    dictionaries.py             # Reader word lookup (on-demand StarDict)
  templates/                    # _layout, bulk_metadata (main view, Jinja shell only), metadata*, settings_*, authors, reader, offline
  translations/sv/              # Swedish .po
  static/css/bulk_metadata.css
  static/js/                    # see below
  static/vendor/{tabler-icons,foliate-js}/
tests/                          # pytest, one file per area (~49 files)
tools/install_{calibre_plugins,kepubify,fonts}.sh   # Dockerfile build steps
logo/                           # Brand SVGs; favicons from colophon-mark-flat.svg, iOS/PWA from colophon-icon-ios.svg
docs/                           # design-decisions.md, kobo-reading-state-sync.md, plan-batch-scenarios.md, TODO.md, handbooks, …
```

### Frontend modules (`app/static/js/`)

`bulk_metadata.html` is ~1000 lines of Jinja; behaviour lives here. Edit the module, never add logic back into the template.

```
core.js                  # Bootstrap, shared state, i18n lookup (window.__colophonConfig.i18n); _esc/_cleanDate/_applyFieldLabel/_resultLabel/_resultTooltip
filters-sort-paging.js   # Search, filters, sort, pagination (+ "missing cover" banner)
selection.js             # Row selection
shelf-view.js / series-view.js   # Gallery layout / series grouping (+ "Order the series")
series-rename.js         # Rename one series card (no AI)
series-order.js          # Series-order review modal (one series, or a whole author)
book-modal.js            # Single-book edit modal — the only writing path for enrichment
bulk-result-modal.js     # Post-batch summary
duplicates.js, cleanup-misc.js, reading-now.js, scan-sync.js, upload.js, url-state.js
author-combobox.js       # Registry-backed multi-author fields (hidden #modalAuthor = ' & '-joined string)
authors-manage.js        # /authors page (own page, own i18n block)
reader.js                # In-browser reader (ES module, foliate-js); pageOf/anchorForPage/printPageAt mirror page_map.py
covers-batch.js          # "Fetch covers for these" (dry-run stream, review grid, per-book apply)
language-check.js        # Tools → Check language
reader-dict.js           # Reader selection sheet (word → definition; passage → copy)
offline.js               # "Downloaded" chip/filter
```

## Architecture

- **Blueprints (8):** `metadata`, `authors`, `scan`, `settings`, `kobo` (`/kobo/<token>/…`), `reader` (`/reader`), `opds` (`/opds/<token>`), `kosync` (`/kosync/<token>`). No `library`/`bookstores` — removed in the fork from Bookstation; `url_for('library.*')` crashes.
- **Metadata extraction:** scanning uses `ebooklib` directly, never subprocess `ebook-meta` (Gunicorn sync-worker timeouts at scale). `ebook-meta` is only for *writing*.
- **Enrichment flow:** `scan_file_local()` → `build_search_input()` (ISBN > title+author > filename) → `google_books_search_with_status()` + `fetch_calibre_metadata_with_status()` → `choose_best_metadata_explained()` (auto_apply / review_needed / no_match) → `apply_metadata_to_item()`.
- **Settings:** DB value > `COLOPHON_<KEY>` env > legacy `COLOPHON_MISTRAL_*` env > default. UI always wins.
- **Format grouping:** `group_key` = SHA256 of normalized title (first 16 chars); metadata operations apply to the whole group.
- **SSE:** scan and bulk metadata stream via background threads + `queue.SimpleQueue`; one shared `_abort_event`. Gunicorn timeout is 300 s — long work streams, never blocks.

## Load-bearing invariants

Each line is binding; the story behind it is in `docs/design-decisions.md` under the same heading.

**Kobo delta sync (v1.48.0)**
- Pagination cursor keys on `id` with a `high_water` ceiling, never on `updated_at`; at the end `since := high_water`. Test: `test_state_put_between_pages_does_not_skip_books`.
- The ledger (`kobo_book_states.sent_updated_at`/`sent_content_at`) decides the wrapper: no row → `NewEntitlement`; content newer → `ChangedEntitlement` (with `DownloadUrls`); state newer → `ChangedReadingState` (never `DownloadUrls`). Sync token v2 only.
- `CoverImageId` = `<uuid>-v<mtime>`; `_find_item_by_uuid` strips the suffix. Cover-only repair = Settings → Kobo → Force full resync (`clear_ledger`).
- Adding a column to `kobo_book_states` = model + `CREATE TABLE` in `database.py` + `ALTER TABLE` + backfill (NULL `sent_*` reads as "newer" and re-ships everything).
- `book_uid` is the device-facing identity (not the PK); existing rows are `"book-<id>"`.

**Reader, reading state, OPDS/KOSync (v1.5.0–v1.64.0)**
- One writer for reading state: `services/reading_state.py:apply_reading_state()` (Kobo PUT, `/reader/<id>/progress`, KOSync). *Progress* is furthest-read-wins; *position* (`read_position_json`) is last-write-wins. Rules and triage: `docs/kobo-reading-state-sync.md` — read before touching `reading_state.py` or the Kobo PUT/DTO paths.
- Exact position = non-whitespace characters into the chapter (`kobo_location.py`); when unresolvable, fall back to percent and **clear** the stored location (`clear_location=True`).
- Virtual page = 1500 dense characters (`page_map.py`); `reader.js` `pageOf`/`anchorForPage`/`printPageAt` must stay in lockstep. The page map is in the offline `cacheBook` asset list.
- KOSync GET answers with the *position*, never `read_progress`; PUT never sets Finished; `koreader_xpath.py` mirrors CrossPoint's `ChapterXPathResolver`.
- `/reader/<id>/file` serves the raw EPUB, token-free and stable (offline cache `colophon-offline`; `/offline` landing page; `/reader/offline-index.json`).
- The "Läs" button is `display-only`, EPUB only, shelf-view modal only.

**`_DEVICE_CONTENT_COLUMNS` (models.py)** — `language`, `series`, `series_index`, `cover_path` are in it: a DB-only change stamps `content_updated_at` and the Kobo re-downloads. That is correct; every flow says so in its modal instead of hiding it. `test_language_only_db_change_still_stamps_content` pins it.

**Scenario flows (v1.51–v1.60; `docs/plan-batch-scenarios.md`)**
- The batch wizard is gone (v1.60.0). `bulk_stream` always runs with `dry_run=1`; the only writing path for enrichment is `book-modal.js`. A dry run must not group-sync. Tests: `tests/test_batch_dry_run.py` (keep its control case green) and `tests/test_cover_batch.py`.
- Language check: `detect_language_confident` samples at 30 % and 60 % through the spine; two disagreeing samples → `agree=False`, unticked. The stream is read-only (`test_stream_never_writes`); apply writes only `language`.
- Series order: sanitize the AI answer (invented ids dropped, duplicates once, id in both lists → `not_in_series`, unmentioned → `unranked`). Status priority in `series_batch._build_group`, first match wins: `not_in_series`/`standalone` → `unknown` → `unchanged` (byte-identical, no checkbox) / `normalize` → `conflict` → `confirmed` → `ai_only`. `conflict` outranks `confirmed`. Pre-ticking (`series-order.js`): `confirmed` ticked, `ai_only` only at `high`; a lone unconfirmed proposal is downgraded to `low`, per group. `_WIKIDATA_BUDGET_SECONDS` (90 s) is one deadline for the whole proposal, never per group. `series-order.js` reads `order_series=1` at script-evaluation time (before `url-state.js` rewrites the query).
- `rename_series` (`POST /metadata/series/rename`) renames one card with no AI, via `apply_series_changes`, touching only `series`/`series_index`.
- Completeness: `missing_fields(item)` is the single source of truth; `refresh_completeness(item)` on every write path (`upsert_library_item`, `save_metadata_json`, `enrichment_apply`, `ai_apply`, `cover_apply_json`, `apply_cover`, `apply_metadata_to_item`). Bands green ≤1, yellow 2–5, red ≥6 in three places that must agree: `_completeness_bucket` (routes/metadata.py), `completeness_level` (bulk_metadata.html), `applyFilters` (filters-sort-paging.js). Never re-derive "missing" in a template.
- Covers batch: `_filteredIds()` reads `row.dataset.filterHidden` (collapsed siblings included); applying is sequential in the browser.
- AI library context: a suggested series matching an existing one (casefold + whitespace) is snapped to the library spelling and promoted to `high`; subjects are only nudged.

**Authors (v1.21–v1.59)**
- Every row action is a `<button data-act>` inside the same `<tr>` (`authors-manage.js` delegates from the table); the `⋯` popover is `position: fixed`.
- Wikidata verify: a candidate needs a writing occupation (`P106` in `_WRITING_OCCUPATIONS`) *or* a held title credited to it (`_works_by_candidate`, one SPARQL for all candidates; `_author_of_a_book_we_hold` when the name path finds nobody). `result["matched_on"]` records the evidence. `authority_label`/`authority_description` have no backfill — don't invent values. `_search_ids`/`_get_entities` swallow errors; the main search surfaces `ok=False`. Don't unify them. `POST /authors/<id>/unlink` exists on purpose. Bulk verify runs serially in the browser.
- Author strings: `' & '` is the canonical separator; other fused forms stay one entity until split manually (`author_split_rules`). Rules never reference tentative entries. `source` (`tentative`/`user_confirmed`/`authority_linked`) gates file writes.

**Author folders (v1.38.0)** — move = disk + `file_path` in one commit, `id` preserved, `content_updated_at` deliberately *not* stamped. Upstream orphan cleanup only when `UPSTREAM_CLEANUP_ORPHANS` is on (default off). No bulk move.

## Models

Nine tables in `app/models.py`: `library_items` (catalogue; `book_uid`, `manual_metadata`, `cover_locked`, `group_key`, `pipeline_status`, `author_id`/`author_status` reset by a `before_flush` listener on `author` edits), `authors` + `author_aliases` (`docs/author-authority-design.md`), `book_authors` + `author_split_rules` (multi-author, position 0 mirrored in `author_id`), `kobo_devices`, `kobo_book_states` (the ledger), `reader_devices` (OPDS/KOSync, carries `language`), `kosync_documents` (index, rebuilt lazily on miss).

## Tech stack

Python 3.12, Flask 3.0, Gunicorn (timeout 300 s, 2 sync workers), SQLite via Flask-SQLAlchemy, ebooklib 0.18, Calibre CLI, BeautifulSoup, mutagen, Flask-Babel (EN + SV), Flask-Session (filesystem). Docker base `python:3.12-slim`.

## i18n

All user-facing strings use `gettext()` / `_()`. After changing strings:

```bash
pybabel extract -F babel.cfg -o messages.pot . && pybabel update -i messages.pot -d app/translations
# edit app/translations/sv/LC_MESSAGES/messages.po
pybabel compile -d app/translations
```

`babel.cfg` extracts Python and Jinja only. JS strings go in the `i18n: {` map rendered by Jinja in `bulk_metadata.html`; `core.js` only reads it. **Do not add a `[javascript: …]` line to `babel.cfg`:** Babel's JS extractor stops silently at a regex literal containing a quote (`.replace(/'/g, …)`, present in five modules), losing every later string in that file.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
```

Tests mock external services. The repo `.env` (gitignored via `.git/info/exclude`) sets `COLOPHON_DATA_DIR`/`COLOPHON_LIBRARY_DIR` to local dirs under `data/` and `var/`; without it `create_app()` defaults to `/data` and `/books` and fails. Local `.venv` is Python 3.14, the container 3.12 — suspect that first if results differ.

- **Never run the suite inside the live container:** `test_kobo_sync.py` runs `DELETE FROM library_items …` on `DATA_DIR/colophon.db`. Locally, or in a throwaway container with no `/data` mount.
- Dev instance against real books: `COLOPHON_DATA_DIR=$PWD/var/data-dev COLOPHON_LIBRARY_DIR=$PWD/var/books-dev .venv/bin/gunicorn -b 127.0.0.1:5055 -w 2 -t 300 wsgi:app`, then `curl -s http://127.0.0.1:5055/scan`. Own data dir — the suite wipes the one `.env` points at. Fill `var/books-dev/` by rsync **pull** from the server's working copy `/mnt/docker/appdata/colophon/bibliotek/`, never from the Synology originals. No API keys there, so AI/metadata fetches do nothing.
- If `tests/test_kobo_covers.py` reports skips, `pip install Pillow`.
- Known pre-existing failures: see `docs/design-decisions.md` → "Known test failures" (verify against a fresh run before assuming a regression).

## Common pitfalls

1. Never spawn subprocesses per file for reading metadata — ebooklib.
2. Always `--no-cache` on rebuild.
3. Only the eight blueprints above exist.
4. Main view is split: template = shell, logic in `static/js/`, styling in `static/css/bulk_metadata.css`.
5. Settings priority as above.
6. Long operations stream (SSE); Gunicorn kills blocking requests at 300 s.

## Git workflow

Push directly to `main`. No branches or PRs — single-developer project. If local edits conflict with remote changes: `git reset --hard origin/main`.

## Versioning

SemVer, canonical in `app/version.py`; templates read `app_version`. Bump in the same commit as the change, before pushing. PATCH: fix, copy/i18n, dependency bump, docs-only release. MINOR: user-visible feature, setting, integration, source, automatic schema migration. MAJOR: user must act (renamed env var, config format, manual migration, removed feature, Kobo `.conf` rewrite). No bump for refactors, test-only commits or `CLAUDE.md`/`docs/` edits.

Three hand-maintained copies, always together: `app/version.py`, the README badge, and the "Version X.Y.Z" line at the top of this file. Then tag:

```bash
OLD=1.0.0 NEW=1.0.1 && sed -i "s/$OLD/$NEW/" app/version.py README.md CLAUDE.md
git tag v$NEW && git push --tags
```

## Debugging

```bash
docker logs colophon --tail 50
docker exec -it colophon bash
docker exec colophon python -c "from app.services.cover_search import search_covers; print(search_covers(isbn='9780261103573'))"
curl -s http://192.168.1.100:5055/scan | python -m json.tool
```

## UI verification with Playwright

The Playwright MCP tools (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_take_screenshot`) are available in the session; point them at `http://192.168.1.100:5055` after a rebuild. Prefer accessibility snapshots (structure, labels, button states; an order of magnitude cheaper) and use screenshots only for pixels (layout, colour, dark mode).

**Production safety:** the running instance is the real library. Without explicit per-action authorization never: delete anything, save metadata edits, run a scenario flow to Apply, toggle settings, or click "Fetch metadata"/"Ask AI" on real books. Safe: navigate views, open and close modals without saving, search/filter/paginate, hover, scroll, screenshot, toggle theme or language. When in doubt, ask first — "Radera permanent (inkl. fil)" deletes real files.
