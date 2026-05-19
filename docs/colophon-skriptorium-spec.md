# Colophon — Skriptorium Spec

Detailed CSS, SVG, and algorithmic specification for the Skriptorium series-grouping
feature in Hyllvy. Pairs with [`colophon-view-architecture.md`](./colophon-view-architecture.md);
where the architecture doc describes the *what*, this doc nails down the *how*.

The name **Skriptorium** comes from the medieval manuscript rooms where related codices
were curated together — the feature treats the grid as a curated shelf.

---

## 1. Data contract

Every `.grid-card` rendered in `#gridView` MUST carry the following attributes,
propagated from the underlying `<tr>` in `#bookTableBody`:

```html
<div class="grid-card"
     data-item-id="123"
     data-series="The Expanse"
     data-series-index="3">
  ...
</div>
```

| Attribute | Source column | Notes |
|---|---|---|
| `data-series` | `library_items.series` | Empty/missing → standalone book |
| `data-series-index` | `library_items.series_index` | Float-parseable, e.g. `"3"`, `"3.5"`, `""` |

The table row is the source of truth. `shelf-view.js` reads
`row.dataset.series` / `row.dataset.seriesIndex` and copies them onto the card it
renders.

---

## 2. Algorithm — `applySkriptorium()`

Idempotent. Safe to call after any state change.

1. Call `removeSkriptorium()` first — strip any existing frames.
2. **Measure columns:** `cols = floor((gridWidth + gapX) / (colWidth + gapX))`.
   `colWidth` is set via the CSS variable `--cover-width` (default `160px`); `gapX`
   defaults to `20px` (matches `#gridView { gap: 20px; }`).
3. **Collect groups:** iterate over all `.grid-card` elements in DOM order.
   Group cards by `data-series` (non-empty). Remember the first-occurrence index of
   each group — that's where the wrapper will be inserted.
4. **Filter singletons:** drop any group with fewer than 2 visible cards. Those
   cards stay as flat grid children.
5. **Sort within group:** by `parseFloat(data-series-index)` ascending. Cards
   without a numeric index sort *last*, alphabetically by title.
6. **Build wrappers:** for each remaining group, create:
   ```html
   <div class="series-frame" style="grid-column: span K">
     <div class="series-tag">
       <span class="series-flourish">…SVG…</span>
       <span class="series-name">The Expanse</span>
       <span class="series-flourish" style="transform: scaleX(-1)">…SVG…</span>
     </div>
     <div class="series-inner">
       <!-- moved .grid-card children, each gets a .series-index-badge -->
     </div>
   </div>
   ```
   where `K = min(groupSize, cols)`. Move the group's cards into `.series-inner`.
7. **Insert wrapper** at the position of the group's first card in the grid.
8. Set `#gridView { grid-auto-flow: dense; }` and add class
   `.series-grouping-active` to `#gridView`.
9. **Standalone alignment:** standalone cards (direct children of
   `.series-grouping-active`, not inside a `.series-frame`) get
   `padding-top: 18px` so their covers align vertically with framed covers.

## 3. `removeSkriptorium()`

1. For each `.series-frame` in `#gridView`:
   - Move each `.grid-card` out of `.series-inner` back to `#gridView` (preserving order).
   - Remove the wrapper element.
2. Remove `.series-grouping-active` from `#gridView`.
3. Reset `grid-auto-flow` to its default.
4. Remove the `padding-top` adjustment from standalone cards.
5. Strip `.series-index-badge` elements that were added during grouping.

## 4. Resize handling

A `ResizeObserver` is attached to `#gridView` after `initShelfView()`. The callback:

```js
var newCols = computeCols();
if (newCols !== _prevCols) {
  _prevCols = newCols;
  if (_skriptoriumOn()) applySkriptorium(); // full rebuild
}
```

No throttling needed — `applySkriptorium()` is O(N) over visible cards and only
fires on actual column changes (not on every pixel of resize).

---

## 5. CSS

### 5.1 Grid container in Skriptorium mode

```css
#gridView {
  display: grid;
  grid-template-columns: repeat(auto-fill, var(--cover-width, 160px));
  gap: 20px;
  padding: 16px 0;
}

#gridView.series-grouping-active {
  grid-auto-flow: dense;
}

/* Standalone alignment: only direct children of #gridView, not nested in a frame */
#gridView.series-grouping-active > .grid-card {
  padding-top: 18px;
}
```

### 5.2 Frame

```css
.series-frame {
  position: relative;
  border: none;                                       /* box-shadow doesn't shift layout */
  box-shadow: 0 0 0 2.5px rgba(76, 175, 80, 0.55);
  border-radius: 6px;
  background: rgba(76, 175, 80, 0.03);
  padding: 18px 6px 10px;
}

.series-frame .series-inner {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
  padding: 4px 3px 6px;
}

.series-frame .series-inner .grid-card {
  width: var(--cover-width, 160px);
  flex: 0 0 var(--cover-width, 160px);
}

/* Tooltips/popups clip badly inside frames — suppress */
.series-frame .synopsis-popup {
  display: none !important;
}
```

### 5.3 Series tag

```css
.series-tag {
  position: absolute;
  top: -10px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-primary, #1e2128);
  padding: 0 10px;
  white-space: nowrap;
  z-index: 4;
  line-height: 1;
  display: flex;
  align-items: center;
  gap: 4px;
}

.series-name {
  font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif;
  font-size: 16px;
  font-weight: 500;
  font-style: italic;
  color: rgba(196, 164, 90, 0.88);                    /* the ONLY gold element */
  letter-spacing: 0.4px;
  padding: 0 3px;
}

.series-flourish {
  display: inline-block;
  width: 22px;
  height: 10px;
}
```

### 5.4 Series index badge

```css
.series-index-badge {
  position: absolute;
  left: 5px;
  top: 5px;
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 500;
  letter-spacing: 0.3px;
  z-index: 5;
  pointer-events: none;
}
```

---

## 6. SVG flourish

Left flourish (right flourish is the same SVG, mirrored via `transform: scaleX(-1)`):

```svg
<svg viewBox="0 0 22 10" width="22" height="10" xmlns="http://www.w3.org/2000/svg">
  <path d="M21 5c-3 0-4-3.6-7-3.6S10 5 7 5 4 1.4 1 1.4"
        fill="none" stroke="rgba(76,175,80,0.55)"
        stroke-width="0.7" stroke-linecap="round"/>
  <path d="M21 5c-3 0-4 3.6-7 3.6S10 5 7 5 4 8.6 1 8.6"
        fill="none" stroke="rgba(76,175,80,0.55)"
        stroke-width="0.7" stroke-linecap="round"/>
</svg>
```

Stroke colour matches the frame border (green), **not** the gold of the series
name. The gold appears only on text — flourishes and frame are green.

---

## 7. Font loading

In `<head>` of `bulk_metadata.html`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@1,400;1,500&display=swap"
      rel="stylesheet">
```

Only the italic axis at weights 400 and 500 is used.

---

## 8. Interaction with shared behaviour

- **Modal opening:** clicking a cover inside a `.series-frame` still calls
  `openBookModal(itemId)`. Grouping does not interpose any handlers.
- **Selection:** the `.grid-card-checkbox` keeps working — `removeSkriptorium()`
  preserves checked state because it moves the same DOM nodes (it does not
  re-render them).
- **Filtering / sorting:** the shared layer calls `refreshShelfView()` which
  rebuilds the grid from `getFilteredRows()` in current sort order, then
  re-applies Skriptorium if it was on.

---

## 9. Verification checklist

1. Series with ≥2 visible books → green frame, gold italic name, two green flourishes.
2. Series with 1 visible book → no frame (singleton rule).
3. Filter that hides all but one book in a series → frame disappears.
4. Sort change → groups re-positioned at their first member's new location.
5. Resize browser narrower → column count drops → frame spans recompute.
6. Skriptorium toggle off → flat grid, no frames, no padding adjustments.
7. Standalone cards inside `.series-grouping-active` have `padding-top: 18px`;
   cards inside `.series-frame` do not.
8. Series-index badge on each cover when grouped, hidden when not grouped.
