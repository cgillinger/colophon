# TODO — Colophon

Deferred ideas and planned work. Implemented items get removed (the code/git
history is the record).

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
