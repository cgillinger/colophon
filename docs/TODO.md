# TODO — Colophon

Deferred ideas and planned work. Implemented items get removed (the code/git
history is the record).

## Offline reading for the in-browser reader

**Done (v1.5.0):** the online in-browser EPUB reader itself — `reader_bp`
(`/reader/<id>`), foliate-js rendering, percent-based resume, and progress that
syncs with Kobo through the shared `services/reading_state.py`. See the
"In-browser reader" section in CLAUDE.md. What remains is **offline**.

**What:** Let a book read in the browser work with no network — "Kobo sync for
any phone/tablet browser, offline too". The reader works online today; this adds
the ability to download a book into the browser and read it on a plane.

**Why the PWA scaffolding is already in place (v1.4.0):** installability
(`/manifest.json`) and a reliable update mechanism (version-tied cache,
`?v=<version>` on assets, "new version" reload prompt) are the reusable
foundation. The service worker is conservative (network-first navigations — see
`app/templates/sw.js`). Keep it; don't re-litigate the PWA each time.

**What is NOT done (net-new for offline):**
- Caching actual book content. The current SW caches the app shell and versioned
  static assets only — NOT books. Offline reading needs an explicit "download
  for offline" flow writing the EPUB (from the stable `/reader/<id>/file` URL)
  into Cache Storage / IndexedDB, plus quota + eviction handling and a
  "downloaded books" UI.
- Offline progress buffering: today progress POSTs straight to the server. While
  offline it must queue locally and flush on reconnect (the reader's percent
  model makes this straightforward — no location coordinate to reconcile).

**Where it hooks in:** extend `app/templates/sw.js` to (a) intercept
`/reader/<id>/file` cache-first when the book is downloaded, and (b) cache books
in a **separate** cache (NOT `colophon-v<version>`, which `activate` purges on
every version bump — book data must survive app updates); a "download for
offline" action in the book modal; HTTPS required (mobile must reach the app via
Tailscale Serve, not the raw LAN IP, for the SW to run).

**Scope:** medium-large. New user-visible feature → MINOR bump.

## Deep-link to an open book modal (`?book=<id>`)

**What:** Let a book's display modal be reflected in the URL so you can link
straight to it and use the browser Back button to close it. This is the "open
book in URL" scope we deliberately deferred when adding URL state sync in
v1.3.0 (see `app/static/js/url-state.js`).

**Intended behaviour:**
- Opening a book → push `&book=<id>` onto the current view/filter URL, e.g.
  `?view=shelf&q=Reynolds&book=42`. Browser **Back** then closes the modal.
- Closing via the X → strip `book` from the URL (back to the list URL).
- Direct link / reload with `?book=42` → filter the list as usual, then open
  that book in the display (read-only) modal on top.

**Where it hooks in:**
- `app/static/js/book-modal.js` — `openBookModal(itemId)` (push book param) and
  `closeBookModal()` (strip book param). Both already on `window`.
- `app/static/js/url-state.js` — extend `readStateFromUrl()` to open/close the
  modal to match the URL (open if `book` present and not open; close if absent
  and one is open). Add `book` to the params it writes.

**The one tricky bit:** if the user arrives via a direct link (the book entry is
the first/only history entry), "close" must NOT call `history.back()` (that
leaves the site) — strip the param via `replaceState` instead. Track whether we
were the ones who pushed the book entry.

**Scope:** small-to-medium. New user-visible feature → MINOR version bump.
Verify with Playwright: open→Back closes; direct `?book=` load opens; close via X
returns to the list URL.

## Sync to library: add a preview→confirm step + consolidate the duplicate affordances

**Two things, one change.** (a) Today clicking **Sync to library** fires
`/sync/push` immediately — no chance to see what's about to be written upstream.
The user wants the old Bookstation-style two-step: click → see the list of books
that will be pushed → click again to confirm. Better control. (b) While in here,
fix the long-standing duplicate-affordance bug below.

**Decision (made 2026-06-01):** the sidebar item is the **single** trigger;
**drop `#syncBar`**. Clicking it opens a **preview modal** (not an immediate
sync); the confirm button inside the modal starts the SSE push.

**Backend — net-new (no list-pending capability exists today, only a count):**
- Add `list_pending_items()` to `app/services/upstream_sync.py` — same filter as
  `get_unsynced_count()` (`file_modified_by_colophon` newer than
  `upstream_synced_at`) but returns `[{id, title, author, file_modified,
  last_synced}]`, **no side effects**.
- Add a JSON route `GET /sync/pending` in `app/routes/metadata.py` →
  `{ok, items, count}`. The existing `/sync/push` SSE endpoint stays as the
  confirm action, unchanged.

**Frontend — `app/static/js/scan-sync.js`:**
- Split `startPushSync()`: the sidebar now calls `openSyncPreview()` →
  `fetch('/sync/pending')` → render a modal listing the books (title + author +
  "modified" time). Confirm button calls the existing push-SSE logic
  (rename current body to `confirmPushSync()`).
- **Pattern to copy:** `app/static/js/duplicates.js` already does exactly this
  (GET a JSON list → render modal → act). Mirror its modal shell.
- **Bonus (cheap, high-value):** per-row checkboxes in the modal so the user can
  exclude individual books from this push. Requires `/sync/push` to accept an
  optional `ids` filter; skip if it balloons scope.

**Drop `#syncBar`:** remove the `#syncBar`/`#syncBarText` markup from
`bulk_metadata.html`, its second `startPushSync()` button, and the show/hide in
`app/static/js/filters-sort-paging.js` (~L313). That also retires the hardcoded
Swedish bar text (`' filer redo att synka till bibliotek'`, ~L318) that never
switched to English — no i18n fix needed if the bar is gone. Sync progress now
lives in the modal instead of the bar.

**Scope:** small-to-medium. New user-visible behaviour (preview step) + removed
visible bar → MINOR. Verify on iPad viewport with the prod lab book "12|21|12":
preview lists it, confirm pushes, cancel does nothing.

## Make scroll restore after edit-reload pixel-accurate (v1.6.0 follow-up)

**What:** After an edit, `closeBookModal()` reloads the list and `core.js`
restores the stashed scroll position (`colophonRestoreScroll`,
`history.scrollRestoration = 'manual'`). The *data* refresh works, but the
restored scroll drifts on long, cover-heavy lists — it lands a few hundred px
off, not at the exact spot.

**Root cause:** browser **scroll anchoring**. The restore runs on `load`, but
the table's cover images load lazily *after* that; as rows above the viewport
gain height, the browser shifts `scrollY` to keep visible content stable,
moving it off the restored pixel. Verified on prod (375 rows): stashed 400 →
landed 588.

**Options:**
- **(recommended) Anchor to a row, not a pixel.** Before reload, stash the
  `data-item-id` of the topmost visible row (+ its offset within the row).
  After reload, `scrollIntoView()` that row. Immune to height changes above it.
- Cheaper stopgap: re-apply `scrollTo` after covers settle (a short delay, or
  after the near-top `img` load events fire), or set `overflow-anchor: none`
  on the scroll container during restore (has its own side effects).

**Where it hooks in:** `app/static/js/book-modal.js` (`closeBookModal` stash) +
`app/static/js/core.js` (the `load` restore handler).

**Scope:** small. Polish → PATCH. Not blocking — the reported "stale data after
edit" bug is already fixed (v1.6.0); this is just exact scroll position.

## Remove the Calibre dependency

**Why:** Calibre is the heaviest, least robust, hardest-to-maintain dependency
(see the investigation around v1.11.0). It pulls in Qt/X11 (`libxcb-*`), needs
`QT_QPA_PLATFORM=offscreen`, is the slowest part of every `--no-cache` build, and
its value as a *metadata source* has largely been replaced by the native sources
added in v1.8.0–v1.11.0 (Hardcover, Wikidata, LIBRIS, Open Library + the
embedded-file OPF candidate). It is already gated to the on-demand "Deep" tier.

**Two Calibre CLI tools are used — handle them separately:**

1. **`fetch-ebook-metadata`** — the metadata *source* (`metadata_calibre.py`,
   wired in `metadata_pipeline.py` as tier-2, plus legacy
   `metadata_sources.search_all_sources`). The easy half.
2. **`ebook-meta`** — piggybacked for TWO things:
   - **Writing** metadata back to files (`metadata_writer.py:write_metadata_to_file`
     — `--title/--authors/--comments/--publisher/--identifier/--language/--tags/
     --series/--index/--date/--cover`).
   - **Reading** MOBI/AZW3/kepub metadata (`scanner.py:_extract_ebook_meta_metadata`
     → `metadata_calibre.read_all_ebook_meta_fields`); EPUB already uses ebooklib.

`ebook-meta` ships *inside* the `calibre` package, so the image dependency can
only be dropped once both the write path and the MOBI/AZW3 read path stop needing
it.

**Key fact that shrinks the work:** the live library is **371 EPUB + 4 PDF — zero
MOBI/AZW3/kepub**. PDFs aren't writable by `ebook-meta` anyway. So in practice the
write path is EPUB-only and the MOBI/AZW3 read path is unexercised. `kepubify`
(Kobo conversion) is a *separate* binary, NOT Calibre — unaffected.

**Phase A — drop Calibre as a metadata source (low risk, do first):**
- Remove the tier-2 Calibre step from `metadata_pipeline.py`; drop
  `include_calibre`, `METADATA_SOURCE_CALIBRE_ENABLED`, the settings toggle +
  `calibre_available`, and the Calibre column/skipped-dash handling in
  `book-modal.js`/`batch.js` (or leave the columns, just never populated).
- Net loss of sources (verified 2026-06-01 against the Calibre manual + the
  installed kiwidude plugins): **four**, not three — **Amazon.com, Edelweiss,
  Fantastic Fiction, FictionDB**. Calibre's built-in set in this install is
  Google / Google Images / Amazon.com / Edelweiss / Open Library, plus the three
  kiwidude plugins (Goodreads / Fantastic Fiction / FictionDB). Of those:
  - **No real loss:** Google (native Google Books), Open Library (native since
    v1.11.0), Google Images (cover-only — Google Books already in `cover_search.py`),
    Goodreads (~covered via Hardcover — not 1:1; Hardcover is its own DB).
  - **Amazon — loss is largely theoretical.** The Calibre Amazon source is broadly
    broken in 2025 (captcha / 503 / bot-detection); it often returns nothing.
  - **Edelweiss** — the earlier "three sources" figure missed this built-in. B2B
    bookseller catalogue, not covered natively, but thin value over the native stack.
  - **Fantastic Fiction + FictionDB — the only loss with real substance**: both are
    strong on *series + genre + synopsis*, which overlaps heavily with what
    Wikidata/Hardcover/Open Library already cover natively. Neither has a public
    API — FF uses an undocumented JSON/CloudSearch endpoint, FictionDB is HTML
    scraping, and both kiwidude plugins are GPL + tightly coupled to Calibre's
    `Source` base class. **Recommendation: accept the loss; do NOT reimplement
    them as native scrapers** — that keeps exactly the fragility this whole task
    exists to remove. Lean on Hardcover / Wikidata / Open Library for series+genre.
- Keep `metadata_calibre.py`'s `ebook-meta` *read* helpers for now.
- Keeps `calibre` in the image, so trivially reversible.

**Phase B — replace the `ebook-meta` piggyback, then drop the package:**
- **EPUB writing** → reimplement `write_metadata_to_file` with `ebooklib`
  (`read_epub` → set DC fields + `calibre:series`/`series_index` OPF meta +
  cover → `write_epub`; `epub.write_epub` is available). The real work — preserve
  the file and round-trip series.
- **MOBI/AZW3** → none in the library: drop write support (DB-only, return
  `unsupported_format`) and read via a tiny pure-Python EXTH parser or the `mobi`
  package, OR accept reduced MOBI support. Degrade gracefully rather than add a
  dependency.
- Once nothing calls `ebook-meta`/`fetch-ebook-metadata`, remove `calibre` from
  the `Dockerfile` and delete `tools/install_calibre_plugins.sh` + its build
  step. Win: smaller image, faster `--no-cache` builds, fewer fragile scraper
  plugins to maintain.

**Verify:** save metadata to a real EPUB and confirm fields + cover + series
round-trip (read back with ebooklib AND open in a reader). Test on the prod lab
book "12|21|12".

**Scope:** Phase A small (MINOR — removed source/setting). Phase B medium
(rewrites the file-write path; MINOR, or MAJOR if MOBI/AZW3 write support is
formally dropped as a breaking change).
