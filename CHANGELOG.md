# Changelog

What changed in each release, written for the person running Colophon.
Version numbers follow [semantic versioning](https://semver.org/): PATCH is a
fix, MINOR is a new feature or an automatic database update, MAJOR means you
have to change something yourself. Releases before 1.41.0 are summarised at
the end; the [tags](https://github.com/cgillinger/colophon/tags) have the full
history.

## What's new since 1.50

The one-size-fits-all batch job is gone. In its place are **scenarios**: jobs
for books that belong together, such as one series, one author's books, or
every book without a cover. Each scenario shows you a proposal first. You tick
the rows you want, and nothing is saved until you press Apply.

**Upgrading.** Run `docker compose pull && docker compose up -d`. The database
updates itself on first start. Your book files are not touched by the upgrade.
Two things to check:

- If your compose file sets `COLOPHON_SHOW_LEGACY_BATCH`, remove the line. It
  no longer does anything.
- If AI features stopped working, change the model before you suspect your
  quota. Mistral's free plan no longer includes the `mistral-*` models. Pick a
  `ministral-*` model under **Settings → AI**. New installs already use one.

### New features

| Feature | Where | Handbook | Since |
|---|---|---|---|
| **Order a series.** One AI call for the whole series, checked against Wikidata, reviewed row by row. | Series view → **Order the series** on a card | [§9d](docs/handbook-en.md#9d-ordering-a-series) | 1.53.0 |
| **Order an author's series.** Same review across everything one author wrote. The AI also decides which series exist. | Authors page → ⋯ menu → **Order series**, or the banner when you filter on an author | [§9e](docs/handbook-en.md#9e-ordering-an-authors-series) | 1.54.0 |
| **Fetch covers for a filter.** Searches every book without a cover, not just the visible page. | Click **N missing cover** → **Fetch covers for these** | [§9g](docs/handbook-en.md#9g-fetching-covers-for-a-whole-filter) | 1.60.0 |
| **See what's missing.** A colour dot per book, three counters that filter, and *Least complete first* in the sort menu. | Table view | [§9b](docs/handbook-en.md#9b-seeing-whats-missing) | 1.52.0 |
| **Check language.** Reads the text inside your EPUBs and lists the books whose recorded language is wrong or missing. | **Tools → Check language** | [§9c](docs/handbook-en.md#9c-checking-language) | 1.52.0 |
| **Rename a series.** No AI. Gives every book on the card the same name and keeps their numbers. | Series view → **Rename** on a card | [§9f](docs/handbook-en.md#9f-renaming-a-series) | 1.55.0 |
| **AI suggestions that know your library.** A proposed series that matches one you already have gets your spelling. | Anywhere the AI suggests metadata | [§7](docs/handbook-en.md#7-ai-features) | 1.51.0 |
| **The Authority column says who.** "British science fiction writer" instead of a Wikidata code, plus **Verify selected**. | Authors page | [§10](docs/handbook-en.md#10-managing-authors) | 1.57.0 |

### Fixes worth knowing about

- **Nothing is saved before you see it.** Bulk metadata fetching used to write
  confident matches into your files before showing the review list (1.51.1).
- **Authors could be linked to the wrong person** on Wikidata, with no way to
  undo it. Your own books now decide, and the link can be removed (1.58.0,
  1.59.0).
- **Swedish interface showed English** in the newer screens (1.55.0).
- **A brand-new installation could fail on first start** (1.61.1).

### Still to do

- **Aligning spellings that already differ.** The AI now converges on your
  spelling for new suggestions, but a series already spelled three ways in
  your library stays that way. A cleanup view is planned
  ([#173](https://github.com/cgillinger/colophon/issues/173)).
- **Bulk file moves** are deliberately left out. Use *Move to author folder*
  per book.

---

## [1.61.3] — 2026-09-16

### Changed
- **The README, the handbooks and this changelog were rewritten for
  readability.** Shorter sentences, less about how things work inside, more
  about what you see and what to do.
- The handbooks no longer say the browser reader resumes by percentage. Exact
  position sync between browser and Kobo has existed since 1.42.0.

## [1.61.2] — 2026-09-16

### Fixed
- **Closing the tab stops the language check.** It used to keep reading every
  remaining book for nobody.
- **A series number can no longer be saved without a series.** The review
  screen never offered it, but the server now refuses it too.
- **An unexpected AI answer no longer breaks the whole proposal.** A book the
  model describes in the wrong shape is skipped instead of failing the
  request.

## [1.61.1] — 2026-09-16

### Fixed
- **A brand-new installation could fail on first start.** Two parts of
  Colophon tried to create the database at the same time. It is now created
  once, in order. Existing installations were never affected.

## [1.61.0] — 2026-09-16

### Removed
- **The generic batch wizard is deleted.** It had been hidden since 1.51.0.
  Every job it did now has its own scenario (see 1.52.0 to 1.60.0).
- **`COLOPHON_SHOW_LEGACY_BATCH` no longer does anything.** Remove it from your
  compose file if you set it.

## [1.60.0] — 2026-09-16

### Added
- **Fetch covers for a whole filter** ([handbook §9g](docs/handbook-en.md#9g-fetching-covers-for-a-whole-filter)).
  Click the **N missing cover** count, then **Fetch covers for these**.
  Colophon searches every book in the filter and shows what it found. All
  results start ticked because these books have no cover to lose. Up to 100
  books per run.

### Fixed
- **A preview could move a cover between formats.** If you keep the same book
  as EPUB and MOBI, a cover could be copied from one to the other during a
  preview, before you applied anything. Previews no longer touch formats.
- **Applying a cover did not update the completeness dot.**

## [1.59.0] — 2026-09-16

### Fixed
- **Your own books decide who an author is.** When several people on Wikidata
  share a name, the one credited with a book you already have wins. If the
  name search finds nobody, Colophon searches on one of your titles instead
  and reads the author from there.

## [1.58.0] — 2026-09-16

### Added
- **Remove authority link**, in the author row's ⋯ menu. The entry becomes
  *confirmed*, since the spelling was never the problem.

### Fixed
- **A name is not a person.** Verification used to take the first Wikidata
  person with a matching name, which could be a footballer rather than the
  novelist. A candidate must now have a writing occupation. Not a full cure:
  a namesake who also writes could still win. See 1.59.0.

## [1.57.0] — 2026-09-16

### Added
- **Verify selected**, on the Authors page. Tick several authors and verify
  them in one go. They are looked up one at a time, so a few hundred take
  minutes, and the page counts as it goes.

### Changed
- **The Authority column shows a description**, like "British science fiction
  writer", instead of a Wikidata code. The codes are in the link tooltips.
  Authors verified before this release show no description until you verify
  them again.

## [1.56.0] — 2026-09-16

### Changed
- **Author row actions moved into a ⋯ menu.** Only the action the row needs
  stays visible: **Confirm**, when the entry is tentative.
- **The sidebar's Views section is always there.** Table, Shelf and Series are
  now links on every page, not just the library page.

## [1.55.1] — 2026-09-16

### Fixed
- Series card actions are now text links, not buttons. They are always
  visible, since an iPad has no hover.
- The **New** badge no longer sticks to the front of a title on series cards.

## [1.55.0] — 2026-09-16

### Added
- **Rename a series** ([handbook §9f](docs/handbook-en.md#9f-renaming-a-series)),
  on the series card. No AI. Every book on the card gets the new name and
  keeps its number.

### Fixed
- **A Swedish interface showed English** in the language check and the whole
  series flow, and sometimes an internal word like "confirmed" where a status
  should be. Since 1.52.0.
- **"Unchanged" rows were not always unchanged.** A row is now *Unchanged* only
  when the text is identical, and then it has no checkbox. A row that means
  the same but is written differently ("#03" → "#3") is **Spelling only**,
  never pre-ticked. The columns are now **Now** and **Becomes**.

## [1.54.0] — 2026-09-16

### Added
- **Order an author's series** ([handbook §9e](docs/handbook-en.md#9e-ordering-an-authors-series)).
  The same review as *Order the series*, across everything one author wrote.
  The AI also decides which series exist. Books it places outside every
  series get no checkbox, so a standalone book cannot get a number by
  accident. Two ways in: the author's row on the Authors page, and the blue
  banner when you filter the library on an author.

## [1.53.2] — 2026-09-16

### Changed
- **The default AI model is now `ministral-14b-latest`**, the largest model
  that answers on a free Mistral key. Existing installations keep their own
  setting and must change it themselves under Settings → AI.

### Fixed
- **The 429 error was the model, not your quota.** Mistral's free plan no
  longer includes `mistral-small`, `mistral-medium` or `magistral-small`.
  They return the same error as a used-up quota. The error message now says
  so and tells you to pick another model.

## [1.53.1] — 2026-09-16

### Fixed
- **AI errors now say what went wrong.** Too many requests, quota used up, or
  a model your plan cannot use each get their own message, on all five places
  Colophon asks the AI. "Try again later" is gone where waiting would not
  help.

## [1.53.0] — 2026-09-16

### Added
- **Order the series** ([handbook §9d](docs/handbook-en.md#9d-ordering-a-series)).
  Every card in the Series view gets a button that asks the AI about the whole
  series in one call and checks the answer against Wikidata. Each row shows
  its status: *Confirmed*, *Suggested*, *Differs from what is recorded*,
  *Spelling only*, or no checkbox at all for books outside the series. The
  header warns about duplicate numbers and gaps.

  Series and series number are fields the Kobo reads, so a synced device
  reloads those books even if you leave **Write to the files too** unticked.
  The panel says how many.

## [1.52.0] — 2026-09-16

### Added
- **See what's missing** ([handbook §9b](docs/handbook-en.md#9b-seeing-whats-missing)).
  A dot next to every book in the table view: green is complete, amber is
  missing something, red is missing most things. Three counters above the
  list filter to each colour, and the sort menu has **Least complete first**.
  The score behind the dot now updates on every change to a book.
- **Check language** ([handbook §9c](docs/handbook-en.md#9c-checking-language)).
  **Tools → Check language** reads the text inside every EPUB and lists only
  the books where the recorded language is missing or wrong. It samples from
  the middle of the book, because forewords and copyright pages are often in
  another language. **Write to the files too** is pre-ticked here, because the
  Kobo picks its dictionary from this field.

## [1.51.1] — 2026-09-16

### Changed
- **The generic batch button is hidden.** `COLOPHON_SHOW_LEGACY_BATCH=1` brings
  it back while its replacements are built.

### Fixed
- **Bulk fetching wrote before you saw anything.** A confident match was saved
  to your library and into the e-book files before it appeared in the review
  list. "Ask AI" in bulk was worse: anything it felt sure about, titles and
  authors included, went straight into the files with no review. Both now
  only look. Saving happens only where you ask for it.

## [1.51.0] — 2026-09-16

### Changed
- **AI suggestions now see your library** ([handbook §7](docs/handbook-en.md#7-ai-features),
  [#173](https://github.com/cgillinger/colophon/issues/173)). The model is
  shown the author's other books, the series names you already use and your
  subjects. A suggested series that matches one you have gets your spelling.
  This helps new suggestions only. Spellings that already differ still need
  a cleanup view.

## [1.50.1] — 2026-08-10

### Fixed
- **One unremovable book could break a whole Kobo sync.** Telling the reader a
  book is gone requires an id that was sometimes never recorded. That case
  crashed the sync. It is now skipped and logged.

## [1.50.0] — 2026-08-10

### Added
- **See what your Kobo is carrying.** Plug it in over USB and Settings → Kobo
  shows how many books it holds, how many Colophon recognises, and why they
  differ. It also counts books with reading progress that never reached
  Colophon and points to **Import reading state**. Read-only.

## [1.49.0] — 2026-08-10

### Fixed
- **The Kobo stopped re-sending the same books every sync.** Timestamps sent
  to the reader lost their milliseconds, so Colophon appeared to be behind
  and the reader repeated itself.

### Added
- **The mass-delete guard can be unlocked from Settings.** Colophon refuses to
  tell a reader that more than a fifth of its books are gone. There is now a
  one-time unlock button for when you really did remove them.

## [1.48.0] — 2026-08-10

Six Kobo sync bugs, found by comparing Colophon with its sibling project
Bookstation.

### Fixed
- **Broken values were written to the reader's configuration.** Fixed values
  are sent on the next sync.
- **Books could be skipped during a sync and never arrive.** Reading progress
  arriving mid-sync reordered the list Colophon was walking through.
- **A reader that lost its sync token re-downloaded the whole library.**
  Colophon now keeps its own record of what it sent to each device.
- **Covers were sent at full size.** On a real library: 187 MB down to 20 MB.
- **Every cover request searched the whole library.** Now a direct lookup.
- **A replaced cover never reached the reader.** The cover's address now
  changes when the file does.

### Added
- **Force full resync**, per device, in Settings → Kobo. Use it to push
  corrected covers to books the reader already has.

### Known
- Withdrawing a book from a reader does not work and never has. A factory
  reset of the reader clears stale entries.

## [1.47.0] — 2026-08-09

### Added
- **Drag the selection sheet in the reader** and it stays where you drop it.
  **Reset position** puts it back to automatic placement.

## [1.46.2] — 2026-08-09

### Fixed
- The button that moves the selection sheet is now labelled **Move up** or
  **Move down**, next to the close button, instead of hiding on the grab
  handle.

## [1.46.1] — 2026-08-09

### Fixed
- **The selection sheet no longer covers the text you selected.** It opens at
  the end of the screen your selection is not on.

## [1.46.0] — 2026-08-09

### Added
- **Copy text out of a book.** Select more than one word in the reader and
  you get **Copy** and **Copy with source**, which adds title and author.
  Works over plain `http://` too.

## [1.45.0] — 2026-08-09

### Changed
- **USB import works when Colophon runs in Docker** on the same machine as
  the reader. The README says what to add to `docker-compose.yml`. A reader
  plugged into a different machine cannot be seen; use wireless sync.
- New `COLOPHON_USB_MOUNT_ROOTS` for a non-standard mount location. Set it
  empty to turn USB detection off.

## [1.44.0] — 2026-08-09

### Added
- **Import reading state from a Kobo over USB**, including the exact
  position. Colophon never writes to the reader, and it reads a private copy
  of the device database so an unplugged-mid-write Kobo does not look
  corrupt. Furthest read wins, as with wireless sync.

### Groundwork
- Colophon now records which books it put on which device by USB, so
  wireless sync does not offer them again. Without this, a book sent both
  ways appears twice on the Kobo.

## [1.43.0] — 2026-08-09

### Fixed
- **Renaming or moving a book file no longer loses it.** A scan recognises a
  moved file and keeps its reading position, rating and Kobo pairing. Only
  unambiguous matches count.
- **A book's identity no longer depends on its database row.** Every book
  carries its own permanent id. Nothing re-downloads on your Kobo.
- **Removing a Kobo also forgets what it was sent**, so the next device you
  pair gets the whole library.

## [1.42.0] — 2026-08-09

### Added
- **Your reading position moves between browser and Kobo exactly.** Read a
  chapter in the browser, sync the Kobo, and it opens on the same sentence.
  Where an exact position is not possible (PDF, a book never sent to a Kobo)
  you land on the nearest chapter. Page numbers still differ between devices,
  because each device paginates for its own screen.

## [1.41.2] — 2026-08-09

### Fixed
- **An empty library folder could wipe the catalogue.** A scan that finds no
  books at all now refuses to delete anything.
- **An unreadable file no longer counts as deleted.** A stale network mount
  or a permissions error used to remove the book.
- **The Kobo mass-delete guard could not be overridden.** There is now a
  one-shot `KOBO_ALLOW_MASS_DELETE`.

## [1.41.1] — 2026-08-09

### Fixed
- **The Kobo ignored corrected positions.** Colophon now re-dates a position
  when it overrules a device, so the correction lands.
- A bookmark deep inside a long chapter was wrongly treated as stale.

## [1.41.0] — 2026-08-09

### Fixed
- **The Kobo could get stuck behind Colophon's reading position.** A stale
  Kobo bookmark is now dropped when you read in the browser, and every stored
  bookmark is checked against the percentage before it is sent.
- Reading progress for a book Colophon never sent is now logged instead of
  vanishing.

### Added
- After reading in the browser, the Kobo opens at the chapter matching your
  progress.

## [1.40.0] — 2026-07-29
- Prebuilt Docker image on GHCR, published on every push (amd64 + arm64).

## [1.39.x]
- Embedded series is read from EPUB files again (1.39.6).
- `rsync` ships in the image; upstream pull failures show in the scan UI (1.39.5).
- "Missing author folder" filter and retroactive upstream cleanup (1.39.0).

## [1.38.0]
- Author folders for uploaded books, plus upstream orphan cleanup.

## [1.36.0] — [1.37.0]
- Multi-author support: one registry entry per person, with a dismissable
  "looks like several people" badge.

## [1.31.0] — [1.35.0]
- In-browser reader gains PDF support, a scrub bar and in-reader restart.
- Dictionary word lookup with on-demand dictionary downloads.

## [1.28.1] — [1.28.2]
- Kobo reading-state sync: furthest-read-wins, and the full bookmark
  round-trip that stopped every sync resetting the device to the start.
