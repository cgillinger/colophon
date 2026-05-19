# Colophon — View Architecture

Design document governing how the bulk metadata page (`/metadata/bulk`) organises its display modes, scroll behaviour, and view-specific features. This is the authoritative reference for all future development on the library views.

---

## 1. Two paradigms, not three modes

The library has **two view paradigms**, each with its own rendering pipeline, scroll model, and feature set. The former "compact / gallery / grid" trichotomy is replaced by:

| Paradigm | Purpose | Internal variants |
|---|---|---|
| **Tabellvy** | Data-focused browsing — rows, sortable columns, metadata scanning | Density toggle: *kompakt* (small covers, tight rows) / *luftig* (larger covers, more padding) |
| **Hyllvy** | Visual browsing — cover-first grid, "bookshelf" feel | Skriptorium series grouping (on/off toggle) |

### Why this matters

Every feature belongs to exactly one paradigm or to the shared layer. There is no "check which of three modes we're in" branching. The decision tree is:

```
Is it about rendering, scrolling, or a view-specific interaction?
  → Yes: it belongs to that paradigm's module
  → No: it belongs to the shared layer
```

---

## 2. Shared layer

Logic consumed by both paradigms:

- **Filter state** — search text, file type filter, "saknar" filter
- **Selection state** — which books are checked, "select all" logic
- **Data access** — reading metadata from the DOM (table rows are the source of truth; grid cards are rendered from them)
- **Batch operations** — enrich, export, etc. (operate on selection, agnostic to view)
- **Sort state** — current sort key + direction (UI differs per paradigm, but the underlying sorted row order is shared)

The shared layer exposes functions like `getFilteredRows()`, `getSelectedIds()`, `getCurrentSort()` that both paradigms call.

---

## 3. Tabellvy

### Rendering

Standard HTML `<table>` with `<tr>` per book. Density toggle changes CSS class on the table, adjusting cover size and row padding. No DOM rebuild — pure CSS switch.

### Scroll model

Pagination (20 / 50 / 100 / all). Page buttons at bottom. Unchanged from current implementation.

### Features

- Column-click sorting (title, author, date, etc.)
- Author grouping (expandable groups)
- Density toggle (kompakt / luftig) — visible only in this paradigm

### Container width

Standard content width (unchanged).

---

## 4. Hyllvy

### Rendering

CSS Grid of `.grid-card` elements inside `#gridView`. Each card carries `data-series` and `data-series-index` attributes read from the underlying table row.

### Scroll model

**Infinite scroll (lazy-load).** Initial render: ~60 books. `IntersectionObserver` on a sentinel element at the bottom loads the next batch (~40) from the already-filtered row list in memory. No new backend requests.

Pagination controls are hidden in this paradigm.

### Container width

Wider layout: `max-width: 95vw` (capped at ~1600px) to utilise screen real estate. Reverts to standard width when switching to Tabellvy.

### Features

- **Skriptorium** series grouping (see §5) — toggle visible only in this paradigm
- Sort dropdown in toolbar (same sort keys as table columns, different UI)

---

## 5. Skriptorium — Series Grouping

A visual system for grouping books that belong to the same series inside the grid. Named after the medieval manuscript rooms — the feature treats the grid as a curated shelf.

### 5.1 Data requirements

Each `.grid-card` needs:

| Attribute | Source | Example |
|---|---|---|
| `data-series` | `library_items.series` | `"The Expanse"` |
| `data-series-index` | `library_items.series_index` | `"3"` |

Empty or missing `data-series` → standalone book (never grouped).

### 5.2 Algorithm

1. **Collect:** Walk grid cards in DOM order. For each unique `data-series`, collect all cards into a group. Group is placed at the position of its first member in current sort order.
2. **Sort within group:** By `data-series-index` (float, ascending). Items without index sort last, alphabetically by title.
3. **Singleton rule:** A series with only one visible card → treated as standalone, no frame.
4. **Span:** The wrapper element spans `K = min(books_in_series, visible_grid_columns)` columns.
5. **Wrapping:** If books > columns, `flex-wrap: wrap` inside the frame. Books flow to a second row, left-aligned. No horizontal scroll — all books always visible.
6. **Dense flow:** Parent grid uses `grid-auto-flow: dense` so standalone books fill gaps.

### 5.3 Idempotent rebuild

Every `applySkriptorium()` call starts with `removeSkriptorium()`:

- All wrapper elements are removed
- All cards are returned to the grid as flat children
- Then grouping is re-applied

This makes the function safe to call after any state change (filter, sort, page, resize, toggle).

### 5.4 Resize handling

A `ResizeObserver` on the grid element recomputes column count. When it changes, full rebuild is triggered. Column count formula:

```
cols = floor((gridWidth + gapX) / (colWidth + gapX))
```

### 5.5 Visual design

**Frame:** `box-shadow: 0 0 0 2.5px rgba(76, 175, 80, 0.55)` (green, Colophon's accent). No `border` — box-shadow doesn't affect layout. Background: `rgba(76, 175, 80, 0.03)`.

**Series name tag:** Positioned on top of the frame border, centred. Gold text in Cormorant Garamond italic. Flanked by SVG flourish ornaments.

| Element | Colour | Notes |
|---|---|---|
| Frame border | `rgba(76, 175, 80, 0.55)` | Green — Colophon accent, via box-shadow |
| Frame background | `rgba(76, 175, 80, 0.03)` | Barely-there green tint |
| Series name text | `rgba(196, 164, 90, 0.88)` | Antique gold — **only element in gold** |
| Flourish ornaments | `rgba(76, 175, 80, 0.55)` | Green — matches frame, not gold |
| Series index badge | `rgba(0, 0, 0, 0.72)` bg, `#fff` text | Top-left corner of each cover |

**Standalone alignment:** When grouping is active, standalone cards get `padding-top` equal to the frame's overhead (tag height + frame padding) so covers align vertically with framed covers.

**Popup suppression:** Hover popups on items inside frames are hidden (`display: none !important`) — frame overflow clipping makes them render incorrectly.

### 5.6 Font

Cormorant Garamond (italic, weights 400 + 500) loaded via Google Fonts. Used only for series name tags.

---

## 6. File structure

```
app/
  templates/
    bulk_metadata.html      ← shared template, both paradigms
  static/
    js/
      shelf-view.js         ← Hyllvy: grid rendering, infinite scroll, Skriptorium
    css/
      skriptorium.css       ← Skriptorium-specific styles (or inline in template)
```

Tabellvy logic remains in the existing `<script>` block in `bulk_metadata.html` (it's already there and working). Hyllvy logic is extracted into `shelf-view.js` to keep the paradigms separate.

### 6.1 Interface contract

`shelf-view.js` exports (or exposes globally):

```javascript
initShelfView()       // called when switching to Hyllvy
destroyShelfView()    // called when switching away
refreshShelfView()    // called after filter/sort changes
```

The view switcher in the toolbar calls these. The shared layer (filters, sort) calls `refreshShelfView()` when state changes and Hyllvy is active.

---

## 7. Toggle persistence

| Setting | Storage | Key |
|---|---|---|
| Active paradigm (tabell/hylla) | localStorage | `colophon-view-mode` |
| Table density (kompakt/luftig) | localStorage | `colophon-table-density` |
| Skriptorium on/off | localStorage | `colophon-skriptorium` |

---

## 8. Migration from current state

The current three-way toggle (`compact` / `gallery` / `grid`) maps to:

| Old value | New value |
|---|---|
| `compact` | Tabellvy, density = kompakt |
| `gallery` | Tabellvy, density = luftig |
| `grid` | Hyllvy |

A one-time migration in JS reads the old localStorage key (`colophon-view-mode`) and maps it.

---

## 9. Future extension points

- **Cover size slider** (Hyllvy) → `shelf-view.js`, adjusts `--cover-width`
- **Column customisation** (Tabellvy) → table-specific, doesn't touch Hyllvy
- **Drag-and-drop manual ordering** → `shelf-view.js`
- **New filter types** → shared layer, both paradigms react
- **Reading status overlay** → per-card, both paradigms can show it
- **Optimal rectangle spanning** (Skriptorium) → isolated change in span calculation function
