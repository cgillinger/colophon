# TODO — Colophon

Deferred ideas and planned work. Implemented items get removed (the code/git
history is the record).

## In-browser reader + offline (the reason the PWA exists)

**What:** An in-browser EPUB reader inside Colophon. The mobile-consumption need
this serves is today met by Kobo sync (read on the e-reader); a browser reader
would be "Kobo sync for any phone/tablet browser" — read a book offline on a
device that isn't a Kobo.

**Why the PWA scaffolding is already in place (v1.4.0):** installability
(`/manifest.json`) and a reliable update mechanism (version-tied cache,
`?v=<version>` on assets, "new version" reload prompt) are the reusable
foundation. They were added now because they're low-risk and the service worker
is conservative (network-first navigations — see `app/templates/sw.js`). Keep
them; don't re-litigate the PWA each time.

**What is NOT done (net-new when the reader lands):**
- Caching actual book content for offline. The current SW caches the app shell
  and versioned static assets only — NOT books. Offline reading needs an
  explicit "download for offline" flow writing to Cache Storage / IndexedDB,
  plus quota + eviction handling and a "downloaded books" UI.
- The reader UI itself (rendering EPUB, pagination, progress, theming).

**Where it would hook in:** new reader blueprint/route serving book content to
the browser; extend `app/templates/sw.js` to cache explicitly-downloaded books
(a separate cache from `colophon-v<version>`, NOT purged on version bump — book
data must survive app updates); a "download for offline" action in the book
modal. Reuse the existing Kobo download/kepub path (`kobo_kepub.py`,
`kobo_sync.py`) for serving file bytes.

**Scope:** large (multi-part feature). New user-visible feature → MINOR bump.

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
