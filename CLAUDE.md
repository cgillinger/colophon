# CLAUDE.md — Colophon

## What is this?

Colophon is a self-hosted e-book metadata manager. Flask + Gunicorn + SQLite, running in Docker. Single-user, hobby project. Version 1.62.5.

## Författarmappar (v1.38.0 — byggt)

Uppladdning lägger platt i roten (oförändrat). "Flytta till författarmapp"-knappen i
edit-modalen (rot-böcker, aktiv när författare finns) flyttar hela formatgruppen till
huvudförfattarens mapp — disk + `file_path` i samma commit, radens `id` bevaras, och
`content_updated_at` stämplas medvetet INTE (suppression-flagga i `models.py`) så Kobo
inte laddar om boken. Systermappsåteranvändning via `author_folder_key()` (kosmetisk,
inte semantisk). Uppströmsstädning: flytten sparar gamla sökvägen i
`pending_upstream_cleanup`; pushen tar bort den Colophon-pushade dubbletten uppströms
(nytt-före-gammalt, containment-vaktad, tom mapp beskärs) — men bara när
`UPSTREAM_CLEANUP_ORPHANS` slagits på (checkbox i inställningarna, **av som default**;
väntande städningar överlever och tas retroaktivt). Se `DESIGN-author-folders.md` och
`app/services/author_folders.py`. Beslut: ingen bulk-flytt, ingen massomdöpning av
befintliga mappar (skjutet upp).

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
  models.py                     # LibraryItem + Author/AuthorAlias + KoboDevice + KoboBookState
  version.py                    # __version__ = "1.26.1"
  paths.py                      # Central path constants
  config.py                     # Flask Config class (reads env vars)
  routes/
    __init__.py
    metadata.py                 # metadata_bp — bulk view, single-book modal, SSE streams
    authors.py                  # authors_bp — /authors manage view + registry JSON APIs
    scan.py                     # scan_bp — /scan (JSON + SSE) + /upload (in-app file upload)
    settings.py                 # settings_bp — API keys, AI config, upstream sync settings
    kobo.py                     # kobo_bp — /kobo/<token>/* sync endpoints for Kobo devices
    reader.py                   # reader_bp — /reader/<id> in-browser EPUB reader + progress
    helpers.py                  # Shared route helpers
  services/
    __init__.py
    scanner.py                  # File discovery + ebooklib-based metadata extraction + upsert
    metadata_pipeline.py        # Orchestrates enrichment: tiers + completeness escalation + fetch modes
    metadata_merge.py           # Field-level merge: anchor + trust-gate + per-field precedence + provenance
    metadata_sources.py         # Google Books search, scoring, deduplication
    metadata_calibre.py         # Calibre fetch-ebook-metadata subprocess wrapper
    metadata_wikipedia.py       # Wikipedia/Wikidata metadata lookup
    metadata_hardcover.py       # Hardcover GraphQL metadata source (series/genre/synopsis)
    metadata_wikidata.py        # Wikidata source: structured series + ordinal (P179/P1545)
    metadata_libris.py          # LIBRIS Xsearch — Swedish national bibliography (KB)
    metadata_openlibrary.py     # Open Library search + work description (synopsis/subjects)
    metadata_writer.py          # Write metadata back to files (ebook-meta), group sync
    ai_metadata.py              # Provider-agnostic AI enrichment (series detection etc.)
    cover_search.py             # 5 sources: Open Library, Google Books, Hardcover, Wikidata, DDG
    quality.py                  # is_better_* heuristics for field-by-field replacement
    author_authority.py         # Author matching layers 1-3 as pure functions (no DB)
    author_resolver.py          # DB layer: links items, grows registry, cascade merge/rename
    author_authority_lookup.py  # Wikidata person lookup → QID/VIAF/LIBRIS anchoring
    series_batch.py             # Series-order scenario: AI + Wikidata proposal, then apply
    duplicate_detector.py       # Fuzzy duplicate detection for the cleanup UI
    app_settings.py             # DB+env hybrid settings (DB wins, env fallback)
    upstream_sync.py            # rsync-based pull/push to upstream library (e.g. Komga NFS)
    grouping.py                 # Format grouping: SHA256 of normalized title
    text_utils.py               # Title cleaning, series extraction from title strings
    language_detect.py          # langdetect-based language identification for EPUBs
    language_check.py           # Language scenario: read the text, report only the books that disagree
    database.py                 # DB migrations (ensure_*_table, backfill_*)
    kobo_auth.py                # Per-device token generation, lookup, revoke (+ its bookkeeping)
    kobo_sync.py                # Kobo sync protocol: catalogue, state, deltas
    cover_thumbs.py             # Shared cover downscaler (web UI + Kobo endpoint)
    kobo_kepub.py               # On-the-fly EPUB→KEPUB conversion via kepubify
    kobo_location.py            # Percent ↔ KoboSpan, and the exact character bridge
    kobo_conf.py                # Render Kobo .conf snippets for the setup UI
    kobo_usb.py                 # Read a mounted Kobo: detect, harvest reading state
    device_transfers.py         # USB channel ledger — what WiFi must NOT re-offer
    reading_state.py            # Shared monotonic reading-state writer (Kobo + reader)
    dictionaries.py             # Reader word lookup: on-demand StarDict download + server-side lookup
  templates/
    _layout.html                # Base template — sidebar, topbar, theme bootstrap
    bulk_metadata.html          # Main library view (~1000 lines; JS/CSS extracted to static/)
    metadata.html               # Single book detail (rarely used standalone)
    metadata_ai_preview.html    # AI suggestion review UI
    metadata_enrichment_preview.html  # Source enrichment review UI
    cover_lookup.html           # Standalone cover picker
    settings_api.html           # API keys + cover source toggles
    settings_ai.html            # AI config + usage stats + upstream library
    settings_kobo.html          # Kobo device list + per-device URL + .conf snippet
    authors.html                # Manage authors: registry table, duplicates, cascade actions
    reader.html                 # Standalone in-browser reader page (no _layout chrome)
  translations/
    sv/LC_MESSAGES/messages.po  # Swedish translation
  static/
    css/bulk_metadata.css       # Extracted styles for the main view
    js/                         # Extracted frontend modules (17 files, see below)
    icons/                      # Favicons, app/PWA icons, header logo SVGs (light+dark)
    vendor/tabler-icons/        # Icon font
    vendor/foliate-js/          # Vendored EPUB renderer (MIT) for the reader
tests/                          # 44 pytest files: ai_library_context, ai_rate_limit,
                                # author_authority, author_folders, author_lookup,
                                # author_resolver, author_routes, batch_dry_run, bookf,
                                # calibre_metadata, completeness, cover_batch,
                                # device_transfers, drm, grouping, kobo_conf, kobo_covers,
                                # kobo_location, kobo_sync, kobo_usb, language,
                                # language_check, metadata_escalation, metadata_hardcover,
                                # metadata_libris, metadata_merge, metadata_openlibrary,
                                # metadata_pipeline, metadata_wikidata, modal_author_save,
                                # multi_author, quality, reader_dict, reader_position,
                                # reading_state, scan_delete_guard, scanner, schema_lock,
                                # scoring, series_batch, source_status, title_clean, upload,
                                # wikipedia
tools/
  install_calibre_plugins.sh    # Dockerfile build step: Goodreads, FF, FictionDB plugins
  install_kepubify.sh           # Dockerfile build step: kepubify binary for Kobo conversion
  install_fonts.sh              # Dockerfile build step: self-host Cormorant Garamond
                                #   woff2 into static/fonts/ (no render-blocking
                                #   fonts.googleapis.com <link> → fast first paint on LAN/iPad)
logo/                           # Brand source: master SVGs + export specs. Favicons
                                # (transparent) come from colophon-mark-flat.svg; the
                                # apple-touch / PWA icons (solid creme bg, so iOS doesn't
                                # black-fill on the home screen) from colophon-icon-ios.svg
```

### Frontend assets

`bulk_metadata.html` used to hold ~6000 lines of inline JS. It's now ~1000 lines of Jinja markup. Styles live in `app/static/css/bulk_metadata.css`; behaviour is split across `app/static/js/`:

```
core.js                  # Bootstrap, shared state, i18n lookup (reads window.__colophonConfig.i18n)
filters-sort-paging.js   # Search, filters, sort, pagination
selection.js             # Row selection + multi-select helpers
shelf-view.js            # Gallery/shelf layout
series-view.js           # Series grouping layout (+ the "Order the series" button)
series-rename.js         # Rename one series card (deterministic, no AI)
series-order.js          # Series-order review: one block per group, ticked rows only.
                         #   Two entry points — one series (series card) and a whole
                         #   author (/authors row, author-filter banner)
book-modal.js            # Single-book edit modal (large)
bulk-result-modal.js     # Post-batch summary modal
duplicates.js            # Duplicate cleanup UI
reading-now.js           # "Currently reading" widget
scan-sync.js             # Scan trigger + SSE handling for live progress
upload.js                # In-app book upload: file picker + window-level drag-and-drop → POST /upload
cleanup-misc.js          # Misc cleanup actions
url-state.js             # Mirrors view/search/filters/sort/page to the URL (back + deep links)
author-combobox.js       # Registry-backed multi-author fields in the book modal (one row per author, typeahead + create-guard; hidden #modalAuthor holds the ' & '-joined string for legacy flows)
authors-manage.js        # /authors page: confirm/rename/merge/verify + AI adjudicator (own page, not the bulk view)
reader.js                # In-browser reader controller (standalone /reader page, not the bulk view; ES module, loads foliate-js)
covers-batch.js          # "Fetch covers for these": the missing-cover filter as a batch — dry-run stream, review grid, per-book apply
language-check.js        # Language scenario: Tools → Check language, findings table, per-book apply
reader-dict.js           # Selection sheet for the reader. One word → definition + translation + AI; more than one → passage mode with Copy / Copy with source (v1.46.0). WORD_RE decides which.
```

When editing the main view, look in the relevant JS module first — most logic lives there, not in the template.

## Architecture decisions

### Blueprints

Six: `metadata_bp`, `authors_bp`, `scan_bp`, `settings_bp`, `kobo_bp`, `reader_bp`. `authors_bp` (added v1.21.0) serves the `/authors` manage view plus the registry JSON APIs the combobox uses. No `library` or `bookstores` blueprints — those were removed during the fork from Bookstation. `kobo_bp` is mounted at `/kobo` and only serves authenticated Kobo devices via per-device path tokens. `reader_bp` is mounted at `/reader` (added v1.5.0 — the fork's original `reader` blueprint was a different, removed thing; this is a fresh in-browser EPUB reader, see below).

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

### Language check (v1.52.0)

The second scenario flow. `services/language_check.py` reads the text out of
every EPUB and reports only what deserves a human: no stored language, or a
stored language the text contradicts. The stream is read-only — proven at the
HTTP boundary by `test_stream_never_writes`, not just in the service — and
`/metadata/language-check/apply` writes only what the user ticked, with
`selected_fields={"language"}` so nothing else can ride along.

`detect_language_confident` samples at **30 % and 60 % through the spine**,
not from the start: front matter is routinely copyright boilerplate in
another language, and sampling it answers the wrong question. Two samples
that disagree set `agree=False`, which the UI flags and leaves unticked.

**This flow contradicts the plan's invariant 3, deliberately.** `language`
is in `models._DEVICE_CONTENT_COLUMNS`, so even a DB-only correction stamps
`content_updated_at` and the Kobo re-downloads. That is correct — the device
picks its dictionary and hyphenation from this field — which is also why the
"write to the files too" checkbox is pre-ticked here and nowhere else. The
label says how many books will reload. `test_language_only_db_change_still_
stamps_content` pins it; if it ever goes red, someone removed `language`
from that set and quietly stopped language fixes from reaching a reader.
Series is in that set too, so steps 4–5 will meet the same thing.

### Ordering a series (v1.53.0)

The third scenario flow, and the first that asks the AI about a *set* of
books rather than one. `ai_metadata.propose_series_order()` sends the whole
group in one call — ids, titles, what the library already records — and gets
back an index per book plus a `not_in_series` list. Sanitizing that answer is
the load-bearing part, not the HTTP call: invented ids are dropped, repeated
ids kept once, and an id the model put in **both** lists lands only in
`not_in_series`, because the safest reading of "unsure" is to write no number
at all. Ids it never mentioned come back as `unranked` and show as "No answer"
rather than being silently treated as excluded.

`services/series_batch.py` turns that into a reviewable proposal. Status per
row, first match wins: `not_in_series` → `unknown` → `unchanged` → `conflict`
→ `confirmed` → `ai_only`. **`conflict` deliberately outranks `confirmed`**:
a number someone already entered is never pre-ticked away, even when Wikidata
backs the new one — the row carries `wikidata_index` so the tooltip can say
so, and the user decides. Only rows that reach the `confirmed`/`ai_only`
branch cost a Wikidata round trip, and the lookups share a
`_WIKIDATA_BUDGET_SECONDS` deadline (90 s) so a long series degrades to
unconfirmed rows instead of hitting Gunicorn's 300 s timeout.

Pre-ticking is the whole safety story and lives in `series-order.js`:
`confirmed` ticked, `ai_only` ticked only at `high` confidence, everything
else unticked, and `not_in_series`/`unknown` get no checkbox at all. A lone
unconfirmed proposal is downgraded to `low` so it can never arrive pre-ticked.

This flow meets invariant 3 head-on, like the language check: `series` and
`series_index` are in `models._DEVICE_CONTENT_COLUMNS`, so a synced Kobo
re-downloads the book even with "Write to the files too" unticked. The modal
says so in a line under the table rather than pretending otherwise. The review
component takes a **list** of groups (`groups: [...]`) even though step 4 only
ever sends one — step 5 sends several, and the renderer already loops.

### Ordering an author's series (v1.54.0)

The fourth scenario flow, and the last one the plan called for. Same
review modal, same statuses, same apply route as "Order the series" — the
only wider thing is the selection: every format group by one author, and
the AI is asked to do the **grouping** as well as the ordering
(`ai_metadata.propose_author_series`).

The status logic now lives in one place, `series_batch._build_group`, and
both flows call it. The priority order is unchanged and still binding:
`not_in_series`/`standalone` → `unknown` → `unchanged` → `conflict` →
`confirmed` → `ai_only`. The single-unconfirmed downgrade is applied
**per group**, so a thin series in an author's shelf cannot arrive
pre-ticked on the strength of a thicker one beside it.

Books the model places in no series land in a final group with
`standalone: true` and `series_name: null`. Rows there carry status
`standalone` and get **no checkbox** — that, not a rule in the apply
path, is what stops this flow putting an index on a standalone book.
Books the model never mentioned share that group as `unknown`.

`_WIKIDATA_BUDGET_SECONDS` (90 s) is deliberately **not** reset per
group: one deadline covers the whole proposal. An author with many series
is exactly the case the budget exists for, and per-group budgets would
let a large shelf hold a blocking POST open past Gunicorn's 300 s. Past
the deadline rows simply stay `ai_only`.

Two entry points, one modal. The author-filter banner on
`/metadata/bulk?author=<id>` calls `openAuthorSeriesOrder()` directly;
the `/authors` row button is a plain link to
`/metadata/bulk?author=<id>&order_series=1`, and `series-order.js`
captures that parameter **at script-evaluation time** because
`url-state.js` loads later and rewrites the query string to its own known
keys. `/authors` is a separate page with its own i18n block — duplicating
the modal there was not worth it.

### Renaming a series, and "Spelling only" (v1.55.0)

Two corrections to the series scenario, both driven by what the review
table actually looked like in use.

**`normalize` is a status of its own.** A row where the proposal means the
same as what is recorded but the *text* differs — `"Children of time #03"`
vs `"Children of Time #3"` — used to read `unchanged` while showing two
different strings. That is the one thing a review table must not do. The
`unchanged` branch in `_build_group` now splits: byte-identical text stays
`unchanged` and loses its checkbox entirely (nothing to apply), everything
else becomes `normalize`, keeps a checkbox, is never pre-ticked, and sorts
with the primary rows rather than the trailing block. The columns are now
labelled **Now** and **Becomes**, not "Recorded" and "Proposed".

**`rename_series` renames one card, with no AI at all.** The series view
groups cards by a normalized key, so one card can already hold two
spellings; renaming from the card collapses them, which is the point. Each
book keeps its own `series_index` — this renames, it does not reorder. It
goes through `apply_series_changes`, so it fans out to format siblings and
still cannot touch anything but `series`/`series_index`. Route:
`POST /metadata/series/rename`.

Both meet invariant 3 the same way the rest of the series flow does:
`series` is in `_DEVICE_CONTENT_COLUMNS`, so even a DB-only rename stamps
`content_updated_at` and a synced Kobo re-downloads. The modal says so
instead of hiding it.

### The Authors page: one action, one menu, one readable column (v1.56.0–1.57.0)

Three things this page got wrong, all found by using it rather than reading it.

**Six actions per row is not a row, it is a toolbar.** Confirm · Verify ·
Rename · Merge · Split · Order series meant over a hundred buttons on a
17-author page and nothing usable on a phone. Now the row shows only what
its state needs — **Confirm**, and only while `source == 'tentative'` —
and the rest live in a `⋯` popover. Every menu item is still a
`<button data-act="…">` **inside the same `<tr>`**, which is the whole
trick: `authors-manage.js` delegates from the `<table>`, so the action
handlers did not change at all. The popover is `position: fixed` and
placed from the toggle's rect, because a menu on the last row must not be
clipped by an ancestor's overflow.

**`Q31191175` is not an answer.** The question after Verify is always
"did it find the right person?", and an opaque id cannot answer it.
`Author.authority_label` / `authority_description` store what Wikidata
said the match *is*; the cell shows the description and puts the raw ids
in named links' tooltips. The lookup already returned both and threw them
away, so **there is no backfill** — entries verified before v1.57.0 keep
their ids and show no description until verified again. The UI degrades
to links-only for exactly that case; don't "fix" it by inventing a value.

**A name is not a person.** The lookup is a free-text Wikidata search on
the canonical name plus filters; nothing from the library — titles, years,
the other authors — takes part. Wikidata ranks by notability, so "Dennis
Taylor" returned a British snooker player and the old human + name-match
rule accepted him, anchoring a science fiction author to a snooker player
*and* promoting the entry to `authority_linked`, which gates file writes.
A candidate must now also have a writing occupation (`P106` in
`_WRITING_OCCUPATIONS`), and the walk continues past candidates that fail
it rather than stopping at the first name match. That is only a guess about a
person, though, so v1.59.0 puts a fact above it: `_works_by_candidate`
asks Wikidata, in one SPARQL query for all candidates at once, which
works list each of them as author (`P50`), and a candidate credited with
a title the library already holds wins outright — **even if it failed the
occupation test**, which also rescues authors Wikidata gave no occupation.
The query is skipped unless there is a real choice to make (two or more
candidates and some known titles), and any failure returns `{}` so the
lookup falls back to occupation: Wikidata is evidence here, never a
precondition. `result["matched_on"]` records which evidence decided.
Titles are compared through `grouping.normalize_title_key`, lifted out of
`compute_group_key` so both places mean the same thing by "same title".

**The weak link was the search, not the filter.** "Dennis Taylor" returns
a snooker player, a racing driver, a footballer and a disambiguation page;
the novelist is labelled "Dennis E. Taylor" and is never a candidate at
all, so no filter can reach him. `_author_of_a_book_we_hold` therefore
searches a *title* the library holds, reads the work's `P50`, and checks
that person's name against ours. It runs only when the name path chose
nobody, and it deliberately skips the occupation test: being credited
with a book on the shelf outranks a `P106` claim, and this is how an
author Wikidata gave no occupation gets anchored.

`_search_ids` / `_get_entities` swallow their errors and return empty,
because on that path a failure means "no evidence". The main search does
**not** use them: there, a network failure must surface as `ok=False`
rather than a silent miss. Don't unify them.

`POST /authors/<id>/unlink` exists because a wrong anchor the user cannot
remove is the worst state of all.

**A column nobody can fill stays empty.** Verify was per-row only, so on
a real library Authority was `—` everywhere while most entries read
*Confirmed* — the two are unrelated, and the page never said so. There is
now a bulk **Verify selected**, and the page explains the column in prose
rather than a `title` tooltip, because this is read on an iPad where hover
does not exist. The bulk loop runs **in the browser**, one author at a
time: each verify is a SPARQL round trip, and a few hundred serially on
the server would run past Gunicorn's 300 s with nothing to show.

### Completeness traffic light (v1.52.0)

`completeness_score` (0..10 since `series` joined `FIELD_WEIGHTS`) stopped
being an internal prefetch heuristic and became something the user reads: a
dot in the table row, three clickable counters, a filter and a sort. That
promotion has a cost — the score has to be true on **every** write path, not
just the enrichment pipeline's. `refresh_completeness(item)` is called from
`scanner.upsert_library_item`, `save_metadata_json`, `enrichment_apply`,
`ai_apply`, `cover_apply_json` and `apply_metadata_to_item`, and
`backfill_completeness_scores()` fills rows that predate the column.

`missing_fields(item)` is the single source of truth: `completeness_score`
sums its weights, and the dot's tooltip lists it via the
`completeness_missing_fields` context processor. Do not re-derive "what is
missing" in the template with `if not item.x` — a 20-character synopsis
counts as missing to the scorer (`QUALITY_THRESHOLDS`) but not to a naive
truth test, and the dot would then contradict its own explanation.

Bands are green ≤1, yellow 2–5, red ≥6, and they are written down in three
places that must agree: `_completeness_bucket` in `routes/metadata.py`, the
`completeness_level` set in `bulk_metadata.html`, and the `completeness`
branch of `applyFilters` in `filters-sort-paging.js`.

### Fetching covers for the filter (v1.60.0)

The fifth and last scenario flow, and the only one that still drives the
generic enrichment engine. The shared fact is the filter itself: click the
**"N missing cover"** chip and a banner offers **"Fetch covers for these"**
(`app/static/js/covers-batch.js`, banner shown from the patched
`applyFilters` in `filters-sort-paging.js`).

**It runs the stream with `dry_run=1`, contrary to what step 6 of the plan
specified**, because the pipeline downloads a `preview_<id>` file for every
candidate cover whether or not anything is applied — so `cover_url_fetched`
reaches the browser either way, and running without the dry run would only
add unreviewed *text*-field writes to the files. `tests/test_cover_batch.py`
pins this, for `covers-batch.js` and for every other module except
`book-modal.js` (the single-book path, which is an explicit one-book action
and writes on purpose).

Two things the flow forced into the open:

**A dry run was not dry.** `bulk_stream` group-synced and committed *before*
the search, regardless of `dry_run`, so a format group whose EPUB had a cover
handed it to the MOBI sibling during a preview — the book then left the
"missing cover" filter without the user applying anything, and the review
grid's "Now" column described a state that no longer existed. Group sync is
now skipped in a dry run; the writing path keeps it.
`tests/test_batch_dry_run.py::test_dry_run_does_not_group_sync_either`, with
its control, pins both halves.

**`apply_cover` did not refresh completeness.** `cover_apply_json` did, the
form route did not, so a batch of covers left every traffic-light dot and
counter one band too red. The cover weighs 3 of the 10.

`_filteredIds()` reads `row.dataset.filterHidden` directly rather than
calling `getFilteredRows()`: that helper also drops rows a grouped or series
view has collapsed, and a collapsed format sibling needs a cover just as
much — a cover is applied per file. "These" therefore means the same set in
the table, the shelf and the series view.

Applying is sequential, one book at a time, in the browser. Each apply is a
download plus an `ebook-meta` write; a hundred in parallel against two sync
workers is Gunicorn's timeout with nothing on screen. `cover_path` is in
`_DEVICE_CONTENT_COLUMNS`, so the modal says how many books reload on Kobo
instead of pretending a cover is invisible to the device.

### Batch: preview before write (v1.51.1)

The generic batch wizard used to write before the user saw anything:
`bulk_stream` classified `auto_apply` and then ran
`apply_metadata_to_item(write_to_file=True)` on every group member *before*
emitting `book_done`, and a separate `action == "ai"` branch in
`bulk_metadata` wrote every `high`-confidence AI field straight to file with
no review at all. Both are gone. `bulk_stream` now takes **`dry_run=1`**:
same classification, no `_apply`, `apply_details` is `None` — and the wizard
always passes it. The writing path is now the single-book modal's alone
(`book-modal.js`) — the cover scenario drives this engine too, but as a dry
run like everything else (see "Fetching covers for the filter").

The wizard itself is **gone** as of v1.60.0 — `batch.js`, its modal and
`SHOW_LEGACY_BATCH` with it — because a batch over N books with no shared
fact is N independent reviews. The five scenario flows of
[`docs/plan-batch-scenarios.md`](docs/plan-batch-scenarios.md) replaced it.
What survived the file: `_esc`, `_cleanDate`, `_applyFieldLabel`,
`_resultLabel` and `_resultTooltip` moved to `core.js`, because the book
modal and the bulk result modal still render fetch results. Regression
test: `tests/test_batch_dry_run.py`, whose control case must stay green, or
a false-green dry-run test would hide a harness that never reaches `_apply`.
The wizard's CSS was removed in v1.61.0; the `bp-*` and `cover-review-*`
rules that remain in `bulk_metadata.css` are shared with the single-book modal
and the cover scenario.

### AI library context (v1.51.0)

`fetch_ai_suggestions()` no longer sees one book in isolation. `build_library_context()`
in `services/ai_metadata.py` adds three capped extracts to the prompt: the same
author's other books (one per format group, most complete sibling), the series
vocabulary in use (own author's first, then by frequency, with author so
same-named series don't collide) and the subject vocabulary (by frequency). A
suggested series that matches an existing one (casefold + whitespace) is
**snapped to the library spelling and promoted to `high`**, so a batch AI run
converges on one spelling instead of minting a new one per book. Subjects are
only nudged via the prompt, never promoted. There is no series registry — the
value still lives as free text on each row; merging already-divergent spellings
is the deferred series-cleanup view in `docs/TODO.md`.

### Kobo delta sync (v1.48.0)

Six bugs found by Bookstation's file-by-file comparison against Colophon
(their Kobo never finished "downloading book covers" on 639 books; ours did,
so the differences were the suspects). All six are fixed here. Two invariants
are load-bearing — don't undo them:

**The pagination cursor keys on `id`, never on `updated_at`.** `updated_at`
has `onupdate` and the Kobo PUTs reading state *between* page fetches, so an
OFFSET walk over an `updated_at` sort loses the row on the page boundary —
permanently. Each round carries a `high_water` ceiling set when it began, so
the row set shrinks monotonically and the walk terminates; at the end
`since := high_water`, **not** `max(updated_at)`. Regression test:
`test_state_put_between_pages_does_not_skip_books` (verify it red before
touching the walk — it fails with "1 book lost" against the old code).

**The ledger decides the wrapper, not the token.** No row → `NewEntitlement`;
`content_updated_at > sent_content_at` → `ChangedEntitlement` (carries
`DownloadUrls`, device re-downloads); `updated_at > sent_updated_at` →
`ChangedReadingState` (must *not* carry them); otherwise nothing. `since` is
now a pure optimisation. Sync token is **v2** (`since`/`hw`/`cur`/`full`); v1
is rejected as "no token".

`CoverImageId` carries the cover file's mtime (`<uuid>-v<mtime>`) because the
device caches by that id and never revalidates; `_find_item_by_uuid` strips
the suffix, so devices on the old form still work. It cannot repair a book
already on the device — there is no cover-only signal in the protocol —
so Settings → Kobo → **Force full resync** (`clear_ledger`) is the remedy.

Adding a column to `kobo_book_states` means updating **three** hand-maintained
places: the model, the `CREATE TABLE` body in `database.py`, and an `ALTER
TABLE` for upgrades — plus a backfill. A NULL `sent_*` reads as "newer", so a
missing backfill re-ships the entire library once.

### In-browser reader + reading-state sync (v1.5.0)

`reader_bp` (`/reader/<id>`) renders an EPUB in the browser with vendored
foliate-js (`static/vendor/foliate-js/`, an ES module, no build step). `/reader/<id>/file` serves the **raw** EPUB (not the kepubified Kobo variant); the URL is stable and token-free so it can be cached for offline reading (see below — v1.26.0 onward).

**Offline reading (v1.26.0, landing page + modal button + filter added v1.62.0)**: "Save for offline" caches the book + reader shell into the persistent `colophon-offline` service-worker cache. As of v1.62.0 that action is also reachable from the book modal in Shelf view (`#modalOfflineBtn`, `book-modal.js`), not just from inside an open reader; a precached `/offline` landing page (`app/templates/offline.html`, its own service-worker index at the synthetic `/reader/offline-index.json`) lists every saved book and is what a no-connection app launch lands on instead of a dead fallback; and a "Downloaded" chip/filter in the library view (`app/static/js/offline.js`) surfaces which rows are cached. See `docs/TODO.md`'s "Offline reading" entry and §12b of the handbooks.

Reading progress is **not** a separate store: the reader writes to the same canonical `LibraryItem` reading-state fields the Kobo sync uses (`read_status`, `read_progress`, …) via the shared `services/reading_state.py:apply_reading_state()`, which both the Kobo PUT handler and `/reader/<id>/progress` call. Because it bumps `read_last_modified`, progress made in the browser rides the existing Kobo delta to the device, and vice versa — no new sync infra. Position syncs **exactly in both directions** since v1.42.0. Kobo spans (`kobo.N.M`) don't exist in the source EPUB, but kepubify preserves the text character for character, so the shared coordinate is *non-whitespace characters into the chapter*: the reader posts `{href, offset}`, `services/kobo_location.py` walks the cached KEPUB's spans to that offset, and `reader.py:_resume_anchor` runs it backwards for resume. When that can't resolve (PDF, no KEPUB) the reader falls back to percent and **clears** the stored location (`clear_location=True`, v1.41.0), and the Kobo gets a chapter derived from the percent — a stale bookmark paired with newer progress used to drag the device back and deadlock the sync. The "Läs" button is a `display-only` element gated to EPUB, so it appears only in the shelf view's passive modal, not the table view's edit modal.

**Dictionary lookup (v1.32.0)**: selecting a single word in the reader opens a
bottom sheet with an English definition (GCIDE) + Swedish translation
(FreeDict/WikDict) + optional AI explanation-in-context. Dictionaries download
on demand (pinned URL + checksum in `services/dictionaries.py`'s MANIFEST) to
`DATA_DIR/dictionaries/<pair>/` and lookups run **server-side** — full design
and how to add languages in [`docs/reader-dictionary-lookup.md`](docs/reader-dictionary-lookup.md).

**Reading-state sync gotchas live in [`docs/kobo-reading-state-sync.md`](docs/kobo-reading-state-sync.md)** — read it before touching `reading_state.py` or the Kobo PUT/DTO paths. It records the conflict-resolution rules (monotonic status + furthest-read-wins, v1.28.1), the full-Location round-trip (`read_location_json`, v1.28.2 — `Source` is the chapter file, never the book UUID), the content-vs-progress re-download distinction, why sideloaded books (foreign v4 UUIDs) can't sync, and a symptom→cause triage table.

## Models

Seven tables in `app/models.py`:

**`library_items` (LibraryItem)** — the catalogue. Important fields:
- `book_uid` — device-facing identity (v1.43.0), deliberately **not** the PK.
  `routes/kobo.py:_book_uuid` hashes it; existing rows backfilled to `"book-<id>"`
  so historical Kobo UUIDs are unchanged. A delete + re-add used to mint a new
  book on the device and strand the old entitlement.
- `manual_metadata` (bool) — locks text fields from auto-overwrite
- `cover_locked` (bool) — locks cover from auto-overwrite
- `group_key` — format grouping hash
- `pipeline_status` — scanned / enriched / polished
- `file_modified_by_colophon` / `upstream_synced_at` — upstream sync tracking
- `author_id` / `author_status` — registry link + resolution outcome
  (linked/new/review/missing, NULL = pending). `author` edits reset both via a
  `before_flush` listener; the next scan/upload re-resolves.

**`authors` (Author)** + **`author_aliases` (AuthorAlias)** — author authority
control: canonical author entities and observed variant spellings. `source`
(`tentative`/`user_confirmed`/`authority_linked`) gates file writes — tentative
entries are DB-only. See `docs/author-authority-design.md`.

**`book_authors` (BookAuthor)** + **`author_split_rules` (AuthorSplitRule)** —
multi-author support (v1.36.0). Ordered book↔author links; position 0 is the
primary author, mirrored in `library_items.author_id` so single-author call
sites keep working. `item.author` stays the file-mirroring display string —
`' & '` is the canonical separator (Calibre convention; the scanner joins
explicit `dc:creator` entries with it, the resolver auto-splits on it, and the
sources join fetched author lists with it). Strings fused with other
separators ("A och B", "A, B") stay one registry entity — splitting them is
manual (the `/authors` Split dialog), and the decision persists as
`author_split_rules` (normalized fused string → ordered author ids) that the
resolver consults so re-scans of still-fused files don't resurrect the fused
entry. Rules never reference tentative entries (the GC relies on it). The book
modal renders one combobox row per author + "Lägg till författare" — the user
never types separator syntax. The looks-multi badge is deliberately broad
(commas flag sort-form names too); clicking it dismisses it per entry
(`Author.split_dismissed`, v1.37.0 — reset on rename).

**`kobo_devices` (KoboDevice)** — registered Kobo e-readers. Each row has a path token used in the device's sync URL (`/kobo/<token>/...`). Revokable from the settings UI.

**`kobo_book_states` (KoboBookState)** — the ledger: a per-device record of which `library_items` the device has been told about, and **in what shape** (`sent_updated_at` / `sent_content_at`, v1.48.0). The ledger — not the sync token's `since` — decides what is said about a book, so a device that lost its token gets only what it lacks instead of the whole library as `ChangedEntitlement`. See "Kobo delta sync" below.

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

`babel.cfg` extracts **Python and Jinja only** — no JavaScript. JS strings reach
the frontend through `window.__colophonConfig.i18n`, rendered by Jinja in
`bulk_metadata.html`, so they are extracted from the template like any other
`_()` call.

> ⚠️ **Before adding a `[javascript: …]` line to `babel.cfg`**, know that
> Babel's JS extractor stops silently at a regex literal containing a quote —
> everything after it in that file is skipped, with no warning and nothing
> looking wrong. Five of our modules already carry the pattern
> (`.replace(/'/g, '&#39;')` around lines 23–45 of `upload.js`,
> `author-combobox.js`, `reading-now.js`, `scan-sync.js`, `shelf-view.js`), so
> enabling JS extraction today would quietly lose most of those files. A
> character class (`/[']/g`) avoids it. Reported by the Bookstation project,
> who lost nine strings to it; verified present here 2026-08-10.

## Testing

```bash
python -m pytest tests/ -v
```

Tests mock external services (Google Books, Calibre subprocess). No integration tests requiring Docker.

### Running tests locally (outside Docker)

The dev box only has system Python with no project deps. One-time setup:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
```

`create_app()` defaults `DATA_DIR=/data` and `LIBRARY_DIR=/books` (the container
mounts), which don't exist locally → `PermissionError` in any test that builds
the app (e.g. `test_kobo_sync`). Point them at writable local dirs via a repo
`.env` (loaded by `load_dotenv()`; gitignored locally via `.git/info/exclude`,
since `.env` is not yet in `.gitignore`):

```
COLOPHON_DATA_DIR=<repo>/data        # under gitignored data/
COLOPHON_LIBRARY_DIR=<repo>/var/books-dev   # under gitignored var/
```

Then `.venv/bin/python -m pytest tests/ -q`. Containers ignore this file — they
get their env from docker-compose.

The local `.venv` runs **Python 3.14** (the dev box has no 3.12); the container
runs 3.12. The suite is green on both, but that is the one difference to
suspect if something passes locally and fails in the image.

### Running a real local instance (dev library)

Useful for seeing a change against real books without touching prod. It needs
its **own data dir**, separate from the one the `.env` above points at — the
suite wipes `DATA_DIR/colophon.db` on every run, so sharing it means every
`pytest` empties the dev library:

```bash
COLOPHON_DATA_DIR=$PWD/var/data-dev COLOPHON_LIBRARY_DIR=$PWD/var/books-dev \
  .venv/bin/gunicorn -b 127.0.0.1:5055 -w 2 -t 300 --error-logfile - wsgi:app
# then: curl -s http://127.0.0.1:5055/scan   (GET, not POST) to populate the DB
```

Fill `var/books-dev/` by **copying** from server2's working copy — never the
Synology originals, and never a move:

```bash
rsync -a -r --files-from=<list of author folders> \
  chris@192.168.50.8:/mnt/docker/appdata/colophon/bibliotek/ var/books-dev/
```

`/mnt/docker/appdata/colophon/bibliotek/` is itself already a working copy
(the originals live on the Synology at `/volume2/komga`), so an rsync **pull**
from it touches nothing of value. Both `var/` and `data/` are gitignored.

Note that the local instance has **no API keys** (`ai_is_configured()` is
False, no Google Books key), so AI flows and metadata fetches do nothing there
until keys are added to its settings.

> ⚠️ **Never run the suite inside the live `colophon` / `colophon2` container.**
> The `test_kobo_sync.py` fixture calls the real `create_app()` and runs
> `DELETE FROM library_items / kobo_devices / kobo_book_states` on
> `DATA_DIR/colophon.db` — i.e. the **production DB** at `/data`. Run it locally
> (above) or in a throwaway container with **no `/data` mount**:
> ```bash
> docker run --rm -v /mnt/docker/stacks/colophon/repo:/src -w /src \
>   -e PYTHONPATH=/src --entrypoint sh colophon:latest \
>   -c "pip install -q pytest && python -m pytest tests/ -q"
> ```

Note: `Pillow` is in `requirements.txt` but was missing from an older local
`.venv`, which silently *skipped* the cover tests instead of failing. If
`tests/test_kobo_covers.py` reports skips, `pip install Pillow`.

**Known pre-existing failures (as of v1.61.3):** a clean run is *790 passed, 10
failed, 1 skipped*. The 10 are not regressions — `test_quality.py` (6) and
`test_scoring.py` (3) assert Swedish reason/warning substrings the code now
emits in English, and `test_scanner.py::...test_does_not_overwrite_manual_metadata`
expects a `manual_metadata` guard the scanner no longer applies. Treat "the same
10" as green; fixing them (decide SV vs EN reasons, confirm scanner intent) is a
separate cleanup.

## Common pitfalls

1. **Never spawn subprocesses per-file for reading metadata** — use ebooklib. Subprocesses + Gunicorn sync workers = timeouts.
2. **Docker cache** — always `--no-cache` on rebuild. Cached layers have hidden stale code.
3. **Blueprint references** — only `metadata.*`, `authors.*`, `scan.*`, `settings.*`, `kobo.*`, `reader.*` exist. Any `url_for('library.*')` etc. will crash.
4. **Main view is split** — `bulk_metadata.html` is the Jinja shell (~1000 lines); behaviour lives in `app/static/js/*.js` and styling in `app/static/css/bulk_metadata.css`. The i18n string map for JS is **rendered by Jinja** into `window.__colophonConfig.i18n` in `bulk_metadata.html` (search for `i18n: {`); `core.js` only reads it. Add a new JS string there, not in a `.js` file. Edit the right file — don't add new logic back into the template.
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
- Run a scenario flow to completion (the Apply step mutates many rows at once)
- Toggle settings in the Settings pages
- Click "Fetch metadata" / "Ask AI" on real books (these mutate state and consume API quota)

**Safe to do** during verification:
- Navigate between views (Tabell / Hyllvy / Serie)
- Open modals and inspect their layout (closing without saving is fine)
- Use the search box, filters, pagination
- Hover, scroll, take screenshots
- Toggle theme, change language

When in doubt, **ask first**. A single misclick on "Radera permanent (inkl. fil)" deletes real ebook files from disk.
