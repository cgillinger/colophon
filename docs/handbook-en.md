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

## 5. Opening and editing a book

Click a book (a row in Table, a cover in Shelf) to open its **details**. From
here you can:

- **Edit the fields** — title, author, series and position, description,
  publisher, language, ISBN, genres, published date. Click **Save** to write
  your changes. Saving also writes the metadata **back into the e-book file**, so
  other tools (Komga, Kavita, your Kobo) see the same data.
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

- **Search depth.** When fetching (especially in batch), you can choose how hard
  to look — a quick pass over the fast sources, or a deeper search that brings in
  the slower ones.

## 7. AI features

AI is optional and only runs when you ask. Configure a provider in **AI
settings** first (Mistral, OpenAI, DeepSeek, or a local Ollama — see §17).

- **Ask AI** (in a book's details) — when the ordinary sources can't pin down a
  book's **series** and position, AI can infer it. It proposes; you review and
  approve.
- **AI author check** (on the Authors page) — for two names that look like the
  same person, AI can advise whether they really are. Advisory only — you decide.
- **Usage stats** — *AI settings* shows how many tokens you've spent, so there
  are no surprises on a metered plan.

## 8. Covers

- **Finding a cover** — open a book and look up cover art. Colophon searches
  **Open Library, Google Books, Hardcover, Wikidata/Commons** and **DuckDuckGo**
  and shows you the candidates to pick from.
- **Locking a cover** — once you're happy with a cover, lock it so enrichment and
  rescans never replace it.
- Covers are stored from the file and cached at display size, so catalogue views
  stay quick.

## 9. Doing many books at once: batch operations

Select several books (tick them in Table, or multi-select) and open **Batch
operations** to enrich them all in one run.

1. **Choose what to fill** — e.g. *Basic info*, *Description*, and other field
   groups. Tick only what you want touched.
2. **Choose search depth** and whether to **overwrite** existing values, and a
   **maximum** number of books for this run.
3. **Run** — progress streams as it works; if it hits your maximum it stops and
   tells you to run again for the next batch.
4. **Review the summary** — a tidy report of what was saved and any files it
   couldn't write back to.

The same wizard can run cover lookups and AI across a selection. Batch
operations change many books at once, so they always confirm before writing.

## 10. Managing authors

Colophon keeps **one canonical entry per author**, so every book by the same
person is labelled identically — even when the files spell the name differently
("J.R.R. Tolkien" / "Tolkien, J.R.R." / "JRR Tolkien" all become one author).

- **The author field** in a book's details is backed by the registry: start
  typing and it suggests existing authors, so you reuse an entry instead of
  creating a near-duplicate.
- **The Authors page** (Tools → *Authors*) is where you curate the registry:
  - **Confirm** tentative entries — filter to unconfirmed, tick several, confirm
    them in one go. This is the fastest way to tidy up after a scan.
  - **Rename** or **Merge** — both cascade, relabelling every linked book in one
    sweep.
  - **Verify** against Wikidata to anchor an author with authority ids (QID,
    VIAF, LIBRIS).
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

## 11. Finding and clearing duplicates

**Find duplicates** (Tools) scans for books that look like the same title (fuzzy
matching, so it catches near-misses) and presents the candidate pairs for you to
review and clean up. Nothing is deleted without your say-so.

## 12. Reading in the browser

Colophon has a built-in reader — no app needed. It opens **EPUB, MOBI and
AZW3**; DRM-protected files can't be opened (Colophon never strips DRM).

- **Open it** from a book's details in **Shelf** view: tap **Read** (EPUB,
  MOBI, AZW3). MOBI and AZW3 reflow just like EPUB, so the reading settings
  below apply to them too.
- **Turn pages** by tapping the left/right edges, or with the arrow keys.
- **Reading settings** (the **Aa** button) let you tune:
  - **Theme** — Light, Sepia, Dark.
  - **Text size**, **Font** (the publisher's own, Serif, Sans, or a
    **dyslexia-friendly** face), **Line spacing**, **Margins**.
  - **Reading mode** — Paged (tap to turn) or Scroll.
  These are remembered across books.
- **Save for offline** (the download icon) caches the book so you can read it
  with no connection; your progress is kept locally and re-syncs when you're back
  online. *Requires a secure (HTTPS) connection* — see §15 on serving over
  Tailscale.

Your reading position is saved automatically and **syncs with your Kobo** (see
§13).

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
- **Note:** exact-page sync works between Kobo readings of the same book; the
  browser reader resumes by **percentage**, because a browser and a Kobo describe
  positions in different ways. The technical details (and troubleshooting) live
  in [`kobo-reading-state-sync.md`](kobo-reading-state-sync.md).

## 14. Sharing a book (giving it away)

You can hand a DRM-free EPUB to someone in person — *"you can have it from me"* —
straight from the reader.

- **Where:** open the book in the reader (Shelf → **Read**); in the reader's top
  bar, the **share** icon (between the offline-download icon and **Aa**).
- **What happens:** Colophon hands the EPUB to your phone's normal share sheet —
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

If you keep a "master" library elsewhere — for example a Komga share — Colophon
can push the files it has changed up to it.

- When you've edited books (so their files differ from upstream), a **Sync to
  library** item appears in the sidebar with a count of pending files.
- Clicking it shows a **preview** of what's about to be pushed; you confirm, and
  it syncs (using rsync under the hood). Nothing leaves until you confirm.

This keeps the server you actually serve from (Komga/Kavita) in step with the
metadata and covers you curated in Colophon.

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

- **Language** — switch **EN / SV** in the top bar at any time. (Adding a third
  language is just a translation file — see the README.)
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
