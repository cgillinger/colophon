# Future idea: per-field locking

**Status:** Not implemented. Sketched 2026-05-24 as a follow-up after
removing the row-level `manual_metadata` flag.

## Problem

Auto-flows (scan re-read, "Hämta metadata", "Fråga AI", batch wizard)
overwrite text fields. A user who curates one field (say a clean
title) has no way to say "leave this exact field alone, but feel free
to enrich the rest." The previous row-level `manual_metadata` flag
only gated *scan* — not enrichment / AI / batch — so it didn't even
solve the part of the problem users actually encounter.

## Proposed shape

**Schema:** one JSON column on `LibraryItem`:

```
locked_fields = {"title": true, "cover": true}
```

Flexible, no per-field column explosion. Absorbs `cover_locked` (the
one surviving lock today) into the same structure on the way.

**UI:**

- Small 🔓 / 🔒 icon next to each field label in the bok-modal (title,
  author, series, isbn, publisher, language, genre, published date,
  synopsis, cover — ~10 toggles)
- Click toggles the lock. Closed = accent-coloured, open = muted.
- POST to a small endpoint that updates `locked_fields` and commits.
- Tabellvy / hyllvy: optionally a single small lock-icon on the row /
  card if ANY field is locked. Modal is the source of truth.

**Gating — must hit ALL auto-flows, not just scan:**

| Flow | Honor lock? | Where |
|---|---|---|
| Skanna (re-read EPUB) | Yes | `scanner.py` upsert_library_item |
| Hämta metadata | Yes | `apply_metadata_to_item` in metadata_writer |
| Fråga AI | Yes | same path |
| Batch wizard | Yes | same path + warning in review step |
| Manual modal save | No — user input always wins | n/a |

Central helper: `is_field_locked(item, field) -> bool`. Every
overwrite call site checks it before writing.

Surfacing in batch / enrichment review:
- Skip-summary: "{n} fält hoppade pga lås"
- Optional: opt-in checkbox "Skriv över låsta fält ändå" for power-users

**Optional filter:** "Har låsta fält" / "Inga lås" in the existing
filter row.

## Migration

If `manual_metadata=True` ever shipped, treat it as "lock all currently
non-empty text fields" on first run, then drop the column. We removed
the flag entirely instead in 2026-05-24, so the migration on this
branch starts from a clean slate — no legacy locks to import.

## Why not now

Three reasons we chose to remove rather than expand:

1. **It's a real refactor.** Touches scanner, writer, AI flow, batch
   wizard, single-book modal — five flows that all need the helper
   and the schema migration.
2. **For a single-developer hobby library, the value is unclear.**
   95% of rows are "scan + accept Google Books" — the curation
   workflow that benefits most from per-field locks is rare.
3. **The row-level `manual_metadata` we had was confusing on its own.**
   Wanted to clean that out before adding more state.

Revisit when:
- The library grows past a few hundred manually-curated rows
- A specific frustration shows up (e.g. "I keep losing my title fixes")
- There's appetite for a structural data-model change
