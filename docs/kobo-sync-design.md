# Kobo Sync for Colophon — Design Document

**Status:** Phase 1 + Phase 2 implemented; Phase 3 pending
**Author:** Initial draft generated 2026-05-22
**Goal:** Let a Kobo e-reader sync EPUB books wirelessly from Colophon as if Colophon were the Kobo store.

---

## 1. Background

Komga (Kotlin/Spring) ships a Kobo-compatible sync endpoint. A Kobo device whose `api_endpoint` config has been pointed at a Komga URL believes it is talking to Kobo's store and happily downloads, lists, and tracks reading position for books served by Komga.

We want the same capability in Colophon, in Python/Flask, reusing the existing `LibraryItem` model.

### Prior art and licensing

| Project | Lang | License | Usable as reference? | Usable as source? |
|---|---|---|---|---|
| [Komga](https://github.com/gotson/komga) | Kotlin | **MIT** | Yes | Yes (with attribution) |
| [Calibre-Web PR #1100](https://github.com/janeczku/calibre-web/pull/1100) | Python/Flask | **GPLv3** | Yes (read) | **No** — would GPL-infect Colophon |
| [kobink](https://github.com/potatoeggy/kobink) | Python | check before use | TBD | TBD |
| [kepubify](https://github.com/pgaskin/kepubify) | Go CLI | **MIT** | Yes | Yes (binary in Docker) |

**Plan:** Use Komga as the architectural and protocol reference. Translate (don't copy) the DTOs and controller logic to Python. Add Komga's MIT notice to `THIRD_PARTY_LICENSES.md`. Calibre-Web is read-only — useful to confirm protocol details but no code lifted.

---

## 2. User-facing flow

### One-time setup per device
1. User opens Colophon → Settings → **Kobo Sync** (new tab).
2. Clicks **"Generate API key for new device"**, optionally names it ("My Libra 2").
3. Colophon shows a URL like `http://192.168.50.8:5055/kobo/ab12cd34ef56…` and a short setup guide.
4. User connects Kobo via USB, edits `.kobo/Kobo/Kobo eReader.conf`, replaces the `api_endpoint=` line under `[OneStoreServices]` with that URL, ejects.
5. On the Kobo, Settings → Sync. New books appear in the library.

### Ongoing
- Each scan / metadata update in Colophon bumps a per-book `last_modified` timestamp.
- Next time the Kobo syncs, only changed items appear in the delta response.
- Reading position written from the Kobo lands back in `LibraryItem` and is visible in the bulk view.

### Revoking
- Settings → Kobo Sync → trash icon next to a device. The API key is invalidated; the Kobo silently fails to sync until reconfigured.

---

## 3. Architecture

### New files

```
app/
  routes/
    kobo.py                  # New blueprint kobo_bp — all /kobo/<token>/... endpoints
  services/
    kobo_sync.py             # Delta computation, sync-token (de)serialization
    kobo_kepub.py            # kepubify subprocess wrapper, on-disk cache
    kobo_auth.py             # API-key creation, lookup, hashing
  templates/
    settings_kobo.html       # Device management UI
  models.py                  # +KoboDevice, +KoboBookState (see §4)
tools/
  install_kepubify.sh        # Dockerfile build step — fetch kepubify binary
docs/
  kobo-sync-design.md        # This document
```

### Blueprint registration
Register `kobo_bp` in `app/__init__.py` next to the existing three. URL prefix is `/kobo` so the existing routes stay untouched.

### Dockerfile additions
Append a stage that downloads kepubify (single static Go binary, ~5 MB) into `/usr/local/bin/kepubify`. Versioned, no apt package needed. See §13 for the native-install equivalent.

### Gunicorn implications
The `/library/sync` response can be large on first sync (every EPUB in the library). The 300 s timeout is fine; the response is a single JSON array, not streamed. For now we accept the blocking write — if it ever becomes a problem we can switch to SSE-style chunked JSON like the scan endpoint does.

---

## 4. Data model

Two new tables. No changes to `library_items` schema; reading-state lives in a side table so we don't churn the main model and so multi-device state stays separable.

```python
class KoboDevice(db.Model):
    __tablename__ = "kobo_devices"
    id              = Column(Integer, primary_key=True)
    name            = Column(String, nullable=False)         # user label
    api_key_hash    = Column(String, nullable=False, unique=True, index=True)
    api_key_prefix  = Column(String, nullable=False)         # first 8 chars, for UI display
    created_at      = Column(DateTime, default=utcnow)
    last_seen_at    = Column(DateTime, nullable=True)
    last_sync_at    = Column(DateTime, nullable=True)
    revoked         = Column(Boolean, default=False)

class KoboBookState(db.Model):
    __tablename__ = "kobo_book_states"
    id                   = Column(Integer, primary_key=True)
    device_id            = Column(Integer, ForeignKey("kobo_devices.id"), index=True)
    library_item_id      = Column(Integer, ForeignKey("library_items.id"), index=True)
    status               = Column(String)        # ReadyToRead / Reading / Finished
    current_bookmark     = Column(JSON)          # opaque-to-us Kobo bookmark blob
    statistics           = Column(JSON)          # spent reading time, words, etc.
    last_modified        = Column(DateTime)
    __table_args__ = (UniqueConstraint("device_id", "library_item_id"),)
```

Migration goes in `app/services/database.py` next to the existing `ensure_*_table()` functions.

### What we sync (filter on `LibraryItem`)
- Format must be EPUB (we convert to KEPUB on the fly; MOBI/AZW3 are skipped — Kobo can't read them via this protocol).
- Group dedup: if a group has both EPUB and other formats, only the EPUB is exposed.
- `archived` items skipped (if that flag exists — confirm).

---

## 5. Endpoint catalog

All paths prefixed with `/kobo/<auth_token>`. Auth = lookup `KoboDevice` by `sha256(auth_token)` → 401 if missing/revoked.

| Method | Path | Purpose | Priority |
|---|---|---|---|
| GET | `/ping` | Healthcheck the Kobo hits first | P0 |
| GET | `/v1/initialization` | Returns map of resource URLs the device should use | P0 |
| POST | `/v1/auth/device` | Device handshake; we return a static OK | P0 |
| GET | `/v1/library/sync` | **Delta sync.** Returns new/changed/deleted entitlements since `x-kobo-synctoken` | P0 |
| GET | `/v1/library/<id>/metadata` | Fresh download URL for one book | P0 |
| GET | `/v1/books/<id>/file/epub` | KEPUB stream (kepubify on demand) | P0 |
| GET | `/v1/books/<id>/thumbnail/<w>/<h>/<grey>/image.jpg` | Cover thumbnail | P0 |
| GET | `/v1/library/<id>/state` | Read reading state | P1 |
| PUT | `/v1/library/<id>/state` | Write reading state from device | P1 |
| ANY | `/{*path}` | **Catch-all proxy to `https://storeapi.kobo.com`** so non-sync features (store browse, dictionary) keep working | P1 |

`/v1/library/sync` response is a JSON array of typed wrappers, mirroring Komga's `SyncResultDto.kt`:

```json
[
  { "NewEntitlement":         { "NewEntitlement":         { "BookEntitlement": {...}, "BookMetadata": {...}, "ReadingState": {...} } } },
  { "ChangedEntitlement":     { "ChangedEntitlement":     { ... } } },
  { "ChangedProductMetadata": { "ChangedProductMetadata": { ... } } },
  { "ChangedReadingState":    { "ChangedReadingState":    { ... } } }
]
```

Exact DTO field names are copied verbatim from Komga (the Kobo client is brittle about casing). DTOs live in `kobo_sync.py` as plain dicts assembled from `LibraryItem`.

### Headers
- Response sets `x-kobo-synctoken` (see §7).
- Response sets `x-kobo-sync: continue` if the page is truncated (we paginate at e.g. 200 entitlements per call); device will call back.

---

## 6. EPUB → KEPUB conversion

KEPUB is EPUB with Kobo-specific span/markup that the reader needs for accurate reading-position tracking. `kepubify` does the conversion and is idempotent.

### Binary detection (Docker + native)

Same pattern Colophon uses for Calibre tools (`shutil.which("ebook-meta")`):

```python
KEPUBIFY_BIN = os.environ.get("COLOPHON_KEPUBIFY_BIN") or shutil.which("kepubify")
```

- Docker: binary installed at `/usr/local/bin/kepubify` by the Dockerfile, found via `which`.
- Native: user installs via brew / `go install` / GitHub release. As long as it's on `$PATH`, found via `which`. Custom locations supported via `COLOPHON_KEPUBIFY_BIN`.
- If not found: Settings → Kobo Sync shows a `✗ kepubify not installed` banner with install instructions. Sync continues to work, but `/v1/books/<id>/file/epub` falls back to streaming the raw EPUB (Kobo accepts it with degraded position tracking).

### Cache

**Strategy:** convert lazily, cache on disk.

```
<DATA_DIR>/kobo-cache/<library_item_id>-<source_mtime>.kepub.epub
```

Cache root resolves to `app.config["KOBO_CACHE_DIR"]`, defaulting to `os.path.join(DATA_DIR, "kobo-cache")` and overridable via `COLOPHON_KOBO_CACHE_DIR`. This makes Docker (where `DATA_DIR=/data`) and native installs (where `DATA_DIR` is wherever the user pointed it) both work without code branches.

- On `/v1/books/<id>/file/epub`: if cache hit and source unchanged, stream cached file.
- Else: run `kepubify -o <tmp> <source>`, move into cache, stream.
- Cache eviction: simple LRU by file mtime, capped at e.g. 2 GB (configurable via `COLOPHON_KOBO_CACHE_MB`).
- If the source file is touched by Colophon's metadata writer (`ebook-meta`), the source mtime changes and the cache entry becomes stale automatically.

Failure modes: if kepubify exits non-zero (malformed EPUB), fall back to streaming the raw EPUB.

---

## 7. The sync algorithm

### Sync token format
Komga uses an opaque-to-the-client token. We do the same. Internally it's JSON, base64-encoded:

```python
{ "v": 1, "since": "2026-05-22T10:14:33Z", "page": 0 }
```

- `since`: max `updated_at` we've already returned to this device.
- `page`: pagination cursor within a sync run, if response was truncated.

The Kobo treats it as a blob and echoes it back next time — we can change the format freely as long as we bump `v`.

### Delta computation
1. Decode incoming `x-kobo-synctoken` (or treat absence as `since=epoch` — first sync).
2. Query: `LibraryItem WHERE format='EPUB' AND updated_at > since ORDER BY updated_at LIMIT 200`.
3. For each item, classify:
   - Not present in `kobo_book_states` for this device → `NewEntitlement`.
   - Present and item is soft-deleted → `DeletedEntitlement`.
   - Present and metadata changed → `ChangedProductMetadata` (cheaper than `ChangedEntitlement`).
4. Append any `KoboBookState` rows whose `last_modified > since` as `ChangedReadingState` (covers cross-device propagation — books read on device A show progress on device B).
5. Emit new sync token = max `updated_at` seen.

### Implications for `LibraryItem`
We need a reliable `updated_at` column. **Confirm one exists**; if not, add it and stamp it from `apply_metadata_to_item()` and from the scanner.

---

## 8. UI / UX

Three surfaces in the existing UI are touched. No new top-level area.

### 8.1 Navigation — new topbar icon

Today's topbar (`bulk_metadata.html:2622` and mirrored in every settings page) has, from left to right:

```
[📊 Stats]  [EN | SV]  [🌙 theme]  [⚙ API settings]
```

`📊 Stats` links to `settings.ai_settings`, `⚙` links to `settings.api_settings`. Two settings areas, two icons. Same pattern for Kobo: add a third icon between Stats and the language switcher.

```
[📊 Stats]  [📱 Kobo]  [EN | SV]  [🌙]  [⚙]
```

- Icon: Tabler `ti-device-tablet` (or `ti-book-upload`).
- Tooltip: `_('Kobo sync')`.
- Links to `settings.kobo_settings` → `settings_kobo.html`.
- Must be added to every page that renders the topbar: `bulk_metadata.html`, `settings_api.html`, `settings_ai.html`, `settings_kobo.html`, plus any of the preview templates that include it.

### 8.2 New page — `settings_kobo.html`

Same visual language as `settings_api.html` (dark background, card sections, status pills). Sections top to bottom:

1. **Devices** — table of `KoboDevice` rows.
   Columns: name, key prefix (e.g. `ab12cd34…`), created, last seen, books synced, revoke (trash icon).
   Empty state: "No devices yet. Add one below to start syncing."

2. **Add device** — single input ("Device name", e.g. "Libra 2") and a `Generate` button.
   On submit: modal opens showing the full URL **exactly once**, with a copy-to-clipboard button and a QR code (for easier reading on a phone before connecting the Kobo). Modal headline: "Save this URL now — it will not be shown again." On close, the key is hashed and the plaintext is dropped.

3. **Setup guide** — collapsible (closed by default), titled `_('How do I connect my Kobo?')`. Inside: the 4-step instruction (USB-connect, open `.kobo/Kobo/Kobo eReader.conf`, replace `api_endpoint=` under `[OneStoreServices]` with the URL, eject + Sync). Include a small screenshot of the relevant config-file section.

4. **KEPUB cache** — shows current size, file count, and a `Clear cache` button. Caption: `_('KEPUB files are regenerated on demand. Clearing the cache is safe.')`.

### 8.3 Bulk view changes — `bulk_metadata.html`

Reading state lives where the user already looks at books, not in Settings. Two new optional columns surfaced via the existing column-toggle menu:

- **`Kobo: % read`** — 0–100 from the most recently updated `KoboBookState` row for this book across all devices. Empty if no device has touched the book.
- **`Kobo: last read`** — date stamp from same row.

Both columns **off by default** so existing users don't see clutter. Sortable like other columns.

No per-device breakdown in the table; for a single-user installation the "most recent device wins" rule is sufficient. A future per-book modal expansion could show per-device detail if needed.

### 8.4 Not in the UI

The Kobo sync protocol routes (`/kobo/<token>/...`) are invisible to the user. No menu entry, no link, no list of recent sync requests. The endpoints exist only for the Kobo device to call. If we want observability we add it to the existing logs, not to the UI.

### 8.5 i18n

All new strings wrap in `_()`. Add Swedish translations to `app/translations/sv/LC_MESSAGES/messages.po` and run the `pybabel` cycle from `CLAUDE.md` §i18n. Estimated ~25–30 new strings.

---

## 9. Security

- API keys are 256 bits, generated via `secrets.token_urlsafe(32)`, stored as `sha256(key)`. Plaintext shown to the user once.
- Key in URL path: not ideal but mandated by the Kobo's request pattern. Mitigate by requiring HTTPS on any externally-exposed deployment (local LAN is the assumed default per `CLAUDE.md`).
- Catch-all proxy (`§5`) must strip the auth token from the path before forwarding to `storeapi.kobo.com`. Otherwise we leak our key to Kobo.
- Rate-limit failed auths to slow brute force (Flask-Limiter, optional).

---

## 10. Decisions and open questions

### Decided
1. **UX model: Komga-style "Library", not fake Store.** Every EPUB in Colophon appears in the Kobo's **Library** tab as a pre-owned book (cover, title, author, series). User taps to download and read. This is what the user wants and matches what Komga does. We do **not** attempt to simulate the Kobo Store browse experience — that would require reverse-engineering a separate undocumented API surface for no UX win.
2. **Reading position: DB-only, no EPUB writeback.** Bookmark blobs from the Kobo are stored in `KoboBookState` per device. Bulk view will surface "% read" and "last read". The EPUB file is never touched. (If multi-reader interop is ever needed, revisit.)
3. **Store proxy: in MVP, not deferred.** ~40 lines of Python. Without it the Kobo shows "cannot connect" errors in non-sync UI areas and some background features (dictionary, recommendations) misbehave. Catch-all route forwards anything we don't handle to `https://storeapi.kobo.com`, stripping our auth token from the path first.
4. **`updated_at` on `LibraryItem`: already present** with `onupdate=datetime.utcnow`. No migration needed for sync token logic.

### Still open
5. **Multi-format groups.** If a `group_key` contains EPUB + MOBI, we expose only the EPUB. If the user later deletes the EPUB but keeps the MOBI, the Kobo will see a `DeletedEntitlement`. Assumed fine — flag if not.
6. **Library subset.** Phase 1 sends every EPUB. A per-book or per-tag "Sync to Kobo" toggle is listed in Phase 4. Confirm Phase 1 default is correct.
7. **Series & collections.** Kobo supports series metadata in the sync response. Colophon already extracts series — populate the `Series` field in the entitlement DTO from day 1.

---

## 11. Implementation phases

### Phase 1 — Proof of life (1–2 days)
- Blueprint + `KoboDevice` table + settings UI for key generation.
- `/ping`, `/v1/initialization`, `/v1/auth/device` — hardcoded responses.
- `/v1/library/sync` returns **one** hardcoded entitlement pointing at a known test EPUB.
- `/v1/books/<id>/file/epub` streams the raw EPUB (no kepubify yet).
- **Catch-all proxy to `storeapi.kobo.com`** — included in P1 per §10 decision so the Kobo's non-sync UI behaves from the start.
- Verify on a real Kobo: book appears in Library tab, downloads, opens; store browse still works.

### Phase 2 — Real sync (2–3 days)
- `KoboBookState` table + migration.
- Full delta computation against `LibraryItem`, including sync token.
- Cover thumbnail endpoint reusing existing cover assets.
- Series metadata populated in entitlement DTO.
- Pagination.
- kepubify integration + disk cache.

### Phase 3 — Reading state sync (3–4 hours)

**Goal:** When the Kobo PUTs `/v1/library/<uuid>/state` (which it does
every page-turn), persist the progress so it survives sleep, multi-
device setups, and shows up in Colophon's UI. A second Kobo
connected later picks up where the first one left off.

#### Design decisions

**Progress is library-state, not device-state.** Reading state lives
on `LibraryItem`, not on `(device, item)`. Per-device tracking in
`kobo_book_states` stays — that's "have we sent this book to this
device?" — but the actual progress moves up to the book row.

**Why:** lets a new Kobo inherit progress at first sync without any
merge logic, lets a "Mark as read manually" button in the UI affect
every device automatically, and matches how Komga/Kindle/Audible all
handle multi-device reading. The cost is per-device "I last read on
device X" data is collapsed — we keep `last_modified` but lose
fidelity on "who finished what". That's an acceptable trade for a
single-user home setup.

**Last-write-wins with monotonic status.** When the canonical row is
`Reading 60%` and an incoming PUT says `Reading 40%`, the older
timestamp loses and we ignore. When canonical is `Finished` and
incoming says `Reading 30%`, we treat that as a downgrade and
**ignore regardless of timestamp** — finished books stay finished.
Status rank: `ReadyToRead=0 < Reading=1 < Finished=2`. Only equal-or-
higher ranks can win.

**Location strings round-trip untouched.** The Kobo's
`CurrentBookmark.Location.Value` is an opaque kobospan / EPUB-CFI
string. We store it as text and play it back on next sync.

#### Schema changes

Add columns to `LibraryItem`:

```python
read_status         = Column(String, default="ReadyToRead", nullable=False)
                    # ReadyToRead | Reading | Finished
read_progress       = Column(Float, nullable=True)   # 0.0–100.0
read_location       = Column(Text, nullable=True)    # opaque
read_last_modified  = Column(DateTime, nullable=True)
read_started_at     = Column(DateTime, nullable=True)
read_finished_at    = Column(DateTime, nullable=True)
times_started       = Column(Integer, default=0, nullable=False)
```

Migration ensures defaults for existing rows (`read_status='ReadyToRead'`,
`times_started=0`). Wire it into `app/services/database.py`'s
`ensure_*_table` helpers.

#### Backend work

**1. Replace catch-all stub for state PUTs with a real handler.**

```python
@kobo_bp.route("/<token>/v1/library/<book_id>/state", methods=["PUT"])
@require_device
def update_reading_state(device, book_id):
    item = _find_item_by_uuid(book_id)
    if item is None:
        return jsonify({}), 200   # ack and drop (might be from a
                                  # previous server, not our book)

    payload         = request.get_json(silent=True) or {}
    status_info     = payload.get("StatusInfo") or {}
    bookmark        = payload.get("CurrentBookmark") or {}
    location        = bookmark.get("Location") or {}

    incoming_status = status_info.get("Status")
    incoming_mod    = _parse_iso(payload.get("LastModified") or
                                 status_info.get("LastModified"))

    # Monotonic status — finished books stay finished
    RANK = {"ReadyToRead": 0, "Reading": 1, "Finished": 2}
    if RANK.get(incoming_status, 0) < RANK.get(item.read_status, 0):
        return jsonify({}), 200

    # Last-write-wins on the timeline
    if item.read_last_modified and incoming_mod \
       and incoming_mod <= item.read_last_modified:
        return jsonify({}), 200

    item.read_status   = incoming_status or item.read_status
    item.read_progress = bookmark.get("ProgressPercent")
    item.read_location = location.get("Value")
    item.read_last_modified = incoming_mod
    if incoming_status == "Reading" and not item.read_started_at:
        item.read_started_at = incoming_mod
        item.times_started = (item.times_started or 0) + 1
    if incoming_status == "Finished" and not item.read_finished_at:
        item.read_finished_at = incoming_mod
    db.session.commit()

    return jsonify({}), 200
```

The route must be registered **before** the catch-all so it shadows
the stub. Add a `@kobo_bp.before_request` no-op test to confirm.

**2. Populate `ReadingState` block in `_entitlement_dtos` from the DB.**

Replace the current `None`/`0` defaults with values read from
`item.read_*`. Make sure `CurrentBookmark.Location` is shaped exactly
as `{"Value": <string>, "Type": "KoboSpan", "Source": <book_uuid>}`
when location is present, and `null` when absent (don't send an
empty dict — Komga sends null).

**3. Tests in `tests/test_kobo_sync.py`.**

- Empty library, PUT state on unknown UUID → 200, no DB row touched.
- Synced book, PUT `Reading 30%` → row updated.
- Existing `Reading 60%`, PUT `Reading 40%` with older timestamp → ignored.
- Existing `Finished`, PUT `Reading 30%` with newer timestamp → ignored (monotonic).
- Existing `ReadyToRead`, PUT `Reading 30%` → `read_started_at` set; PUT same again → `times_started` not double-counted.
- `_entitlement_dtos` for a `Reading 50%` book returns `StatusInfo.Status=Reading`, `CurrentBookmark.ProgressPercent=50`.

#### UI work — shelf view only

Per §8.3 of this doc, the bulk view has three modes: table, shelf,
series. We only add the indicator to shelf. Table stays curator-mode
clean.

**Shelf cover overlay** in `bulk_metadata.html`:

```html
{% if item.read_status != 'ReadyToRead' %}
<div class="cover-progress {{ 'finished' if item.read_status == 'Finished' }}">
    <div class="fill" style="width: {{ item.read_progress or 0 }}%"></div>
</div>
{% endif %}
{% if item.read_status == 'Finished' %}
<span class="cover-check" title="{{ _('Finished') }}">✓</span>
{% endif %}
```

CSS — bottom 3px bar, amber for Reading, green for Finished. Top-
right corner check badge for Finished. No animation, no transitions
(the JS list is large; cheap renders matter).

**Header filter tabs** — vy-agnostic, work in all three modes:

```
[All N] [Unread M1] [Reading M2] [Finished M3]
```

Implemented as URL query param `?status=reading`. Counts come from
the same query that builds the page. Tabs are persistent across
view switches (table↔shelf↔series). Indicator on cover only in
shelf mode.

**Book modal extension.** In the existing single-book modal:

- New "Reading state" section showing status, progress %, last_modified,
  started_at / finished_at when present, times_started.
- **"Mark as read manually"** button — sets `read_status='Finished'`,
  `read_progress=100`, `read_finished_at=utcnow()`. Triggers a Kobo
  re-sync on the next device sync because we bump
  `read_last_modified`, which advances `LibraryItem.updated_at` via a
  hook.
- **"Reset reading state"** button — clears everything back to
  `ReadyToRead`. Useful for stuck syncs or testing.

**Series view ("X/Y read")** — optional but cheap. On the series
header row, compute `len([b for b in series if b.read_status ==
'Finished']) / len(series)` and render as `"3/5 read"`. Doesn't
require any progress-bar work, just one aggregate per series.

#### i18n

New strings: "Finished", "Reading", "Unread", "All", "Mark as read
manually", "Reset reading state", "Reading state", "Started", "X/Y
read". Add to `messages.pot`, translate in `app/translations/sv/`.

#### Out of scope for Phase 3

- **Per-device reading-time aggregation** (`SpentReadingMinutes`).
  Kobon reports it but it's per-device. Aggregating belongs in a
  separate `kobo_reading_sessions` table when someone wants
  statistics.
- **Statistics export** ("year in books"). Separate endpoint, separate
  session.
- **Import from Calibre/Goodreads CSV.** Uses the same canonical
  columns but is a Settings-page feature, not part of sync.
- **EPUB writeback** of position. Per §10 decision — DB-only.

#### Verification

End-to-end test, by hand:

1. Mark a book as Finished in Colophon UI.
2. Trigger Sync on Kobo.
3. Confirm the book shows up as "Finished" / has a check badge on Kobo.
4. Start reading another book on Kobo to 30%.
5. Wait for `PUT /state` in the log.
6. Refresh Colophon — the book has a partial progress bar in shelf view.
7. Connect a second Kobo (or wipe and reconnect the first). Both
   states show up on the device at first sync.

### Phase 4 — Nice to have
- "Sync to Kobo" per-book toggle.
- Per-device library filter (tags / series).
- Bulk view column showing per-device read state.

---

## 12. Docker vs native install

Colophon supports both deployment modes today. Kobo sync follows the same conventions so neither is special-cased.

### Path resolution

All Kobo-sync paths derive from `app.config` values that already read env vars with Docker-friendly defaults:

| Concern | Config key | Env var | Docker default | Native install |
|---|---|---|---|---|
| Data root | `DATA_DIR` | `COLOPHON_DATA_DIR` | `/data` (existing) | User sets, e.g. `~/.local/share/colophon` |
| KEPUB cache | `KOBO_CACHE_DIR` | `COLOPHON_KOBO_CACHE_DIR` | `<DATA_DIR>/kobo-cache` | Same default; override if you want it elsewhere |
| Cache size cap | `KOBO_CACHE_MB` | `COLOPHON_KOBO_CACHE_MB` | `2048` | Same |
| kepubify binary | n/a (resolved at runtime) | `COLOPHON_KEPUBIFY_BIN` | `/usr/local/bin/kepubify` (installed by Dockerfile) | Whatever `which kepubify` finds |

No code path checks "am I in Docker?" — everything goes through these config values.

### kepubify installation

**Docker:** `tools/install_kepubify.sh` runs in the Dockerfile, downloads a pinned release from GitHub (we choose a version, e.g. `v4.5.1`), verifies the SHA-256, drops the binary in `/usr/local/bin/kepubify`.

**Native:** zero manual install. On first request that needs conversion, if no kepubify is on `$PATH` and `COLOPHON_KEPUBIFY_BIN` is unset, Colophon downloads a pinned release from GitHub into `<DATA_DIR>/bin/kepubify`, verifies the SHA-256, and caches it. Subsequent requests reuse the cached binary. The user does nothing.

Detection order at startup:
1. `COLOPHON_KEPUBIFY_BIN` if set → use it.
2. `shutil.which("kepubify")` → use system binary if user already has one (brew, distro package).
3. `<DATA_DIR>/bin/kepubify` if previously downloaded → use cached.
4. Else: trigger one-time download (logged, blocking the first KEPUB request by a few seconds), then use it.

If the download fails (offline install, blocked network), sync gracefully degrades to raw-EPUB streaming and the Kobo Sync settings page shows a banner with manual install hints. No GitHub repo hunting required for the default case.

The pinned version + per-platform SHA-256 checksums live in `app/services/kobo_kepub.py` as a constant. Bumping the version is a one-line change.

### Network binding

Kobo device talks HTTP to Colophon over the LAN. Both deployment modes already bind the same way (Gunicorn on `0.0.0.0:5055`) so no change needed. Reverse-proxy in front (Caddy, nginx) works for both; the catch-all proxy to `storeapi.kobo.com` requires outbound HTTPS, which both modes have by default.

### Where data persists

`KoboDevice` and `KoboBookState` rows live in the same SQLite DB as everything else (`<DATA_DIR>/colophon.db`). KEPUB cache files live in `<DATA_DIR>/kobo-cache/`. A native user who already backs up `DATA_DIR` automatically backs up the Kobo state — no separate concern.

---

## 13. What this design explicitly does NOT cover

- The Kobo store features beyond sync (recommendations, purchases, browse) — handled by the catch-all proxy as a black box.
- DRM. Colophon doesn't store DRM'd files; we won't start now.
- Multi-user. Colophon is single-user per `CLAUDE.md`; devices belong to "the user".
- Other e-readers (Tolino, Pocketbook). The same code shape could be reused but is out of scope.
