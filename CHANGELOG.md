# Changelog

Notable changes per release. Colophon follows [semantic versioning](https://semver.org/):
PATCH for fixes, MINOR for user-visible features and automatic migrations, MAJOR for
changes that need you to act. Releases before 1.41.0 are summarised from the git log —
see the [tags](https://github.com/cgillinger/colophon/tags) for the full history.

## [1.50.0] — 2026-08-10

### Added
- **See what your reader is actually carrying.** Plug a Kobo in over USB and
  Settings → Kobo now tells you how many books it holds and how many Colophon
  recognises. If the two disagree, it says why: entries left behind by an
  earlier library rebuild, which look like ordinary books on the reader but
  which Colophon can neither update nor remove.

  It also counts how many of those hold reading progress that never reached
  your library — the only part of the situation that costs you anything — and
  points at **Import reading state**, which matches by title and brings that
  progress across. The panel explains the one reliable way to clear the rest
  (a factory reset of the reader, which loses nothing because Colophon keeps
  every position).

  Read-only. Colophon never writes to your reader's database.

## [1.49.0] — 2026-08-10

### Fixed
- **The same books stopped being reported over and over.** Timestamps sent to
  the reader had their milliseconds hard-coded to zero, so Colophon echoed
  back a moment up to a second *older* than the one the reader had just sent.
  The reader read that as the server lagging behind, sent the same state
  again, Colophon declined it as not-newer, and the two never agreed. Visible
  in the log as the same book being dropped round after round.

### Added
- **The mass-delete guard can be unlocked from the settings page.** Colophon
  refuses to tell a reader that more than a fifth of its books are gone,
  because that is usually a fault rather than your intent — but until now the
  only way to say "yes, really" was a shell. There is a button for it, and it
  stays a one-time unlock.

## [1.48.0] — 2026-08-10

Six bugs found by comparing Colophon against its sibling project Bookstation,
after a reader there never finished downloading covers on a large library.

### Fixed
- **Colophon was writing broken values onto your reader.** Two entries in the
  configuration Colophon hands the device were malformed — copied long ago out
  of a rendered document, bringing its link markup with them. The reader
  stores that configuration itself, so the damage persisted on the hardware.
  Confirmed on a real device. Fixed values are written on the next sync.
- **Books could be skipped during a sync and never arrive.** Pages were sliced
  by position over a list ordered by last-changed time — but the reader reports
  reading progress *between* page fetches, which reorders that list. Whatever
  sat on a page boundary was passed over, permanently. The walk now keys on
  something that cannot move.
- **A reader that lost its place re-downloaded the whole library.** What to say
  about a book was derived from the sync token rather than from what had
  actually been delivered, so a device without a token was told every book had
  changed. Colophon now keeps a per-device record of what it shipped and in
  what state.
- **Covers were sent at full size.** The reader asks for a thumbnail and got
  the original — several megabytes each, one per book, on every sync. Measured
  on a real library: 187 MB down to 20 MB.
- **Every cover request scanned the whole library.** The reverse lookup from a
  cover id to a book walked every book and recomputed its identity, thousands
  of times over during one cover phase. It is an indexed lookup now.
- **A replaced cover never reached the reader.** The cover's address never
  changed, so the device had no reason to fetch the image again and showed its
  cached copy forever. The address now changes with the file.

### Added
- **Force full resync**, per device, in Settings → Kobo. Needed to push
  corrected covers to books a reader already holds — the protocol has no way
  to refresh a cover on its own.

### Known
- Withdrawing a book from a reader does not work, and never has. Colophon
  sends the withdrawal and the device ignores it. Documented in
  `docs/kobo-reading-state-sync.md`; a factory reset is the way to clear stale
  entries in the meantime.

## [1.47.0] — 2026-08-09

### Added
- **Put the selection sheet wherever you want it.** Drag it by the handle at
  its edge and it stays where you drop it — across books and across sessions,
  not just until you close it. **Reset position** hands it back to placing
  itself opposite your selection.

  The handle now does what a grab handle looks like it does; the up/down button
  remains for a one-tap flip and for anyone using a keyboard. A parked sheet is
  always kept far enough on screen to grab again, including after rotating a
  tablet or resizing a window.

## [1.46.2] — 2026-08-09

### Fixed
- **The move control is now something you can actually see.** 1.46.1 put it on
  the small grab handle at the sheet's edge — which is a decoration, not a
  button, and nobody found it. It is now a labelled button beside the close
  button, where a control on that sheet is expected to be. It names where it
  will send the sheet rather than where the sheet is: **Move up** when the sheet
  is at the bottom, **Move down** when it's at the top, with the icon following
  suit.

## [1.46.1] — 2026-08-09

### Fixed
- **The selection sheet no longer lands on the text you just selected.** It sat
  at the bottom of the screen always, so selecting anything low on the page
  covered the very passage you were trying to read or copy. It now opens at
  whichever end of the screen your selection *isn't* at. If that guess is ever
  wrong, the grab handle at the sheet's edge moves it to the other end — and
  that choice is forgotten when the sheet closes, so it can't fight your next
  selection somewhere else on the page. The settings sheet is unchanged; it is
  meant to cover the page.

## [1.46.0] — 2026-08-09

### Added
- **Copy text out of a book.** Select more than a single word in the reader and
  a sheet now shows the passage with two actions: **Copy**, and **Copy with
  source**, which adds the title and author so a quote arrives somewhere else
  already attributed. Single words get the same actions alongside the
  dictionary entry.

  Until now, selecting several words did nothing at all — the sheet only ever
  opened for one word, so a phrase left you reaching for the browser's own
  menu, which can copy the text but knows nothing about which book it came
  from.

  Works without an HTTPS connection: where the modern clipboard isn't
  available, it falls back to the older method rather than failing on exactly
  the plain-`http://` home setups most likely to be used.

## [1.45.0] — 2026-08-09

### Changed
- **USB import now works for people who run Colophon in Docker on the same
  machine they plug the reader into.** Detection used to rely purely on the
  system's mount table, which is enough when Colophon runs directly on your
  computer but not inside a container: mounting your media folder into a
  container shows up as a single entry, so a reader plugged in afterwards
  stayed invisible. Colophon now also looks for a Kobo in the usual media
  folders. The README says exactly what to add to `docker-compose.yml`, and is
  honest that a reader plugged into a *different* machine than the one running
  Colophon can't work at all — that is what wireless sync is for.
- New `COLOPHON_USB_MOUNT_ROOTS` for a non-standard mount location, or set it
  empty to switch USB detection off. If you never plug a reader in, nothing
  changes and nothing is shown; the panel only appears when a Kobo is found.

## [1.44.0] — 2026-08-09

### Added
- **Import reading state from a Kobo over USB.** A reader that has been off
  Wi-Fi for weeks still knows what you read on it, and now you can plug it in
  and take that back — including the **exact position**, not just a percentage,
  because the Kobo's own bookmark turns out to be in the same form Colophon
  stores. Connected devices appear on the Kobo settings page.

  It never writes to the reader, and it reads the device's database from a
  private copy rather than in place: a Kobo unplugged mid-write leaves the
  database in a state that looks corrupt unless its journal is copied along
  with it. A genuinely damaged database is salvaged page by page rather than
  abandoned, and the receipt says so instead of pretending the result is
  complete.

  Imports follow the same "furthest read wins" rule as wireless sync, so a
  device that is behind can never drag your progress backwards. Bookmarks left
  on the device by a bug fixed in 1.28.2 are recognised and ignored rather than
  imported back in.

### Groundwork
- Colophon now keeps a record of which books it has put on which device by USB,
  and wireless sync withholds those books from that device. This exists before
  any USB transfer feature does, deliberately: a Kobo cannot tell a
  copied-over file from a wirelessly-synced one, so sending a book both ways
  makes it appear twice. Building the transfer without the bookkeeping *is* the
  duplicate bug — the reason this is in place first.

## [1.43.0] — 2026-08-09

### Fixed
- **Renaming or moving a book file no longer loses it.** Colophon identified a
  book purely by where its file sat, so a file renamed or moved outside the app
  looked like a deletion followed by an unrelated new book. Your reading
  position, rating and read history went with the old entry, and a synced Kobo
  saw a different book — the old one stranded on the device holding progress
  Colophon could no longer reach. A scan now recognises a moved file and keeps
  the book intact. It only does so when the match is unambiguous, so a copy or
  an edited file is never mistaken for a move, and the Kobo isn't told anything
  changed (no re-download).
- **A book's identity no longer depends on its position in the database.** It
  used to be derived from the row's internal number, which changes whenever a
  book is removed and re-added for any reason — and to a Kobo, a changed
  identity is a different book. Every book now carries its own permanent
  identity. Existing books keep exactly the identity they already have on your
  device, so nothing re-downloads and no reading position moves.
- **Removing a Kobo now also forgets what it had been sent.** Otherwise the next
  device you paired could inherit the old one's history, so Colophon would think
  it had already received the whole library and send it nothing to download.
- Withdrawing a book from a device now quotes the identity it was actually given
  when it was sent, rather than recomputing one that may since have changed.

## [1.42.0] — 2026-08-09

### Added
- **Your reading position now moves between devices exactly.** Read a chapter in
  the browser, pick up the Kobo, sync — and it opens on the same sentence, not
  just the same chapter. The same in the other direction: a book you were
  reading on the Kobo opens in the browser where you left off.

  The two readers describe positions in incompatible ways (the Kobo uses
  markers inserted when a book is converted for it; the browser doesn't have
  them). But the conversion preserves the text itself character for character,
  so "how many characters into this chapter am I" means the same thing to both,
  and that is what now travels between them. Verified against a real 144-chapter
  book: every chapter's text matches exactly, all 16,825 markers.

  Where an exact position isn't available — a PDF, a book never sent to a Kobo —
  you still land on the nearest chapter, as before. Note that the *page number*
  will still differ between devices: a Kobo paginates for its own screen and
  font settings, so the page is a property of the device, not of the book.

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
