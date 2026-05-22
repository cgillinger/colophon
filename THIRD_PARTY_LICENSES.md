# Third-party licenses

## Python packages

| Package | License | URL |
|---|---|---|
| Flask | BSD-3-Clause | https://github.com/pallets/flask |
| Flask-Session | MIT | https://github.com/pallets-eco/flask-session |
| Flask-SQLAlchemy | BSD-3-Clause | https://github.com/pallets-eco/flask-sqlalchemy |
| requests | Apache-2.0 | https://github.com/psf/requests |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| gunicorn | MIT | https://github.com/benoitc/gunicorn |
| EbookLib | AGPL-3.0 | https://github.com/aerkalov/ebooklib |
| beautifulsoup4 | MIT | https://www.crummy.com/software/BeautifulSoup |
| mutagen | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| playwright | Apache-2.0 | https://github.com/microsoft/playwright-python |
| langdetect | Apache-2.0 | https://github.com/Mimino666/langdetect |

## Vendor / frontend assets (bundled)

| Package | License | URL |
|---|---|---|
| @tabler/icons-webfont | MIT | https://github.com/tabler/tabler-icons |

## System tools (runtime dependencies, not bundled)

| Tool | License | URL |
|---|---|---|
| Calibre (`ebook-meta`, `fetch-ebook-metadata`) | GPL-3.0+ | https://calibre-ebook.com |
| Goodreads Calibre plugin (optional) | GPL-3.0 | https://github.com/kiwidude68/calibre_plugins |
| Fantastic Fiction Calibre plugin (optional) | GPL-3.0 | https://github.com/kiwidude68/calibre_plugins |
| FictionDB Calibre plugin (optional) | GPL-3.0 | https://github.com/kiwidude68/calibre_plugins |
| kepubify (optional, for Kobo sync) | MIT | https://github.com/pgaskin/kepubify |

## Protocol references

The Kobo sync endpoints in `app/routes/kobo.py` implement the wire
protocol that a Kobo e-reader expects when its `api_endpoint` config is
pointed at a self-hosted server. The protocol shape — endpoint paths,
DTO field names, casing — was reconstructed by reading the Kotlin
implementation in **Komga** (MIT, Copyright 2019 Gauthier Roebroeck,
https://github.com/gotson/komga). No source code was copied; the
Python implementation was written from scratch using Komga's DTOs as
a reference for what the Kobo client requires.

## External APIs (require separate accounts and keys)

| Service | Terms | URL |
|---|---|---|
| Mistral AI | Mistral AI Terms of Service | https://mistral.ai |
| Google Books API | Google APIs Terms of Service | https://developers.google.com/books |
