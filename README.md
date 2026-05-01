# Colophon

Colophon is a self-hosted e-book library manager. It scans a folder of book files, fetches metadata and cover art from Google Books and Calibre metadata sources, lets an AI (Mistral) suggest series membership and description improvements, and queues those suggestions for manual review before anything is saved. The web interface runs in a Docker container and is accessed through a browser.

---

## Quick start

```bash
cp .env.example .env
# Edit .env and set at least COLOPHON_SECRET_KEY
docker-compose up
```

Open `http://localhost:5000` in your browser.

---

## Environment variables

All variables are read from `.env` (loaded via `env_file` in `docker-compose.yml`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `COLOPHON_SECRET_KEY` | Yes | — | Secret key for Flask sessions and CSRF protection. Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `COLOPHON_LIBRARY_DIR` | No | `/books` | Path to the book folder inside the container |
| `COLOPHON_DATA_DIR` | No | `/data` | Path to the data folder (database, covers) inside the container |
| `COLOPHON_LIBRARY_HOST` | No | `./bibliotek` | Host path mounted as `COLOPHON_LIBRARY_DIR` (used by docker-compose) |
| `COLOPHON_DATA_HOST` | No | `./data` | Host path mounted as `COLOPHON_DATA_DIR` (used by docker-compose) |
| `COLOPHON_LOG_LEVEL` | No | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `COLOPHON_GOOGLE_BOOKS_KEY` | No | — | Google Books API key for metadata lookups |
| `COLOPHON_MISTRAL_API_KEY` | No | — | Mistral AI API key for AI-assisted metadata suggestions |
| `COLOPHON_MISTRAL_MODEL` | No | `mistral-small-latest` | Mistral model name |

---

## Pipeline

Colophon processes books in four stages:

1. **Scan** — The scanner walks `COLOPHON_LIBRARY_DIR` and registers every supported file (`.epub`, `.pdf`, `.txt`, `.cbz`, `.cbr`, `.mp3`, `.m4a`, `.m4b`, `.zip`) in the SQLite database. Files already in the database are skipped.

2. **Enrich** — For each book, Colophon queries Google Books (and optionally Calibre metadata plugins) to fetch title, author, series, ISBN, publisher, description, and cover art.

3. **Polish** — If a Mistral API key is configured, the AI can suggest improvements to series, description, and subjects for a selected book. Suggestions are generated on demand from the book's metadata page.

4. **Review** — Every AI suggestion is held in a review queue. Nothing is written to the database until you explicitly accept or reject each suggestion in the web interface.

---

## Calibre plugins (optional)

Installing Calibre and its community metadata plugins gives access to additional sources (Goodreads, Fantastic Fiction, FictionDB) with better series and genre data.

```bash
bash tools/install_calibre_plugins.sh
```

Calibre must be installed on the host or inside the container before running the script. The plugins are optional — Colophon works without them using Google Books alone.
