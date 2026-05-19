# Colophon — Skriptorium Spec

Detailed CSS, SVG, and algorithmic specification for the Skriptorium series-grouping
feature in Hyllvy. Pairs with [`colophon-view-architecture.md`](./colophon-view-architecture.md).

The name **Skriptorium** comes from the medieval manuscript rooms where related codices
were curated together — the feature treats the grid as a curated shelf.

> **Design choice:** distributed per-book borders, not wrapper elements.
> Each book remains its own `.grid-card` grid item. The series contour is drawn by
> adding a border only on the *exposed* sides of each book (sides that don't touch
> another book in the same series). This supports L-shaped, T-shaped and irregular
> contours, and lets `grid-auto-flow: dense` move standalone books into any gaps.

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
`row.dataset.series` / `row.dataset.seriesIndex` and copies them onto the card.

---

## 2. Algorithm — `applySkriptorium()`

Idempotent. Safe to call after any state change.

### Phase 1 — DOM reorder

1. Call `removeSkriptorium()` first.
2. Collect groups by `data-series` (skip empty). Drop singletons.
3. Sort each group by `parseFloat(data-series-index)` ascending; index-less items
   sort last, alphabetically by title.
4. Walk the current card list in DOM order. When the first card of a group is
   encountered, emit *the whole group* consecutively. Mark each card with
   `.in-series` and `data-series-group="<name>"`. Mark all other cards `.standalone`.
5. Re-append the cards in the new order into `#gridView`. The sentinel
   (`#shelfSentinel`) is detached first and re-appended last so the IntersectionObserver
   still fires.
6. Add `.series-grouping-active` to `#gridView`. CSS sets `grid-auto-flow: dense`
   so standalones can backfill any holes.

### Phase 2 — Compute grid positions

After the reorder, layout is current. For each card, read `offsetTop` and
`offsetLeft`. Distinct `offsetTop` values → row indices. Distinct `offsetLeft`
values → column indices. Build a `Map<card, {row, col}>`.

This is more reliable than `index % cols` arithmetic, because `grid-auto-flow:
dense` can move items into earlier holes — the linear index no longer matches the
visual position.

### Phase 3 — Distributed borders

For each series, build `occupied = Set<"row,col">` from its members. For each
member, check its 4 grid neighbours:

```js
var r = pos.row, c = pos.col;
var up    = occupied.has((r - 1) + ',' + c);
var down  = occupied.has((r + 1) + ',' + c);
var left  = occupied.has(r + ',' + (c - 1));
var right = occupied.has(r + ',' + (c + 1));

card.classList.add('se-bg');
if (!up)    card.classList.add('se-top');
if (!down)  card.classList.add('se-bottom');
if (!left)  card.classList.add('se-left');
if (!right) card.classList.add('se-right');
if (!up   && !left)  card.classList.add('se-r-tl');
if (!up   && !right) card.classList.add('se-r-tr');
if (!down && !left)  card.classList.add('se-r-bl');
if (!down && !right) card.classList.add('se-r-br');
```

This produces a continuous contour around any rectilinear shape the series
occupies, including L's and partial last rows.

### Phase 4 — Series name tag

For each series, find the first row (lowest `row`) and the leftmost/rightmost
cards on that row. Create a `.series-tag` element, position it absolutely in the
grid (which is `position: relative`) centred between those two cards, sitting on
the top border:

```js
var firstRowMembers = members.filter(c => positions.get(c).row === firstRow);
var first = firstRowMembers[0];
var last  = firstRowMembers[firstRowMembers.length - 1];

var centerX = (first.offsetLeft + last.offsetLeft + last.offsetWidth) / 2;
var topY    = first.offsetTop - 9;   /* sits on the top border */

tag.style.left      = centerX + 'px';
tag.style.top       = topY + 'px';
tag.style.transform = 'translateX(-50%)';
```

The tag has its own background that masks the border line behind the text.

---

## 3. `removeSkriptorium()`

1. Remove all `.series-tag` elements from `#gridView`.
2. For every `.grid-card`, strip the classes
   `in-series`, `standalone`, `se-bg`, `se-top`, `se-bottom`, `se-left`, `se-right`,
   `se-r-tl`, `se-r-tr`, `se-r-bl`, `se-r-br` and clear `data-series-group`.
3. Restore original DOM order by sorting cards on `data-render-seq` and
   re-appending (sentinel stays at end).
4. Remove `.series-grouping-active` from `#gridView`.

---

## 4. Resize handling

A `ResizeObserver` is attached to `#gridView` after `initShelfView()`. The callback
computes a new column count from `gridWidth`, `--cover-width` and the grid gap.
If it changed, the observer calls `applySkriptorium()` — the new contour shape is
derived purely from the recomputed positions.

---

## 5. Series integrity (infinite scroll)

`_renderBatch(count)` always extends its slice forward to include every visible
member of any series that has cards in the slice. New series introduced by the
extension itself are also followed, transitively. This guarantees Skriptorium
never sees a half-loaded series and avoids re-render churn when the user scrolls
and a series completes one batch later.

---

## 6. CSS

### 6.1 Grid container

```css
#gridView {
  --cover-width: 160px;
  position: relative;                /* anchors absolutely-positioned series-tag */
  display: grid;
  grid-template-columns: repeat(auto-fill, var(--cover-width));
  gap: 20px;
  padding: 16px 0;
}

#gridView.series-grouping-active {
  grid-auto-flow: dense;             /* lets standalone cards backfill gaps */
}
```

### 6.2 Distributed border + background

```css
.se-top    { border-top:    2.5px solid rgba(76, 175, 80, 0.55) !important; }
.se-right  { border-right:  2.5px solid rgba(76, 175, 80, 0.55) !important; }
.se-bottom { border-bottom: 2.5px solid rgba(76, 175, 80, 0.55) !important; }
.se-left   { border-left:   2.5px solid rgba(76, 175, 80, 0.55) !important; }

.se-r-tl { border-top-left-radius:     6px; }
.se-r-tr { border-top-right-radius:    6px; }
.se-r-bl { border-bottom-left-radius:  6px; }
.se-r-br { border-bottom-right-radius: 6px; }

.se-bg   { background: rgba(76, 175, 80, 0.03); }
```

The hover transform on `.grid-card` is suppressed for `.in-series` so the
contour stays intact when the cursor moves over a member:

```css
.in-series:hover { transform: none; box-shadow: none; }
```

### 6.3 Series name tag

```css
.series-tag {
  position: absolute;
  z-index: 4;
  line-height: 1;
  display: flex;
  align-items: center;
  gap: 4px;
  pointer-events: none;
  background: var(--bg-primary);     /* masks the border line behind the text */
  padding: 2px 10px;
  border-radius: 3px;
}

.series-name {
  font-family: 'Cormorant Garamond', Georgia, 'Times New Roman', serif;
  font-size: 16px;
  font-weight: 500;
  font-style: italic;
  color: rgba(196, 164, 90, 0.88);    /* the ONLY gold element */
  letter-spacing: 0.4px;
  padding: 0 3px;
}

.series-flourish {
  display: inline-block;
  width: 22px;
  height: 10px;
  line-height: 0;
}
```

### 6.4 Series index badge

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

The badge is rendered inline by `_cardHtml()` for any card whose
`data-series-index` is non-empty. It is visible regardless of the Skriptorium
toggle.

### 6.5 Popup suppression

```css
.in-series .synopsis-popup { display: none !important; }
```

---

## 7. SVG flourish

Left flourish (right flourish uses the same SVG, mirrored via `transform: scaleX(-1)`):

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

Stroke colour matches the book border (green), **not** the gold of the series
name. The gold appears only on text.

---

## 8. Font loading

In `<head>` of `bulk_metadata.html`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@1,400;1,500&display=swap"
      rel="stylesheet">
```

---

## 9. Interaction with shared behaviour

- **Modal opening:** clicking a cover still calls `openBookModal(itemId)`.
- **Selection:** the `.grid-card-checkbox` keeps working — Skriptorium only adds
  classes and re-orders existing nodes, it doesn't re-render them.
- **Filtering / sorting:** the shared layer calls `refreshShelfView()` which
  rebuilds the grid from `getFilteredRows()` in current sort order, then
  re-applies Skriptorium if it was on.

---

## 10. Verification checklist

1. Series with ≥2 visible books on the same row → green contour, gold italic name.
2. Series with one row + a partial second row → "P"/inverted-L contour without inner edges.
3. Series with one visible book → no border (singleton rule).
4. Filter that hides all but one book in a series → border disappears.
5. Sort change → series reorders to its new first-member position.
6. Resize browser narrower → column count drops → contour recomputes correctly.
7. Skriptorium toggle off → flat grid, no borders, no tag overlays.
8. Series-index badge present on every card that has a `series_index`, in both states.
9. Hover over a member doesn't lift the card and break the contour.
