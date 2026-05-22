# Kobo Sync for Colophon — Design Document

**Status:** Draft for review
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
Append a stage that downloads kepubify (single static Go binary, ~5 MB) into `/usr/local/bin/kepubify`. Versioned, no apt package needed.

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

**Strategy:** convert lazily, cache on disk.

```
/data/kobo-cache/<library_item_id>-<source_mtime>.kepub.epub
```

- On `/v1/books/<id>/file/epub`: if cache hit and source unchanged, stream cached file.
- Else: run `kepubify -o <tmp> <source>`, move into cache, stream.
- Cache eviction: simple LRU by file mtime, capped at e.g. 2 GB (configurable via `COLOPHON_KOBO_CACHE_MB`).
- If the source file is touched by Colophon's metadata writer (`ebook-meta`), the source mtime changes and the cache entry becomes stale automatically.

Failure modes: if kepubify exits non-zero (malformed EPUB), fall back to streaming the raw EPUB. Kobo accepts it, just with degraded position tracking.

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

## 8. Settings UI

New tab `Settings → Kobo Sync` in `settings_kobo.html`:

- Section 1: **Devices** — table of `KoboDevice` rows with name, last seen, total syncs, revoke button.
- Section 2: **Add device** — name field + "Generate". Modal shows the URL exactly once with copy button + QR code. Plaintext key never stored.
- Section 3: **Setup instructions** — collapsible block with the `.kobo/Kobo/Kobo eReader.conf` steps and a screenshot.
- Section 4: **Cache** — current kepub cache size, "Clear cache" button.

i18n via `_()` like everything else; add Swedish strings to `messages.po`.

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

### Phase 3 — State + polish (1–2 days)
- Reading-state GET/PUT (DB-only per §10 decision — no EPUB writeback).
- "% read" / "last read" columns in the bulk view.
- Multiple devices, revocation flow, cache management UI.
- Swedish translation strings.
- Tests: `test_kobo_sync.py` mocking a Kobo client through the full flow.

### Phase 4 — Nice to have
- "Sync to Kobo" per-book toggle.
- Per-device library filter (tags / series).
- Bulk view column showing per-device read state.

---

## 12. What this design explicitly does NOT cover

- The Kobo store features beyond sync (recommendations, purchases, browse) — handled by the catch-all proxy as a black box.
- DRM. Colophon doesn't store DRM'd files; we won't start now.
- Multi-user. Colophon is single-user per `CLAUDE.md`; devices belong to "the user".
- Other e-readers (Tolino, Pocketbook). The same code shape could be reused but is out of scope.
