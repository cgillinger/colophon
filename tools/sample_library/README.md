# Sample library for the README screenshots

Everything here is invented: titles, authors, publishers, ISBNs, cover art and
text. The scripts rebuild the four screenshots in `docs/screenshots/` from
scratch, so they can be redone when the interface changes.

```bash
V=.venv/bin/python
$V tools/sample_library/covers.py        # 24 covers → tools/sample_library/covers/
$V tools/sample_library/build_epubs.py   # EPUBs with metadata → tools/sample_library/library/
COLOPHON_DATA_DIR=$PWD/tools/sample_library/data \
COLOPHON_LIBRARY_DIR=$PWD/tools/sample_library/library \
COLOPHON_SECRET_KEY=shots .venv/bin/gunicorn -b 127.0.0.1:5056 -w 2 wsgi:app &
curl -s http://127.0.0.1:5056/scan
$V tools/sample_library/shoot.py         # sets reading state, screenshots → tools/sample_library/png/
cp tools/sample_library/png/*.png docs/screenshots/
```

`shoot.py` expects Chromium at `/opt/pw-browsers/chromium`; change
`executable_path` if yours lives elsewhere. Generated folders (`covers/`,
`library/`, `data/`, `png/`) are gitignored.
