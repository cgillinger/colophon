# Author Authority Control — design

Status: **design only, not implemented.** This document is the spec; it is meant
to be read top-to-bottom by whoever implements it (possibly a different model in
a fresh session). It is self-contained — you should not need the originating
conversation. Code anchors are given as `path:line` against the tree at the time
of writing; verify they still hold before relying on them.

---

## The problem

Authors are handled case-by-case today. The same person therefore ends up with
several spellings across the library — "J.R.R. Tolkien", "Tolkien, J.R.R.",
"JRR Tolkien" — because:

- `_collect_authors()` (`app/services/scanner.py:119`) reads `dc:creator`
  verbatim from each EPUB; whatever the publisher/scanner embedded is what we
  store.
- `compute_group_key()` (`app/services/grouping.py:7`) **deliberately ignores
  the author** and groups on the normalised title only, so nothing reconciles
  author spellings anywhere.

Consequences: inconsistent author facets/filtering, and — if the library is
ever sorted into author folders (see `docs/TODO.md` / the paused
upload-to-author-folder idea) — *parallel* folders for one person.

This is a known library-science problem: **authority control** — one
*authorised* (canonical) form per author, with cross-references from variant
forms. VIAF, LIBRIS and Wikidata all do it, and Colophon already talks to LIBRIS
(`metadata_libris.py`) and Wikidata (`metadata_wikidata.py`), which we exploit in
the escalation layer.

---

## What an EPUB can and cannot carry (grounding)

This constrains where each piece of data must live.

EPUB metadata is Dublin Core in the OPF package. Author-relevant fields that
real readers/apps honour:

- **`dc:creator`** — the author(s); multiple allowed, each may carry an
  `opf:role` ("aut", "edt", "ill", …). Already parsed in `_collect_authors`.
- **sort form** (`opf:file-as` in EPUB2 / a `file-as` refinement in EPUB3) — a
  separate sortable form, e.g. "Tolkien, J. R. R.". This is the `author_sort`.

An EPUB has **no** standard way to carry a foreign key, a Wikidata QID / LIBRIS
id for the author, or a list of alternative spellings. (You can stuff custom
identifiers in, but no normal reader uses them for authors.)

That split drives the core architecture decision below.

---

## Core principle: the file stays the source of truth

Colophon's invariant: **the EPUB file itself always holds the best metadata**,
so a book pulled out of Colophon does not regress. `apply_metadata_to_item()`
writes the chosen author back into the file via `write_metadata_to_file()` and
stamps `item.file_modified_by_colophon` (`app/services/metadata_writer.py`
~:181, ~:201); upstream push only ships files Colophon has modified
(`push_to_upstream`, `app/services/upstream_sync.py:109`).

Therefore:

- The **canonical author name** is written into the file's `dc:creator`, exactly
  like title/cover already are. **No competing "raw" string is kept** as a
  parallel truth. (An earlier draft proposed an `author_raw` column — rejected:
  it would let an orphan EPUB carry a worse name than Colophon "knew", which is
  the regression the invariant exists to prevent.)
- The **sort form** can also be written (EPUB has `author_sort`), consistent
  with the invariant.
- **`author_id` (FK), `wikidata_qid`, `libris_id`, the alias list** live in the
  DB only. They carry no information the file lacks (the FK points at the same
  canonical string that is already in the file) or are facts about the *author
  entity*, not the book. The FK is an index / relational convenience, not a
  source of truth. Pulling the file out loses query speed, not data. No
  violation of the invariant.

---

## Data model

Two new tables plus one column. Migrate via the existing pattern in
`app/services/database.py` (`ensure_*_table` / `backfill_*`).

**`authors`** (canonical entities)
- `id`
- `canonical_name` — the display form written into files
- `sort_name` — the `author_sort` form (nullable)
- `wikidata_qid`, `libris_id`, `viaf_id` — nullable authority ids
- `verified` (bool) / `source` enum — see "earning the right to be written"
  below. Values: `tentative` (free-text, first-occurrence), `user_confirmed`,
  `authority_linked`.

**`author_aliases`** (variant → canonical)
- `id`
- `variant_key` — the *normalised* form of an observed spelling (unique)
- `author_id` → `authors.id`

**`library_items`** — add `author_id` (nullable FK → `authors.id`).
Keep the existing `author` string column; it mirrors the file (= the canonical
name once resolved), same as today.

`compute_group_key` is **not** touched — grouping stays title-based and
`author_id` is orthogonal.

---

## Matching — layered, cheapest first

AI is the last resort, not the primary mechanism. Most reconciliation is
deterministic and free.

1. **Exact after light normalisation** — casefold, Unicode NFC, trim, collapse
   whitespace. Catches "tolkien" vs "Tolkien".
2. **Format-/order-invariant signature** — handle "Lastname, First" vs "First
   Lastname" and initials ("J.R.R." / "J. R. R." / "JRR"). Build a signature of
   sorted, punctuation-stripped tokens: `{j, r, r, tolkien}`. All three variants
   collapse to one signature. **This layer does the most work and needs no AI.**
   It is also what prevents the parallel-folder problem.
3. **Fuzzy** — typos, diacritics, transliteration ("Dostoevsky" /
   "Dostoyevsky", "Müller" / "Mueller"). Reuse the stdlib `SequenceMatcher`
   approach already in `app/services/duplicate_detector.py`
   (`_normalize_for_fuzzy`, `_FUZZY_THRESHOLD = 0.85`). **Above threshold →
   suggest, never auto-merge.**
4. **Authority lookup** (LIBRIS / Wikidata, already integrated) — for a genuinely
   new author, resolve to an entity and capture a QID. The QID then becomes the
   dedup key, far more robust than strings ("Leo Tolstoy" = "Lev Tolstoj" =
   "Лев Толстой" → one QID).
5. **AI (Mistral)** — last, as an *adjudicator* for the ambiguous middle where
   fuzzy says "maybe" and authority lookup is inconclusive, and for name-order in
   cultures the deterministic rules miss. Use the provider-agnostic
   `app/services/ai_metadata.py`. AI proposes and ranks; it is never
   load-bearing for correctness.

Put author normalisation **after** the metadata pipeline has chosen an author
string, as a final resolution layer. Implement the matcher as **pure functions
with unit tests, no UI** — this is where the real work is. Suggested home:
`app/services/text_utils.py` (normalisation lives there already) or a new
`app/services/author_authority.py`.

### Iron rule

> Auto-apply only layers 1–2 (high precision). Everything fuzzy/AI (3–5)
> *proposes* and requires user confirmation. When uncertain, do **not** merge.

A false merge — collapsing two distinct people with similar names ("Michael
Connelly" vs "Michael Connolly") — is the worst outcome: hard to detect, painful
to unwind, and because we write canonical names into files, it **mutates real
book files and propagates upstream**. Set the auto-apply threshold
conservatively precisely because the outcome is persistent and outward-facing.

---

## Registry data quality — what happens if a misspelling gets in

A typo that becomes a *canonical* entry is worse than a typo in one book,
because the registry is reused:

- **Propagation** — later books matching the bad entry link to it, and the bad
  name gets written into their files + pushed upstream. A registry typo is a
  *typo factory*.
- **Fragmentation** — the typo becomes a near-duplicate canonical ("Tolkein"
  beside "Tolkien"), splitting one author into two → parallel folders / split
  facets again.

Typos mostly originate in the file's own `dc:creator` (publishers and scanned
EPUBs are full of them), so a confirmation dialog does not reliably stop them —
the user may click through, or not know the correct spelling. You **cannot**
fully prevent typos from entering.

But a registry makes typos *cheaper, not more dangerous*, provided fixes
**cascade**: rename one canonical entry → all linked books are relabelled → (if
written) all their files are rewritten in one sweep. The fix is one action
instead of N scattered edits. That is the whole point of authority control, and
one of the stronger arguments *for* the registry over today's case-by-case.

Three guards make that real:

1. **Gate file-writes on confidence.** A fresh free-text canonical
   (`source = tentative`) **stays DB-only** — it does not mutate the file or push
   upstream until it has *earned* it: user-confirmed, authority-linked, or used
   by ≥ N books. So an unconfirmed typo never reaches the "truth in the file"
   layer; propagation harm is eliminated. *Principle: a canonical entry earns
   the right to be written into files.* (This is also the answer to the
   file-write-timing question below.)
2. **Fuzzy-check at creation.** When the combobox is about to create a *new*
   author, run layer-3 fuzzy against existing canonicals: "This is 1 character
   from **Tolkien** — sure it's a new author?" Stops fragmentation at the door,
   cheaply, without blocking.
3. **A "Manage authors" view as backstop.** List canonical entries with a
   per-entry book count. A 1-book entry beside a near-identical 30-book entry
   screams typo. From there: merge (cascades) or rename (cascades). The same
   fuzzy can proactively flag likely in-registry duplicates.

With these, **silent first-occurrence is acceptable**: the typo is contained
(DB-only until earned) and one-click-fixable (cascade), so the user is spared a
confirm click per new author, while guard 2 catches most typos anyway.

---

## User journey — "I just uploaded an EPUB"

Current upload flow: `/upload` (`app/routes/scan.py:61`) writes the file into
`LIBRARY_DIR` (root today), runs `extract_local_metadata` + `upsert_library_item`,
stamps `created_at` (drives the "Nytillagt" badge), and `upload.js` shows a live
per-file progress panel and reloads on completion.

**Design rule: upload is never blocked by a dialog.** Bulk drag-and-drop of many
EPUBs is normal; a modal per book is intolerable. Ingest immediately, resolve
authors silently where confident, collect the uncertain into a queue the user
clears later (mirrors the "Nytillagt" pattern).

After ingest each book is in one of four **author states** (a small status
marker on the row / in the modal):

- **✅ Known** — `dc:creator` matches the registry exactly or via the
  format-invariant key. Linked silently to the canonical entry. No action.
- **⚠️ Needs review** — only a fuzzy near-match found. Colophon has a
  *suggestion* but changes nothing until clicked. Enters the review queue.
- **➕ New author** — no match. The file's spelling becomes a *tentative*
  canonical entry (registry grows itself), flagged once for confirmation. The
  next book by that person becomes a ✅.
- **❓ No author** — file had no `dc:creator` (the old "root case"). Must be
  assigned by the user.

The `upload.js` panel gains a summary line, e.g.:
`12 uploaded · 9 authors known · 2 to review · 1 missing author → [Review 3]`.
Doing nothing is fine — known books are already tidy. A **"Authors to review"**
filter/badge (sibling of "Nytillagt") collects ⚠️/➕/❓ for clearing in the user's
own time.

### The review step — the combobox

In the existing edit modal (`app/static/js/book-modal.js`) the author field
becomes a **combobox**:

- ⚠️ near-match: the suggestion is preselected — "Did you mean **J.R.R.
  Tolkien**?"; one click confirms.
- Type-ahead against all canonical authors while typing, so the user never
  accidentally creates a duplicate of an existing one.
- Always last: **"Create new: «typed text»"** (triggers guard 2's fuzzy check).
- ❓ case: empty field, same combobox.

i18n: all new strings go through `gettext`/`_()`; the JS string map lives in
`app/static/js/core.js`; Swedish in `app/translations/sv/`.

---

## File-write timing (resolved)

Separate **DB linking** (immediate, free, for all confident cases) from **file
writing** (`ebook-meta` subprocess — noticeably slower than reading; never do it
synchronously per file in a bulk upload). File writes ride the existing
metadata-write moment (`apply_metadata_to_item`) and are **gated on confidence**
per the registry-quality guard 1: only `user_confirmed` / `authority_linked`
canonicals are written into files; `tentative` ones stay DB-only. The
"truth in the file" guarantee is fulfilled at the same point all other metadata
is written back — not necessarily in the upload instant. Accept the consequence:
between linking and writing, Colophon shows the canonical name while the file
still holds its variant — but that window coincides exactly with the
"not yet polished" state, so it is understandable.

---

## Implementation order (deterministic first, AI last)

1. **Data model + migration** — `authors`, `author_aliases`,
   `library_items.author_id`, `verified/source`. Via `database.py`
   `ensure_*`/`backfill_*`.
2. **Matcher as pure functions + tests** — normalisation, format-invariant
   signature, fuzzy (reuse `SequenceMatcher`). No UI. Fully testable in
   isolation. *This is where the real work is.*
3. **Resolve-on-upload, DB-only** — hook into the upsert path
   (`scanner.py:upsert_library_item` / the `/upload` route): link confident
   matches, flag uncertain, do **not** write to file until the entry has earned
   it.
4. **UI** — combobox in `book-modal.js`, "Authors to review" filter/badge,
   "Manage authors" view (with cascade merge/rename + per-entry book counts).
5. **Escalations** — LIBRIS/Wikidata authority anchoring (QID capture), Mistral
   adjudicator, and a one-time **bootstrap pass** that clusters the existing
   library by the format-invariant signature and lets the user confirm a
   canonical per cluster (Mistral may propose the clustering).

Steps 1–2 are the MVP at ~zero risk (nothing touches files yet); each later step
is a bounded add-on.

---

## Cross-cutting gotchas for the implementer

- **Never move-then-rescan to relabel.** `scan_directory` deletes DB rows whose
  file no longer exists (`scanner.py:613-617`); a new row gets a new `id`, losing
  `manual_metadata`, `cover_locked`, reading state, and the `kobo_book_states`
  association (which references `library_items.id`). Any operation that would
  reorganise must update rows **in place**.
- **Versioning** — this is a new user-visible feature ⇒ MINOR bump, per
  `CLAUDE.md` (update `app/version.py`, `README.md` badge, `CLAUDE.md` intro
  line together; tag the commit).
- **Subprocess-per-file** — only for *writing* (`ebook-meta`); never add
  per-file subprocesses to the read/scan path (Gunicorn sync-worker timeouts —
  see `CLAUDE.md` pitfalls).
- **Tests** — follow the `tests/` convention (mock external services). The
  matcher gets its own unit-test file; add `/upload` resolution-path coverage to
  `tests/test_upload.py`.
