# Third-party licenses

## Python packages

| Package | License | URL |
|---|---|---|
| Flask | BSD-3-Clause | https://github.com/pallets/flask |
| Flask-Babel | BSD-3-Clause | https://github.com/python-babel/flask-babel |
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
| ddgs | MIT | https://github.com/deedy5/ddgs |

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

## Protocol references — Komga

The Kobo sync endpoints in `app/routes/kobo.py` and the delta logic
in `app/services/kobo_sync.py` implement the wire protocol that a
Kobo e-reader expects when its `api_endpoint` config is pointed at a
self-hosted server.

**Source of inspiration:** Komga (Kotlin/Spring), MIT, Copyright (c)
2019 Gauthier Roebroeck. https://github.com/gotson/komga

**What we borrowed:** the protocol shape — endpoint paths, DTO field
names and casing, the catch-all stub strategy for unhandled
endpoints, the set of feature flags Komga returns in
`/v1/initialization`, the field-level fixups noted in their
`KoboDtoDao.kt` (force `Description` to a single space, set
`Platform=Generic`, etc.). All of that is fair game for
re-implementation under MIT.

**What we did not borrow:** any actual Kotlin source. The Python
implementation in this repository was written from scratch using
Komga's structure as a reference for *what* the device expects,
not *how* to express it. No Komga source files appear in this repo
as-is or in modified form.

If you need to verify the lineage, the relevant Komga files at the
time of writing were `KoboController.kt`, `KoboDtoDao.kt`,
`KoboDtos.kt`, and `KomgaSyncTokenGenerator.kt`.

A copy of the MIT notice that ships with Komga is reproduced below
for the avoidance of doubt:

> MIT License
>
> Copyright (c) 2019 Gauthier Roebroeck
>
> Permission is hereby granted, free of charge, to any person
> obtaining a copy of this software and associated documentation
> files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy,
> modify, merge, publish, distribute, sublicense, and/or sell copies
> of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be
> included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
> EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
> MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
> BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
> ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
> CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Bundled binaries — kepubify

Docker images built from this repository bundle the `kepubify` binary
(used to convert EPUB to KEPUB during Kobo downloads). `kepubify` is
distributed under the MIT license, Copyright (c) Patrick Gaskin.
https://github.com/pgaskin/kepubify

The binary is downloaded verbatim at image-build time from the
upstream releases page (`tools/install_kepubify.sh`); no source
modifications. Native installs auto-download the same binary on
first use.

## External APIs (require separate accounts and keys)

| Service | Terms | URL |
|---|---|---|
| Mistral AI | Mistral AI Terms of Service | https://mistral.ai |
| Google Books API | Google APIs Terms of Service | https://developers.google.com/books |
