# Colophon — self-hosted e-book metadata manager with Kobo wireless sync

[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/) [![Flask](https://img.shields.io/badge/flask-3.x-green?logo=flask)](https://flask.palletsprojects.com/) [![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/) [![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](https://github.com/cgillinger/colophon/releases) [![i18n](https://img.shields.io/badge/i18n-EN%20%7C%20SV-yellow)](#-internationalisation) [![Kobo compatible](https://img.shields.io/badge/Kobo-wireless%20sync-FF6E1F?logo=rakuten&logoColor=white)](#-kobo-wireless-sync) [![Self-hosted](https://img.shields.io/badge/self--hosted-✓-blueviolet)](#) [![GitHub stars](https://img.shields.io/github/stars/cgillinger/colophon?style=social)](https://github.com/cgillinger/colophon/stargazers) [![Last commit](https://img.shields.io/github/last-commit/cgillinger/colophon)](https://github.com/cgillinger/colophon/commits/main)

Colophon is a **self-hosted e-book metadata manager** for home libraries. Drop your EPUBs (and MOBI, AZW3, KEPUB, PDF, CBZ, CBR) into a folder and Colophon will scan them, fetch fresh metadata from Google Books and Calibre, identify book series with AI, pick the best cover art from five free sources, and let a Kobo e-reader sync the result wirelessly as if it were the Kobo store.

Built for home use. Plays nicely with **Komga**, **Kavita**, **Bookstation**, and any other server that reads embedded metadata from e-book files. Self-hosted, MIT-licensed, no telemetry, runs in a single Docker container.

> **Keywords for the algorithm:** ebook server, kobo sync, kobo wireless, komga alternative, calibre alternative, ebook metadata, self-hosted library, EPUB management, kepubify, koreader.

---

## What Colophon is — and isn't

Colophon is a **metadata manager**. The simplest way to understand the scope: anything that's *data about books in your library* belongs here. Anything else doesn't.

That includes two kinds of metadata:

- **Bibliographic metadata** — title, author, ISBN, description, cover art, series, publisher, language. Facts about the book that exist in the world independent of you.
- **Library-state metadata** — reading progress, finished date, started date, your personal rating *(planned)*, tags and collections *(planned)*. Facts about *your* relationship to the book.

Kobo wireless sync is a consequence of this scope, not a separate feature: because Colophon knows about every book in your library and can serve their files and covers, a Kobo can use it as if it were the official Kobo store. The reading state your Kobo sends back is just more metadata.

### What it does

- Scans a folder of e-book files and builds a queryable catalogue
- Fetches and cleans bibliographic metadata from Google Books, Calibre's metadata sources, and embedded EPUB data
- Identifies book series with AI (Mistral / OpenAI / DeepSeek / local Ollama)
- Finds cover art from five free sources
- Writes metadata back into the e-book files so other tools see the same data
- Lets one or more Kobo e-readers sync wirelessly — covers, titles, downloads, reading progress *(Phase 3)*
- Survives multiple devices: progress from one Kobo carries over to another

### What it isn't

- **Not a reader.** You don't open books inside Colophon. Open them in your e-reader, in Calibre, in KOReader, on a Kobo.
- **Not a comic server.** Kavita and Komga handle CBZ/CBR/manga page-by-page reading with the polish that domain needs. Colophon can store comics as files but doesn't render them.
- **Not multi-user.** No accounts, no permissions, no per-user libraries. One household, one library, one set of metadata.
- **Not an OPDS server.** If your reader app expects an OPDS catalogue, use Komga in front of (or instead of) Colophon.
- **Not exposed to the internet.** Bind it to your LAN. The Kobo sync flow uses path-based tokens, not real authentication; security beyond your local network is out of scope.
- **Not a backup tool.** Colophon writes to your e-book files. Keep your own backups.

### Where the line goes

For features other people request, the test is *"is this data about books in my library?"*

Likely yes → could fit:

- Personal ratings, notes, highlights
- Tags, collections, virtual shelves
- "Loaned to X" / physical-shelf location
- Importing reading history from Goodreads / StoryGraph
- Aggregate statistics ("year in books")

Likely no → belongs in a different tool:

- An in-browser reader
- User accounts / roles / sharing
- Real-time annotation sync between users
- Page-level comic rendering
- Audiobook playback

If you want all of that in one piece of software, you want Komga or Kavita. If you want clean metadata curation with AI assistance and your Kobo to behave, you want Colophon.

---

## Features

### 📚 Library management

- Automatic file scanning: EPUB, MOBI, AZW3, KEPUB, PDF, CBZ, CBR
- Format grouping — multiple formats of the same book appear as one entry
- Batch operations for bulk metadata management
- Compact list view and gallery view
- Search and filter by title, author, ISBN, genre, status

### 🔍 Metadata enrichment

- **Google Books API** — automatic metadata fetching
- **Calibre metadata** — reads embedded metadata directly from e-book files
- Smart scoring — picks the best match from multiple sources
- Field-by-field review before changes are applied
- Smart replacement rules — only overwrites when fetched data is better

### 🤖 AI-assisted metadata

- Series identification — AI recognises book series and volume numbers
- Provider-agnostic — works with Mistral (free tier), OpenAI, DeepSeek, Ollama (local)
- Transparent review — see what the AI suggests and why, accept fields individually
- The reasoning behind each suggestion is shown

### 🖼️ Cover search

- Five sources: Open Library, Google Books, Hardcover, Wikidata/Wikimedia Commons, DuckDuckGo
- Thumbnail grid — see all candidates, click to select
- Independent from metadata enrichment — fast, doesn't interrupt the main workflow
- Works without API keys (all free sources)

### ⚙️ Settings

- Web UI for all API keys — no `.env` editing required
- Hybrid model: UI values take priority, environment variables as fallback
- "Test connections" button with per-source status
- Collapsible instructions for obtaining each API key

### 📖 Kobo wireless sync

- Point a Kobo e-reader at Colophon and it syncs your library wirelessly, like the official Kobo store
- Covers, titles, authors and series info show on the device
- Books download on-demand when you tap them; EPUB is converted to KEPUB on the fly for accurate reading-position tracking
- One unique URL per device, revokable from the settings UI
- See [Setting up Kobo sync](#setting-up-kobo-sync) below

### 🌐 Internationalisation

- English (default) and Swedish
- Language switcher in the top bar
- Easy to add more languages (see [Adding a language](#adding-a-language))

---

## Quick start

```bash
git clone https://github.com/cgillinger/colophon.git
cd colophon
cp .env.example .env
# Edit .env — set at least COLOPHON_SECRET_KEY
docker compose up -d
```

Open `http://localhost:5000` in your browser.

---

## Environment variables

All variables are read from `.env` (loaded via `env_file` in `docker-compose.yml`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `COLOPHON_SECRET_KEY` | Yes | — | Secret key for Flask sessions |
| `COLOPHON_LIBRARY_DIR` | No | `/books` | Book folder inside the container |
| `COLOPHON_DATA_DIR` | No | `/data` | Data folder (database, covers) inside the container |
| `COLOPHON_LIBRARY_HOST` | No | `./bibliotek` | Host path mounted as the book folder |
| `COLOPHON_DATA_HOST` | No | `./data` | Host path mounted as the data folder |
| `COLOPHON_LOG_LEVEL` | No | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `COLOPHON_PUBLIC_URL` | Only for Kobo sync | — | The URL the Kobo will use to reach Colophon, e.g. `http://192.168.x.x:5000`. Include the port. See [Setting up Kobo sync](#setting-up-kobo-sync). |
| `COLOPHON_GOOGLE_BOOKS_KEY` | No | — | Google Books API key |
| `COLOPHON_AI_API_URL` | No | Mistral URL | AI chat completions endpoint |
| `COLOPHON_AI_API_KEY` | No | — | AI provider API key |
| `COLOPHON_AI_MODEL` | No | `mistral-small-latest` | AI model name |
| `COLOPHON_UPSTREAM_DIR` | No | — | Upstream library path inside the container (for sync) |

> **Note:** All API keys can also be configured through the web UI at **Settings → API settings**. UI values take priority over environment variables.

---

## Cover sources

| Source | Key required | Searches by |
|---|---|---|
| Open Library | No | ISBN |
| Google Books | No | ISBN, title, author |
| Hardcover | Optional token | ISBN, title, author |
| Wikidata/Commons | No | ISBN |
| DuckDuckGo | No | Title, author |

---

## AI providers

| Provider | URL | Free tier |
|---|---|---|
| Mistral (recommended) | `https://api.mistral.ai/v1/chat/completions` | ~1M tokens/month |
| OpenAI | `https://api.openai.com/v1/chat/completions` | Pay-as-you-go |
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | Very cheap |
| Ollama (local) | `http://localhost:11434/v1/chat/completions` | Free, no key needed |

---

## Adding a language

Colophon uses Flask-Babel with gettext for translations. Adding a new language requires no code changes — just a translation file.

### Steps

1. **Initialise the language:**
   ```bash
   # Inside the container or development environment:
   pybabel init -i messages.pot -d app/translations -l <LANG_CODE>
   ```
   Example for German: `pybabel init -i messages.pot -d app/translations -l de`

2. **Translate the strings:**
   Edit `app/translations/<LANG_CODE>/LC_MESSAGES/messages.po`

   Each entry looks like:
   ```po
   msgid "Search covers"
   msgstr ""  ← fill in your translation
   ```

3. **Compile:**
   ```bash
   pybabel compile -d app/translations
   ```

4. **Register the language:**
   Add your language code to the `SUPPORTED_LANGUAGES` tuple in `app/__init__.py`.

5. **Rebuild and test:**
   ```bash
   docker compose down && docker compose build --no-cache && docker compose up -d
   ```

### Contributing a translation

If you'd like to contribute a translation, submit a PR with:
- The `.po` file in `app/translations/<LANG_CODE>/LC_MESSAGES/`
- Your language code added to the supported languages list

No Python knowledge needed — just translate the strings in the `.po` file!

---

## Setting up Kobo sync

This makes your Kobo e-reader use Colophon as if it were Kobo's official store. You sync books over WiFi, see covers and titles on the device, and tap to download — no more dragging EPUB files over USB.

**Before you start, you'll need:**

- A Kobo e-reader (Libra, Clara, Sage, Forma, Aura — anything modern)
- The Kobo on the same WiFi as your Colophon server
- A USB cable for the Kobo (one-time setup only)
- A computer (Linux, Mac or Windows)
- The Kobo signed in to a real Kobo account, with WiFi configured

It's a one-time configuration. After this the Kobo syncs on its own whenever you press **Sync** on the device.

### Step 1 — Set the public URL in Colophon's environment

Colophon needs to know the URL the Kobo will use to reach it. Add this line to your `.env` file:

```
COLOPHON_PUBLIC_URL=http://192.168.x.x:5000
```

Replace `192.168.x.x:5000` with whatever URL your Colophon is actually reachable at from inside your network — the same one you type into a browser to open the Colophon web UI. **Include the port number** if it's not 80.

Restart Colophon (`docker compose up -d` or `docker compose restart`) for the change to apply.

### Step 2 — Generate a URL for your Kobo in Colophon

1. Open Colophon in your browser.
2. Click the device icon in the top bar (or go to Settings → Kobo Sync).
3. Click **Add device**, give it a name (e.g. "Libra in the kitchen"), and click **Generate URL**.
4. A long URL appears, something like `http://192.168.x.x:5000/kobo/abc123def456...`. **Copy it.**

Important: the URL only shows once. If you lose it, revoke it and generate a new one.

### Step 3 — Connect your Kobo to your computer with USB

Plug the Kobo into your computer using a USB cable.

The Kobo will pop up a question on its screen: **"Connect"** vs **"Continue reading"** — pick **Connect**.

Your computer should see the Kobo as a USB drive:

- **Mac:** it appears in Finder under "Locations". Look for **KOBOeReader**.
- **Windows:** open This PC / File Explorer. Look for **KOBOeReader**.
- **Linux (Ubuntu/Mint):** it usually mounts automatically and shows up in your file manager's sidebar.

### Step 4 — Find the configuration file

The file you need to edit is at this path on the Kobo:

```
KOBOeReader/.kobo/Kobo/Kobo eReader.conf
```

The `.kobo` folder starts with a dot, which means it's **hidden** on most systems. Show hidden files:

- **Mac (Finder):** press `Cmd + Shift + .` (period). The folder appears.
- **Windows (File Explorer):** View tab → tick "Hidden items".
- **Linux:** in most file managers, `Ctrl + H` toggles hidden files.

Once you can see `.kobo`, navigate to `.kobo/Kobo/`. You'll see `Kobo eReader.conf` there.

### Step 5 — Edit the configuration file

**Important:** use a plain text editor. **Not** Microsoft Word, **not** TextEdit in rich-text mode, **not** Google Docs. Those will silently add formatting that breaks the file.

Good editors:

- **Mac:** TextEdit (in plain-text mode: Format → Make Plain Text), or Sublime Text
- **Windows:** Notepad, Notepad++
- **Linux:** xed, gedit, nano, vim

Open `Kobo eReader.conf`. It's a long file with sections in square brackets like `[OneStoreServices]`.

Find the section that starts with `[OneStoreServices]`. Inside that section, locate **four** lines (some might not exist yet):

```
api_endpoint=...
image_host=...
image_url_template=...
image_url_quality_template=...
```

Replace those four lines with these (paste the long URL you copied in step 2 in place of `<YOUR-COLOPHON-URL>`):

```
api_endpoint=<YOUR-COLOPHON-URL>
image_host=http://192.168.x.x:5000
image_url_template=<YOUR-COLOPHON-URL>/v1/books/{ImageId}/thumbnail/{Width}/{Height}/false/image.jpg
image_url_quality_template=<YOUR-COLOPHON-URL>/v1/books/{ImageId}/thumbnail/{Width}/{Height}/{Quality}/{IsGreyscale}/image.jpg
```

The last three lines must include `http://192.168.x.x:5000` with the **port number** — the Kobo's quirk strips the port from headers, so we have to write it explicitly.

Make sure no extra spaces, no quotation marks around the URLs. Save the file.

**Tip:** before you save, also use File → Save As (or copy the original) to keep a backup as `Kobo eReader.conf.bak` next to it. If anything goes wrong, you can restore the original and the Kobo behaves normally again.

### Step 6 — Eject the Kobo safely

- **Mac:** click the eject button next to KOBOeReader in Finder, or drag it to the Trash icon (which becomes an eject icon).
- **Windows:** right-click KOBOeReader in This PC → Eject. Or use the "Safely Remove Hardware" tray icon.
- **Linux:** right-click in file manager → Eject / Safely Remove.

Wait for the Kobo's screen to say it's safe to disconnect. **Then** unplug the cable.

### Step 7 — Sync on the Kobo

The Kobo will reload its library. Then:

1. On the Kobo, tap **Settings** → **Sync now**.
2. Wait. First sync of a large library takes a minute or two (about a second per 100 books for the protocol, then the Kobo spends a while updating its internal index).
3. Books from Colophon appear in **My Books**.

Tap a book to download it. The first download per book takes a couple of seconds (Colophon converts EPUB to KEPUB on the fly). Subsequent reads are instant.

### Troubleshooting

**Nothing shows up after Sync.** Check Colophon's logs — `docker logs colophon` — for lines containing `192.168.50.46` or whatever your Kobo's IP is. If you see HTTP requests there, sync is happening; the Kobo just needs more time. If you see nothing, the URL in your conf file is wrong.

**Books appear but covers don't load.** The `image_host` / `image_url_template` lines are wrong or missing the port. Go back to step 5.

**"Sync failed" on the Kobo.** Try restarting the Kobo (hold the power button 8 seconds). If still failing, double-check that `COLOPHON_PUBLIC_URL` in `.env` exactly matches the URL the Kobo can reach.

**You want to remove a device.** Settings → Kobo Sync in Colophon → trash icon next to the device.

**You want to undo and use Kobo's real store again.** Restore the backup `Kobo eReader.conf.bak`, or replace `api_endpoint=...` with `api_endpoint=https://storeapi.kobo.com` and remove the `image_*` lines.

---

## Works well with

Colophon manages metadata for e-book files on disk. It pairs well with:

- **[Komga](https://komga.org/)** — comic/e-book media server
- **[Kavita](https://www.kavitareader.com/)** — self-hosted reading server
- **Bookstation** — e-book server with reading support

Colophon writes metadata back into e-book files, so any reader that parses embedded metadata will benefit.

---

## A note about this project

Colophon is a personal project I built for managing my own e-book library. I'm sharing it because it might be useful to others in a similar situation, but please keep in mind:

- **This is a hobby project.** I work on it when I have time and energy, which means updates may be sporadic.
- **Pull requests are welcome**, but I may not always be able to review them promptly. Please don't take slow responses personally — it's a matter of time, not interest.
- **Issues and bug reports are appreciated!** They help me understand what matters to other users. Even if I can't fix everything right away, I read everything.
- **Use at your own risk.** This software is provided as-is. Always keep backups of your e-book files.

If you find Colophon useful, that makes my day. If you improve it, even better. 🙂

---

## License

MIT License — see [LICENSE](LICENSE) for details.
