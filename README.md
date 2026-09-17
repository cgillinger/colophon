# Colophon — self-hosted e-book library manager with Kobo wireless sync

[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/) [![Flask](https://img.shields.io/badge/flask-3.x-green?logo=flask)](https://flask.palletsprojects.com/) [![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/) [![GHCR](https://img.shields.io/badge/ghcr.io-prebuilt%20image-2496ED?logo=github&logoColor=white)](https://github.com/cgillinger/colophon/pkgs/container/colophon) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Version](https://img.shields.io/badge/version-1.62.1-brightgreen)](https://github.com/cgillinger/colophon/releases) [![Kobo compatible](https://img.shields.io/badge/Kobo-wireless%20sync-FF6E1F?logo=rakuten&logoColor=white)](#setting-up-kobo-sync)

**Colophon** is a self-hosted web app that turns a folder of e-book files into a clean, browsable library and syncs it to a Kobo e-reader over WiFi.

It scans your books (EPUB, MOBI, AZW3, KEPUB, PDF, CBZ, CBR), fills in metadata from seven sources, finds covers, reads books in the browser, and syncs the lot to a Kobo. What sets it apart is an AI that works as a cataloguing assistant, ordering series and tidying authors, and that only ever proposes. You approve every change.

One Docker container, MIT licence, no telemetry. It is a personal project built for my own library and shared in case it helps someone else. Think of it as a lighter alternative to Calibre and Calibre-Web. Because it writes metadata back into the files, it also works well alongside Komga, Kavita and other servers that read embedded metadata.

📖 **New here?** The **[User Handbook](docs/handbook-en.md)** (också på **[svenska](docs/handbook-sv.md)**) explains every feature in plain language, with an index so you can jump straight to *Kobo sync*, *Managing authors* or *Sharing a book*.

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
- Adds books by drag-and-drop or file picker, no rescan needed
- Fetches metadata from Google Books, Hardcover, Open Library, Wikidata, Wikipedia, LIBRIS and Calibre, and merges the best value per field
- Finds covers from Open Library, Google Books, Hardcover, Wikidata and DuckDuckGo
- Writes metadata back into the files, so other tools see the same data
- Groups several formats of the same book as one entry
- Keeps one entry per author, links spelling variants, flags likely typos, and can verify an author against Wikidata
- Handles books with several authors, one field per person, and can split a mashed-together name into proper entries
- Moves a book into a per-author folder when you ask, never on its own
- Works on many books at once through **scenarios**: what is missing, a language check, the order of a series, covers for a whole filter. Each one is a proposal you tick through before anything is saved
- Uses AI, if you want it, to order a series or an author's books in one pass, checked against Wikidata; to suggest metadata; to tell whether two author spellings are the same person; and to explain a word while you read. Mistral, OpenAI, DeepSeek or a local Ollama
- Syncs to a Kobo over WiFi: covers, downloads, reading progress both ways
- Reads EPUB, MOBI, AZW3 and PDF in the browser, with themes, fonts (including a dyslexia-friendly one) and save-for-offline
- Looks up words while you read: English definition, Swedish translation, and an optional AI explanation of the word in its sentence
- Hands a DRM-free book to a friend in person, from the reader via your phone's share sheet
- Installs as an app (PWA) on phone, tablet or desktop
- English and Swedish interface, light and dark themes

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
- **AI-assisted cataloguing.** This is the part I have not found in any other self-hosted book server. Order a whole series, or everything one author wrote, in one reviewed pass checked against Wikidata. Get metadata suggestions that use the spellings already in your library. Ask whether two author spellings are the same person. The AI only proposes; nothing is written until you tick the rows. See [AI as a librarian's assistant](#ai-as-a-librarians-assistant).
- **An AI that helps you read.** Select a difficult word and get a definition, a translation, and an explanation of what the word means in that sentence. Useful in a second language and for older books.
- **Your choice of engine.** Any OpenAI-compatible provider, or a local Ollama so no book data leaves your machine. Everything works without a key; the AI features simply stay off.

It is *not* a comics page-reader, a multi-user server, or an internet-facing app — see [What it doesn't do](#what-it-doesnt-do).

---

## Quick start

**You need:** Docker with Compose, a folder with your e-book files, and a computer or NAS on your home network to run it on (x86_64 or ARM64, so a Synology or a Raspberry Pi works).

### Option 1: prebuilt image (recommended)

A ready-made image is published to GitHub Container Registry on every code change: [`ghcr.io/cgillinger/colophon`](https://github.com/cgillinger/colophon/pkgs/container/colophon). No cloning or building needed.

1. Make an empty folder and save this as `docker-compose.yml` in it:

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

2. Put your e-book files in the `bibliotek` folder next to it (or change the path on the `volumes` line).

3. Start it:

```bash
docker compose up -d
```

4. Open `http://localhost:5000` (or the server's address) and click **Find new books** in the sidebar.

To update later:

```bash
docker compose pull && docker compose up -d
```

`:latest` follows the main branch. To stay on a fixed version, use a version tag instead, for example `ghcr.io/cgillinger/colophon:1.61.3`. Every [release](https://github.com/cgillinger/colophon/releases) has a matching image tag.

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

Set these in `.env` (loaded via `env_file` in `docker-compose.yml`) or under `environment:` in the compose file.

### Must set

| Variable | What it is |
|---|---|
| `COLOPHON_SECRET_KEY` | A random string that protects your browser session. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `COLOPHON_PUBLIC_URL` | Only if you use Kobo sync. The address the Kobo uses to reach Colophon, with the port, e.g. `http://192.168.x.x:5000` |

### Can set

Everything below has a sensible default. API keys can also be entered in the web UI under **Settings → API settings**, and values set there win over these.

| Variable | Default | What it does |
|---|---|---|
| `COLOPHON_LIBRARY_HOST` | `./bibliotek` | Folder on your machine that holds the books |
| `COLOPHON_DATA_HOST` | `./data` | Folder on your machine for the database and covers |
| `COLOPHON_GOOGLE_BOOKS_KEY` | — | Google Books API key. Without one, Google Books is rate-limited |
| `COLOPHON_AI_API_URL` | Mistral | The AI provider's chat endpoint |
| `COLOPHON_AI_API_KEY` | — | The AI provider's key. No key, no AI features |
| `COLOPHON_AI_MODEL` | `ministral-14b-latest` | The AI model name |
| `COLOPHON_UPSTREAM_DIR` | — | Path inside the container to an upstream library, if you sync to one |
| `COLOPHON_UPSTREAM_CLEANUP_ORPHANS` | off | Let a push remove the old upstream copy of a book you moved to an author folder |
| `COLOPHON_LIBRARY_OWNER` | — | A name shown under the logo, e.g. `Christians bibliotek` |
| `COLOPHON_NEW_BADGE_DAYS` | `14` | How many days a new book shows the "New" badge |
| `COLOPHON_MAX_UPLOAD_MB` | `1024` | Largest file the in-app upload accepts |
| `COLOPHON_USB_MOUNT_ROOTS` | `/media:/run/media:/mnt:/Volumes` | Where to look for a Kobo plugged in by USB. Set empty to turn it off |
| `COLOPHON_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `COLOPHON_LIBRARY_DIR` | `/books` | Book folder inside the container. Leave as is |
| `COLOPHON_DATA_DIR` | `/data` | Data folder inside the container. Leave as is |


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

As far as I know, no other self-hosted book server does this. Colophon uses an
AI model as a cataloguing assistant for the things the metadata databases are
worst at, series above all. It is optional, and it follows one rule: **the AI
proposes, you decide.** Every suggestion lands in a
review screen where you tick rows and fields. Nothing is written to your
library or your files on the AI's say-so.

### What it helps with

- **Series detection.** "Ask AI" on a book proposes the series name and the
  book's position, from the title, author and description.
- **Ordering a whole series.** Asking book by book is what makes numbering
  drift. Colophon asks about the series once, checks the answer against
  Wikidata, and shows every row with a status: *Confirmed* (AI and Wikidata
  agree), *Suggested* (AI alone), *Differs from what is recorded* (never
  pre-ticked), *Spelling only*. The header warns about duplicate numbers and
  gaps.
- **Ordering an author's books.** The same review across everything one
  author wrote. The AI also decides which series exist. Books it places
  outside every series get no checkbox, so a standalone can't get a number by
  accident.
- **Suggestions that know your library.** The model sees the series names and
  subjects you already use, and the author's other books. A suggestion that
  matches something you have gets your spelling, so you end up with one
  "The Expanse" instead of three variants.
- **Metadata suggestions.** "Ask AI" on a book proposes values for empty
  fields, side by side with what you have.
- **Author disambiguation.** For two author entries that look like the same
  person, the AI gives an opinion and its reasoning. Merging is your click.
- **Word explanations while reading.** Select a word in the reader and you
  get a dictionary definition, a Swedish translation, and the AI explaining
  what the word means in that exact sentence. That last part is what a
  dictionary cannot do.

### The guardrails

- **Nothing is written while the model is thinking.** Every scenario looks
  first. You get a proposal, you tick rows, then it saves.
- **Your own values are protected.** A row that contradicts something already
  recorded is red and unticked. You have to choose to overwrite it.
- **Changing the library and changing your files are separate choices.**
  Writing into the e-book files is its own checkbox, and the panel says how
  many books a synced Kobo will re-download.
- **A second opinion where one exists.** Series proposals are checked against
  Wikidata. *Confirmed* means both agree.
- **It can stay on your machine.** With Ollama, no book data leaves the house.

### Providers

Any OpenAI-compatible provider works. Token usage is tracked locally in the
settings.

| Provider | URL | Cost |
|---|---|---|
| Mistral (recommended) | `https://api.mistral.ai/v1/chat/completions` | Free tier, `ministral-*` models |
| OpenAI | `https://api.openai.com/v1/chat/completions` | Pay as you go |
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | Very cheap |
| Ollama (local) | `http://localhost:11434/v1/chat/completions` | Free, no key |

**If the AI stops answering, change the model first.** Mistral's free plan does
not include every model. A model outside the plan returns error 429, which
looks exactly like a used-up quota, even on an untouched account. As of
September 2026 the `ministral-*` models work on the free plan
(`ministral-14b-latest` is the default) and `mistral-small`, `mistral-medium`
and `magistral-small` do not. Mistral changes this from time to time. Colophon's
error message points at the model when it can tell.

---

## Managing authors

Colophon keeps **one entry per author**, so every book by the same person is
labelled the same way even when the files spell the name differently. The
**Authors** page in the sidebar is where you look after that registry.
Spelling variants are linked automatically, and near-identical entries are
flagged as likely duplicates.

Each entry has a status that decides whether the name is written into your
files:

| Status | Meaning | Written to files? |
|---|---|---|
| Tentative | Created automatically from file metadata | No, database only |
| Confirmed | You confirmed the spelling | Yes |
| Authority-linked | Verified against Wikidata | Yes |

On the page you can:

- **Confirm** several tentative entries at once. The fastest way to tidy up
  after a scan.
- **Rename** or **merge** an entry. Both relabel every linked book.
- **Verify** an entry against Wikidata. The Authority column then says who
  the person is ("British science fiction writer"). Your own books help pick
  the right person when several share a name. **Remove authority link** undoes
  a wrong match.
- **Ask AI** whether two likely duplicates are the same person. Advisory only.

Tentative entries are never written into files until you confirm them, so an
automatic guess can't quietly rewrite your library.

**Books with several authors.** The edit view shows one field per author plus
*Add author*. You never type separators. Internally Colophon uses `&` between
names, the same convention as Calibre, so files written by either tool
round-trip cleanly. A file that arrives with several names in one string
("Sören Karlsson och Deanne Rauscher") becomes one flagged entry. **Split** on
the Authors page turns it into proper person entries and remembers the
decision, so a rescan doesn't bring the mashed entry back. If the flag is
wrong, for example on a sort-form name like "Ashton, Edward", click it once to
dismiss it.

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
a live library on a network share is a known way to lose it. Calibre's manual
[says it plainly](https://manual.calibre-ebook.com/faq.html): *"Do not put your
calibre library on a networked drive."* Network filesystems have unreliable
file locking, and a database kept on one ends up corrupted.

Colophon's two-library model avoids the problem:

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

Everything that needs locking stays on local disk. The server share stays a
plain file tree that any other tool can serve from.

---

## Adding a language

Colophon uses Flask-Babel. A new language is a translation file plus one
line of code.

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

### Optional: import reading state over USB

A Kobo that has been off Wi-Fi still knows what you read on it. Plug it into the machine running Colophon and **Settings → Kobo sync** offers to import that reading state — including the exact position, not just a percentage. Colophon only reads the device; it never writes to it.

This needs Colophon to be able to see the mounted reader, so it depends on how you run it:

- **Colophon running directly on your machine** — nothing to do. The reader is found as soon as you plug it in.
- **Colophon in Docker on the same machine** — the container has to be shown where your system mounts removable media:

  ```yaml
  services:
    colophon:
      volumes:
        - /media:/media:ro          # or /run/media, or /Volumes on macOS
  ```

  Add `:rslave` instead of `:ro` if devices plugged in *after* the container starts don't show up.
- **Colophon on a server, reader plugged into a different machine** — not supported. Nothing on the server can see a device attached to another computer; use wireless sync, which is what it is for.

If you never plug a reader in, this costs nothing and shows nothing: the panel only appears when a Kobo is actually found. Set `COLOPHON_USB_MOUNT_ROOTS=` to switch the search off entirely.

---

## A note about this project

This is a hobby project I build for my own library and share as-is. I develop it to fit my own needs, so I may not respond to issues or take pull requests. Use at your own risk and keep backups of your e-book files.

## License

MIT — see [LICENSE](LICENSE).
