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
  browser-read book has `read_location_json = NULL` and the Kobo keeps its own
  position.

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
- *Open follow-up:* there is no log line in the unknown-UUID branch, so this
  failure is invisible. A one-line `WARNING` there would make a sideloaded book
  diagnosable instead of a silent mystery.

## Symptom → cause (fast triage)

| Symptom | Cause |
|---|---|
| Book resets to ~1% on **every sync**, but **holds offline** | Location round-trip / fabricated `Source`. Check `read_location_json` has the real chapter `Source`. *(Fixed v1.28.2.)* |
| Progress jumps **backwards** / a quick peek wipes a real position | Equal-status resolution. Should be furthest-read-wins. *(Fixed v1.28.1.)* |
| A book read on the Kobo **never shows as Reading** in Colophon | Either (a) sideloaded → foreign v4 UUID, silently dropped (grep the log for a `state PUT` whose UUID doesn't resolve), or (b) the Kobo hasn't synced since you read it (state is device-local until sync). |
| A **finished** book the Kobo keeps re-reporting as Reading, logged `dropped (monotonic/older)` | Correct if you finished it — harmless. If you're genuinely re-reading, use the reset action to un-finish it. |
| Colophon browser-reader progress doesn't set the **exact page** on the Kobo | By design — only percent + status sync, not exact position (browser CFIs ≠ Kobo spans). |

## Footgun

**Never run `pytest` inside the live `colophon` / `colophon2` container** — the
`kobo_sync` fixture DELETEs the `/data` DB. Run the suite in a venv with `.env`
path overrides instead.

## Fix history

- **v1.28.1** — furthest-read-wins (`reading_state.py`).
- **v1.28.2** — full Location round-trip (`read_location_json` column + both DTO
  sites + the PUT handler; reset clears it).
