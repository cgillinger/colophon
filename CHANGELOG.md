# Changelog

Notable changes per release. Colophon follows [semantic versioning](https://semver.org/):
PATCH for fixes, MINOR for user-visible features and automatic migrations, MAJOR for
changes that need you to act. Releases before 1.41.0 are summarised from the git log —
see the [tags](https://github.com/cgillinger/colophon/tags) for the full history.

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
