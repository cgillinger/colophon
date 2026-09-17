# Colophon — User Handbook

*Svensk version: [handbook-sv.md](handbook-sv.md)*

This handbook explains everything Colophon can do, in the order you'll usually
meet it. You can read it start to finish the first time, or use the index below
to look up one thing — *How do I share a book? Why won't my Kobo sync? What's a
"tentative" author?*

> Colophon is a self-hosted web app that turns a folder of e-book files into a
> clean, browsable library, enriches the metadata, and syncs the whole thing to
> a Kobo e-reader over WiFi. One library, several ways to look at it.

## Index

1. [First look: the screen](#1-first-look-the-screen)
2. [The three library views](#2-the-three-library-views)
3. [Finding books: search, filters, sorting](#3-finding-books-search-filters-sorting)
4. [Adding books](#4-adding-books)
5. [Opening and editing a book](#5-opening-and-editing-a-book)
6. [Getting good metadata](#6-getting-good-metadata)
7. [AI features](#7-ai-features)
8. [Covers](#8-covers)
9. [Doing many books at once: batch operations](#9-doing-many-books-at-once-batch-operations)
   - [9b. Seeing what's missing](#9b-seeing-whats-missing)
   - [9c. Checking language](#9c-checking-language)
   - [9d. Ordering a series](#9d-ordering-a-series)
   - [9e. Ordering an author's series](#9e-ordering-an-authors-series)
   - [9f. Renaming a series](#9f-renaming-a-series)
   - [9g. Fetching covers for a whole filter](#9g-fetching-covers-for-a-whole-filter)
10. [Managing authors](#10-managing-authors)
11. [Finding and clearing duplicates](#11-finding-and-clearing-duplicates)
12. [Reading in the browser](#12-reading-in-the-browser)
13. [Reading progress and status](#13-reading-progress-and-status)
14. [Sharing a book (giving it away)](#14-sharing-a-book-giving-it-away)
15. [Kobo wireless sync](#15-kobo-wireless-sync)
16. [Syncing to an upstream library](#16-syncing-to-an-upstream-library)
17. [Settings](#17-settings)
18. [Install as an app (PWA)](#18-install-as-an-app-pwa)
19. [Language and theme](#19-language-and-theme)
20. [Glossary](#20-glossary)

---

## 1. First look: the screen

When you open Colophon you land on your **library**. The screen has two lasting
parts:

- **The sidebar** (left on desktop; the **☰ menu** button, top-right, on phone/tablet). It's grouped into:
  - **Views** — how the current library is laid out (Table / Shelf / Series).
  - **Tools** — *Upload books*, *Find new books*, *Find duplicates*, *Authors*, *Kobo sync*, *API settings*, *AI settings*, and *Sync to library* (only when you have local changes to push upstream).
  - **Reading** — filtered views of the same library: *All*, *Unread*, *Reading*, *Finished*, each with a live count.
- **The top bar** — language (EN/SV), the light/dark theme toggle, and on small screens the menu button.

Everything is one library; the sidebar just changes what you're looking at or
what you're doing to it.

## 2. The three library views

Switch between these from the **Views** section. They show the same books,
arranged for different jobs.

- **Table** — a sortable, filterable spreadsheet of your metadata. Best for
  curating: you can see title, author, series, language and reading state at a
  glance, and it's where the *Reading now* cards appear (see §13).
- **Shelf** — a wall of covers, like a bookshelf. Best for browsing and for
  reading: cover badges show reading progress, and a freshly added book wears a
  **New** badge for a couple of weeks. Tapping a cover opens its details, and
  this is where the **Read** button (the in-browser reader) lives.
- **Series** — books grouped by series, in reading order. Best for seeing what
  you have and what's missing in a series.

Your chosen view, search and filters are kept in the page address, so the
browser **Back** button and bookmarks work the way you'd expect.

## 3. Finding books: search, filters, sorting

- **Search** — the search box matches title, author and series as you type.
- **Filters** — narrow the list by language, reading state and more. The
  **Reading** group in the sidebar (*All / Unread / Reading / Finished*) is the
  quickest way to filter by how far you've got.
- **Sort** — order by title, author, date added (*Recently added* surfaces your
  newest books) and other fields.
- **Pagination** — long libraries are paged; covers load lazily as you scroll so
  the first screen is fast even on a tablet over WiFi.

## 4. Adding books

There are two ways to get books into Colophon.

- **Upload books** (Tools → *Upload books*) — pick files, or just **drag and
  drop** them anywhere on the window. They're uploaded straight into your
  library; no rescan needed. Good for adding a handful of books from the device
  you're on.
- **Find new books** (Tools → *Find new books*) — scans your book folder on the
  server for anything new or changed and reads its embedded metadata. Use this
  after you've copied files into the folder by other means. Progress streams
  live while it runs.

Supported formats: **EPUB, MOBI, AZW3, KEPUB, PDF, CBZ, CBR**.

**Format grouping.** If you have the same book in several formats (say EPUB +
MOBI), Colophon groups them as **one** library entry, so your shelf isn't
cluttered with duplicates of the same title. Metadata operations apply to the
whole group.

Newly added books wear a **New** badge for a while (14 days by default) so you
can spot what just arrived.

**Author folders.** Uploaded books land flat in the root of your book folder —
deliberately: Colophon never moves your files on its own. When a book's
metadata is in shape, open it, and in the edit view you'll find **Move to
author folder** with the target path spelled out (e.g. `John Hedgecoe/`). One
click moves the book — all its formats together — into its primary author's
folder; an existing folder with a cosmetically different spelling
(`arthur_c_clarke` vs `Arthur C. Clarke`) is reused, never duplicated. Your
reading progress, rating and Kobo pairing follow along untouched. To see which
books still sit in the root, use the **Missing: author folder** filter in the
library. (If you sync to an upstream library, the move also queues a cleanup of
the old upstream copy — see §16.)

## 5. Opening and editing a book

Click a book (a row in Table, a cover in Shelf) to open its **details**. From
here you can:

- **Edit the fields** — title, author, series and position, description,
  publisher, language, ISBN, genres, published date. Click **Save** to write
  your changes. Saving also writes the metadata **back into the e-book file**, so
  other tools (Komga, Kavita, your Kobo) see the same data.
- **Several authors?** The author area shows one field per person. **Add
  author** gives you a new field; the × removes one. The order matters — the
  first author is the book's primary author (used for sorting and author
  folders). You never type "and", commas or `&` — each person is their own
  field, and each field suggests existing authors as you type.
- **Your rating** — give the book your own 1–5 stars. This is *your* rating,
  never fetched from anywhere.
- **Reading state** — see and set how far you've read (see §13). *Mark as
  finished* sets it done by hand; *Reset reading state* clears it.
- **Delete** — the trash control removes the book. Deleting can also remove the
  file from disk, so it asks first. Treat it as permanent.

**Protecting your edits.** Once you've curated a book by hand, Colophon respects
that: automatic enrichment won't quietly overwrite your text, and a cover can be
**locked** so it's never replaced. Your manual work wins.

## 6. Getting good metadata

Colophon can fill in missing details from several online sources and merge them
intelligently.

- **Fetch metadata** (in a book's details) looks the book up, scores the
  candidates, and either applies a confident match or shows you a **preview** to
  approve. Merging is **field by field** — the best value for each field wins,
  and Colophon remembers where each one came from.
- **Sources** (all toggleable in *API settings*):

  | Source | What it's good for |
  |---|---|
  | Embedded file | Title/author/series already inside the file — trusted first |
  | Google Books | Title, author, description, ISBN, categories |
  | Hardcover | Series, genres, synopsis, rating — strong for popular English titles |
  | Open Library | Subjects, synopsis, ISBNs — strong for older/obscure titles |
  | Wikidata | Structured series **and position in the series**, genre, date |
  | Wikipedia | Quick description and a fallback thumbnail cover |
  | LIBRIS (KB) | Swedish national bibliography — authoritative Swedish data |
  | Calibre | "Deep" tier via Calibre's own plugins (Goodreads and others) |

- **Search depth.** The book's own panel lets you choose how hard to look — a
  quick pass over the fast sources, or a deeper search that brings in the
  slower ones. Colophon escalates on its own when the quick pass leaves the
  important fields empty.

## 7. AI features

AI is optional and only runs when you ask. Configure a provider in **AI
settings** first (Mistral, OpenAI, DeepSeek, or a local Ollama — see §17).

- **Ask AI** (in a book's details) — when the ordinary sources can't pin down a
  book's **series** and position, AI can infer it. It proposes; you review and
  approve.
- **Suggestions that know your library** — when AI proposes a series it is
  shown the series names and subjects already in use, and the author's other
  books. A suggestion that matches something you already have is snapped to
  your spelling instead of minting a new one, so running it over several books
  converges on one name rather than drifting into variants.
- **AI author check** (on the Authors page) — for two names that look like the
  same person, AI can advise whether they really are. Advisory only — you decide.
- **Order the series** (on a series card in the Series view) — asks about the
  whole series at once and checks it against Wikidata. See §9d.
- **Word lookup** (in the reader) — select a word and see what it means in that
  exact sentence. See §12.
- **Usage stats** — *AI settings* shows how many tokens you've spent, so there
  are no surprises on a metered plan.

### When the model stops answering

Not every model is included in a provider's free plan, and one that isn't
answers with the same error code as sending too many requests. So it looks as
if your quota is gone when it has not been touched at all.

With Mistral, as of September 2026, the `ministral` models answer on the free
plan while `mistral-small`, `mistral-medium` and `magistral-small` do not.
Colophon defaults to `ministral-14b-latest`, the largest that answers.
Providers change this from time to time.

If the AI features stop working, try another model under **AI settings**
before looking for usage. Colophon says so in the error message whenever the
provider's answer makes it visible.

## 8. Covers

- **Finding a cover** — open a book and look up cover art. Colophon searches
  **Open Library, Google Books, Hardcover, Wikidata/Commons** and **DuckDuckGo**
  and shows you the candidates to pick from.
- **Locking a cover** — once you're happy with a cover, lock it so enrichment and
  rescans never replace it.
- **Fetching covers for many at once** — see section 9g: filter down to the
  books with no cover and let Colophon look for all of them together.
- Covers are stored from the file and cached at display size, so catalogue views
  stay quick.

## 9. Doing many books at once: batch operations

Colophon has no general batch function where you select a pile of books and
let it write. Instead there are five **scenarios**, one for each kind of job
where the books belong together: a series, an author, every book without a
cover, and so on.

All scenarios work the same way:

1. Colophon shows a proposal, row by row.
2. You tick the rows you want. Nothing is saved until you press **Apply**.
3. The **Write to the files too** checkbox decides whether the change also
   goes into the e-book files themselves. The panel says how many books a
   synced Kobo will reload.

To enrich one book at a time, use the book's own panel, see section 6.

## 9b. Seeing what's missing

Every book in the table view has a small dot beside its checkbox:

- **Green**: the metadata is essentially complete.
- **Amber**: something is missing.
- **Red**: most of it is missing.

Hover the dot to see which fields. Above the list are three counters, one
per colour. Click one to filter the list to those books. The sort menu has
**Least complete first**.

Cover and synopsis weigh most, then genre, publication date, publisher and
series. A one-sentence synopsis counts as missing.

## 9c. Checking language

**Tools → Check language** reads the text inside every EPUB and compares it
with the language recorded in the metadata. Only books where the language is
missing or wrong are listed.

Colophon reads two passages from inside the book, not from the start.
Forewords and copyright pages are often in another language. If the two
passages disagree, the book is marked amber and left unticked.

- Books with no language are pre-ticked.
- Books where an existing value is contradicted are unticked. Someone may
  have set it on purpose.
- **Write to the files too** is pre-ticked here, unlike the other scenarios.
  The Kobo picks its dictionary and hyphenation from the language, so
  reaching the device is the point.

PDF and MOBI cannot be read and are counted in a footnote.

## 9d. Ordering a series

In the **Series** view every card has an **Order the series** button.
Colophon asks the AI about the whole series in one go and checks the answer
against Wikidata before you see anything.

The columns are **Now** and **Becomes**. Every row has a status:

- **Confirmed** (green): the AI and Wikidata agree. Pre-ticked.
- **Suggested** (amber): the AI alone. Pre-ticked only when it is confident.
- **Differs from what is recorded** (red): another number is already there.
  Never pre-ticked. A value you set yourself is not overwritten unless you
  tick the row.
- **Spelling only** (blue): same series and number, written differently
  ("#03" vs "#3"). Never pre-ticked.
- **Unchanged**, **Not in the series**, **No answer**: dimmed, no checkbox. A
  book the AI places outside the series never gets a number.

The header warns about duplicates and gaps ("2 duplicate numbers", "gap at
5"). The spelling of the series name is left alone unless you tick **Change
the series spelling on all of them** in the header.

Good to know: series and series number are fields the Kobo reads. A synced
device reloads the books even if you leave **Write to the files too**
unticked, which it is by default here.

## 9e. Ordering an author's series

The same review, for everything one author wrote. Reach it from the
**Authors** page (the row's ⋯ menu → **Order series**) or from the blue bar at
the top of the book view when you have filtered on an author.

The difference is that here the AI also decides *which* series exist. You
get one block per series and a last block **Not in a series**. Those rows
have no checkbox, so a standalone book cannot get a number by accident.

Each block is judged on its own. A series with a single book and no Wikidata
confirmation never arrives pre-ticked. Books written with someone else are
marked **co-written**.

The Wikidata check may take at most 90 seconds for the whole proposal. For an
author with many series, not everything gets confirmed in time. Those rows
show as **Suggested** instead of **Confirmed**. Nothing is wrong; you just
have less backing on the last rows.

## 9f. Renaming a series

The **Rename** button on the series card in the **Series** view. No AI. You
type the name, every book on the card gets it, and each book keeps its
number. A card already gathers books whose series names differ only in
spelling, so renaming fixes those variants at the same time.

The series name is a field the Kobo reads, so the books reload on a synced
device even if you leave the files alone.

## 9g. Fetching covers for a whole filter

Click the **N missing cover** count below the list. The filter narrows to
those books, and a row appears above: **Fetch covers for these**.

Colophon searches the whole filter, not just the page you can see, and shows
each cover it found beside the empty slot. All are ticked to start with,
since these books have no cover to lose. Untick what you don't want and press
**Apply**.

Covers are written one at a time, into the e-book file as well, so each
takes a moment. One run takes at most 100 books. If the filter holds more,
it says how many are left. A new cover makes the book reload on a synced
Kobo.

## 10. Managing authors

Colophon keeps **one canonical entry per author**, so every book by the same
person is labelled identically — even when the files spell the name differently
("J.R.R. Tolkien" / "Tolkien, J.R.R." / "JRR Tolkien" all become one author).

- **The author field** in a book's details is backed by the registry: start
  typing and it suggests existing authors, so you reuse an entry instead of
  creating a near-duplicate.
- **The Authors page** (Tools → *Authors*) is where you curate the registry.
  Each row shows the action it actually needs — **Confirm**, when the entry is
  tentative — and the rest sit behind **⋯** at the end of the row:
  - **Confirm** tentative entries — filter to unconfirmed, tick several, confirm
    them in one go. This is the fastest way to tidy up after a scan.
  - **Rename** or **Merge** — both cascade, relabelling every linked book in one
    sweep.
  - **Verify** against Wikidata. The **Authority** column then shows what
    Wikidata says the person is ("British science fiction writer"), so you can
    see whether the right person was found. *Confirming* a name does not fill
    the column; it only says the spelling is right. Tick several and use
    **Verify selected** to do them in one go. They are looked up one at a
    time, so it takes a moment. When several people share the name, the one
    credited with a book you already have wins. If it still picks the wrong
    one, **Remove authority link** is in the ⋯ menu.
  - For likely-duplicate pairs, merge with one click, or **Ask AI** whether
    they're the same person.

Each author has a **status** that controls whether the name is written into your
files:

| Status | Meaning | Written to files? |
|---|---|---|
| Tentative | Auto-created from file metadata during a scan/upload | No — database only |
| Confirmed | You confirmed the spelling | Yes |
| Authority-linked | Verified against Wikidata | Yes |

Tentative entries are never written into files until you confirm them, so an
auto-guessed spelling can't quietly rewrite your library.

**Books with several authors.** Each co-author is a full registry entry of
their own — searchable, linkable, with their own author page. Some files
arrive with all the names mashed into one string ("Sören Karlsson och Deanne
Rauscher"); those become a single entry wearing a small **group icon**. Click
**Split…** on that entry to fix it: you get one field per person (pre-filled
with a best guess), typed names are matched against the registry so existing
authors are reused, and every linked book is relinked in one sweep. The
decision is remembered — re-scanning the still-unchanged files won't bring the
mashed entry back. If the icon is wrong (sort-form names like "Ashton, Edward"
trip it on purpose — only a human can tell a sort form from two surnames),
click the icon itself and confirm "this is one person" to dismiss it for good.

## 11. Finding and clearing duplicates

**Find duplicates** (Tools) scans for books that look like the same title (fuzzy
matching, so it catches near-misses) and presents the candidate pairs for you to
review and clean up. Nothing is deleted without your say-so.

## 12. Reading in the browser

Colophon has a built-in reader — no app needed. It opens **EPUB, MOBI, AZW3 and
PDF**; DRM-protected (or password-encrypted) files can't be opened (Colophon
never strips DRM).

- **Open it** from a book's details in **Shelf** view: tap **Read** (EPUB,
  MOBI, AZW3, PDF). MOBI and AZW3 reflow just like EPUB, so the reading settings
  below apply to them too.
- **PDFs** are page images (fixed layout), so the text-size/font/margin settings
  don't apply and the page keeps its own background — the theme only tints the
  reader's chrome around it. Page-turning, progress and offline still work.
- **Turn pages** by tapping the left/right edges, or with the arrow keys.
- **Reading settings** (the **Aa** button) let you tune:
  - **Theme** — Light, Sepia, Dark.
  - **Text size**, **Font** (the publisher's own, Serif, Sans, or a
    **dyslexia-friendly** face), **Line spacing**, **Margins**.
  - **Reading mode** — Paged (tap to turn) or Scroll.
  These are remembered across books.
- **Look up words** — select a single word in the book (long-press on a tablet
  or phone) and a card opens at the bottom: the **Swedish translation** on top
  and an English dictionary definition (Webster's) below it, collapsed behind
  **Show more** when it runs long. The **✦ Explain with AI** button explains the
  word *in that exact sentence* — great for idioms and archaic words, and the
  fallback when the dictionary doesn't know the word (requires AI to be
  configured, see §7). The first time you look up a word, Colophon automatically
  downloads the dictionaries (open-source, ~37 MB, one-time) — after that,
  lookups are instant and fully local. Works for books in English in EPUB, MOBI
  and AZW3 (not PDF); lookups need the server, so a book saved for offline has
  no dictionary without a connection.
- **Save for offline** (the download icon) caches the book so you can read it
  with no connection; your progress is kept locally and re-syncs when you're back
  online. *Requires a secure (HTTPS) connection* — see §15 on serving over
  Tailscale.

Your reading position is saved automatically and **syncs with your Kobo** (see
§13).

## 12b. Reading offline

- **Requirement:** open Colophon via the **secure Tailscale address**
  (`https://…`), not `http://<lan-ip>:5055` — offline needs HTTPS (see §15).
- **Install as an app** — "Add to Home Screen" (§18), especially on iOS:
  otherwise the system can clear the saved storage when the device needs
  space.
- **Save a book offline** two ways: from inside the reader (the download icon
  in the toolbar, §12) or straight from the book's card/modal in **Shelf**
  view — the **Save for offline** button appears once the book is readable
  and a secure connection is active.
- **Find your downloads:** the **"N downloaded"** chip in the library counter
  filters them into view. Opening the app with no connection at all lands you
  straight on the **"Downloaded books"** shelf instead of a dead page.
- **Reading position syncs back** to the Kobo/library as soon as the
  connection returns — for **every** book you read offline, not just the last
  one open (§13).
- **Remove an offline copy** by opening the book again (or its card) and
  tapping the same button — it now reads "Saved offline"; tap again to
  remove it.

## 13. Reading progress and status

Reading state is one shared truth, whether you read on the Kobo or in the
browser. Every book is *Unread* (Ready to read), *Reading*, or *Finished*, plus a
progress percentage.

- **Where you see it:** the **Reading** filters in the sidebar (with counts), the
  cover badges in **Shelf** view, the **Reading state** box in a book's details,
  and the **Reading now** / **Resume?** cards at the top of **Table** view —
  *Reading now* picks up where you left off recently; *Resume?* nudges you about
  books you started but drifted from (each can be dismissed).
- **How it syncs:** reading on the Kobo updates Colophon on the next sync, and
  reading in the browser rides the same channel back to the Kobo. Progress only
  ever moves **forward** — a quick "peek" on one device can't wipe how far you
  actually read on another. Status only moves forward too (a finished book stays
  finished); to re-read, use *Reset reading state*.
- **Position syncs exactly** both ways: read a chapter in the browser, sync
  the Kobo, and it opens on the same sentence. For PDFs, and for books never
  sent to a Kobo, you land on the nearest chapter. Page numbers still differ
  between devices, because each device paginates for its own screen.
  Troubleshooting lives in [`kobo-reading-state-sync.md`](kobo-reading-state-sync.md).

## 14. Sharing a book (giving it away)

You can hand a DRM-free book (**EPUB, MOBI, AZW3 or PDF**) to someone in person —
*"you can have it from me"* — straight from the reader.

- **Where:** open the book in the reader (Shelf → **Read**); in the reader's top
  bar, the **share** icon (between the offline-download icon and **Aa**).
- **What happens:** Colophon hands the file to your phone's normal share sheet —
  **AirDrop, Nearby Share, Messages, mail** — and your friend gets the file
  directly. No accounts, nothing exposed to the internet.
- **When it's unavailable**, the button explains why instead of failing silently:
  - **DRM** — a copy-protected book can't be shared (the recipient couldn't open
    it anyway).
  - **Not a secure connection** — sharing needs HTTPS; open Colophon via your
    Tailscale `https://…` address rather than the plain `http://` LAN address.
  - **Browser without file-sharing** (e.g. desktop Firefox) — it falls back to a
    plain download so you can send the file yourself.

## 15. Kobo wireless sync

This points a Kobo e-reader at Colophon as if it were Kobo's own store: your
library, covers and titles appear on the device, you tap to download, and reading
progress syncs both ways over WiFi. One-time setup, then it's automatic.

**Setup** is a short, one-time job — the step-by-step (editing the Kobo's
`.conf`, generating a device URL) is in the project README under *Setting up Kobo
sync*. In Colophon, you manage devices under **Kobo sync** (Tools): add a device,
copy its URL (shown once), or revoke one.

**Good to know:**

- The first download of each book converts EPUB → KEPUB on the fly (a couple of
  seconds); later opens are instant.
- **Only books delivered to the Kobo by Colophon sync their reading state.** A
  book you side-loaded onto the Kobo by USB, or bought from the Kobo store, is a
  different copy as far as the device is concerned — its progress can't sync.
- Reading progress is device-local until the Kobo actually syncs, so a book you
  read offline shows up in Colophon only after the next sync.

**Troubleshooting** (more in the README): if nothing appears after a sync, the
URL in the Kobo's `.conf` is usually wrong; if books appear but covers don't,
it's the `image_host`/`image_url_template` lines (they must include the port).

## 16. Syncing to an upstream library

This whole section is **optional**: Colophon is self-contained, and if its own
book folder is your only library you can skip ahead. It matters when you keep
a "master" copy of your books elsewhere — for example a NAS share, perhaps
served by Komga or Kavita — and want Colophon to act as the curation front-end
for it: Colophon then works against a local copy and pushes the files it has
changed up to the master on your command.

**Why two libraries at all?** Because keeping a live e-book library directly on
a network share is a known way to lose it. Calibre's own manual says it
plainly: *"Do not put your calibre library on a networked drive"* — network
filesystems have unreliable file locking, and a library database that lives on
one (or gets opened from two places at once) ends up corrupted. Colophon is
built around that lesson: the database and your working library stay on fast
local disk where locking works, and the upstream library is treated as a
**passive file mirror** that Colophon only touches during explicit,
previewed sync steps — it never keeps state there and never writes to it in
the background. You get the convenience of a server-hosted library without
gambling its integrity on a network filesystem.

- When you've edited books (so their files differ from upstream), a **Sync to
  library** item appears in the sidebar with a count of pending files.
- Clicking it shows a **preview** of what's about to be pushed; you confirm, and
  it syncs. Nothing leaves until you confirm.
- Pulls never overwrite files you've changed locally, and pushes never delete
  anything upstream on their own.

This keeps the server you actually serve from (Komga/Kavita) in step with the
metadata and covers you curated in Colophon.

**Cleaning up after author-folder moves.** Moving a book into an author folder
(§4) changes its path — so after the next push, the upstream library holds the
new copy *and* the old one. With **Clean up moved files upstream on push**
enabled (AI settings, under the upstream section; off by default), the same
push removes the old copy: only files Colophon itself pushed there, only after
the new copy is verified in place, and always listed in the preview first
("N old copies of moved books will be removed upstream"). Until you enable it,
old copies simply stay as duplicates — nothing is forgotten, and the cleanups
run retroactively at the next push once you switch it on.

## 17. Settings

All settings live in the sidebar. API keys set in the UI **override**
environment variables.

- **API settings** — keys for Google Books, Hardcover and others, and toggles to
  turn individual metadata and cover **sources** on or off.
- **AI settings** — choose your AI provider and model, paste the key, and watch
  token **usage**. Providers: **Mistral** (recommended, generous free tier),
  **OpenAI**, **DeepSeek** (very cheap), or **Ollama** (local, free, no key).
- **Kobo sync** — your registered devices, each device's sync URL, the `.conf`
  snippet to paste, and the revoke control.
- **Library owner label** — an optional name shown under the logo, so a
  per-person instance identifies itself (set via the `COLOPHON_LIBRARY_OWNER`
  environment variable).

## 18. Install as an app (PWA)

Colophon is an installable web app. On a phone or tablet, use your browser's
**Add to Home Screen**; on desktop, the **install** icon in the address bar. It
then opens full-screen like a native app. (Installing also makes offline reading
storage durable on iOS.) When a new version is deployed, a small **New version
available → Reload** prompt appears — it never interrupts you mid-edit.

## 19. Language and theme

- **Language** — switch **EN / SV** in the top bar at any time. Adding a
  third language is described in the README.
- **Theme** — the sun/moon button toggles **light / dark**. Your choice is
  remembered on the device.

## 20. Glossary

- **Library entry / group** — one book in your library. If you have several
  *formats* of the same title, they're one entry (a "group").
- **Embedded metadata** — the title/author/etc. stored *inside* the e-book file.
  Colophon reads it first and writes your edits back into it.
- **Enrichment** — filling in or improving metadata from online sources.
- **Manual metadata / locked cover** — a book you edited by hand, or a cover you
  locked, so automatic enrichment leaves it alone.
- **Tentative / Confirmed / Authority-linked author** — an author's status (see
  §10); only confirmed and authority-linked names are written into files.
- **Reading state** — *Unread / Reading / Finished* plus a progress percentage,
  shared between the browser reader and the Kobo.
- **KEPUB** — Kobo's enhanced EPUB format; Colophon converts to it on the fly
  when a Kobo downloads a book.
- **Upstream library** — a separate "master" store (e.g. Komga) that Colophon can
  push curated files to.
- **PWA** — Progressive Web App; a website you can install like an app.

---

*Colophon is a personal project, built first and foremost for my own library and
shared as-is. This handbook describes it as it currently stands; features come
and go to suit how I use it.*
