# Changelog

Notable changes per release. Colophon follows [semantic versioning](https://semver.org/):
PATCH for fixes, MINOR for user-visible features and automatic migrations, MAJOR for
changes that need you to act. Releases before 1.41.0 are summarised from the git log —
see the [tags](https://github.com/cgillinger/colophon/tags) for the full history.

## [1.41.2] — 2026-08-09

### Fixed
- **An empty library folder could wipe the entire catalogue.** A scan removes
  books whose files it can't find, and the only check was that the library
  folder itself existed — not that there was anything in it. If the folder ever
  came up empty (a NAS not exported yet, a re-created Docker volume, a bind
  mount pointing somewhere new), every book was deleted along with its reading
  progress, and the next scan added them all back as *new* books, which a synced
  Kobo then treats as different titles. A scan that finds no books at all now
  refuses to delete anything and says so in the log. The upstream sync has had
  this guard since it was written; the scanner, which is far more destructive,
  did not.
- **A failing disk no longer looks like a deleted book.** A stale network mount,
  a disconnected share or a permissions error made a file look exactly as
  missing as a deleted one, and the book was removed. Only a file that is
  genuinely gone is now treated as gone; anything unreadable is kept and logged.
- **The Kobo mass-delete safeguard was a trap you couldn't get out of.** When it
  decided a deletion looked implausible it suppressed the signal but left its
  bookkeeping untouched, so every later sync reached the same conclusion and
  suppressed it again — permanently, with no way to say "yes, I really did
  remove those". There's now a one-shot override (`KOBO_ALLOW_MASS_DELETE`),
  spent as soon as it's used so it can't become a standing permission.

## [1.41.1] — 2026-08-09

### Fixed
- **The Kobo still ignored the corrected position.** 1.41.0 made Colophon send
  the right place, but the device kept discarding it. Colophon settles a
  disagreement by "whoever read furthest wins"; the Kobo settles it by "whoever
  saved most recently wins". So every time Colophon overrode the device, the
  device threw the correction away as older than its own copy — and its own got
  newer each time it reported, so neither side ever moved. Colophon now re-dates
  its position when it overrules a device, which makes the correction land. Your
  reading position itself is never changed by this; only the "last updated"
  stamp.
- A bookmark in a book with **few, long chapters** could get thrown away as
  stale. Colophon compared your progress against where the bookmarked chapter
  *began*, so reading deep into a long chapter looked like drift, and the next
  sync would rewind you to the chapter boundary. It now checks whether your
  progress falls anywhere inside that chapter.

## [1.41.0] — 2026-08-09

### Fixed
- **The Kobo could get stuck at a lower percentage than Colophon, and re-syncing
  never fixed it.** Reading progress and the Kobo bookmark are sent together, and
  the device obeys the *bookmark* — so when the two described different places in
  the book, the Kobo jumped back to the old position, recomputed a lower
  percentage from it, and sent that back, where the "furthest read wins" rule
  rejected it. The two drifted apart because reading in the browser moves the
  percentage but has no Kobo bookmark to offer (EPUB and Kobo use different
  coordinate systems), and the old bookmark was left behind. Colophon now drops
  the stale bookmark when you read in the browser, and cross-checks any stored
  bookmark against the percentage before sending it. Existing books repair
  themselves on the next sync — no migration needed.
- Kobo reading-state updates for a book UUID Colophon never issued are still
  ignored (they can't be matched to anything), but now log a warning instead of
  vanishing silently. Without it the failure is invisible from both ends: a
  withdrawn entitlement disappears from the Kobo's library while still recording
  everything you read on it, so the device looks normal and Colophon simply never
  hears about the reading.
- The "dropped" sync log line now records the progress values it compared, not
  just the read status, so it's clear *why* an update lost.

### Added
- After reading in the browser, the Kobo now opens at the chapter matching your
  progress instead of wherever it last was. Colophon derives the position from the
  book's own spine, weighted by chapter size (`app/services/kobo_location.py`).
  Chapter-level, which is as precise as a percentage can be.

## [1.40.0] — 2026-07-29
- Prebuilt Docker image on GHCR, auto-published on every push (amd64 + arm64).

## [1.39.x]
- Embedded series is read from EPUB files again (`1.39.6`).
- `rsync` ships in the image; upstream pull failures surface in the scan UI (`1.39.5`).
- "Missing author folder" filter and retroactive upstream cleanup (`1.39.0`).
- README and handbooks cover multi-author, author folders and the local/upstream split.

## [1.38.0]
- Author folders for uploaded books, plus upstream orphan cleanup.

## [1.36.0] — [1.37.0]
- Multi-author support: one registry entity per person, with a dismissable
  "looks like several people" badge.

## [1.31.0] — [1.35.0]
- In-browser reader gains PDF support, a scrub bar, snapback chip and in-reader restart.
- Dictionary word lookup with on-demand dictionary downloads.

## [1.28.1] — [1.28.2]
- Kobo reading-state sync: furthest-read-wins conflict resolution, and the full
  bookmark round-trip that stopped every sync resetting the device to the start.
