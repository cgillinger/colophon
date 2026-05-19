/* ------------------------------------------------------------------ *
 * shelf-view.js — Hyllvy paradigm for the bulk metadata page
 *
 * Owns: grid card rendering, infinite scroll, Skriptorium series grouping
 * (distributed per-book borders, no wrapper element).
 *
 * Reads from the shared layer in bulk_metadata.html via globals:
 *   getFilteredRows()  → table rows in current filter+sort order
 *   isSkriptoriumOn()  → boolean toggle state
 *
 * Exposes globals consumed by the template:
 *   initShelfView, destroyShelfView, refreshShelfView,
 *   applySkriptorium, removeSkriptorium, updateGridSelectionState
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var INITIAL_BATCH = 60;
    var SCROLL_BATCH  = 40;
    var GAP_X         = 20;
    var COVER_DEFAULT = 160;

    var FLOURISH_SVG =
        '<svg viewBox="0 0 22 10" width="22" height="10" xmlns="http://www.w3.org/2000/svg">' +
            '<path d="M21 5c-3 0-4-3.6-7-3.6S10 5 7 5 4 1.4 1 1.4" fill="none" stroke="rgba(76,175,80,0.55)" stroke-width="0.7" stroke-linecap="round"/>' +
            '<path d="M21 5c-3 0-4 3.6-7 3.6S10 5 7 5 4 8.6 1 8.6" fill="none" stroke="rgba(76,175,80,0.55)" stroke-width="0.7" stroke-linecap="round"/>' +
        '</svg>';

    var SE_CLASSES = [
        'in-series', 'standalone',
        'se-bg', 'se-top', 'se-bottom', 'se-left', 'se-right',
        'se-r-tl', 'se-r-tr', 'se-r-bl', 'se-r-br'
    ];

    var _renderedCount = 0;
    var _renderSeq     = 0;
    var _io            = null;
    var _ro            = null;
    var _prevCols      = 0;

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _grid() { return document.getElementById('gridView'); }

    function _coverWidth() {
        var grid = _grid();
        if (!grid) return COVER_DEFAULT;
        var v = getComputedStyle(grid).getPropertyValue('--cover-width').trim();
        var n = parseFloat(v);
        return isNaN(n) ? COVER_DEFAULT : n;
    }

    function _computeCols() {
        var grid = _grid();
        if (!grid) return 1;
        var w  = grid.clientWidth;
        var cw = _coverWidth();
        return Math.max(1, Math.floor((w + GAP_X) / (cw + GAP_X)));
    }

    function _rows() {
        if (typeof window.getFilteredRows !== 'function') return [];
        return window.getFilteredRows();
    }

    function _formatIdx(raw) {
        var n = parseFloat(raw);
        if (!isNaN(n) && n % 1 === 0) return '#' + parseInt(n, 10);
        return '#' + raw;
    }

    function _cardHtml(row) {
        var itemId    = row.dataset.itemId || '';
        var titleEl   = row.querySelector('.book-title');
        var title     = titleEl ? (titleEl.textContent || '').trim() : (row.dataset.title || '');
        var authorEl  = row.querySelector('.author-cell');
        var author    = authorEl ? (authorEl.textContent || '').trim() : '';
        var coverImg  = row.querySelector('.cover img');
        var coverSrc  = coverImg ? coverImg.getAttribute('src') : '';
        var cb        = row.querySelector('.book-checkbox');
        var checked   = cb && cb.checked ? ' checked' : '';
        var value     = cb ? cb.value : itemId;
        var series    = row.dataset.series || '';
        var seriesIdx = row.dataset.seriesIndex || '';
        var seq       = _renderSeq++;

        var imgStyle = coverSrc ? '' : 'display:none;';
        var phStyle  = coverSrc ? 'display:none;' : 'display:flex;';

        var badgeHtml = seriesIdx
            ? '<span class="series-index-badge">' + _esc(_formatIdx(seriesIdx)) + '</span>'
            : '';

        return '<div class="grid-card"'
            +    ' data-item-id="' + _esc(itemId) + '"'
            +    ' data-series="' + _esc(series) + '"'
            +    ' data-series-index="' + _esc(seriesIdx) + '"'
            +    ' data-render-seq="' + seq + '">'
            +    '<div class="grid-card-cover" onclick="openBookModal(' + _esc(itemId) + ')">'
            +      '<img src="' + _esc(coverSrc) + '" alt="" loading="lazy" style="' + imgStyle + '"'
            +        ' onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'flex\';">'
            +      '<div class="grid-card-placeholder" style="' + phStyle + '">'
            +        '<i class="ti ti-book"></i>'
            +        '<span class="grid-card-placeholder-title">' + _esc(title) + '</span>'
            +        '<span class="grid-card-placeholder-author">' + _esc(author) + '</span>'
            +      '</div>'
            +      '<input type="checkbox" class="grid-card-checkbox" value="' + _esc(value) + '"' + checked + '>'
            +      badgeHtml
            +    '</div>'
            +    '<div class="grid-card-info" onclick="openBookModal(' + _esc(itemId) + ')">'
            +      '<div class="grid-card-title">' + _esc(title) + '</div>'
            +      '<div class="grid-card-author">' + _esc(author) + '</div>'
            +    '</div>'
            +  '</div>';
    }

    function updateGridSelectionState() {
        var grid = _grid();
        if (!grid) return;
        var any = document.querySelectorAll('.book-checkbox:checked').length > 0;
        grid.classList.toggle('has-selection', any);
    }
    window.updateGridSelectionState = updateGridSelectionState;

    /* ---- Series-integrity: extend the slice forward to include every visible
     *      member of any series whose cards appear in [start, end). New series
     *      pulled in by the extension are followed transitively. ---- */
    function _expandEndForSeriesIntegrity(rows, start, end) {
        var active = Object.create(null);
        var i;
        for (i = start; i < end; i++) {
            var s = rows[i].dataset.series;
            if (s) active[s] = true;
        }
        for (i = end; i < rows.length; i++) {
            var si = rows[i].dataset.series;
            if (si && active[si]) {
                for (var j = end; j <= i; j++) {
                    var sj = rows[j].dataset.series;
                    if (sj) active[sj] = true;
                }
                end = i + 1;
            }
        }
        return end;
    }

    function _renderBatch(count) {
        var grid = _grid();
        if (!grid) return;
        var rows = _rows();
        if (_renderedCount >= rows.length) { _ensureSentinel(); return; }

        var end = Math.min(_renderedCount + count, rows.length);
        end = _expandEndForSeriesIntegrity(rows, _renderedCount, end);

        var html = '';
        for (var i = _renderedCount; i < end; i++) html += _cardHtml(rows[i]);

        var sentinel = document.getElementById('shelfSentinel');
        if (sentinel) sentinel.insertAdjacentHTML('beforebegin', html);
        else          grid.insertAdjacentHTML('beforeend', html);

        _renderedCount = end;
        _ensureSentinel();
        updateGridSelectionState();
        if (window.isSkriptoriumOn && window.isSkriptoriumOn()) applySkriptorium();
    }

    function _ensureSentinel() {
        var grid = _grid();
        if (!grid) return;
        var rows = _rows();
        var s    = document.getElementById('shelfSentinel');

        if (_renderedCount >= rows.length) {
            if (s && s.parentNode) s.parentNode.removeChild(s);
            if (_io) _io.disconnect();
            return;
        }
        if (!s) {
            s = document.createElement('div');
            s.id = 'shelfSentinel';
            s.style.cssText = 'grid-column: 1 / -1; height: 1px;';
        }
        grid.appendChild(s);
        if (!_io) {
            _io = new IntersectionObserver(function (entries) {
                for (var i = 0; i < entries.length; i++) {
                    if (entries[i].isIntersecting) { _renderBatch(SCROLL_BATCH); return; }
                }
            }, { root: null, rootMargin: '400px' });
        } else {
            _io.disconnect();
        }
        _io.observe(s);
    }

    function _setupResizeObserver() {
        if (typeof ResizeObserver === 'undefined') return;
        var grid = _grid();
        if (!grid) return;
        if (_ro) _ro.disconnect();
        _prevCols = _computeCols();
        _ro = new ResizeObserver(function () {
            var c = _computeCols();
            if (c !== _prevCols) {
                _prevCols = c;
                if (window.isSkriptoriumOn && window.isSkriptoriumOn()) applySkriptorium();
            }
        });
        _ro.observe(grid);
    }

    /* -------------------- Skriptorium -------------------- */

    function _clearSkriptoriumClasses(card) {
        for (var i = 0; i < SE_CLASSES.length; i++) {
            card.classList.remove(SE_CLASSES[i]);
        }
        if (card.dataset.seriesGroup) delete card.dataset.seriesGroup;
    }

    function removeSkriptorium() {
        var grid = _grid();
        if (!grid) return;

        var tags = grid.querySelectorAll('.series-tag');
        for (var i = 0; i < tags.length; i++) tags[i].parentNode.removeChild(tags[i]);

        var cards = Array.from(grid.querySelectorAll('.grid-card'));
        for (var j = 0; j < cards.length; j++) _clearSkriptoriumClasses(cards[j]);

        /* Restore original render order. */
        cards.sort(function (a, b) {
            return (parseInt(a.dataset.renderSeq, 10) || 0) - (parseInt(b.dataset.renderSeq, 10) || 0);
        });
        var sentinel = document.getElementById('shelfSentinel');
        if (sentinel && sentinel.parentNode) sentinel.parentNode.removeChild(sentinel);
        for (var k = 0; k < cards.length; k++) grid.appendChild(cards[k]);
        if (sentinel) grid.appendChild(sentinel);

        grid.classList.remove('series-grouping-active');
    }
    window.removeSkriptorium = removeSkriptorium;

    function _computePositions(cards) {
        var positions = new Map();
        if (cards.length === 0) return positions;

        var topsSet  = Object.create(null);
        var leftsSet = Object.create(null);
        for (var i = 0; i < cards.length; i++) {
            topsSet[cards[i].offsetTop]   = true;
            leftsSet[cards[i].offsetLeft] = true;
        }
        var tops  = Object.keys(topsSet ).map(Number).sort(function (a, b) { return a - b; });
        var lefts = Object.keys(leftsSet).map(Number).sort(function (a, b) { return a - b; });
        var topIdx = {};  for (var t = 0; t < tops.length;  t++) topIdx [tops [t]] = t;
        var leftIdx = {}; for (var l = 0; l < lefts.length; l++) leftIdx[lefts[l]] = l;

        for (var c = 0; c < cards.length; c++) {
            positions.set(cards[c], {
                row: topIdx [cards[c].offsetTop],
                col: leftIdx[cards[c].offsetLeft]
            });
        }
        return positions;
    }

    function applySkriptorium() {
        var grid = _grid();
        if (!grid) return;

        removeSkriptorium();

        /* Phase 1: collect & sort groups, mark cards, reorder DOM. */
        var allCards = Array.from(grid.querySelectorAll('.grid-card'));
        var groups   = Object.create(null);
        var order    = [];
        for (var i = 0; i < allCards.length; i++) {
            var card = allCards[i];
            var name = (card.dataset.series || '').trim();
            if (!name) continue;
            if (!groups[name]) { groups[name] = []; order.push(name); }
            groups[name].push(card);
        }

        var validGroups = [];
        for (var g = 0; g < order.length; g++) {
            if (groups[order[g]].length >= 2) validGroups.push(order[g]);
        }

        /* Always switch to dense flow so standalone cards can backfill gaps. */
        grid.classList.add('series-grouping-active');

        if (validGroups.length === 0) {
            for (var s0 = 0; s0 < allCards.length; s0++) allCards[s0].classList.add('standalone');
            return;
        }

        /* Sort within each group. */
        for (var sg = 0; sg < validGroups.length; sg++) {
            var members = groups[validGroups[sg]];
            members.sort(function (a, b) {
                var ai = parseFloat(a.dataset.seriesIndex);
                var bi = parseFloat(b.dataset.seriesIndex);
                var aHas = !isNaN(ai), bHas = !isNaN(bi);
                if (aHas && bHas) return ai - bi;
                if (aHas) return -1;
                if (bHas) return 1;
                var at = (a.querySelector('.grid-card-title') || {}).textContent || '';
                var bt = (b.querySelector('.grid-card-title') || {}).textContent || '';
                return at.localeCompare(bt);
            });
            for (var m = 0; m < members.length; m++) {
                members[m].classList.add('in-series');
                members[m].dataset.seriesGroup = validGroups[sg];
            }
        }
        for (var st = 0; st < allCards.length; st++) {
            if (!allCards[st].classList.contains('in-series')) {
                allCards[st].classList.add('standalone');
            }
        }

        /* Build new DOM order: walk original cards; emit the whole group when
         * its first member is encountered. */
        var emitted  = new Set();
        var newOrder = [];
        for (var oi = 0; oi < allCards.length; oi++) {
            var ca = allCards[oi];
            if (emitted.has(ca)) continue;
            var gname = ca.dataset.seriesGroup;
            if (gname && groups[gname] && groups[gname].length >= 2) {
                for (var k2 = 0; k2 < groups[gname].length; k2++) {
                    newOrder.push(groups[gname][k2]);
                    emitted.add(groups[gname][k2]);
                }
            } else {
                newOrder.push(ca);
                emitted.add(ca);
            }
        }

        var sentinel = document.getElementById('shelfSentinel');
        if (sentinel && sentinel.parentNode) sentinel.parentNode.removeChild(sentinel);
        for (var n = 0; n < newOrder.length; n++) grid.appendChild(newOrder[n]);
        if (sentinel) grid.appendChild(sentinel);

        /* Phase 2: read positions after layout. */
        var positions = _computePositions(newOrder);

        /* Phase 3: per-side borders + exposed-corner radii. */
        for (var vg = 0; vg < validGroups.length; vg++) {
            var gn       = validGroups[vg];
            var mem      = groups[gn];
            var occupied = Object.create(null);
            for (var p = 0; p < mem.length; p++) {
                var pp = positions.get(mem[p]);
                if (pp) occupied[pp.row + ',' + pp.col] = true;
            }
            for (var q = 0; q < mem.length; q++) {
                var card2 = mem[q];
                var pos = positions.get(card2);
                if (!pos) continue;
                var r = pos.row, c = pos.col;
                var up    = !!occupied[(r - 1) + ',' + c];
                var down  = !!occupied[(r + 1) + ',' + c];
                var left  = !!occupied[r + ',' + (c - 1)];
                var right = !!occupied[r + ',' + (c + 1)];
                card2.classList.add('se-bg');
                if (!up)    card2.classList.add('se-top');
                if (!down)  card2.classList.add('se-bottom');
                if (!left)  card2.classList.add('se-left');
                if (!right) card2.classList.add('se-right');
                if (!up   && !left)  card2.classList.add('se-r-tl');
                if (!up   && !right) card2.classList.add('se-r-tr');
                if (!down && !left)  card2.classList.add('se-r-bl');
                if (!down && !right) card2.classList.add('se-r-br');
            }
        }

        /* Phase 4: series-name tags centred above the first row of each series. */
        for (var ti = 0; ti < validGroups.length; ti++) {
            var gn2 = validGroups[ti];
            var mem2 = groups[gn2];
            var firstRow = null;
            for (var fr = 0; fr < mem2.length; fr++) {
                var fp = positions.get(mem2[fr]);
                if (fp && (firstRow === null || fp.row < firstRow)) firstRow = fp.row;
            }
            if (firstRow === null) continue;

            var onFirstRow = mem2.filter(function (cc) {
                var pp2 = positions.get(cc);
                return pp2 && pp2.row === firstRow;
            }).sort(function (a, b) { return a.offsetLeft - b.offsetLeft; });
            if (onFirstRow.length === 0) continue;

            var firstCard = onFirstRow[0];
            var lastCard  = onFirstRow[onFirstRow.length - 1];
            var centerX   = (firstCard.offsetLeft + lastCard.offsetLeft + lastCard.offsetWidth) / 2;
            var topY      = firstCard.offsetTop - 9;

            var tag = document.createElement('div');
            tag.className = 'series-tag';
            tag.dataset.seriesTagFor = gn2;
            tag.innerHTML =
                '<span class="series-flourish">' + FLOURISH_SVG + '</span>' +
                '<span class="series-name">' + _esc(gn2) + '</span>' +
                '<span class="series-flourish" style="transform: scaleX(-1)">' + FLOURISH_SVG + '</span>';
            tag.style.left      = centerX + 'px';
            tag.style.top       = topY + 'px';
            tag.style.transform = 'translateX(-50%)';
            grid.appendChild(tag);
        }
    }
    window.applySkriptorium = applySkriptorium;

    /* -------------------- Lifecycle -------------------- */

    function initShelfView() {
        var grid = _grid();
        if (!grid) return;
        document.body.classList.add('shelf-active');
        _renderedCount = 0;
        _renderSeq     = 0;
        grid.innerHTML = '';
        _renderBatch(INITIAL_BATCH);
        _setupResizeObserver();
        /* renderBatch already applies Skriptorium when toggled on. */
    }
    window.initShelfView = initShelfView;

    function destroyShelfView() {
        removeSkriptorium();
        if (_io) { _io.disconnect(); _io = null; }
        if (_ro) { _ro.disconnect(); _ro = null; }
        var s = document.getElementById('shelfSentinel');
        if (s && s.parentNode) s.parentNode.removeChild(s);
        var grid = _grid();
        if (grid) grid.innerHTML = '';
        document.body.classList.remove('shelf-active');
        _renderedCount = 0;
        _renderSeq     = 0;
    }
    window.destroyShelfView = destroyShelfView;

    function refreshShelfView() {
        var grid = _grid();
        if (!grid) return;
        removeSkriptorium();
        if (_io) _io.disconnect();
        _renderedCount = 0;
        _renderSeq     = 0;
        grid.innerHTML = '';
        _renderBatch(INITIAL_BATCH);
    }
    window.refreshShelfView = refreshShelfView;
})(window, document);
