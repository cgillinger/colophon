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
- The **in-browser reader never writes a location** (it resumes by percent via
  `goToFraction`). EPUB CFIs and Kobo KEPUB spans are different coordinate
  systems, so exact position only flows **Kobo → Colophon → Kobo**; a
  browser-read book has `read_location_json = NULL` and the Kobo gets a
  chapter derived from the percentage (next section).

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
  which is how a **duplicate** copy of a book — the same title present twice on
  a device, once under a foreign UUID — could sit there absorbing real reading
  time while none of it ever reached Colophon. Grep for
  `unknown book UUID` when a book "won't sync".

## Symptom → cause (fast triage)

| Symptom | Cause |
|---|---|
| Book resets to ~1% on **every sync**, but **holds offline** | Location round-trip / fabricated `Source`. Check `read_location_json` has the real chapter `Source`. *(Fixed v1.28.2.)* |
| Progress jumps **backwards** / a quick peek wipes a real position | Equal-status resolution. Should be furthest-read-wins. *(Fixed v1.28.1.)* |
| A book read on the Kobo **never shows as Reading** in Colophon | Either (a) sideloaded → foreign v4 UUID, silently dropped (grep the log for a `state PUT` whose UUID doesn't resolve), or (b) the Kobo hasn't synced since you read it (state is device-local until sync). |
| A **finished** book the Kobo keeps re-reporting as Reading, logged `dropped (monotonic/older)` | Correct if you finished it — harmless. If you're genuinely re-reading, use the reset action to un-finish it. |
| The Kobo sits at a **lower percentage than Colophon** and re-syncing never fixes it; log shows repeated `dropped (monotonic/older)` | Stale `read_location_json` paired with a newer `read_progress`. The device obeys the location and reports its percentage back, which furthest-read-wins rejects. *(Fixed v1.41.0.)* |
| A book **read on the Kobo** never reaches Colophon, and the same title appears **twice** on the device | One copy carries a foreign UUID Colophon never minted. Grep the log for `unknown book UUID`. Delete the duplicate on the device. |
| Colophon browser-reader progress doesn't set the **exact page** on the Kobo | By design — percent syncs exactly, position only to chapter granularity (browser CFIs ≠ Kobo spans). |

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
