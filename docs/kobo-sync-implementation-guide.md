# Implementing Kobo Wireless Sync in Your Own E-Book Server

**Audience:** Developers who want to add Kobo over-the-air sync to a Python/Flask-style ebook server. Assumes you already store EPUBs and basic metadata (title, author, series, cover) in a database.

**Goal of this document:** Save you several days of trial-and-error by laying out exactly what the Kobo protocol expects, which fields the device silently rejects, and the diagnostic loop that gets a stalled sync moving again. Written from the perspective of someone who debugged this on a Kobo Libra Color (firmware 4.45.23684) against a real library of 372 EPUBs.

**Companion document:** [`kobo-sync-design.md`](kobo-sync-design.md) covers the original architecture choices in Colophon (blueprints, data model, kepubify pipeline). This guide is the protocol-and-pitfalls reference.

---

## 1. What this does and why

A Kobo e-reader normally syncs only with Kobo's official store. Its `api_endpoint` config setting points at `storeapi.kobo.com`. Change that pointer to your own server and the Kobo will happily download books, sync reading position, and show titles+covers in its native library UI — assuming your server speaks the Kobo OneStore protocol.

**Who benefits.** Anyone running a self-hosted e-book library who owns a Kobo and wants real bookshelf-style sync rather than Calibre→USB sneakernet. Major prior art: [Komga](https://github.com/gotson/komga) (Kotlin/Spring, MIT), [Calibre-Web's Kobo integration](https://github.com/janeczku/calibre-web/pull/1100) (Python/Flask, GPLv3).

**Licensing note.** Komga is MIT-licensed and was our protocol reference. We translated rather than copied — DTOs rebuilt in Python from scratch — and added Komga's notice to `THIRD_PARTY_LICENSES.md`. Calibre-Web is GPL, so we never read its source: doing so would obligate the entire host project to GPL.

---

## 2. The protocol in one paragraph

The Kobo, after the user edits `Kobo eReader.conf` to point `api_endpoint` at your URL, will hit four endpoint families on your server during a sync: `/v1/affiliate` and `/v1/initialization` to bootstrap, `POST /v1/auth/device` once for a bearer token, `GET /v1/library/sync` for the catalogue, then on-demand `GET /v1/library/{id}/metadata`, `GET /v1/books/{id}/file/epub`, and `GET /v1/books/{id}/thumbnail/...` per book. Plus a long tail of UI-related endpoints (user profile, wishlist, recommendations) that you stub with empty `{}` responses. The sync response is a JSON array of "entitlement" objects, each with `BookEntitlement`, `BookMetadata`, and `ReadingState`. The Kobo stores those in its on-device SQLite and starts fetching files and covers lazily.

That's the whole shape. The rest is field-level details that the firmware checks more strictly than you'd expect.

---

## 3. Architecture overview

Five logical pieces. Pick names that fit your codebase.

```
ebook-server/
  routes/kobo.py              # Blueprint with all /kobo/<token>/v1/* handlers
  services/kobo_sync.py       # Delta computation, sync-token (de)serialisation
  services/kobo_auth.py       # Per-device API key generation, lookup, hashing
  services/kobo_kepub.py      # kepubify subprocess wrapper, on-disk cache
  templates/settings_kobo.html # UI for generating per-device URLs
```

**Per-device tokens.** Each Kobo that wants to sync gets its own URL with a unique key in the path: `http://your.server/kobo/abc123…/`. Store the key hashed (sha256, like a password) in a `kobo_devices` table; the plaintext shows once at generation, never again. This is what the user pastes into `api_endpoint`. A `@require_device` decorator on every route looks up the device by URL key and 401s anonymous traffic.

**Format support.** Sync only EPUBs (and any KEPUB you already have). Drop PDFs, AZW3, etc. — they don't work over the Kobo protocol.

**KEPUB conversion.** Kobos read EPUB but with annoying limitations (no exact reading position tracking, weird page breaks). KEPUB is Kobo's enhanced EPUB format. Run [kepubify](https://github.com/pgaskin/kepubify) as a subprocess at download time and cache the output on disk keyed by `(book_id, source_mtime)`. The catch-all download endpoint sniffs whether kepubify is available and rewrites `DownloadUrls[0].Format` accordingly (more below).

---

## 4. The endpoints, ordered by what the Kobo calls first

What follows is the actual call sequence in the order the device dispatches them, with one device's UA string for reference: `Kobo Touch 0390/4.45.23684` (the UA is misleading — same string is used on Libra Color, Sage, etc.).

### 4.1 `GET /kobo/<token>/v1/affiliate`

First request the device makes. Returns affiliate tracking data in the real store; in self-hosted setups, ignore the meaning and just return something non-error.

```python
@kobo_bp.route("/<token>/v1/affiliate")
@require_device
def affiliate(device):
    return jsonify({"Name": "Kobo"})
```

**Gotcha.** If you proxy this to the real `storeapi.kobo.com`, it answers 400 because your request isn't signed. The device then loops `affiliate → initialization → affiliate → initialization` forever and never progresses. Stub it locally.

### 4.2 `GET /kobo/<token>/v1/initialization`

The Kobo asks for a resource map of where every API endpoint lives. Returns roughly 180 key→URL pairs and feature flags, wrapped as `{"Resources": {...}}`.

**Critical realisation.** The Kobo does *not* actually use most of these URLs. It uses `api_endpoint` from its conf as the base for all `/v1/*` calls. The Resources map is there so the device knows which features to expose (audiobooks, subscriptions, wishlists) — feature flags matter more than URLs. **Mirror Komga's response key-for-key**, and override only:

- `image_host` → your server's public URL
- `image_url_template` → `{base}/kobo/{token}/v1/books/{ImageId}/thumbnail/{Width}/{Height}/false/image.jpg`
- `image_url_quality_template` → same with extra `/{Quality}/{IsGreyscale}/` segments
- Possibly `library_*` if you've got Komga-style endpoints

Leave everything else pointing at the real Kobo hosts (`storeapi.kobo.com`, `oauth.kobo.com`, `social.kobobooks.com:8443`, `discovery.kobobooks.com`, `ereaderfiles.kobo.com`). Don't try to be clever and reroute them — the device follows `api_endpoint`, so those URLs are decoration.

**Auth gate.** Komga returns 401 on this endpoint when no `Authorization: Bearer` header is present. We do the same, and it's worth doing:

```python
auth = request.headers.get("Authorization", "")
if not auth.startswith("Bearer "):
    return jsonify({"error": "unauthorized"}), 401
```

Without this, the Kobo skips `/v1/auth/device` and tries to use stale tokens from the previous setup.

**Response header.** Set `x-kobo-apitoken: e30=` (base64 of `{}`). Komga does, we do, the device likes it.

**Critical feature flags.** Match Komga's values exactly. The two that matter most:

```
use_one_store = "True"            # NOT "False" — controls a big behaviour branch
kobo_audiobooks_enabled = "True"
kobo_subscriptions_enabled = "True"
```

We had `use_one_store = "False"` and the device looped on initialization forever; flipping it was the unlock.

### 4.3 `POST /kobo/<token>/v1/auth/device`

Device handshake. Returns synthetic tokens — the device wants the shape, not the cryptography.

```python
@kobo_bp.route("/<token>/v1/auth/device", methods=["POST"])
@require_device
def auth_device(device):
    return jsonify({
        "AccessToken": "your-app-stub-access-token",
        "RefreshToken": "your-app-stub-refresh-token",
        "TokenType": "Bearer",
        "TrackingId": str(uuid.uuid4()),
        "UserKey": f"device-{device.id}",
    })
```

Same response shape for `/v1/auth/refresh`. The real auth was the path-based token; this is theatre to satisfy the firmware's flow.

### 4.4 `GET /kobo/<token>/v1/library/sync`

The big one. Returns a JSON **array** (not object) of entitlement wrappers — books on this device's shelf.

Headers in/out:

```
Request:
  Authorization: Bearer <whatever>
  x-kobo-synctoken: <opaque from previous response, or absent on first sync>

Response:
  Content-Type: application/json
  x-kobo-sync: continue   # or "done" on the last page
  x-kobo-synctoken: <opaque, your own format>
  x-kobo-apitoken: e30=   # base64("{}"), placeholder
```

The token format is **entirely your own** — the device treats it as opaque. Komga uses `"KOMGA." + base64(JSON)`. We use raw `base64(JSON)` with `{version, since, page}`. Whatever works for resumable delta sync on your end.

**Paginate at 100 entitlements.** Komga's `syncItemLimit` default. We tried 200 and it appeared to work, but 100 leaves more headroom for the device's processing batches.

**Wrapper structure — and the bug that ate a day.** Each entitlement in the array is wrapped exactly once:

```json
[
  {"NewEntitlement": {
    "BookEntitlement": {...},
    "BookMetadata": {...},
    "ReadingState": {...}
  }},
  {"ChangedEntitlement": {...}},
  {"DeletedEntitlement": {...}}
]
```

We initially wrote `{"NewEntitlement": {"NewEntitlement": {...}}}` — one too many levels of nesting. The device looked for `BookEntitlement` at the wrong depth and silently dropped 371 of 372 entries. One got through and we wasted hours wondering why the library showed exactly one book. **Test with a curl + jq early** to confirm shape.

### 4.5 `GET /kobo/<token>/v1/library/{id}/metadata`

Called per book when the device wants fresh metadata (e.g. before download). Returns `[BookMetadata]` — an array with one element, same DTO as inside the sync wrapper.

**Subtle:** the `{id}` here is whatever you put in the entitlement's `CrossRevisionId` / `Id` / `EntitlementId` / `RevisionId` fields. If you mint UUIDs from your raw DB primary key (we do), you need a reverse lookup. Komga uses the raw DB ID directly, no reverse lookup needed. Choose whichever fits your model.

### 4.6 `GET /kobo/<token>/v1/books/{id}/file/epub`

The actual book download. `{id}` here is the URL we put in `DownloadUrls[0].Url`. Convert to KEPUB on demand if kepubify is reachable, otherwise serve the raw EPUB.

```python
@kobo_bp.route("/<token>/v1/books/<int:book_id>/file/epub")
@require_device
def book_file(device, book_id):
    item = LibraryItem.query.get(book_id)
    if not item:
        abort(404)
    kepub_path = convert_epub_to_kepub(item.file_path, item.id)  # cached
    return send_file(kepub_path or item.file_path,
                     download_name=os.path.basename(item.file_path))
```

### 4.7 `GET /kobo/<token>/v1/books/{ImageId}/thumbnail/{Width}/{Height}/{IsGrey}/image.jpg`

Cover image. There are two route variants — one with quality, one without — register both. `ImageId` is whatever you put in `BookMetadata.CoverImageId`. Most servers don't actually resize; we just return the original JPEG and let the device scale. That's fine.

Note the URL template you advertise: the device may capitalise the IsGrey value as `False` (Python title-case bool) rather than `false` (JSON-lowercase). Treat it as an opaque string in your route signature, don't try to parse it.

### 4.8 Catch-all for everything else

The remaining ~50-100 endpoints the Kobo calls — `/v1/user/profile`, `/v1/user/loyalty/benefits`, `/v1/products/featured`, `/v1/products/{id}/nextread`, `/v1/analytics/event`, `/v1/products/books/series/{id}`, `/v1/user/wishlist`, etc. — all return empty `{}`.

Reading-state endpoints (`GET` / `PUT /v1/library/{id}/state`) used to live here too but should be handled properly — see §6.

```python
@kobo_bp.route("/<token>/<path:rest>", methods=["GET","POST","PUT","DELETE","PATCH"])
@require_device
def store_proxy(device, rest):
    logger.warning("Kobo store_proxy fallthrough: %s %s", request.method, rest)
    return jsonify({}), 200
```

**Do not proxy these to `storeapi.kobo.com`.** Your requests aren't signed, the real store answers 4xx, and the device interprets the 4xx as "my session is broken" and loops back to initialization. Empty 200s let the device move on.

**The WARNING log is your debugging gift to your future self.** When the device misbehaves you'll want to see which endpoints it tried that you didn't handle. Phase 2 might mean adding real implementations for some of these (especially `/v1/products/books/series/{id}` to enable series view, and `/v1/library/{id}/state` to persist reading position).

---

## 5. The `BookMetadata` DTO: every field matters

This is where the device gets picky. After mirroring Komga's response shape and getting all 372 entitlements delivered, we *still* saw the post-sync indexing take ~3 metadata-refetches per 2 minutes — about 4 hours to settle 372 books. The fix was here: several fields where wrong defaults trigger silent-skip or retry-storm on the device.

### Fields that need exact values

**`Description`** — must be at least one space. The Kobo silently refuses to write the row when this is `null` or `""`. Komga's source has the explicit comment `"if null or empty Kobo will not update it, force it to blank"`.

```python
description = (item.description or "").strip() or " "
```

**`DownloadUrls[0].Platform`** — must be `"Generic"`, not `"Android"`. The device's `/v1/library/sync` request has `DownloadUrlFilter=Generic,Android` and prefers `"Generic"`. We had `"Android"` and the device skipped the entry.

**`DownloadUrls[0].Format`** — `"KEPUB"` if kepubify is available, otherwise `"EPUB3"`. **Not `"EPUB"`**. Komga's logic:

```python
download_format = "KEPUB" if resolve_kepubify_path() else "EPUB3"
```

(They also have `EPUB3FL` for fixed-layout books — worth doing if you support comics/manga.)

**`PublicationDate`** — must be a real ISO 8601 datetime with timezone. We initially passed `item.published_date or created[:10]`. The `[:10]` gives you `"2026-05-23"` — a date, not a datetime. The device wants the full form:

```python
def normalise_pub_date(raw, fallback_iso):
    if not raw:
        return fallback_iso
    s = str(raw)
    if len(s) == 4:          # year only
        return f"{s}-01-01T00:00:00.000Z"
    if len(s) == 10:         # date only
        return f"{s}T00:00:00.000Z"
    return s
```

**`Language`** — ISO 639-1 two-letter form. Clamp it: `(item.language or "en")[:2]`. Komga does `language.take(2)`.

**`ReadingState`** — complete every nested field. We had `None` in several spots that should have been `0` or a real timestamp. Komga ships:

```python
reading_state = {
    "Created": created_iso,
    "CurrentBookmark": {
        "LastModified": now_iso,         # not null!
        "Location": None,
        "ProgressPercent": None,
        "ContentSourceProgressPercent": None,
    },
    "EntitlementId": book_id,
    "LastModified": now_iso,
    "PriorityTimestamp": now_iso,
    "StatusInfo": {
        "LastModified": now_iso,
        "Status": "ReadyToRead",
        "TimesStartedReading": 0,        # int 0, not null
    },
    "Statistics": {
        "LastModified": now_iso,
        "SpentReadingMinutes": 0,        # int 0, not null
        "RemainingTimeMinutes": 0,
    },
}
```

The missing `LastModified` and `TimesStartedReading` were enough to make the device queue retries.

### Fields you can pass through verbatim — with one trap

`Title`, `Contributors` (list of strings), `ContributorRoles` (list of `{Name, Role}` dicts), `Publisher.Name`, `Series.{Name, Id}`. These behave reasonably.

**Trap inside `Series`.** Komga's DTO declares `Number` as `String` and `NumberFloat` as `Float` — i.e. `"Number": "3", "NumberFloat": 3.0`. If you send both as float (`"Number": 3.0, "NumberFloat": 3.0`) the device type-rejects the entitlement and never proceeds to `/file/epub` after the metadata refresh. Symptom is identical to the URL-port bug — "Ladda ner" resets without a file request — so they can be hard to disentangle. Send `Number` as `str(series_index)`.

### Fields where reasonable defaults are fine

`Categories: ["00000000-0000-0000-0000-000000000001"]`, `Genre: "00000000-0000-0000-0000-000000000001"`, `CurrentDisplayPrice: {"CurrencyCode": "USD", "TotalAmount": 0}`, `IsEligibleForKoboLove: False`, `IsPreOrder: False`, `OriginCategory: "Imported"`, `Accessibility: "Full"`.

### Full reference

See `app/routes/kobo.py:_entitlement_dtos` in this repo. Every field has a comment if there's a quirk attached.

---

## 6. Reading state — the second sync direction

Everything in §4 and §5 is server-to-device: the Kobo asks for a catalogue, you ship one. Reading state is the other direction — the device tells you "I've read this book to 60%, last bookmark is here." Persisting it lets a wiped or second device pick up where the first one left off, and lets your library UI show progress next to each book.

### 6.1 Endpoint pair

Same URL, two methods:

```
GET  /kobo/<token>/v1/library/<book_uuid>/state    → device asks "what does the server say?"
PUT  /kobo/<token>/v1/library/<book_uuid>/state    → device says "this is my current state"
```

The `<book_uuid>` is the same UUID you put in `BookEntitlement.RevisionId` / `CrossRevisionId`. Reverse-lookup to your DB id the same way you did for `/v1/library/{id}/metadata`.

**Critical:** these endpoints must be registered before any catch-all route. In Flask, more specific routes win over `<path:rest>` regardless of registration order, but write a regression test for it anyway — a stale catch-all silently swallowing PUTs is one of those bugs that takes a real-device session to notice.

### 6.2 The PUT body shape — Kobo wraps it in an array

The Kobo Libra Color (firmware 4.45.23684) sends:

```json
{
  "ReadingStates": [
    {
      "EntitlementId": "12f45e84-b3a7-...",
      "LastModified": "2026-05-23T15:59:52Z",
      "StatusInfo": {
        "LastModified": "2026-05-23T15:59:52Z",
        "Status": "Reading"
      },
      "CurrentBookmark": {
        "LastModified": "2026-05-23T15:59:52Z",
        "ProgressPercent": 69,
        "ContentSourceProgressPercent": 80,
        "Location": {
          "Source": "OEBPS/Text/part0028.html",
          "Type": "KoboSpan",
          "Value": "kobo.157.8"
        }
      },
      "Statistics": {
        "LastModified": "2026-05-23T15:59:52Z",
        "SpentReadingMinutes": 15,
        "RemainingTimeMinutes": 286
      }
    }
  ]
}
```

The wrap in `ReadingStates: [ ... ]` is what tripped us up in production. We initially parsed the inner object directly — `payload.get("StatusInfo")` returned `None` on every PUT, the handler fell back to defaults, and the row stayed `ReadyToRead` even though the user was on page 800/1000. Komga unwraps the array; do the same:

```python
payload = request.get_json(silent=True) or {}
if isinstance(payload.get("ReadingStates"), list) and payload["ReadingStates"]:
    payload = payload["ReadingStates"][0]
# Now StatusInfo / CurrentBookmark / Statistics are at top level
```

Keep the flat-shape path as a fallback so a future firmware shift doesn't silently break parsing. Either: `if "ReadingStates" in payload: payload = payload["ReadingStates"][0]; else: payload stays as-is`.

**`ProgressPercent` vs `ContentSourceProgressPercent`.** ProgressPercent is the user-facing percent the Kobo shows (counts only readable content). ContentSourceProgressPercent includes covers/TOC/colophon. Persist `ProgressPercent` — that's what shows up next to the book in the library UI everywhere else.

**`Location.Value`.** Opaque kobospan / EPUB-CFI string. Store it as text, replay it back on GET. Don't try to parse or transform it.

### 6.3 The status field is monotonic

Three values: `ReadyToRead`, `Reading`, `Finished` (ranks 0, 1, 2). Apply this rule unconditionally on every PUT:

> Incoming status with rank < current row's status rank → drop the entire PUT, even if the timestamp is newer.

Reason: the device sometimes reports `Reading 30%` for books you've explicitly finished server-side ("Mark as read manually" in your UI). Without monotonic guarding, the device's local view silently overwrites yours every sync.

The same rule means promoting `ReadyToRead` → `Reading` or `Reading` → `Finished` always wins regardless of the existing timestamp, which is what you want for fresh reading sessions.

### 6.4 Last-write-wins for equal-rank PUTs

For PUTs where status matches the existing row (e.g. both `Reading`), use the incoming `LastModified` to decide. Reject if older or equal:

```python
RANK = {"ReadyToRead": 0, "Reading": 1, "Finished": 2}
if RANK[incoming_status] < RANK[item.status]:
    return jsonify({}), 200   # monotonic drop

if (RANK[incoming_status] == RANK[item.status]
    and item.read_last_modified
    and incoming_mod and incoming_mod <= item.read_last_modified):
    return jsonify({}), 200   # older timestamp loses
```

The Kobo retries the same state several times in a sync window — without this guard you get noisy log churn and a flapping `read_last_modified` column.

### 6.5 GET /state must return the saved DTO

When `GET /v1/library/<uuid>/state` falls through to your catch-all and returns `{}`, the device reads it as "server has no state for this book — I'll push mine." For books the device hasn't actively tracked, its local state is `ReadyToRead`. So the next PUT effectively wipes whatever you set server-side via your UI's "Mark as read manually" button.

Return the saved state in the same `ReadingStates`-array shape the device uses:

```python
@route("/v1/library/<book_uuid>/state", methods=["GET"])
def get_state(book_uuid):
    item = find_by_uuid(book_uuid)
    if item is None:
        return jsonify({}), 200
    return jsonify({"ReadingStates": [_build_state_dto(item)]})
```

`_build_state_dto` is the same shape you ship in the `ReadingState` block of each entitlement during `/library/sync`. Factor it out so both paths use one helper.

### 6.6 Sync direction summary

Server-originated changes (your "Mark as read manually" UI button):
1. UI updates the row: `status='Finished', progress=100, read_last_modified=now()`.
2. Bump `updated_at` on the book so the next `/library/sync` re-ships it.
3. Server response to `GET /state` now returns the new state.
4. Device's next sync gets the new state, accepts it (incoming rank ≥ current local rank).

Device-originated changes (page-turn / book close):
1. Device PUTs `{ReadingStates: [...]}`.
2. You unwrap, apply monotonic + last-write-wins.
3. Optionally set `read_started_at` on first `Reading`, `read_finished_at` on first `Finished`.
4. Your UI re-renders progress on next page load.

### 6.7 Diagnostic body-logging

When this breaks — and the first attempt usually does — server logs say "PUT 200" but nothing changed in the DB. The bug is almost always shape-related. Make this trivial to confirm:

```python
if logger.isEnabledFor(logging.DEBUG):
    logger.debug("Kobo state PUT body[:600]=%s",
                 request.get_data(as_text=True)[:600])
```

Flip the logger to DEBUG once, do one read on the device, grep the log. You'll see exactly what shape the firmware sends. The first time we did this, the wrap in `ReadingStates: [...]` was visible in one line and the fix was three lines of code.

### 6.8 Out of scope (and why)

- **Per-device `SpentReadingMinutes` aggregation.** The PUT body has it. Useful for "year in books" stats. Belongs in a separate `reading_sessions` table — it's denormalised per-device data, not library state.
- **EPUB writeback of position.** Some sync tools write the bookmark into the EPUB file itself for portability. We didn't — DB-only is simpler and the Kobo's own KEPUB tracking is what matters on-device.
- **Multi-device merge logic beyond LWW.** With one library row and last-write-wins, two devices reading the same book just race and the most recent PUT wins. Good enough for single-user setups. Multi-user needs proper CRDTs.

---

## 7. The device-side reality check

Even with all of the above right, you'll have issues that aren't your server's fault. Three to be aware of:

### Cached state from previous syncs

The Kobo stores entitlements in `/mnt/onboard/.kobo/KoboReader.sqlite`. If the user previously synced with Komga or another store, those entries persist. They'll show up alongside your fresh ones, with the *previous* server's UUIDs — which 404 against your server when the user clicks them.

Two solutions:

1. **Document the cleanup.** Tell the user to connect via USB and delete `KoboReader.sqlite`. Triggers an OOBE-style fresh start on next boot. Painful — they have to re-login to a Kobo account, re-edit `eReader.conf`. Don't do this lightly.

2. **Adopt the old IDs.** Read the old SQLite, map old UUIDs to your books by title+author, emit `ChangedEntitlement` with `IsRemoved: true` for the unmapped ones. We didn't build this; Phase 3 if you have many users with prior setups.

### The Host-header port-stripping bug

The Kobo Libra Color empirically sends `Host: 192.168.50.8` in HTTP requests even when `api_endpoint` is `http://192.168.50.8:5055`. The port disappears from the Host header. If your `/v1/initialization` handler does:

```python
base = request.host_url.rstrip("/")  # ← this!
```

…the resulting `image_host` and `image_url_template` come back as `http://192.168.50.8` without the port. The device writes those to its conf, then tries to fetch covers on port 80, where nothing listens. **Zero thumbnail requests will reach your server.**

The same bug bites you a second time in `/v1/library/sync` and `/v1/library/{id}/metadata`, which build the `DownloadUrls[0].Url` from `request.host_url`. The device follows that URL to port 80, the download silent-fails after a few seconds, and the Kobo UI shows "Ladda ner" reverting back to its pre-download state. No `/v1/books/<id>/file/epub` request ever reaches your server.

Fix: introduce a shared helper that prefers an environment variable for the public base URL, and call it from every endpoint that mints URLs the device will follow:

```python
def _public_base_url() -> str:
    explicit = os.environ.get("MYAPP_PUBLIC_URL", "").rstrip("/")
    return explicit or request.host_url.rstrip("/")
```

Then set `MYAPP_PUBLIC_URL=http://192.168.50.8:5055` in your deployment env (docker-compose, systemd, whatever). The env var wins, your URLs survive Kobo's Host mangling, **and you only need this in one place — the helper.**

### Sleep aggressively interrupts post-sync indexing

Kobos sleep after a couple of minutes idle, even on USB power. When the device wakes, it doesn't automatically resume background indexing. The user has to press "Sync now" again. If your delta logic is `since = max(updated_at)`, the next sync returns 0 entitlements (everything is already "newer than since" filtered out) and the device gets no signal to retry.

Komga handles this with a *SyncPoint* model: snapshot the library state at sync time, persist the snapshot ID in the sync token, mark books as "delivered" only when the device has acknowledged. We have a simpler hack: when our per-device tracking table is empty, force a full sync regardless of incoming token's `since`. Means clearing the tracking table is a "reset" mechanism. Works for one-user scenarios, doesn't scale to multi-user.

---

## 8. Diagnostic workflow

When sync misbehaves, here's the order to debug.

### Turn on access logging

You'll want a line per HTTP request including status code and User-Agent so you can distinguish Kobo traffic from anything else hitting the server. With Gunicorn:

```
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--access-logfile", "-",
     "--access-logformat",
     "%(h)s %(r)s %(s)s %(b)s %(L)ss \"%(a)s\"",
     "wsgi:app"]
```

The Kobo's IP shows up in `%(h)s`; you can grep for it.

### tcpdump for full request inspection

Access logs don't show request headers. When you need to see what the Kobo actually sends (Bearer token? Host header? Accept-Encoding?), `sudo tcpdump -i any -n host <kobo-ip> -A -s0`. The Host-header-port bug above was visible only via tcpdump.

### Curl Komga as a known-good reference

If you have access to a working Komga instance with the same Kobo, you can grab the Bearer the Kobo sends (from your tcpdump) and curl Komga's `/v1/initialization` with that token:

```bash
curl -s -H "Authorization: Bearer <bearer-from-tcpdump>" \
  http://komga.local:8080/kobo/<komga-token>/v1/initialization > /tmp/komga.json
curl -s -H "Authorization: Bearer dummy" \
  http://your.server/kobo/<your-token>/v1/initialization > /tmp/yours.json
diff /tmp/komga.json /tmp/yours.json
```

This is how we found `use_one_store = False` and the 50 missing keys. Worth doing day one.

### Watch the catch-all WARNINGs

Every endpoint the device calls that you don't handle goes through your catch-all, which logs. After a sync, scroll through and look for repeated calls — those are candidates for proper handlers in Phase 2.

### The loop signature

If your log shows `affiliate → initialization → affiliate → initialization` over and over with nothing in between, the device is bailing right after init. Causes, in order of likelihood:

1. You're returning `200 + valid JSON` but with a field the firmware can't parse. Check `use_one_store`, check that you have ~180 resource keys, check that `image_host` is reachable.
2. You're forwarding the catch-all to `storeapi.kobo.com` and getting 4xx back. Stop forwarding, return `{}`.
3. The device's cached Bearer token is invalid and `/v1/auth/device` is reachable but your handler 500s.

### The "library shows 1 of N books" signature

JSON structure is malformed. You're double-wrapping `NewEntitlement` or missing a required key in `BookEntitlement`. Pretty-print one entry and diff against Komga's.

### The "library shows N books but covers never load" signature

Either:

- Your `image_url_template` points at the wrong host/port — see the Host-header bug.
- Your thumbnail endpoint returns 404 for the IDs the device sends — check that `CoverImageId` matches what your route handler expects.

Test thumbnail endpoint in isolation: `curl -sI http://your.server/kobo/<token>/v1/books/<your-cover-id>/thumbnail/300/400/false/image.jpg`. Should be `200 image/jpeg`.

---

## 9. Setup UX for the end user

Once your endpoints work, the user-facing flow is:

1. Generate a unique URL in your app's settings UI. Display once, copy-to-clipboard.
2. User connects Kobo to a computer via USB.
3. User opens `.kobo/Kobo/Kobo eReader.conf` on the device in a text editor.
4. Under `[OneStoreServices]`, replace `api_endpoint=...` with your URL. **Also replace** `image_host=`, `image_url_template=`, `image_url_quality_template=` if present — otherwise stale values from a previous setup linger until the device re-fetches `/v1/initialization` (which sometimes doesn't happen until reboot).
5. Save, eject Kobo safely, wait for it to remount itself.
6. Settings → Sync now on the Kobo. Books appear.

Document the conf file path on the device clearly. We've had users edit the wrong file.

**Recovery for botched setups:** restoring `api_endpoint=https://storeapi.kobo.com` reverts everything. If they nuked `KoboReader.sqlite`, they're in OOBE land — make sure they have their Kobo account credentials.

---

## 10. What we explicitly didn't do (yet)

Honest scope list, so you can pick whether to implement these or live without them.

- **Real `/v1/products/books/series/{id}` responses.** The Kobo's series view depends on this. We return `{}` and the series UI is empty. To fix: return a SeriesDto with the full ordered list of books in the series.
- **Resumable sync via SyncPoint.** Our delta is "since `max(updated_at)` last sent". A snapshot model is cleaner.
- **Cover thumbnail resizing.** We send the original JPEG regardless of requested `{Width}/{Height}`. Larger libraries on slower WiFi might want PIL-based resize + cache.
- **Multi-format download.** Komga distinguishes KEPUB / EPUB3 / EPUB3FL. We just have KEPUB/EPUB3 based on whether kepubify is available.
- **OPDS bridge or KOReader bridge.** Different protocol entirely, but the same library backend can serve both.

---

## 11. A condensed list of every bug we hit (and the fix)

If you implement this from scratch, expect to hit some subset of these. None of them have obvious error messages; the Kobo just behaves weirdly or refuses to progress.

1. **`/v1/affiliate` proxied to real store → 400 → device loops.** Stub it locally with `{"Name": "Kobo"}`.
2. **Catch-all proxied to real store → 4xx → device loops.** Stub all unhandled endpoints with `200 + {}`.
3. **`use_one_store: "False"` in init → device bails silently after init.** Set to `"True"`.
4. **~50 resource keys missing from init response → device bails silently.** Mirror Komga's full key list.
5. **`Authorization: Bearer` not required on init → device skips `/v1/auth/device` → relies on stale tokens.** Return 401 if header absent.
6. **Double-wrapped entitlement DTO (`{"NewEntitlement": {"NewEntitlement": {...}}}`) → device drops 99% of entries.** Single nesting level: `{"NewEntitlement": {"BookEntitlement": ..., "BookMetadata": ..., "ReadingState": ...}}`.
7. **`library_metadata` looked up by integer PK but the device sends back UUIDs → 404 on every metadata refresh → downloads never start.** Reverse-lookup by UUID (or use raw IDs in DTOs to avoid the issue).
8. **Sync returns 0 after clearing tracking table because device's cached sync token still has a recent `since`.** Force full sync when tracking table is empty for the device.
9. **`Description: ""` → device silently skips the metadata update.** Coerce to `" "` (single space).
10. **`DownloadUrls[0].Platform: "Android"` → device's `Generic,Android` filter prefers Generic and skips ours.** Use `"Generic"`.
11. **`DownloadUrls[0].Format: "EPUB"` → invalid, downloads fail silently.** Use `"KEPUB"` (with kepubify) or `"EPUB3"` (without).
12. **`PublicationDate` as 4-char year or 10-char date → device rejects metadata write.** Pad to full ISO 8601 datetime.
13. **`ReadingState.Statistics.LastModified: null` and missing `TimesStartedReading` → device queues retries.** Send complete rows with real timestamps and `0` for unread counters.
14. **`SYNC_PAGE_SIZE = 200` → device processes batches slowly.** Lower to 100 (Komga's default).
15. **`image_host` derived from `request.host_url` → port stripped by Kobo's Host header → covers fetch from port 80 → silent fail.** Read public URL from environment variable, not request.
16. **Same Host-stripping bug bit again in `library_sync` and `library_metadata` → `DownloadUrls[0].Url` came out without the port → device never requests `/file/epub`, "Ladda ner" silently resets.** Factor the env-var-aware base URL into a single helper and call it from every endpoint that mints URLs.
17. **`Series.Number` as float (3.0) instead of string ("3") → Komga's KoboSeriesDto declares Number as String + NumberFloat as Float, the device type-rejects the float-as-Number.** Send `Number` as `str(series_index)`, keep `NumberFloat` as float.
18. **Reading-state PUT body parsed as flat `{StatusInfo, CurrentBookmark, ...}` → every field reads `None` because the device wraps it as `{ReadingStates: [{...}]}` → progress silently never updates server-side even though PUTs return 200.** Unwrap the array before reading fields. See §6.2.
19. **GET `/v1/library/{id}/state` falls through to catch-all and returns `{}` → device assumes server has no state → on next PUT it overwrites your server-set "Finished" with its local `ReadyToRead`.** Implement the GET handler to return the saved state DTO. See §6.5.
20. **Server returns `200 + {}` to state PUTs but DB stays at `ReadyToRead`. No errors anywhere — the access log shows 200, your handler's "saved status=X" log never fires because the parser bailed.** Debug-log the raw body (`request.get_data()[:600]`) once and you see the shape mismatch in one read. Keep the body log gated on DEBUG so it doesn't spam INFO once you're done.

---

## 12. Final notes for porting to your project

If you're building on Flask + SQLAlchemy this maps almost line-for-line. For other stacks:

- **Django:** swap the blueprint for a `urls.py` include + class-based views. Reading-state PUTs become DRF endpoints.
- **FastAPI:** route decorators get cleaner. Watch for the catch-all — FastAPI's path conversion expects different syntax than Flask's `<path:rest>`.
- **Express/Node:** route shapes translate fine. The cover-streaming endpoint may need explicit `res.setHeader('Content-Type', 'image/jpeg')` before piping.
- **Spring:** read Komga's source — that's the reference implementation. The `@RequestMapping("{*path}")` catch-all syntax is theirs.

**Per-device key generation.** Use 32-byte random bytes, hex-encoded → 64-char URL token. Store the sha256 hash. Display the plaintext URL once at creation and never again. Provide a revoke button that flips a flag rather than deleting (forensics).

**Don't expose this on the public internet.** Bearer tokens are stub strings, your endpoint trusts the URL path. Bind to LAN or put it behind a VPN.

**Set a Gunicorn timeout of 300s.** First sync of a large library can ship 600 KB+ of JSON per page; default 30s is tight if your DB query is slow.

**Test with `curl` before testing with a real Kobo.** Every iteration on a real device costs a USB reconnect, a conf edit, an eject, a sync, a stare at the screen. Build a small test harness:

```bash
TOKEN=<your-key>
HOST=http://your.server
curl -s -H "Authorization: Bearer dummy" $HOST/kobo/$TOKEN/v1/initialization | jq '.Resources | keys | length'
# should print ~180

curl -s -H "Authorization: Bearer dummy" $HOST/kobo/$TOKEN/v1/library/sync?Filter=ALL | jq '. | length'
# should print up to your page size

curl -s -H "Authorization: Bearer dummy" $HOST/kobo/$TOKEN/v1/library/sync?Filter=ALL | \
  jq '.[0].NewEntitlement.BookMetadata | {Description,Platform:.DownloadUrls[0].Platform,Format:.DownloadUrls[0].Format,PubDate:.PublicationDate}'
# spot-check critical fields
```

This catches structure bugs without burning a real-device round trip.

---

## 13. Credits

- [gotson/komga](https://github.com/gotson/komga) — protocol reference implementation, MIT-licensed. Read their `KoboController.kt`, `KoboDtoDao.kt`, and `KoboDtos.kt` directly. The values they ship in `nativeKoboResources` are gold.
- [pgaskin/kepubify](https://github.com/pgaskin/kepubify) — the only tool for clean EPUB→KEPUB conversion. Single static binary, MIT.
- Kobo firmware engineers at Rakuten, who built a protocol that is just barely lenient enough that this kind of impersonation is possible. The fact that it doesn't require certificate pinning is the only reason any of this works.

If you ship this and write your own war-story document, link it here and we'll cross-reference.
