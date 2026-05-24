# Refactor: bulk_metadata.html — IN PROGRESS (testing pending)

**Status as of last session (2026-05-23):** All extraction work complete.
Modules 7–11 (filters-sort-paging, batch, book-modal, bulk-result-modal,
cleanup-misc) are committed but **NOT YET TESTED** in the running container.

The next session should pick up here: rebuild on the deploy host, run the
test plan in §6 below via **Playwright MCP**, and address any regressions.

---

## Session-start prompt

> Läs `REFACTOR.md` i repo-roten. Modulerna 1–6 (CSS, scan-sync,
> duplicates, core, series-view, selection) är verifierade; modulerna
> 7–11 (filters-sort-paging, batch, book-modal, bulk-result-modal,
> cleanup-misc) är pushade men otestade. Senaste stabila commit:
> `cea83f6`. HEAD: `a77f658`.
>
> Kör rebuild (§6.0) och sedan hela testplanen via Playwright MCP.
> Rapportera sammanfattning — vilka tester PASS/FAIL. Fixa forward
> om buggarna är små, annars rollback till `cea83f6` (§7).

---

## 1. Goal

Break the 9812-line `app/templates/bulk_metadata.html` into per-feature
JS/CSS modules under `app/static/`. Functional equivalence — no behavior
changes. Pattern set by the pre-existing `app/static/js/shelf-view.js`.

## 2. Final state

| Before                             | After                                                    |
| ---------------------------------- | -------------------------------------------------------- |
| `bulk_metadata.html`: 9812 lines   | 983 lines (−90%)                                         |
| ~3225 lines of inline `<style>`    | `app/static/css/bulk_metadata.css`                       |
| ~5820 lines of inline `<script>`   | 10 new JS modules under `app/static/js/`                 |
| Theme bootstrap inline in `<head>` | **kept** (FOUC prevention)                               |
| Config bridge: none                | `window.__colophonConfig` — 198 i18n strings + URL bases |

## 3. The bridge pattern

The template carries **one** new inline `<script>` block (the bridge) that
sets `window.__colophonConfig`:

```javascript
window.__colophonConfig = {
  i18n: { /* 198 key→localized-string pairs from {{ _('...')|tojson }} */ },
  urls: {
    coverItemBase: '{{ url_for("metadata.cover_item", item_id=0) }}'.replace(/\/0$/, '')
  }
};
```

Every external `.js` file reads from `window.__colophonConfig`. **No `{{ }}` or
`{% %}` allowed in `.js` files** (verified — zero occurrences).

Theme bootstrap in `<head>` (L5–10) is the one allowed exception: it must
run synchronously to set `data-theme` before paint (FOUC prevention).

## 4. Modules

Load order matters. Dependencies load before dependants.

```
<!-- in <head> -->
<script>… theme bootstrap …</script>
<link rel="stylesheet" href=".../css/bulk_metadata.css">

<!-- config bridge -->
<script>… window.__colophonConfig = { … } …</script>

<!-- before main inline (depended on at script-load time): -->
<script src=".../js/core.js">
<script src=".../js/series-view.js">
<script src=".../js/selection.js">
<script src=".../js/filters-sort-paging.js">
<script src=".../js/batch.js">
<script src=".../js/book-modal.js">
<script src=".../js/bulk-result-modal.js">

<!-- after body content (lazy / self-contained): -->
<script src=".../js/duplicates.js">
<script src=".../js/scan-sync.js">
<script src=".../js/shelf-view.js">
<script src=".../js/cleanup-misc.js">
```

### Line counts

| File                                   | Lines |
| -------------------------------------- | ----- |
| `app/templates/bulk_metadata.html`     | 983   |
| `app/static/css/bulk_metadata.css`     | 3224  |
| `app/static/js/batch.js`              | 2092  |
| `app/static/js/book-modal.js`         | 1542  |
| `app/static/js/bulk-result-modal.js`  | 665   |
| `app/static/js/filters-sort-paging.js`| 648   |
| `app/static/js/shelf-view.js`         | 418   |
| `app/static/js/series-view.js`        | 411   |
| `app/static/js/selection.js`          | 254   |
| `app/static/js/duplicates.js`         | 235   |
| `app/static/js/core.js`              | 203   |
| `app/static/js/cleanup-misc.js`      | 84    |
| `app/static/js/scan-sync.js`         | 86    |

## 5. window-mirror pattern

Several state vars are owned by one module but read/written by others.
Pre-refactor they were top-level `var` in non-strict inline JS (implicit
`window.*`). After IIFE-wrapping in strict mode, the fix:

- **Owner** declares with `window._X = initialValue;`
- **Writers** use explicit `window._X = newValue;`
- **Readers** use `window._X` for clarity.

| var | owner | readers / writers elsewhere |
|-----|-------|---------------------------|
| `_viewMode` | core.js | series-view writes briefly, all read |
| `_density`, `_skriptorium`, `_seriesSort`, `_hideOnlyOneSeries`, `_filterOpen` | core.js | series-view, filters-sort-paging |
| `_grouped` | filters-sort-paging.js | selection.js + batch.js read |
| `_activeSeriesFilter` | series-view.js | filters-sort-paging reads |
| `_modalItemId`, `_modalDirty`, `_modalAllCandidates` | book-modal.js | bulk-result-modal reads |

## 6. Test plan — Playwright MCP

Playwright MCP Server är installerad globalt. Claude Code har headless
Chromium via MCP-tools (`browser_navigate`, `browser_click`,
`browser_screenshot`, `browser_snapshot` m.fl.).

**Alla tester körs av Claude Code via Playwright MCP — ingen manuell
webbläsar-testning behövs.**

### 6.0 Rebuild

```bash
cd /mnt/docker/stacks/colophon/repo && \
git pull && \
cd .. && \
docker compose up -d --build && \
docker logs colophon --tail 20
```

Verifiera: Gunicorn startar, inga Python tracebacks.

### 6.1 Sanity

1. Navigera till `http://192.168.50.8:5055`, vänta `networkidle`.
2. Ta screenshot — sidan ska vara stylad, inte rå HTML.
3. Kontrollera browser console: inga `ReferenceError`, `TypeError` eller andra JS-fel.
4. Accessibility snapshot: tabellstruktur med bokrader ska finnas.

### 6.2 Statiska resurser (200-check)

Navigera till varje fil, verifiera HTTP 200:

`/static/css/bulk_metadata.css`, `/static/js/core.js`,
`/static/js/series-view.js`, `/static/js/selection.js`,
`/static/js/filters-sort-paging.js`, `/static/js/batch.js`,
`/static/js/book-modal.js`, `/static/js/bulk-result-modal.js`,
`/static/js/duplicates.js`, `/static/js/scan-sync.js`,
`/static/js/shelf-view.js`, `/static/js/cleanup-misc.js`

### 6.3 Config bridge

Kör i console: `Object.keys(window.__colophonConfig)` → ska innehålla
`i18n` och `urls`. `Object.keys(window.__colophonConfig.i18n).length` ≥ 198.

### 6.4 Tema-toggle

1. Screenshot (utgångsläge).
2. Klicka tema-ikonen (sol/måne).
3. Screenshot — bakgrundsfärg ska ha ändrats.
4. Klicka tillbaka — ska återställas.

### 6.5 Vyväxling

1. Klicka "Hyllvy" — screenshot, grid med bokomslag ska renderas.
2. Klicka "Serie" — screenshot, serie-kort ska renderas.
3. Klicka "Tabell" — screenshot, tabell ska vara tillbaka.

### 6.6 Density

1. Klicka "Kompakt" — snapshot, tabellrader finns.
2. Klicka "Luftig" — snapshot, samma rader med annorlunda layout.

### 6.7 Sortering

1. Klicka kolumnhuvud "BOK" — verifiera att sorteringsordning ändras.
2. Klicka "FÖRFATTARE" — verifiera att sortering byts kolumn.

### 6.8 Filter och sök

1. Skriv "Hamilton" i sökrutan — bara Hamilton-böcker ska visas.
2. Rensa — alla böcker tillbaka.
3. Klicka "Oläst"-fliken — antal ändras.
4. Klicka "Alla" — tillbaka.

### 6.9 Paginering

1. Notera "Visar 1–20 av 376".
2. Klicka sida 2 — "Visar 21–40".
3. Ändra sidstorlek till 50 — "Visar 1–50".

### 6.10 Bokmodal (book-modal.js)

1. Klicka första boken i tabellen.
2. Verifiera att modal öppnas (accessibility snapshot visar modal-element).
3. Screenshot — boktitel, författare, omslag ska synas.
4. Tryck Esc — modalen stängs.

### 6.11 Serie-modal (series-view.js)

1. Byt till serie-vyn, klicka ett serie-kort.
2. Verifiera: serie-detaljmodal med serietitel + boklista.
3. Verifiera: "Böcker i den här serien" (inte engelska).
4. Verifiera: "Visa i tabell" (inte engelska).
5. Stäng modalen.

### 6.12 Dubletter-modal (duplicates.js)

1. I tabellvyn, klicka "..." → "Hitta dubletter".
2. Verifiera: modal öppnas.
3. Stäng modalen.

### 6.13 Skanning (scan-sync.js)

1. Klicka "..." → "Hitta nya böcker".
2. Verifiera: scan-progress visas.
3. Vänta tills klar.

### 6.14 Selection + batch-bar (selection.js)

1. Klicka checkbox på rad 1 — "1 valda" visas.
2. Klicka checkbox på rad 2 — "2 valda", batch-bar syns.
3. Klicka "Avmarkera alla" — count nollställs.

### 6.15 Skriptorium (core.js)

1. Byt till hyllvy.
2. Toggla Skriptorium-knappen.
3. Verifiera: serie-grupper visas/försvinner.

### 6.16 Språkbyte

1. Klicka "EN" — UI-text ändras till engelska.
2. Klicka "SV" — tillbaka till svenska.

### 6.17 i18n spot-checks (svenska)

Med SV aktivt, verifiera i snapshot:
- Sökruta: "Sök titel, författare, ISBN, genre..."
- Meny: "Hitta dubletter" (dubbel-b)
- Serie-modal: "Böcker i den här serien"
- Serie-modal: "Visa i tabell"

### 6.18 Batch wizard (batch.js)

1. Markera 2+ böcker.
2. Klicka batch-knappen.
3. Verifiera: steg 1 visas.
4. Screenshot.
5. Stäng/avbryt wizarden.

### 6.19 Esc-stänger-modal (cleanup-misc.js)

1. Öppna en bokmodal → tryck Esc → modalen stängs.
2. Utan öppen modal → tryck Esc → inget händer.

### 6.20 Kolumn-resize (cleanup-misc.js)

1. Om möjligt via Playwright: dra en resize-handle.
2. Verifiera breddändring.
3. (Manuell fallback om drag inte fungerar via MCP.)

### 6.21 Sammanfattning

Rapportera alla resultat:

| Test | Status |
|------|--------|
| 6.1 Sanity | PASS/FAIL |
| 6.2 Statiska resurser | PASS/FAIL |
| 6.3 Config bridge | PASS/FAIL |
| 6.4 Tema-toggle | PASS/FAIL |
| 6.5 Vyväxling | PASS/FAIL |
| 6.6 Density | PASS/FAIL |
| 6.7 Sortering | PASS/FAIL |
| 6.8 Filter och sök | PASS/FAIL |
| 6.9 Paginering | PASS/FAIL |
| 6.10 Bokmodal | PASS/FAIL |
| 6.11 Serie-modal | PASS/FAIL |
| 6.12 Dubletter-modal | PASS/FAIL |
| 6.13 Skanning | PASS/FAIL |
| 6.14 Selection + batch-bar | PASS/FAIL |
| 6.15 Skriptorium | PASS/FAIL |
| 6.16 Språkbyte | PASS/FAIL |
| 6.17 i18n spot-checks | PASS/FAIL |
| 6.18 Batch wizard | PASS/FAIL |
| 6.19 Esc-stänger-modal | PASS/FAIL |
| 6.20 Kolumn-resize | PASS/FAIL |

Om allt PASS → uppdatera denna fil: ändra rubriken till
"✅ Refactor complete and verified", fyll i §9 med ✓ överallt.

Om FAIL → rapportera vilka tester, console errors, screenshots.
Fixa forward om buggen är liten; annars rollback (§7).

## 7. Rollback recipes

Varje modul är en separat commit. Rollback + rebuild:

| Last known-good | Commit | What survives |
|----------------|---------|--------------|
| Pre-refactor | `6bd912b` | Original 9812-line template |
| CSS only | `4bfe5b6` | CSS extraction |
| + bridge + scan-sync | `b37b351` | + config bridge + scan-sync.js |
| + duplicates | `9fe1ec4` | + duplicates.js |
| + dubletter rename | `c412885` | Swedish term polish |
| + core.js | `ddbe39e` | + theme, view modes, density, skriptorium |
| + series-view.js | `8bde5c3` | + series-view.js |
| + authors/reading sv | `e8481cc` | i18n polish |
| + selection.js + i18n | `b642429` | + selection.js |
| + filters-sort-paging.js | `c6c5a02` | + filters-sort-paging.js |
| + batch.js | `0252e81` | + batch.js (broken state vars) |
| + batch state-var fix | `cea83f6` | **Last verified-working state** |
| + book-modal + bulk-result + cleanup-misc (HEAD) | `a77f658` | Refactor complete |

Rollback example:
```bash
cd /mnt/docker/stacks/colophon/repo && \
git reset --hard cea83f6 && \
cd .. && docker compose up -d --build
```

## 8. Known issues / technical debt

### Pre-existing (not introduced by refactor)
- Hard-coded Swedish strings in `selection.js` and `book-modal.js` (`_modalI18n`).
- 7 empty `msgstr` in `.po` — handle separately:
  ```
  "AI is not configured. Open API settings and add an API key."
  "Cleared %(n)d cached KEPUB files."
  "Device revoked."
  "Wikipedia: no title to search."
  "Wikipedia: no hits."
  "Initial data found. Enriching with Calibre..."
  "Save the downloaded file back over the original on the Kobo (replace)."
  ```
- Duplicate field-label tables across modules.

### Introduced by refactor
- Every top-level function in `batch.js` and `book-modal.js` is `window.X = X`'d (58 + ~50 names). Namespace pollution — tightening pass later.
- Two-pass patch pattern in `filters-sort-paging.js` preserved verbatim.
- `_modalI18n` in `book-modal.js` still hard-codes Swedish-only strings.

## 9. Verification status

| Module | Code-complete | Syntax-checked | Verified in browser |
|--------|:---:|:---:|:---:|
| `bulk_metadata.css` | ✓ | ✓ | ✓ |
| `scan-sync.js` | ✓ | ✓ | ✓ |
| `duplicates.js` | ✓ | ✓ | ✓ |
| `core.js` | ✓ | ✓ | ✓ |
| `series-view.js` | ✓ | ✓ | ✓ |
| `selection.js` | ✓ | ✓ | ✓ |
| `filters-sort-paging.js` | ✓ | ✓ | **NO** |
| `batch.js` | ✓ | ✓ | **NO** |
| `book-modal.js` | ✓ | ✓ | **NO** |
| `bulk-result-modal.js` | ✓ | ✓ | **NO** |
| `cleanup-misc.js` | ✓ | ✓ | **NO** |

## 10. How to continue

1. **Read this file** (`REFACTOR.md` in repo root).
2. **Read `CLAUDE.md`** for project context.
3. **Kör rebuild (§6.0) och hela testplanen via Playwright MCP.** Du har
   headless Chromium via MCP — kör alla tester själv. Säg "Använd
   Playwright MCP" i ditt första anrop.
4. Om ett test FAILar — se rollback-tabellen i §7.
5. **Fix forward** om buggen är liten. Rollback om den inte är diagnosbar.
6. **När allt verifierar** — markera denna fil som "✅ Refactor complete
   and verified" och fyll i §9.

### Diagnostik vid problem

```bash
# Jinja-parse
docker exec colophon python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('app/templates'))
env.parse(open('app/templates/bulk_metadata.html').read())
print('jinja parse OK')
"

# JS-syntax
for f in app/static/js/*.js; do
  node --check "$f" && echo "$(basename $f) OK"
done
```

| Console error | Trolig orsak |
|--------------|-------------|
| `ReferenceError: X is not defined` | Modul som definierar X laddas inte före anroparen. Kolla `<script src>`-ordning. |
| `TypeError: X is not a function` | Funktion skuggad lokalt, eller saknar `typeof`-guard. |
| Ostylade sidor | CSS-path trasig: `/static/css/bulk_metadata.css` returnerar inte 200. |
| Engelska i svenskt UI | Bridge saknar nyckel, eller `.po` har tom `msgstr`. |
| Modal öppnas tom | State-var som borde vara window-mirrored men inte är det (se §5). |

---

**Last edited:** 2026-05-24
**Next session intent:** Playwright MCP test run, fix regressions, mark complete.
