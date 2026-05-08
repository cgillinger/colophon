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
| `COLOPHON_UPSTREAM_DIR` | No | — | Path to the upstream library inside the container (e.g. `/upstream`). See [Upstream sync](#upstream-sync-optional). |
| `COLOPHON_UPSTREAM_HOST` | No | — | Host path mounted as `COLOPHON_UPSTREAM_DIR` (used by docker-compose) |

---

### Google Books API key

1. Go to <https://console.cloud.google.com/apis/library/books.googleapis.com>, select or create a project, then click **Enable**.
2. Go to <https://console.cloud.google.com/apis/credentials>, click **Create Credentials → API key**, and copy the generated key.
3. Add the key to `.env`:
   ```
   COLOPHON_GOOGLE_BOOKS_KEY=your_key_here
   ```

The API is free up to 1 000 requests/day. Colophon works without a key too, but Google Books will apply stricter rate limits to unauthenticated requests.

---

## Pipeline

Colophon processes books in four stages:

1. **Scan** — The scanner walks `COLOPHON_LIBRARY_DIR` and registers every supported file (`.epub`, `.mobi`, `.azw3`, `.kepub`, `.pdf`, `.cbz`, `.cbr`) in the SQLite database. Files already in the database are skipped. Comic formats (`.cbz`, `.cbr`) are scanned by filename only — Google Books and Calibre metadata sources have limited coverage for them.

2. **Enrich** — For each book, Colophon queries Google Books (and optionally Calibre metadata plugins) to fetch title, author, series, ISBN, publisher, description, and cover art.

3. **Polish** — If a Mistral API key is configured, the AI can suggest improvements to series, description, and subjects for a selected book. Suggestions are generated on demand from the book's metadata page.

4. **Review** — Every AI suggestion is held in a review queue. Nothing is written to the database until you explicitly accept or reject each suggestion in the web interface.

---

## Upstream sync (optional)

Colophon can work against a local copy of your book library and sync
changes back to the original location (e.g. a Komga library on a NAS).

1. Set `COLOPHON_UPSTREAM_DIR=/upstream` in `.env`
2. Uncomment the upstream volume mount in `docker-compose.yml`
3. Point it at your original library path

When configured, "Hitta nya böcker" will pull new files from upstream
before scanning. A blue "N osynkade" badge appears in the library bar
when files have been modified locally. Click it to review, then push.

---

## Calibre plugins

Calibre and the community metadata plugins (Goodreads, Fantastic Fiction, FictionDB) are bundled in the Docker image. No manual installation is required — `docker-compose up` is all you need.

The plugins give access to richer series and genre data beyond what Google Books alone provides. They are installed automatically at image build time from the [kiwidude68/calibre_plugins](https://github.com/kiwidude68/calibre_plugins) GitHub releases.
