# Colophon — self-hosted e-book library manager with Kobo wireless sync

[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/) [![Flask](https://img.shields.io/badge/flask-3.x-green?logo=flask)](https://flask.palletsprojects.com/) [![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/) [![GHCR](https://img.shields.io/badge/ghcr.io-prebuilt%20image-2496ED?logo=github&logoColor=white)](https://github.com/cgillinger/colophon/pkgs/container/colophon) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Version](https://img.shields.io/badge/version-1.42.0-brightgreen)](https://github.com/cgillinger/colophon/releases) [![Kobo compatible](https://img.shields.io/badge/Kobo-wireless%20sync-FF6E1F?logo=rakuten&logoColor=white)](#setting-up-kobo-sync)

**Colophon — the e-book manager.** A self-hosted web app that turns a messy folder of e-book files into a clean, browsable library and syncs it to a Kobo e-reader over WiFi. (Not the printing/publishing term — this is the software.)

Colophon scans a folder of e-book files (EPUB, MOBI, AZW3, KEPUB, PDF, CBZ, CBR), fetches and merges metadata from several sources (Google Books, Hardcover, Open Library, Wikidata, Wikipedia, LIBRIS, Calibre), uses AI to detect series, finds cover art, and lets a Kobo e-reader sync the whole library over WiFi.

This is a personal project I built for my own library. I've published it in case someone else has the same problem and can use it as a head start. Runs in one Docker container, MIT-licensed, no telemetry. It started life as a metadata companion to other tools but has grown into a complete library manager in its own right — cataloguing, reading, organising and device sync, no other software required. Think of it as a lightweight alternative to Calibre and Calibre-Web; and because it writes metadata back into the files, it also plays nicely with Komga, Kavita and other servers that read embedded metadata, if you run one.

📖 **New here?** The **[User Handbook](docs/handbook-en.md)** (också på **[svenska](docs/handbook-sv.md)**) walks through every feature in plain language, with a look-up index — so you can jump straight to *Sharing a book*, *Kobo sync*, *Managing authors*, and so on.

---

## Screenshots

> Sample library — the books, covers and authors shown are fictional placeholders.

**Shelf view** — the library as a cover wall, with a "Reading now" band that picks up where you left off.

![Shelf view](docs/screenshots/library-shelf.png)

**Table view** — a sortable, filterable metadata table.

![Table view](docs/screenshots/library-table.png)

**Book details** — metadata, reading state, rating, and a one-tap reader.

![Book detail](docs/screenshots/book-detail.png)

**In-browser reader** — read EPUB, MOBI, AZW3 and PDF in any browser; progress syncs back to your Kobo. Select a word to look it up: English definition + Swedish translation from open-source dictionaries (auto-downloaded on first use), with an optional AI explanation of the word in its sentence.

![In-browser reader](docs/screenshots/reader.png)

---

## What it does

- Scans a book folder and builds a catalogue
- Adds books by drag-and-drop or a file picker — batch upload, no rescan needed; freshly added books wear a "New" badge for a while
- Fetches metadata from seven sources (Google Books, Hardcover, Open Library, Wikidata, Wikipedia, LIBRIS, Calibre) and merges them field by field
- Uses AI as an optional cataloguing assistant — series detection, metadata suggestions, author disambiguation and in-reader word explanations, always propose-only (Mistral, OpenAI, DeepSeek, or fully local Ollama)
- Finds covers from Open Library, Google Books, Hardcover, Wikidata, DuckDuckGo
- Writes metadata back into the files so other tools see the same data
- Keeps authors consistent — one canonical entry per author, spelling variants auto-linked, typos flagged for review, one-click merge/rename that relabels every book, with optional Wikidata verification
- Handles books with several authors — one field per person in the edit view (no separator syntax to learn), every co-author searchable and linkable, and a **Split** tool that turns a mashed-together entry ("A and B") into proper person entries across all their books
- Organises uploads into per-author folders on demand — a deliberate button per book, never an automatic move — and cleans up the old copy on your upstream library after the move (opt-in, verified, surgical)
- Groups multiple formats of the same book as one entry
- Syncs to a Kobo over WiFi — covers, downloads, reading progress
- Reads EPUB, MOBI, AZW3 and PDF in the browser — themes, fonts (incl. a dyslexia-friendly face) and **save-for-offline** — with reading progress synced to and from your Kobo
- Looks up words while you read — select a word to get an English definition (GCIDE/Webster) and Swedish translation (FreeDict/WikDict); open-source dictionaries download automatically on first use, plus an optional AI explanation of the word in its exact sentence
- Hands a DRM-free book (EPUB, MOBI, AZW3 or PDF) to a friend in person, straight from the reader via your phone's share sheet
- Installs as an app (PWA) on phone, tablet or desktop
- UI in English and Swedish, light and dark themes

## What it doesn't do

- Render comics page by page (Komga and Kavita do that well)
- Multi-user accounts
- OPDS
- Internet-facing auth (it's a LAN tool; Kobo sync uses path tokens)
- Backups — it writes to your files, so keep your own

---

## How it compares

If you've searched for any of these, Colophon is aimed at you:

- **A Calibre / Calibre-Web alternative** when you mainly want clean metadata, covers and a nice library view, without running the full Calibre desktop stack.
- **Wireless Kobo sync for a self-hosted library** — point a Kobo at your own catalogue instead of the Kobo store, and get covers, downloads and reading-progress sync over WiFi. No cable after setup.
- **A metadata front-end for Komga or Kavita** — Colophon writes metadata *back into the files*, so the server you already run picks up the same titles, authors, series and covers.
- **An in-browser reader** (EPUB, MOBI, AZW3, PDF) with reading progress that syncs to and from your Kobo, and word lookup backed by open-source dictionaries.
- **AI-assisted cataloguing** — series detection, metadata suggestions and author disambiguation with a propose-only guardrail. Bring any OpenAI-compatible provider, or keep it fully private with local Ollama. I haven't found another self-hosted book server that does this.

It is *not* a comics page-reader, a multi-user server, or an internet-facing app — see [What it doesn't do](#what-it-doesnt-do).

---

## Quick start

### Option 1: prebuilt image (recommended)

A ready-made multi-arch image (x86_64 + ARM64 — works on regular servers, Synology NAS and Raspberry Pi) is published to GitHub Container Registry on every code change: [`ghcr.io/cgillinger/colophon`](https://github.com/cgillinger/colophon/pkgs/container/colophon). No cloning or building needed — save this as `docker-compose.yml` in an empty folder:

```yaml
services:
  colophon:
    image: ghcr.io/cgillinger/colophon:latest
    container_name: colophon
    ports:
      - "5000:5000"
    volumes:
      - ./bibliotek:/books:rw   # your book folder
      - ./data:/data:rw         # database, covers, caches
    environment:
      # Generate one: python3 -c "import secrets; print(secrets.token_hex(32))"
      COLOPHON_SECRET_KEY: change-me
      # Needed for Kobo sync — the LAN address the Kobo will use:
      # COLOPHON_PUBLIC_URL: http://192.168.x.x:5000
    restart: unless-stopped
```

Then:

```bash
docker compose up -d
```

Open `http://localhost:5000`. To update later:

```bash
docker compose pull && docker compose up -d
```

`:latest` follows the main branch. Prefer pinned releases? Use a version tag instead, e.g. `ghcr.io/cgillinger/colophon:1.42.0` — every [release](https://github.com/cgillinger/colophon/releases) gets a matching image tag.

### Option 2: build from source

```bash
git clone https://github.com/cgillinger/colophon.git
cd colophon
cp .env.example .env
# Set at least COLOPHON_SECRET_KEY
docker compose up -d
```

Open `http://localhost:5000`.

---

## Environment variables

All variables are read from `.env` (loaded via `env_file` in `docker-compose.yml`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `COLOPHON_SECRET_KEY` | Yes | — | Flask session secret |
| `COLOPHON_LIBRARY_DIR` | No | `/books` | Book folder inside the container |
| `COLOPHON_DATA_DIR` | No | `/data` | Data folder (database, covers) inside the container |
| `COLOPHON_LIBRARY_HOST` | No | `./bibliotek` | Host path mounted as the book folder |
| `COLOPHON_DATA_HOST` | No | `./data` | Host path mounted as the data folder |
| `COLOPHON_LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `COLOPHON_PUBLIC_URL` | For Kobo sync | — | URL the Kobo uses to reach Colophon, e.g. `http://192.168.x.x:5000` — include the port |
| `COLOPHON_GOOGLE_BOOKS_KEY` | No | — | Google Books API key |
| `COLOPHON_AI_API_URL` | No | Mistral URL | AI chat completions endpoint |
| `COLOPHON_AI_API_KEY` | No | — | AI provider API key |
| `COLOPHON_AI_MODEL` | No | `mistral-small-latest` | AI model name |
| `COLOPHON_UPSTREAM_DIR` | No | — | Upstream library path inside the container (for sync) |
| `COLOPHON_UPSTREAM_CLEANUP_ORPHANS` | No | off | Let a push remove the old upstream copy of a book you've moved to an author folder (also a checkbox in AI settings) |
| `COLOPHON_MAX_UPLOAD_MB` | No | `1024` | Max size per uploaded file (in-app upload) |
| `COLOPHON_NEW_BADGE_DAYS` | No | `14` | Days a newly added book shows the "New" badge |
| `COLOPHON_LIBRARY_OWNER` | No | — | Label shown under the wordmark naming whose library this instance shows (e.g. `Christians bibliotek`) |

All API keys can also be set in the web UI under **Settings → API settings**. UI values take priority over environment variables.

---

## Metadata sources

Colophon queries these in a progressive flow and merges the results **field by field** (the best value per field wins, with provenance kept). Each can be toggled in **Settings → API settings**.

| Source | Key required | What it adds |
|---|---|---|
| Embedded file | No | Title, author and series already inside the e-book — treated as high-trust |
| Google Books | Optional key | Title, author, description, ISBN, categories |
| Hardcover | Optional token | Series, genres, synopsis and rating — strong for popular English titles |
| Open Library | No | Subjects, synopsis and ISBNs — strong for older or obscure titles |
| Wikidata | No | Structured series **and position in the series**, genre, author, date |
| Wikipedia | No | Fast description and a thumbnail cover as a fallback |
| LIBRIS (KB) | No | Swedish national bibliography — authoritative Swedish title/author/publisher/ISBN |
| Calibre | No | Deep tier via Calibre's own metadata plugins (Goodreads and others) |

## Cover sources

| Source | Key required | Searches by |
|---|---|---|
| Open Library | No | ISBN |
| Google Books | No | ISBN, title, author |
| Hardcover | Optional token | ISBN, title, author |
| Wikidata/Commons | No | ISBN |
| DuckDuckGo | No | Title, author |

## AI as a librarian's assistant

As far as I know, no other self-hosted book server has this: Colophon uses an
LLM as a **cataloguing assistant** — for exactly the problems where regular
metadata sources fall short. It is entirely optional (everything works without
a key), and deliberately constrained by one rule: **AI proposes, you decide.**
Every AI suggestion lands in a review view where you approve field by field;
nothing is ever written to your library or your files on an AI's say-so.

What it helps with:

- **Series detection** — the field databases are worst at. The AI reads the
  book's title, author and description and proposes the series name and the
  book's position in it, which you accept or reject per field.
- **Metadata suggestions** — "Ask AI" on a book (or a whole batch) proposes
  values for missing fields, presented side by side with what you have.
- **Author disambiguation** — for likely-duplicate author entries, the AI
  gives an advisory verdict on whether two spellings are the same person, with
  its reasoning. Merging remains your click.
- **A reading companion** — select a word in the in-browser reader and,
  alongside the dictionary definition, the AI explains what the word means *in
  that exact sentence*.

Bring any OpenAI-compatible provider — or run it fully local and private with
Ollama, where no book data ever leaves your machine. Token usage is tracked
locally in the settings so you can see what it costs you.

| Provider | URL | Free tier |
|---|---|---|
| Mistral (recommended) | `https://api.mistral.ai/v1/chat/completions` | ~1M tokens/month |
| OpenAI | `https://api.openai.com/v1/chat/completions` | Pay-as-you-go |
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | Very cheap |
| Ollama (local) | `http://localhost:11434/v1/chat/completions` | Free, no key needed |

---

## Managing authors

Colophon keeps **one canonical entry per author** so every book by the same
person is labelled identically — even when the source files spell the name
differently. The **Authors** page (in the sidebar) is where you curate that
registry. Spelling variants are auto-linked to the canonical entry, and
near-identical entries are flagged as likely duplicates.

Each entry has a status that controls whether the name is written back into
your files:

| Status | Meaning | Written to files? |
|---|---|---|
| Tentative | Created automatically from file metadata during a scan or upload | No — DB only |
| Confirmed | You confirmed the spelling is correct | Yes |
| Authority-linked | Verified against Wikidata; stores the QID, VIAF and LIBRIS ids | Yes |

What you can do from the page:

- **Filter to unconfirmed** and tick the checkboxes to **confirm several at
  once** — the fastest way to clear out freshly-scanned tentative entries.
- **Rename** or **merge** an entry — both cascade, relabelling every linked
  book in one sweep.
- **Verify** an entry against Wikidata to anchor it with authority ids.
- For likely-duplicate pairs, merge with one click, or **Ask AI** whether the
  two names are the same person (advisory only — AI proposes, you decide; needs
  an AI provider configured, see above).

Tentative entries are deliberately never written into files until you confirm
them, so an auto-guessed spelling can't quietly rewrite your library.

**Books with several authors.** The edit view shows **one field per author**
plus an *Add author* button — you never type separator characters, and every
co-author gets their own registry entry, author page and filter. Internally
Colophon uses `&` between names (the same convention Calibre has used for
years), so files written by either tool round-trip cleanly. Files that arrive
with several names mashed into one string ("Sören Karlsson och Deanne
Rauscher") become a single flagged entry; the **Split** action on the Authors
page turns it into proper person entries, relinks every affected book, and
remembers the decision so a future re-scan of the same files doesn't
resurrect the mashed entry. If the flag is wrong — sort-form names like
"Ashton, Edward" trip it on purpose, since only a human can tell them from
two surnames — click it once to dismiss it.

---

## Where your books live: local first, server optional

Out of the box, Colophon is **self-contained**: one container, with your book
folder and its database on local disk. Scanning, metadata, covers, reading,
Kobo sync and author folders all work against that one folder — no Calibre, no
Komga, no NAS required. If that's your setup, this section doesn't apply and
you're done.

**The optional upstream library.** Many self-hosters keep the *master* copy of
their books somewhere else — typically a share on a NAS or home server, often
the same folder a media server like Komga or Kavita serves from. Colophon can
work as the curation front-end for such a setup: it keeps a local working
copy, and syncs files to and from the server copy (the "upstream library") on
your command.

Why a working copy instead of pointing Colophon straight at the share? Because
keeping a *live* library on a network share is a known way to lose it.
Calibre's own manual [warns flatly](https://manual.calibre-ebook.com/faq.html):
*"Do not put your calibre library on a networked drive"* — network filesystems
have unreliable file locking, and a library database kept on one (or reached by
two programs at once) ends in corruption. The warning is sound: a database over
SMB/NFS is exactly where e-book libraries go to die.

Colophon's two-library model sidesteps the problem instead of fighting it:

- **The database and the working library live on fast local disk.** Nothing
  that needs locking ever sits on the network.
- **The upstream library is a file-only mirror.** Colophon never keeps state
  there, never holds files open over the network, and never writes to it
  in the background — a push happens when you click, after a preview of
  exactly what will be copied.
- **Pulls never overwrite your local edits** (rsync `--update`), and pushes
  never delete anything upstream on their own. The one exception is opt-in:
  after you move a book into an author folder, the old upstream copy becomes a
  duplicate, and with *upstream cleanup* enabled the next push removes it —
  only files Colophon itself put there, only after the new copy is verified in
  place, and shown in the preview first.

The moving parts — database, file writes, locking — stay on local disk where
they are safe, while the server share remains a clean, passive file tree that
any other tool can serve from.

---

## Adding a language

Colophon uses Flask-Babel. A new language is a translation file, no code changes.

1. `pybabel init -i messages.pot -d app/translations -l <LANG_CODE>` (e.g. `de`)
2. Translate `app/translations/<LANG_CODE>/LC_MESSAGES/messages.po`
3. `pybabel compile -d app/translations`
4. Add the code to `SUPPORTED_LANGUAGES` in `app/__init__.py`
5. `docker compose down && docker compose build --no-cache && docker compose up -d`

The steps are here if you'd like another language in your own copy.

---

## Setting up Kobo sync

This points a Kobo e-reader at Colophon as if it were Kobo's own store: WiFi sync, covers and titles on the device, tap to download. One-time setup; after that the Kobo syncs on its own.

You'll need: a modern Kobo (Libra, Clara, Sage, Forma, Aura) on the same WiFi as Colophon, a USB cable, and a computer. The Kobo must be signed in to a real Kobo account.

### 1. Set the public URL

Add this to your `.env`:

```
COLOPHON_PUBLIC_URL=http://192.168.x.x:5000
```

Use the URL you'd type in a browser to reach Colophon from inside your network. Include the port if it's not 80. Restart Colophon (`docker compose restart`).

### 2. Generate a device URL

In Colophon: click the device icon in the top bar (or Settings → Kobo Sync) → **Add device** → name it → **Generate URL**. Copy the URL — it only shows once. If you lose it, revoke and generate a new one.

### 3. Connect the Kobo over USB

Plug it in. When the Kobo asks **Connect** vs **Continue reading**, pick **Connect**. It appears as a USB drive called **KOBOeReader**.

### 4. Find the config file

```
KOBOeReader/.kobo/Kobo/Kobo eReader.conf
```

`.kobo` is hidden by default. Show hidden files:

- **Mac (Finder):** `Cmd + Shift + .`
- **Windows (Explorer):** View tab → tick "Hidden items"
- **Linux:** `Ctrl + H` in most file managers

### 5. Edit the config file

Use a plain-text editor — not Word, not TextEdit in rich-text mode. Notepad, Notepad++, nano, vim, gedit, Sublime are all fine. On Mac TextEdit, switch to plain text via Format → Make Plain Text.

Open `Kobo eReader.conf` and find the `[OneStoreServices]` section. Replace these four lines (some may be missing — add them):

```
api_endpoint=<YOUR-COLOPHON-URL>
image_host=http://192.168.x.x:5000
image_url_template=<YOUR-COLOPHON-URL>/v1/books/{ImageId}/thumbnail/{Width}/{Height}/false/image.jpg
image_url_quality_template=<YOUR-COLOPHON-URL>/v1/books/{ImageId}/thumbnail/{Width}/{Height}/{Quality}/{IsGreyscale}/image.jpg
```

The last three lines must include `http://192.168.x.x:5000` with the port — the Kobo strips ports from headers, so it has to be spelled out. No quotes, no extra spaces.

Keep a backup as `Kobo eReader.conf.bak` next to the original.

### 6. Eject and unplug

Eject KOBOeReader properly (Finder eject button / right-click → Eject) and wait until the Kobo says it's safe to disconnect.

### 7. Sync on the Kobo

**Settings → Sync now**. The first sync of a large library takes a minute or two. Books appear in **My Books**; tap to download. The first download per book converts EPUB to KEPUB on the fly and takes a couple of seconds. Subsequent reads are instant.

### Troubleshooting

- **Nothing after sync.** Check `docker logs colophon` for requests from the Kobo's IP. No requests = wrong URL in the conf file.
- **Books load but covers don't.** `image_host` or `image_url_template` is wrong or missing the port. Back to step 5.
- **"Sync failed".** Restart the Kobo (hold power 8s). Double-check `COLOPHON_PUBLIC_URL` matches what the Kobo can reach.
- **Remove a device.** Settings → Kobo Sync → trash icon.
- **Undo and use Kobo's store again.** Restore the `.bak`, or set `api_endpoint=https://storeapi.kobo.com` and delete the `image_*` lines.

---

## A note about this project

This is a hobby project I build for my own library and share as-is, in case it's useful to someone with the same problem. I develop it to fit my own needs, so I may not respond to issues or take on pull requests — that's a matter of time and focus, not disinterest. Use at your own risk and keep backups of your e-book files.

## License

MIT — see [LICENSE](LICENSE).
