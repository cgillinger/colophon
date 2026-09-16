# Changelog

Notable changes per release. Colophon follows [semantic versioning](https://semver.org/):
PATCH for fixes, MINOR for user-visible features and automatic migrations, MAJOR for
changes that need you to act. Releases before 1.41.0 are summarised from the git log —
see the [tags](https://github.com/cgillinger/colophon/tags) for the full history.

## What's new since 1.50

Fourteen releases that replaced one all-purpose batch job with **scenarios** —
jobs where the books actually belong together: one series, one author's shelf,
everything that is missing a cover. Each one shows you what it intends to do,
and you tick your way through it before a single thing is saved.

**Upgrading.** `docker compose pull && docker compose up -d`, or a pinned
version if you prefer one (`ghcr.io/cgillinger/colophon:1.61.1`). Colophon
brings its own database up to date the first time it starts, and no setting
has changed meaning, so there is nothing to do beyond the two notes below.
Your book files are not touched by the upgrade itself.

- **Remove `COLOPHON_SHOW_LEGACY_BATCH` from your compose file** if you set it.
  1.61.0 deleted what it revealed, and the line is now ignored.
- **If the AI features went quiet, suspect the model, not your quota.** Mistral's
  free plan no longer includes the `mistral-*` chat models; they answer `429`,
  which reads exactly like being throttled. Pick a `ministral-*` model under
  **Settings → AI** (1.53.2). New installs already default to one.

### The features

Most useful first. The handbook explains each in full — also
[på svenska](docs/handbook-sv.md).

| Feature | Where you find it | Handbook | Since |
|---|---|---|---|
| **Order a series** — one AI call for the whole series instead of one per book, cross-checked against Wikidata, reviewed row by row. This is the answer to series numbering that drifts. | Series view → a card's **Order the series** | [§9d](docs/handbook-en.md#9d-ordering-a-series) | 1.53.0 |
| **Order an author's whole shelf** — every series one author wrote, in a single review, with the AI also deciding which series exist | Authors page → the row's ⋯ menu → **Order series**, or the banner above the list when you have filtered on an author | [§9e](docs/handbook-en.md#9e-ordering-an-authors-series) | 1.54.0 |
| **Fetch covers for a whole filter** — the missing-cover count turned into a batch, searched across the entire filter rather than the page you can see | Click the **N missing cover** count below the list → **Fetch covers for these** | [§9g](docs/handbook-en.md#9g-fetching-covers-for-a-whole-filter) | 1.60.0 |
| **See what's missing** — a completeness dot on every book, three counters that filter, and *Least complete first* in the sort menu | Table view | [§9b](docs/handbook-en.md#9b-seeing-whats-missing) | 1.52.0 |
| **Check language** — reads the text inside your EPUBs and reports only the books whose recorded language the text contradicts | **Tools → Check language** | [§9c](docs/handbook-en.md#9c-checking-language) | 1.52.0 |
| **Rename a series** — deterministic, no AI; gathers the spelling variants onto one name and leaves every book's number alone | Series view → a card's **Rename** | [§9f](docs/handbook-en.md#9f-renaming-a-series) | 1.55.0 |
| **AI suggestions that know your library** — the model is shown the series names and subjects you already use, and a proposed series that matches one of them is snapped to your spelling instead of becoming variant number four | Wherever the AI proposes metadata | [§7](docs/handbook-en.md#7-ai-features) | 1.51.0 |
| **The Authority column says who** — a plain-language description of the person ("British science fiction writer") rather than a bare Wikidata id, plus **Verify selected** so the column can actually be filled | Authors page | [§10](docs/handbook-en.md#10-managing-authors) | 1.57.0 |

### Fixes worth knowing about

- **Nothing is saved before you have seen it.** Fetching metadata for many
  books at once used to save the ones it felt sure about — into your e-book
  files — before showing you the list you were meant to approve (1.51.1).
- **An author could be anchored to the wrong person** in Wikidata, with no way
  to undo it. Your own shelf now decides, and the link can be removed
  (1.58.0, 1.59.0).
- **A Swedish interface was quietly showing English** in the newer screens,
  and here and there an untranslated word where a status should have been
  (1.55.0).
- **A brand-new installation could fail to start** the very first time
  (1.61.1).

### Still on the list

- **Aligning spellings that have already diverged.** 1.51.0 makes *new*
  suggestions converge on what your library already says, but it does nothing
  about the variants sitting in there today — one series spelled three
  different ways across its own books, a subject that exists as "sci-fi",
  "science fiction" and "SF". A cleanup view that clusters near-duplicate
  series and subject values, the way `/authors` already does for names, is the
  plan — asked for in
  [#173](https://github.com/cgillinger/colophon/issues/173).
- **Bulk file and folder moves.** Deliberately out: they interact badly with
  Kobo sync and upstream syncing. There is a per-book *Move to author folder*
  action instead.

Per-release detail follows.

---

## [1.61.1] — 2026-09-16

### Fixed
- **A brand-new installation could fail to start.** The very first start
  against an empty data folder is where Colophon builds its database, and it
  went about that from two directions at once. Now and then the two collided,
  the start was abandoned, and all you got was a wall of error text on a
  program that had not yet done anything — the worst possible first
  impression, and nothing you could have done differently. It now builds the
  database once, in order. An installation that was already running was never
  affected: its database had been built long ago, so there was nothing left to
  collide over.

## [1.61.0] — 2026-09-16

### Removed
- **The generic batch wizard is gone for good.** Select a pile of unrelated
  books, choose some fields, press go — it had been hidden since 1.51.0,
  because twenty books with nothing in common are twenty separate judgements
  hiding behind one progress bar. Every job it used to do now has a scenario of
  its own (see 1.52.0 through 1.60.0), so the wizard itself is now deleted:
  the window, the few thousand lines behind it, and the wording and styling
  nothing else was using.
- **`COLOPHON_SHOW_LEGACY_BATCH` no longer does anything.** It was the escape
  hatch that brought the old button back while the scenarios were being built.
  If you set it in your compose file, remove the line — it is now ignored.
  Nothing else changes: the button it brought back has not been part of the
  ordinary interface since 1.51.0.

## [1.60.0] — 2026-09-16

### Added
- **Fetch covers for a whole filter** ([handbook §9g](docs/handbook-en.md#9g-fetching-covers-for-a-whole-filter)).
  Click the "N missing cover" count below the list and a row appears above it:
  **Fetch covers for these**. Colophon searches the entire filter — not just
  the page you can see — and shows what it found beside the empty slot each
  cover would fill. Everything starts ticked, because nothing is being
  overwritten; untick what you don't want and apply. A hundred books per run;
  if the filter holds more it says how many are left.

### Fixed
- **A preview could move a cover on its own.** Where you keep several formats
  of the same book — EPUB and MOBI, say — Colophon keeps their covers in step
  with each other. That copying happened, and was saved, before the search had
  even run, so a cover could travel from one format to the other during what
  was only meant to be a look at the options; the book then quietly vanished
  from the list without anyone pressing Apply. Formats are now left alone
  while a run is only looking.
- **A round of covers left every traffic light one step too red.** Applying a
  cover didn't recalculate the completeness score.

## [1.59.0] — 2026-09-16

### Fixed
- **Your own bookshelf now decides who an author is.** The profession filter
  added in 1.58.0 kept the wrong person out but found nobody to put in their
  place, because the right one was never a candidate to begin with. Search
  Wikidata for an everyday name and it answers with whoever is most famous —
  sportspeople, politicians, a disambiguation page — while the novelist you
  actually mean may be filed under a middle initial and never appear at all.
  No filter can rule out the wrong person if the right one was never on the
  list. Colophon now asks Wikidata which of the candidates is credited as the
  author of a book *you already have on the shelf*, and that one wins: having
  written something in your library is a fact, a listed profession is a guess.
  When the name gets nowhere at all, it searches on one of your titles instead
  and reads the author off the work. Evidence, never a condition — if any of
  it fails, verification carries on as before.

## [1.58.0] — 2026-09-16

### Added
- **Remove authority link**, in the author row's menu
  ([handbook §10](docs/handbook-en.md#10-managing-authors)). A wrong anchor you
  cannot undo was the worst situation of the lot. The entry drops to
  *confirmed* rather than *tentative* — the click says the id is the wrong
  person, not that the spelling is wrong.

### Fixed
- **A name is not a person.** Author verification searched Wikidata for the
  name and took the first human whose name matched. Wikidata ranks by fame, so
  a novelist could end up anchored to a sportsman who happens to share the
  name — and because an authority-linked entry is allowed to write to your
  files, a wrong anchor is worse than none. A candidate must now also have a
  writing profession, and the search walks past those who don't instead of
  stopping at the first name match. It is a mitigation, not a cure: a namesake
  who also writes would still win.

## [1.57.0] — 2026-09-16

### Added
- **Verify selected**, on the Authors page
  ([handbook §10](docs/handbook-en.md#10-managing-authors)). Verification
  existed only one row at a time, so in a real library the Authority column
  read "—" everywhere while most entries were confirmed — two unrelated things
  the page never explained. Authors are still looked up one after another
  rather than all at once, with the page counting up as it goes: a few hundred
  of them take minutes, and a version that went quiet until every last one was
  done would look like it had frozen.

### Changed
- **The Authority column says who, not which code.** A bare Wikidata id — the
  letter Q and eight digits — doesn't answer the only question you have after
  pressing Verify: did it find the right person? The lookup already received a label and a description from Wikidata
  and threw them away. The cell now reads "British science fiction writer",
  with the identifiers moved into the tooltips of named links. Entries verified
  before this release keep their identifiers and stay without a description
  until you verify them again — the wording was never kept, so there is
  nothing to fill in after the fact.

## [1.56.0] — 2026-09-16

### Changed
- **The author row's actions moved into a ⋯ menu.** Six filled buttons per row
  became well over a hundred on a single page of authors, wrapped unevenly
  and were unusable on a phone. The row now shows only the action it actually needs —
  Confirm, when the entry is tentative — and the rest live in the menu.
- **The sidebar's VIEWS section stays put.** It only ever appeared on the
  library page, where Table, Shelf and Series switch the view in place. On
  every other page the heading vanished, and the way back to your books looked
  like a reading filter. The three views are now always there as ordinary
  links.

## [1.55.1] — 2026-09-16

### Fixed
- **The series card's actions are text, not furniture.** Two filled buttons
  beside a cover read as bolted-on hardware in a view that is otherwise airy.
  They are now text with an icon, dimmed until you point at them — but never
  hidden, since there is no hover on an iPad.
- **The "New" badge ran into the title.** A series card took its titles from
  the list on screen, badge and all, so a recently added book turned up with
  the word New welded to the front of its name.

## [1.55.0] — 2026-09-16

### Added
- **Rename a series**, on the series card
  ([handbook §9f](docs/handbook-en.md#9f-renaming-a-series)). Deterministic, no
  AI. A card already gathers books whose series names differ only in spelling,
  so the rename fixes those variants on the way past; every book keeps its own
  number.

### Fixed
- **A Swedish interface was showing English.** A slip in how the translations
  were bundled left 55 of them out of reach — the whole language check and the
  whole series flow. Nothing broke and nothing complained; those screens
  simply came out in English, and in a few places showed an internal word like
  "confirmed" where a status should have been. It had been that way since
  1.52.0.
- **"Unchanged" was not always unchanged.** Rows whose text did change
  ("Children of time #03" → "Children of Time #3") were labelled unchanged.
  A row is now called unchanged only when the text really is identical, and
  then it loses its checkbox entirely;
  everything else is **Spelling only**, with a checkbox that is never
  pre-ticked — you decide whether a tidier spelling is worth a reload on the
  Kobo. The columns are now **Now** and **Becomes**.

## [1.54.0] — 2026-09-16

### Added
- **Order an author's series** ([handbook §9e](docs/handbook-en.md#9e-ordering-an-authors-series))
  — the same review as *Order the series*, but across a whole body of work,
  with the AI also deciding which series exist. One block per proposed series,
  and a last block for the books it places outside all of them; those rows have
  no checkbox at all, which is what stops a standalone book from being given a
  number. Each block is judged on its own, so a thin series can't arrive
  pre-ticked on the strength of a fat one beside it. Two ways in: the button on
  the author's row, and the one in the blue bar when you have filtered the
  library on an author.

## [1.53.2] — 2026-09-16

### Changed
- **The default model is now `ministral-14b-latest`**, the largest that answers
  on a free key. It was `mistral-small-latest`, which a fresh install with a
  free key would never get an answer from. Existing installations have their
  own value in the database and need to change it themselves.

### Fixed
- **It is the model that isn't in the free plan, not your quota.** A correction
  to 1.53.1, which blamed the account. Asking Mistral's API directly settles
  it: the `ministral-*` models answer normally on a free key, while
  `mistral-small`, `mistral-medium` and `magistral-small` all return 429 with a
  ceiling of zero requests per minute, and `mistral-large` returns 403. The account is healthy — the
  `mistral-*` family is no longer included in the free plan. The message now
  points at the model and tells you to pick another one under Settings → AI.

## [1.53.1] — 2026-09-16

### Fixed
- **"It failed" is not an explanation.** When an AI provider turns a request
  away, it does so with the same brush-off whatever the reason: you have asked
  too fast, you have used up the month, or your plan may not use that model at
  all. Three of the five places Colophon asks the AI — series ordering, the
  author check and the reader's word lookup — said nothing whatsoever about
  it, and the two that did say something told you to try again later, which is
  useless advice in half the cases. Colophon now passes on whatever the
  provider is willing to say: how long to wait, if it says; that the month's
  allowance is spent, if that is what happened; or that this account may not
  make the call at all, in which case waiting will never help. When the
  provider gives no reason, it says the limit was reached rather than
  inventing one.

## [1.53.0] — 2026-09-16

### Added
- **Order the series** ([handbook §9d](docs/handbook-en.md#9d-ordering-a-series)).
  Every card in the Series view gets a button that asks the AI about the whole
  series in one call — not book by book, which is what makes numbering drift —
  and cross-checks the answer against Wikidata before showing you anything.
  Each row says where it stands: *Confirmed* (both agree), *Suggested* (the AI
  alone, pre-ticked only when it is confident), *Differs from what is recorded*
  (never pre-ticked — a number you typed is not overwritten unless you tick it
  yourself), *Spelling only*, and dimmed rows with no checkbox for books the AI
  puts outside the series or didn't answer about. The header warns about
  duplicate numbers and gaps. A proposal standing on its own with nothing to
  confirm it is treated as less certain, so it can never arrive pre-ticked.

  Series and series number are fields the Kobo reads, so a synced device
  reloads those books even with **Write to the files too** unticked. The modal
  says so under the table rather than pretending otherwise.

## [1.52.0] — 2026-09-16

### Added
- **See what's missing** ([handbook §9b](docs/handbook-en.md#9b-seeing-whats-missing)).
  Every book in the table view has a dot beside its checkbox: green means the
  metadata is essentially complete, amber that something is missing, red that
  most of it is — hover for the list. Above the list, three counters say how
  many sit in each state and filter down to them when clicked, and the sort
  menu gains **Least complete first**. Something like this score existed
  before, but only behind the scenes, and it was only ever recalculated in one
  situation — so on books you had edited yourself, or had just scanned in, it
  was usually out of date. It now follows every change to a book, and the
  books that predate it were brought up to date once.
- **Check language** ([handbook §9c](docs/handbook-en.md#9c-checking-language)).
  **Tools → Check language** reads the text inside every EPUB and reports only
  what deserves a human: no language recorded, or a recorded language the text
  contradicts. It samples two passages from 30 % and 60 % into the book rather
  than the start, because forewords and copyright pages are routinely in
  another language and asking them gives the wrong answer; when the two samples
  disagree the book is flagged and left unticked. Books with no language at all
  arrive pre-ticked, books whose value is merely contradicted do not. **Write
  to the files too** is pre-ticked here and nowhere else — the Kobo picks its
  dictionary and hyphenation from the language, so reaching the device is the
  entire point — and the label says how many books will reload.

## [1.51.1] — 2026-09-16

### Changed
- **The generic batch button is hidden** while the scenarios meant to replace
  it are being built. Setting `COLOPHON_SHOW_LEGACY_BATCH=1` brings it back
  for now.

### Fixed
- **The batch wrote before you saw anything.** Fetching metadata for a pile of
  books, Colophon decided a match was good enough and saved it — to your
  library and into the e-book files themselves — *before* that book ever
  appeared in the list you were supposed to approve. "Ask AI" was worse:
  anything it felt sure about went straight into the files with no review at
  all, titles and authors included. Both now look without touching anything,
  and saving happens only where you ask for it. The handbook claimed batch
  operations always confirmed before writing; that section has been rewritten
  to say what is actually true.

## [1.51.0] — 2026-09-16

### Changed
- **AI suggestions now see the rest of your library**
  ([handbook §7](docs/handbook-en.md#7-ai-features), requested in
  [#173](https://github.com/cgillinger/colophon/issues/173)). The AI used to
  be shown one book and nothing else, so asking it about book after book gave
  a new spelling of the same series every time, and a fresh synonym for every
  subject. It is now also shown the author's other books, the series names
  already in use, and the subjects you already apply. A suggested series that
  matches one you have is corrected to your spelling and treated as certain,
  so working through many books settles on one name instead of drifting into
  variants. Subjects are steered the same way, but never treated as certain.
  If none of that can be gathered, you still get your suggestion.

  This helps new suggestions only. Spellings that have already diverged need
  the cleanup view that is still on the list.

## [1.50.1] — 2026-08-10

### Fixed
- **One unwithdrawable book could take a whole sync down.** When Colophon
  tells a reader that a book is gone it has to quote the id the reader was
  given — the book's own row is long deleted by then. If that id had never
  been recorded, the fallback crashed the request, so the reader got a server
  error instead of a sync. It now skips that one withdrawal, says so in the
  log, and delivers everything else. Nothing in a healthy library reaches this
  path; it is a safety net, not a repair.

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
after an e-reader there never finished downloading covers on a large library.

### Fixed
- **Colophon was writing broken values onto your reader.** Two entries in the
  configuration Colophon hands the device were malformed — copied long ago out
  of a formatted document, and had brought its formatting codes along with
  them. The reader keeps that configuration itself, so the damage stayed on
  the hardware.
  Confirmed on a real device. Fixed values are written on the next sync.
- **Books could be skipped during a sync and never arrive.** The library is
  handed over in batches, and Colophon counted its way through them against a
  list sorted by what had changed most recently. But the reader sends its
  reading progress *between* those batches, which reshuffles that list — so a
  book sitting on the seam between two of them was stepped over, and never
  offered again. The counting now follows something that cannot move.
- **A reader that lost its place re-downloaded the whole library.** What
  Colophon said about a book depended on what the device claimed to already
  know, instead of on what Colophon had actually sent it. So a reader that
  turned up knowing nothing — after a reset, or a fresh setup — was told that
  every book in the library had changed, and dutifully fetched all of them
  again. Colophon now keeps its own record, for each device, of what it sent
  and in what shape.
- **Covers were sent at full size.** The reader asks for a thumbnail and got
  the original — several megabytes each, one per book, on every sync. Measured
  on a real library: 187 MB down to 20 MB.
- **Every cover request searched the whole library.** Working out which book a
  requested cover belonged to meant going through every book in turn and
  working out its identity again — thousands of times over while a reader
  fetched its covers. Colophon now looks it up directly.
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
- Reading progress arriving for a book Colophon has no record of ever sending
  is still ignored — there is nothing to match it to — but it is now noted in
  the log instead of vanishing silently. Without it the failure is invisible from both ends: a
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
