# Colophon

![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white) ![Flask](https://img.shields.io/badge/flask-3.x-green?logo=flask) ![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker) ![License](https://img.shields.io/badge/license-MIT-green) ![Version](https://img.shields.io/badge/version-1.0.0-brightgreen) ![i18n](https://img.shields.io/badge/i18n-EN%20%7C%20SV-yellow)

Colophon is a self-hosted e-book metadata manager. It scans a folder of e-book files, fetches metadata from multiple sources, lets AI identify book series, and searches for cover art — all through a clean web interface running in Docker.

Built for home use. Works with Komga, Kavita, Bookstation, and other e-book servers that read metadata from e-book files.

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
