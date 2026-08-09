# Kobo ↔ Colophon reading-state sync — architecture & gotchas

Written after a long live-debugging session (June 2026). The point of this doc
is simple: **if we come back to reading-state sync, don't re-derive all this.**
Three real bugs and two non-bugs were found the hard way; they're recorded here
with a symptom→cause table for fast triage.

## The canonical model

Reading state lives on `LibraryItem` (`read_status`, `read_progress`,
`read_location`, `read_location_json`, `read_last_modified`, `read_started_at`,
`read_finished_at`, `times_started`) — **not** per device. Both writers go
through one helper so the rules can't drift:

- Kobo PUT handler — `app/routes/kobo.py:update_reading_state`
- In-browser reader — `app/routes/reader.py:update_progress`
- Shared rules — `app/services/reading_state.py:apply_reading_state`

## Conflict resolution (`apply_reading_state`)

- **Status is monotonic:** `ReadyToRead < Reading < Finished`. A lower-ranked
  incoming status is dropped regardless of timestamp. (A Finished book can't go
  back to Reading via sync — deliberate re-reads use the reset endpoint, which
  writes fields directly and **bypasses** this helper.)
- **Equal status → furthest-read-wins (v1.28.1).** Higher-or-equal progress
  applies even with an *older* timestamp; a lower progress is dropped even if
  *newer*. `read_last_modified` only ever advances. Timestamp is the tiebreaker
  only when progress is missing on one side.
  - *Why:* under the old last-write-wins-on-timestamp rule, progress could move
    **backwards** — a stray `progress=0.0` PUT (a cover-reset / sync echo from
    the device) with a newer timestamp wiped a real position (e.g. 24% → 0%).

## The two devices resolve conflicts differently (v1.41.1)

**We resolve by furthest-read; the Kobo resolves by timestamp.** That asymmetry
is a deadlock generator, and fixing the *content* of the DTO is not enough:

- We refuse the device's lower progress (furthest-read-wins) — correct.
- The device refuses our state because its own `LastModified` is newer — also
  correct, by its rules. And its own gets newer every time it reports.
- Neither side ever moves. `docker logs` shows `dropped (monotonic/older)`
  forever while the device sits on the old position, and the correction we
  worked so hard to compute is discarded unread.

So when a device PUT is dropped **and the device's timestamp would beat ours**,
`routes/kobo.py:update_reading_state` re-stamps `read_last_modified = utcnow()`
— progress, status and location untouched, only "as of when do we claim this".
The next DTO then out-ranks the device's local copy and the correction lands.
It is self-terminating: once the device accepts, it reports a matching (or
higher) progress, which applies normally and stops the drops.

*Field report that produced this:* server on 60 %, device stuck on 31 %. The DTO
was already correct (v1.41.0 fixed the location) and the delta shipped it
(`reading=1`), but the device's state was ~2 days newer than
`read_last_modified`, so it threw ours away every single sync.

## Location round-trip (v1.28.2)

The Kobo's `CurrentBookmark.Location` has **three** fields that must be kept
together:

| Field    | Example                    | Meaning                                  |
|----------|----------------------------|------------------------------------------|
| `Value`  | `kobo.47.1`                | the span id                              |
| `Type`   | `KoboSpan`                 | coordinate system                        |
| `Source` | `OEBPS/chapter018.xhtml`   | the **content document** the span is in  |

- Store **all three verbatim** in `read_location_json` and echo them back
  unchanged. `Source` is the chapter file — **not** the book UUID.
- *The original bug:* the PUT handler stored only `Value` (in `read_location`)
  and the outgoing DTO **fabricated** `Source = book_uuid`. The Kobo couldn't
  resolve the span against the wrong Source, so **every sync reset the device to
  the start (~1%)**, while offline the local bookmark held fine. (Both DTO sites
  fabricated it: `_entitlement_dtos` and `_build_state_response`.)
- **Fallback:** when there's no faithful full Location (`read_location_json` is
  NULL), send `Location: null` — **never** fabricate a Source. The device then
  keeps its own local bookmark. (`null`, not an omitted key — matches the
  existing Komga-style contract.)
- `read_location` (Value-only) is kept for display/back-compat; the round-trip
  is driven by `read_location_json`. The **reset path clears
  `read_location_json` too**, else a "re-read from start" resurrects the old
  span on the next sync.
- The in-browser reader **used to** write no location, because EPUB CFIs and
  Kobo KEPUB spans are different coordinate systems. Since v1.42.0 it writes a
  real one, via the character bridge below; when that can't resolve, the old
  behaviour stands and the Kobo gets a chapter derived from the percentage.

## Exact position across readers — the character bridge (v1.42.0)

Percent gets you a chapter. To get the *sentence*, the two readers need a shared
coordinate, and they appear not to have one: the Kobo positions by `kobo.N.M`
spans that **kepubify injects**, and those don't exist in the source EPUB the
browser renders.

They do share one thing, though: **the text**. kepubify wraps it and renames
nothing. Measured across a real 144-document book — 16,825 spans — the
whitespace-free text of the KEPUB is *identical* to the source EPUB's body text
in every single document. So "how many non-whitespace characters into this
chapter am I" is a coordinate both sides can compute, and it bridges them
without reimplementing kepubify's segmentation or parsing a CFI.

- **Why whitespace is excluded, not collapsed.** The source has newlines between
  block elements that belong to no span at all; a collapsing rule drifts by one
  character per paragraph. Ignoring whitespace sidesteps every such difference.
  Both halves of the rule must agree: `services/kobo_location.py:dense_text` and
  the `dense()` in `static/js/reader.js`.
- **Browser → Kobo:** `reader.js` walks the section's text nodes to the visible
  range and posts `{href, offset}` alongside the percent;
  `kobo_location.py:location_for_offset` walks the **cached KEPUB's** spans to
  the same offset and stores the span it lands in.
- **Kobo → browser:** `reader.py:_resume_anchor` runs `offset_for_span` and the
  page hands the reader `resumeHref`/`resumeOffset`; the reader finds that
  offset in its own DOM, builds a CFI and `goTo`s it.
- **The KEPUB must be the one the device has.** `kobo_kepub.py` caches on
  `(item_id, source mtime)`, so an untouched source file means identical bytes
  and identical span ids. Editing the file invalidates both — the device
  re-downloads and the span ids are regenerated together, so they stay in step.
- **Only `koboSpan` elements are counted**, never every text node: kepubify
  injects a `<style class="kobostylehacks">` block whose CSS would otherwise be
  counted as body text and shift every offset in the document.
- Falls back to the chapter-level percent path whenever any of this is
  unavailable. `tests/test_kobo_location.py` re-checks the premise against the
  real book when it happens to be mounted — if kepubify ever changes its text
  handling, that test fails before anyone's position silently drifts.

## Percent and Location must describe the same place (v1.41.0)

`ProgressPercent` and `Location` travel in the same `CurrentBookmark`, and
**the device obeys the Location.** If they disagree, the Kobo jumps to the
Location, recomputes its own percentage from there, and PUTs that *lower*
number back — where `apply_reading_state` rejects it as a regression. Server
and device then disagree forever, and each re-sync re-sends the same stale
position. It looks like "sync does nothing"; it is actually working exactly as
told.

- *The original bug:* the browser reader advances `read_progress` but has no
  span to offer, and `apply_reading_state` only wrote a location `if location:`
  — so a location from an earlier Kobo session survived while the percentage
  moved on. Live example: `ProgressPercent: 60.0` shipped alongside
  `Source: OEBPS/chapter020.xhtml`, a document that starts at **26 %**.
- **Fix, two halves:**
  1. `reader.py:update_progress` passes `clear_location=True` — a caller that
     moves the percentage in a foreign coordinate system must drop the stored
     position. It is an **explicit flag**, not "clear when location is falsy":
     a Kobo PUT legitimately arrives without a Location and must not wipe the
     exact span it sent earlier (that would undo v1.28.2).
  2. `_faithful_location()` cross-checks a stored location against
     `read_progress` via `services/kobo_location.py:percent_for_source()`. More
     than `LOCATION_CONSISTENCY_TOLERANCE` (5 pp) apart → derive a fresh one
     from the percentage with `location_for_percent()`. This **self-heals rows
     already written**, so no migration was needed.
- `services/kobo_location.py` weights each spine document by its
  **uncompressed** size (hence `zipfile`, not ebooklib — `ZipInfo` carries the
  byte counts) and returns `{Source: <spine doc>, Type: KoboSpan, Value: kobo.1.1}`.
  `Source` is the OPF's directory joined with the manifest href
  (`OEBPS/chapter061.xhtml`) — verified against what a real device stores.
  Resolution is chapter-level; that is all a percentage can carry.
- The consistency test is **containment, not distance**: does the percentage
  fall inside the document the location names (`range_for_source`, ±2 pp slack)?
  A bookmark sits *within* its document, so reading through a long chapter moves
  the percentage far past that chapter's start while the location stays valid.
  Comparing against the start alone would rewind the reader to the chapter
  boundary on every sync — worse the fewer chapters a book has.
- This is **not** the fabricated-Source mistake of v1.28.2. That one invented
  `Source = book_uuid`, which resolves to no document at all. A derived Source
  is a real entry from the book's own spine. When the spine can't be read we
  still fall back to `Location: null`.

## Re-download vs progress-only (don't reset the device)

`app/services/kobo_sync.py:compute_delta` ships an already-seen item as:

- **`ChangedEntitlement`** (carries `DownloadUrls` → the device archives and
  **re-downloads** the file, resetting position) when content changed, i.e.
  `content_updated_at > the device's sync token`; or
- **`ChangedReadingState`** (progress only, no re-download) otherwise.

`content_updated_at` is bumped **only** when a device-visible *content* column
changes (title/author/file_path/cover/… — see
`app/models.py:_DEVICE_CONTENT_COLUMNS`). Reading-progress writes must **never**
bump it (they touch `updated_at` only). Invariant:
`content_updated_at <= updated_at`. Breaking this re-downloads books on every
page turn.

## Book identity

- `book_uuid = uuid5(NAMESPACE, "book-{item.id}")` — deterministic, **version 5**.
  Reversed by `app/routes/kobo.py:_find_item_by_uuid` (scans EPUB items).
- **Sideloaded / Kobo-store books carry a foreign version-4 (random) UUID** that
  Colophon never minted → `_find_item_by_uuid` returns `None` → the state PUT is
  silently acknowledged (`200 {}`) and **dropped**. Reading state for such books
  can **never** sync — *by design, not a bug*. To sync, the book must be
  delivered to the device **by Colophon** (so the device holds the v5 UUID).
- The unknown-UUID branch now logs a `WARNING` (v1.41.0). It used to be silent,
  and the failure is **invisible on the device too**: a withdrawn entitlement
  gets `___UserID = 'removed'` in `KoboReader.sqlite` and disappears from the
  library, while still holding the reading history it accumulated. Seen in the
  wild: ~4 h of Kobo reading recorded on a hidden row whose v4 UUID Colophon had
  never minted, so not one page of it ever synced — with no second book visible
  to hint at what was happening. Grep for `unknown book UUID` when a book
  "won't sync", and check `SELECT ___UserID … WHERE Title LIKE …` on the device.

## Symptom → cause (fast triage)

| Symptom | Cause |
|---|---|
| Book resets to ~1% on **every sync**, but **holds offline** | Location round-trip / fabricated `Source`. Check `read_location_json` has the real chapter `Source`. *(Fixed v1.28.2.)* |
| Progress jumps **backwards** / a quick peek wipes a real position | Equal-status resolution. Should be furthest-read-wins. *(Fixed v1.28.1.)* |
| A book read on the Kobo **never shows as Reading** in Colophon | Either (a) sideloaded → foreign v4 UUID, silently dropped (grep the log for a `state PUT` whose UUID doesn't resolve), or (b) the Kobo hasn't synced since you read it (state is device-local until sync). |
| A **finished** book the Kobo keeps re-reporting as Reading, logged `dropped (monotonic/older)` | Correct if you finished it — harmless. If you're genuinely re-reading, use the reset action to un-finish it. |
| The Kobo sits at a **lower percentage than Colophon** and re-syncing never fixes it; log shows repeated `dropped (monotonic/older)` | Two separate causes, both needed fixing. (1) Stale `read_location_json` paired with a newer `read_progress` — the device obeys the location and reports its percentage back, which furthest-read-wins rejects *(v1.41.0)*. (2) Even with a correct DTO, the device discards it while its own `LastModified` is newer than ours *(v1.41.1)*. Compare `GET …/state`'s `LastModified` against `DateLastRead` on the device. |
| A book **read on the Kobo** never reaches Colophon, and the device shows only one (correct-looking) copy | A second, **withdrawn** entitlement (`___UserID = 'removed'`, hidden from the library) is the one that recorded the reading, under a UUID Colophon never minted. Grep the log for `unknown book UUID`; confirm in `KoboReader.sqlite`; delete the hidden row. |
| A book "**re-downloads**" when you open it | Check `IsDownloaded` on the device first — a cloud entitlement that was never fetched downloads on first open. That is not a re-download and not a bug. A real re-download means `content_updated_at` moved (see above). |
| Colophon browser-reader progress doesn't set the **exact page** on the Kobo | Position syncs exactly since v1.42.0; the *page number* still differs by design, because a Kobo paginates for its own screen and font settings. |
| Position lands in the right chapter but the wrong sentence | The character bridge fell back. Check that a KEPUB exists for the item (`kobo_kepub.py` cache) and that `reader.js` posted `href`/`offset` — without them only percent travels. |

## Footgun

**Never run `pytest` inside the live `colophon` / `colophon2` container** — the
`kobo_sync` fixture DELETEs the `/data` DB. Run the suite in a venv with `.env`
path overrides instead.

## Fix history

- **v1.28.1** — furthest-read-wins (`reading_state.py`).
- **v1.28.2** — full Location round-trip (`read_location_json` column + both DTO
  sites + the PUT handler; reset clears it).
- **v1.41.0** — percent/Location consistency (`kobo_location.py`,
  `clear_location=True` from the browser reader, unknown-UUID `WARNING`).
- **v1.41.1** — re-assert `read_last_modified` on a dropped PUT (the device
  resolves by timestamp, we resolve by furthest-read); consistency test changed
  from distance-to-chapter-start to containment-in-chapter-range.
- **v1.42.0** — the character bridge: exact position both ways
  (`kobo_location.py:span_for_offset`/`offset_for_span`, `reader.js`).
