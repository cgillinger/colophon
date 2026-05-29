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
