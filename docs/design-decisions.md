# Design decisions — Colophon

Moved out of `CLAUDE.md` on 2026-10-29: the story behind each binding rule, per version. The rules themselves are listed briefly in `CLAUDE.md` under "Load-bearing invariants"; read the matching section here before changing that area.

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

**Position vs progress and page numbers (v1.63.0)**: two different questions with two different rules. *Progress* (`read_progress`, the percentage) stays furthest-read-wins. *Position* (`read_position_json`) is last-write-wins and is recorded on every reader post, including backward moves, so **resume returns to where you last were**: the reader picks the newest of the server's stored position and the browser's local copy by timestamp (`resumeAt` vs the local `savedAt`; ties go to the server), and the local copy now mirrors the exact `href`/`offset` so an offline flush posts the exact position instead of a percent-only one. A *virtual page* is 1500 dense (non-whitespace) characters, built once per EPUB by `services/page_map.py` (cached under `DATA_DIR/page-maps/`, served at `/reader/<id>/pagemap`) and mirrored in `reader.js` (`pageOf` / `anchorForPage` / `printPageAt` — keep the two in lockstep). The top bar shows `p. 212 / 540`, with the EPUB's own print page-list label in parentheses when it has one; the sheet's **Go to page** row (and a tap on the readout) jumps there, setting the snapback chip first. The page map is cached with the book for offline reading (it is in the `cacheBook` asset list), and the book modal shows the last virtual page beside the percent.

**OPDS + KOSync (v1.64.0)**: a third writer of the same state. The load-bearing rule: KOSync GET answers with the *position*, never `read_progress` — CrossPoint jumps to anything further along than its own page, so the high-water mark would fling it forward. PUTs never set Finished, and a pointer whose chapter disagrees with the device's percentage is reduced to chapter level. `koreader_xpath.py` must keep mirroring CrossPoint's `ChapterXPathResolver` (see the doc below for how it was verified).

**Reading-state sync gotchas live in [`docs/kobo-reading-state-sync.md`](docs/kobo-reading-state-sync.md)** — read it before touching `reading_state.py` or the Kobo PUT/DTO paths. It records the conflict-resolution rules (monotonic status + furthest-read-wins, v1.28.1), the full-Location round-trip (`read_location_json`, v1.28.2 — `Source` is the chapter file, never the book UUID), the content-vs-progress re-download distinction, why sideloaded books (foreign v4 UUIDs) can't sync, and a symptom→cause triage table.

## Known test failures (as of v1.61.3)

A clean run was *790 passed, 10 failed, 1 skipped*. The 10 are not regressions — `test_quality.py` (6) and `test_scoring.py` (3) assert Swedish reason/warning substrings the code now emits in English, and `test_scanner.py::...test_does_not_overwrite_manual_metadata` expects a `manual_metadata` guard the scanner no longer applies. Fixing them (decide SV vs EN reasons, confirm scanner intent) is a separate cleanup.
