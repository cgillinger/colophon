# Refactor: bulk_metadata.html — IN PROGRESS (testing pending)

**Status as of last session (2026-05-23):** All extraction work complete.
Modules 7–11 (filters-sort-paging, batch, book-modal, bulk-result-modal,
cleanup-misc) are committed but **NOT YET TESTED** in the running container.

The next session should pick up here: rebuild on the deploy host, run the
test plan in §6 below, and address any regressions discovered.

---

## Session-start prompt (paste this in a fresh chat tomorrow)

> Läs `REFACTOR.md` i repo-roten — där står exakt vad som är klart,
> vad som inte är testat, och rollback-recept om något brakar. Vi
> sitter mitt i en refaktorisering av `app/templates/bulk_metadata.html`:
> modulerna 1–6 (CSS, scan-sync, duplicates, core, series-view,
> selection) är verifierade i körd container; modulerna 7–11
> (filters-sort-paging, batch, book-modal, bulk-result-modal,
> cleanup-misc) är pushade men oförklarade och otestade. Senaste
> stabila commit du säkert kan rolla tillbaka till är `cea83f6`.
> HEAD är `a77f658`. Börja med rebuild + verifiering enligt
> testplanen i §6, rapportera vad som funkar/inte funkar, så
> går vi fram därifrån.

---

## 1. Goal

Break the 9812-line `app/templates/bulk_metadata.html` into per-feature
JS/CSS modules under `app/static/`. Functional equivalence — no behavior
changes. Pattern set by the pre-existing `app/static/js/shelf-view.js`.

## 2. Final state

| Before | After |
|---|---|
| `bulk_metadata.html`: 9812 lines | 983 lines (−90%) |
| ~3225 lines of inline `<style>` | `app/static/css/bulk_metadata.css` |
| ~5820 lines of inline `<script>` | 10 new JS modules under `app/static/js/` |
| Theme bootstrap inline in `<head>` | **kept** (FOUC prevention) |
| Config bridge: none | `window.__colophonConfig` — 198 i18n strings + URL bases |

## 3. The bridge pattern

The template carries **one** new inline `<script>` block (the bridge) that
sets `window.__colophonConfig`:

```html
<script>
  window.__colophonConfig = {
    i18n: { /* 198 key→localized-string pairs from {{ _('...')|tojson }} */ },
    urls: {
      coverItemBase: '{{ url_for("metadata.cover_item", item_id=0) }}'.replace(/\/0$/, '')
    }
  };
</script>
```

Every external `.js` file reads from `window.__colophonConfig`. **No
`{{ }}` or `{% %}` allowed in `.js` files** (verified — zero occurrences).

Theme bootstrap in `<head>` (L5–10) is the one allowed exception: it must
run synchronously in `<head>` to set `data-theme` before paint, so it
can't move to `<script src>` at end of body without re-introducing the
FOUC it was specifically created to avoid.

## 4. Modules

Load order matters. Modules that the inline JS's bottom-of-script init
calls (or that own state read by other modules at IIFE-load time) load
**before** the main inline block. Modules that just register event
delegates or own self-contained features load **after**.

```html
<!-- in <head> -->
<script>… theme bootstrap …</script>
<link rel="stylesheet" href=".../css/bulk_metadata.css">

<!-- in <body>, just before the next inline block -->
<script>… config bridge …</script>

<!-- before main inline (depended on at script-load time): -->
<script src=".../js/core.js">                ← view state, theme, density, skriptorium, language
<script src=".../js/series-view.js">         ← series view + series modal
<script src=".../js/selection.js">           ← checkboxes, batch-bar, bulk delete, grid↔table mirror
<script src=".../js/filters-sort-paging.js"> ← sort, filter, paginate, group + init block
<script src=".../js/batch.js">               ← wizard + review + SSE search + AI + delete (~2090 lines)
<script src=".../js/book-modal.js">          ← single-book modal (~1540 lines)
<script src=".../js/bulk-result-modal.js">   ← per-source result picker (~660 lines)

<!-- after body content (lazy / self-contained): -->
<script src=".../js/duplicates.js">          ← duplicate-detection modal
<script src=".../js/scan-sync.js">           ← /scan + /sync/push SSE drivers
<script src=".../js/shelf-view.js">          ← Hyllvy paradigm + self-bootstrap
<script src=".../js/cleanup-misc.js">        ← Esc-closes-modal, resize columns
```

### Line counts

| File | Lines |
|---|---|
| `app/templates/bulk_metadata.html` | 983 |
| `app/static/css/bulk_metadata.css` | 3224 |
| `app/static/js/batch.js` | 2092 |
| `app/static/js/book-modal.js` | 1542 |
| `app/static/js/bulk-result-modal.js` | 665 |
| `app/static/js/filters-sort-paging.js` | 648 |
| `app/static/js/shelf-view.js` | 418 |
| `app/static/js/series-view.js` | 411 |
| `app/static/js/selection.js` | 254 |
| `app/static/js/duplicates.js` | 235 |
| `app/static/js/core.js` | 203 |
| `app/static/js/cleanup-misc.js` | 84 |
| `app/static/js/scan-sync.js` | 86 |

## 5. window-mirror pattern (the tricky bit)

Several state vars are owned by one module but read or written by
others. Pre-refactor they were top-level `var` in non-strict inline JS,
which makes them implicit `window.*` properties. After IIFE-wrapping in
strict mode, this auto-mirroring is broken. The fix:

- **Owner** declares with explicit `window._X = initialValue;` (not `var`).
- **Writers** in any module use explicit `window._X = newValue;` (strict
  mode disallows implicit globals on bare writes).
- **Readers** can use bare `_X` (strict mode allows reading globals via
  the scope chain), but the new files prefer explicit `window._X` for
  clarity.

State that's window-mirrored:

| var | owner | readers / writers elsewhere |
|---|---|---|
| `_viewMode` | core.js | series-view writes it briefly (the shelf-trick), all modules read |
| `_density`, `_skriptorium`, `_seriesSort`, `_hideOnlyOneSeries`, `_filterOpen` | core.js | series-view writes _seriesSort + _hideOnlyOneSeries; filters-sort-paging writes _filterOpen |
| `_grouped` | filters-sort-paging.js | selection.js + batch.js read |
| `_activeSeriesFilter` | series-view.js | filters-sort-paging reads |
| `_modalItemId`, `_modalDirty`, `_modalAllCandidates` | book-modal.js | bulk-result-modal reads |

## 6. Test plan (RUN THIS FIRST in the next session)

### 6.1 Rebuild

```bash
cd /mnt/docker/stacks/colophon/repo && \
git pull && \
cd .. && \
docker compose down && \
docker compose build --no-cache && \
docker compose up -d && \
docker logs colophon --tail 20
```

Expect: Gunicorn starts, no Python traceback.

### 6.2 Sanity (cache-bust with Ctrl+Shift+R)

Open http://192.168.50.8:5055 in browser.

1. **Page renders styled.** If raw HTML → CSS path broken.
2. **DevTools → Console** is clean. No `ReferenceError`, no
   `TypeError: X is not a function`.
3. **DevTools → Network**: all 12 `.js` files + 1 `.css` file return
   `200` with correct `Content-Type` (`application/javascript`,
   `text/css`).
4. **DevTools → Console**: type `window.__colophonConfig` → returns
   the config object with `i18n` (198 keys) and `urls`.

### 6.3 Already-verified flows (re-test to confirm no regressions)

These were each verified with a rebuild during the previous session:

| Module | Verified flow | Commit |
|---|---|---|
| `bulk_metadata.css` | Page styles, theme toggle, table/shelf/series layout | `4bfe5b6` |
| `scan-sync.js` | /scan SSE progress text, /sync/push (if upstream configured) | `b37b351` |
| `duplicates.js` | Modal opens, lists groups, delete + skip work, backdrop close | `9fe1ec4` |
| `core.js` | Theme toggle, view mode switching (table/shelf/series), density, skriptorium, language switch | `ddbe39e` |
| `series-view.js` | Series cards render, click → detail modal, click book in modal → opens book modal in display mode (window-mirror trick), filter chip + clear | `8bde5c3` |
| `selection.js` | Checkbox flow, batch-bar visibility, select-all, group mirror, bulk delete dialog | `b642429` |

### 6.4 **UNTESTED — verify these next session**

The four big modules from this session were NOT verified in a running
container. Walk through each flow:

#### filters-sort-paging.js (`c6c5a02`)

- [ ] Click each sort column header — rows reorder, arrow indicator updates.
- [ ] Type in search box — filters apply live.
- [ ] Each status / extension / missing-field dropdown filters correctly.
- [ ] Click stat-badges → filters by format / missing cover / missing metadata / unsynced.
- [ ] Pagination: change page size, click page numbers, prev/next arrows.
- [ ] Toggle group view — same-title formats collapse, chevron expand works.
- [ ] Click ⋯ actions menu → opens, click-outside closes.
- [ ] Toggle filter panel — opens/closes, "any filter active" dot lights up.
- [ ] First load: saved view mode (table/shelf/series) restored from localStorage.

#### batch.js (`0252e81` + `cea83f6`)

- [ ] Select multiple books → "Batch operations" button enables.
- [ ] Step 1: choose fields, +add field popover, language code validation.
- [ ] Step 2: search starts SSE, abort button works, per-row classification labels render.
- [ ] Step 3: text-field review (both TABLE and CARD variants, depending on layout setting).
  - [ ] Source picker (per-field, per-source values).
  - [ ] Apply-all-from-source.
  - [ ] Cherry-pick individual fields.
  - [ ] Reject / restore individual fields.
  - [ ] Save text fields → success message + format count.
- [ ] Step 3 synopsis review: choose between current / fetched / source variants.
- [ ] Step 3 cover review: pick cover, save.
- [ ] Step 3 skip → moves to next book in queue.
- [ ] Step 4 summary: shows saved / skipped / no-match counts; "filter to missing field" buttons work.
- [ ] AI search variant (if AI configured).
- [ ] Batch delete from inside wizard: confirm modal + DELETE token.

#### book-modal.js (`a77f658`)

- [ ] Click any book row / cover → modal opens.
- [ ] Display mirror (read-only formatted view) shows correctly.
- [ ] Toggle modal mode (edit ↔ display).
- [ ] Fetch metadata: synchronous Calibre + SSE per-source progress.
- [ ] Abort fetch mid-search.
- [ ] AI metadata fetch: review modal appears, select rows, apply.
- [ ] Cover search: shows results from each configured source.
- [ ] Apply cover → modal cover updates, table row cover updates.
- [ ] Reading state: mark as finished, reset.
- [ ] Find series via AI.
- [ ] Save metadata: success feedback, row updates, unsynced pill updates.
- [ ] Delete book from modal: with/without DELETE-files token.
- [ ] Esc closes modal.

#### bulk-result-modal.js (`a77f658`)

- [ ] After a batch search, click the result label of a single row → bulk-result modal opens.
- [ ] Per-source detail row (expandable inline in the search table).
- [ ] Per-field source picker: select non-default value, see it marked.
- [ ] Save → "Sparat" feedback + result label updates in search table.
- [ ] Backdrop click + Esc close.

#### cleanup-misc.js (`a77f658`)

- [ ] Esc with no modal open → does nothing.
- [ ] Esc with each modal open → closes that modal only.
- [ ] Drag any table column resize handle → width changes; persists on reload.

### 6.5 i18n re-test (Swedish only)

Switch to Swedish. Visit each of these:

- [ ] Topbar: "Sök titel, författare..." placeholder.
- [ ] Hamburger menu: "Hitta dubbletter" (double-b).
- [ ] Dubletter modal: all labels Swedish.
- [ ] Serie-detail modal: "av N", "Visa i tabell", "Böcker i den här serien", "läser/läst" counts.
- [ ] Batch wizard: "1. Välj fält", "2. Sök", "3. Granska", "4. Klart".
- [ ] Book modal scoring legend: "≥90 stark matchning" etc.

### 6.6 Pre-existing untranslated strings (separate task, NOT done)

These 7 `msgstr ""` were in the .po **before** the refactor — user
said to handle separately:

```
"AI is not configured. Open API settings and add an API key."
"Cleared %(n)d cached KEPUB files."
"Device revoked."
"Wikipedia: no title to search."
"Wikipedia: no hits."
"Initial data found. Enriching with Calibre..."
"Save the downloaded file back over the original on the Kobo (replace)."
```

## 7. Rollback recipes

Each module is a separate commit. Rollback restores the last known-good
state. After rollback, run the rebuild from §6.1.

| Last known-good | Commit | What survives |
|---|---|---|
| Pre-refactor | `6bd912b` | Nothing extracted. Original 9812-line template. |
| CSS only | `4bfe5b6` | Just CSS extraction. |
| + bridge + scan-sync | `b37b351` | Adds config bridge + scan-sync.js |
| + duplicates | `9fe1ec4` | Adds duplicates.js |
| + dubletter/dubbletter rename | `c412885` | Swedish term polish |
| + core.js | `ddbe39e` | Adds core.js (theme + view modes + density + skriptorium + setLanguage) |
| + series-view.js | `8bde5c3` | Adds series-view.js |
| + authors/reading sv | `e8481cc` | i18n polish |
| + selection.js + "Visa i tabell"/"Böcker i den här serien" sv | `b642429` | Adds selection.js |
| + filters-sort-paging.js | `c6c5a02` | Adds filters-sort-paging.js |
| + batch.js | `0252e81` | Adds batch.js — broken state vars |
| + batch state-var fix | `cea83f6` | batch.js working |
| + book-modal + bulk-result + cleanup-misc (HEAD) | `a77f658` | **Refactor complete** |

Rollback to e.g. `cea83f6` (last verified-working state, before the
untested big push):

```bash
cd /mnt/docker/stacks/colophon/repo && \
git reset --hard cea83f6 && \
cd .. && \
docker compose build --no-cache && \
docker compose up -d
```

`git reset --hard <commit>` is a destructive operation — confirms only.

## 8. Known issues / technical debt

### Pre-existing (not introduced by refactor)

- **Hard-coded Swedish strings** in `selection.js` (`' grupp'`, `' bok'`,
  `' valda'`, `'Radering misslyckades.'`, etc.) and in `book-modal.js`
  (the entire `_modalI18n` table). These were inline Swedish before the
  refactor; preserved verbatim. Proper i18n + pluralisation is a follow-up.
- **The 7 empty `msgstr` lines** in `.po` (listed in §6.6).
- **Duplicate field-label tables** scattered across modules
  (`_applyFieldLabels`, `_brcFieldLabels`, `_bpFieldLabels`,
  `_modalFieldInputMap`). Could be a single shared `field-labels.js`
  module. Not done — out of refactor scope.

### Introduced by refactor

- **Every top-level function in `batch.js` and `book-modal.js` is
  `window.X = X`'d** (58 + ~50 names). This was the pragmatic call —
  guarantees HTML onclick handlers work without auditing each one.
  Namespace pollution is the cost. A future tightening pass could
  identify the truly internal helpers and drop their `window.X` line.
- **The two-pass patch pattern in `filters-sort-paging.js`** (originally
  written that way in the inline code) is preserved verbatim inside the
  IIFE — readable but unusual. See the long header comment for the
  rationale.
- **`_modalI18n` (in `book-modal.js`)** still hard-codes a Swedish-only
  string table. The English fallback table mostly works because most
  modal strings now flow through `__colophonConfig.i18n`, but the modal
  has a few labels that ignore the bridge.

## 9. Verification status summary

| Module | Code-complete | Locally syntax-checked (node --check) | Verified in browser |
|---|---|---|---|
| `bulk_metadata.css` | ✓ | ✓ (template parses) | ✓ |
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

## 10. How to continue tomorrow

1. **Read this file first** (it's in repo root: `REFACTOR.md`).
2. **Read CLAUDE.md** for general project context.
3. **Read `~/.claude/projects/-home-christian-Dokument-Github-colophon/memory/`**
   — there are two persistent memories:
   - `project_refactor_bulk_metadata.md`
   - `project_runtime_vs_dev_paths.md` (reminder that this dev box can't
     run the container — deploy host is separate)
4. **Run the test plan in §6.** If any flow breaks, the rollback table
   in §7 gives you a fast escape hatch.
5. **Fix forward** rather than rolling back if the bug is small and
   diagnosable from the console error.
6. **When everything verifies**, mark this file as "✅ Refactor complete
   and verified" at the top.

### If the rebuild fails entirely

Most likely cause is a typo in one of the IIFE files. Diagnose with:

```bash
# Confirm Jinja still parses
docker exec colophon python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('app/templates'))
env.parse(open('app/templates/bulk_metadata.html').read())
print('jinja parse OK')
"

# Confirm each JS file parses (the dev machine has node)
for f in app/static/js/*.js; do
  node --check "$f" && echo "$(basename $f) OK"
done
```

Both pass currently. If a future change breaks one, the offending file
+ line is reported.

### Diagnostic patterns for runtime errors

| Error in console | Likely cause |
|---|---|
| `ReferenceError: X is not defined` where X is a function | Module that defines X isn't loaded before its caller. Check `<script src>` order in template L970–980. |
| `TypeError: X is not a function` | A function is shadowed locally, or `typeof === 'function'` guard missing for an optional cross-module call. |
| Page renders unstyled | CSS path broken: confirm `/static/css/bulk_metadata.css` returns 200 in Network tab. |
| English text in Swedish UI | Either bridge missing key (check `window.__colophonConfig.i18n.X`) or `.po` has empty msgstr (`grep -A1 'msgid "X"' app/translations/sv/LC_MESSAGES/messages.po`). |
| Modal opens empty / missing buttons | Likely a state-var that should be window-mirrored but isn't. Look at §5 list. |

---

**Last edited:** 2026-05-23 (end of session 1)
**Next session intent:** test, fix any regressions, mark complete.
