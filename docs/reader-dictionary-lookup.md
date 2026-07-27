# Reader dictionary lookup (v1.32.0)

Select a single word while reading in the in-browser reader → a bottom sheet
shows an **English definition** (GCIDE) and a **Swedish translation**
(FreeDict/WikDict), plus an optional **AI explanation of the word in its
sentence** (uses the already-configured AI provider). Dictionaries are
downloaded **on demand** the first time a word is looked up in a language,
then served locally forever — no external calls per lookup.

## Why server-side lookup

The vendored foliate-js ships a StarDict parser (`static/vendor/foliate-js/dict.js`),
but the real-world files argue against client-side parsing:

- FreeDict's StarDict archive contains a **gzipped** `.idx` and an
  **uncompressed** `.dict` — `dict.js` expects the opposite (raw idx + DictZip).
- GCIDE's `.dict` is 160 MB uncompressed; shipping a 3.3 MB idx to the browser
  per session is wasteful on iPad.

So lookup happens **server-side** in `services/dictionaries.py`: the `.idx` is
parsed once per worker into an in-memory `{lowercased word → [(offset, size)]}`
map, and entries are read with `seek()` from the uncompressed `.dict`. The
browser does one small JSON fetch per lookup. `dict.js` stays unused.

Consequence: lookups need the server — a book saved for offline reading has no
dictionary offline (acceptable; the AI button needs a network anyway).

## Pinned sources (the manifest)

`MANIFEST` in `services/dictionaries.py` pins **URL + checksum** per pair, so a
moved or changed upstream file fails loudly (checksum error in the sheet)
instead of silently serving something unverified. Updating a dictionary version
= edit the manifest constants, commit.

| pair | source | archive | license |
|------|--------|---------|---------|
| `eng-eng` | GCIDE (Webster 1913 + updates), StarDict build, archive.org | 34 MB tar.bz2, sha256-pinned | GPL |
| `eng-swe` | FreeDict/WikDict 2025.11.23 (44 077 headwords) | 2.7 MB tar.xz, sha512-pinned (from freedict-database.json) | CC BY-SA 3.0 |

`LANGUAGE_PAIRS = {"en": ["eng-eng", "eng-swe"]}` maps a book's `language`
(normalised: `en-GB` → `en`) to the pairs to download and query, in display
order (definition first, then translation).

**Adding a language**: add a manifest entry (find URL + checksum in
https://freedict.org/freedict-database.json) and extend `LANGUAGE_PAIRS`.
Nothing else — download, normalisation, lookup and UI are generic.

## Download + normalisation

`ensure_downloaded(pair)` (behind a module lock, idempotent):

1. Stream the archive to `DATA_DIR/dictionaries/tmp/`, hashing while streaming;
   verify against the pinned checksum, else abort.
2. Extract only the members we want (`.ifo`, `.idx[.gz]`, `.dict[.dz]`, `.syn`)
   **by basename** into the pair dir — tar paths are never trusted.
3. Normalise: gunzip `.idx.gz`/`.dict.dz` (DictZip is valid gzip, Python's
   `gzip` reads it whole-file) → plain `<pair>.ifo/.idx/.dict`. GCIDE becomes
   ~160 MB on disk under `/data` — deliberate: uncompressed enables `seek()`.
4. Write `meta.json` (source URL, headword count, timestamp).

The download runs inside the POST request (Gunicorn timeout 300 s). archive.org
can be slow; if the 34 MB GCIDE fetch ever times out, retrying is safe — the
step is idempotent. Not worth SSE machinery for a once-per-language event.

## Morphology ("ran" → "run")

`_candidates(word)` yields, in order: the raw selection stripped of surrounding
punctuation/quotes, lowercase, possessive-stripped (`'s`/`’s`), then suffix
heuristics (`-ies→y`, `-es`, `-s`, `-ing`, `-ed`, `-er`, `-est`, `-ly`, each
with silent-e restoration and doubled-consonant undoing). Each pair returns the
entries of its **first** matching candidate. What the heuristics miss, the AI
button catches.

## Endpoints (reader_bp)

```
GET  /reader/dict/lookup?word=<w>&lang=<code>
     → {status: "ok", word, matches: [{pair, kind, label, headword, type, text}]}
     | {status: "needs_download", language, download_mb, pairs: [...]}
     | {status: "unsupported_language"}   (sheet falls back to AI-only)
POST /reader/dict/download        {"language": "en"}   → {ok: true} | {error}
POST /reader/<id>/dict/explain    {"word", "sentence"} → {ok, explanation} | {error}
```

`type` is the StarDict `sametypesequence`: `m` = plain text (GCIDE, rendered
pre-wrap), `h` = HTML (FreeDict — sanitised client-side before injection:
scripts/event handlers stripped via DOMParser).

`explain` calls `ai_metadata.explain_word_in_context()` — same provider,
error-code and usage-logging conventions as `adjudicate_author_names()`.
Answers in Swedish, grounded in the sentence the word was selected in.

## Client (`static/js/reader-dict.js`)

ES module, wired from `reader.js` after `view.open()`. On each foliate `load`
event (a section document becoming available) it attaches `pointerup` +
debounced `selectionchange` listeners **inside the book iframe**. A selection
that is a single word (`\p{L}` + apostrophes/hyphens) triggers a lookup; the
surrounding sentence is clipped from the paragraph's `textContent` for the AI
prompt. Multi-word selections are ignored (v1).

The sheet is a non-modal bottom card (`#readerDictSheet`) styled with the same
`--rs-*` theme variables as the Aa panel, so it follows light/sepia/dark.
It closes on ✕, Escape (before Escape leaves the reader — `reader.js` asks the
module first), or a page turn (`relocate`). First lookup in a language renders
the download state (size, progress note) in the same sheet, then re-runs the
lookup. If AI is unconfigured (`cfg.aiConfigured`), the AI button is hidden.

## Scope notes

- EPUB/MOBI/AZW3 only (foliate sections). PDF has a separate text layer —
  deferred, like the rest of the PDF feature set.
- Only book language `en` is mapped in v1. Unsupported languages get the
  AI-only sheet, not an error.
- Lookups are logged nowhere (no vocabulary list yet) — a later feature can
  hang persistence on the lookup endpoint.
