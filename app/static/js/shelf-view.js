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
            '<path d="M21 5c-3 0-4-3.6-7-3.6S10 5 7 5 4 1.4 1 1.4" fill="none" stroke="rgba(76,175,80,0.7)" stroke-width="0.7" stroke-linecap="round"/>' +
            '<path d="M21 5c-3 0-4 3.6-7 3.6S10 5 7 5 4 8.6 1 8.6" fill="none" stroke="rgba(76,175,80,0.7)" stroke-width="0.7" stroke-linecap="round"/>' +
        '</svg>';

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

    function _readStateHtml(row) {
        /* Cover-progress bar + check badge for Phase 3 reading-state sync.
         * Shelf view only. Reads data-read-status / data-read-progress that
         * the bulk template emits on every <tr>. */
        var status = row.dataset.readStatus || 'ReadyToRead';
        if (status === 'ReadyToRead' || !status) return '';
        var html = '';
        var pct = parseFloat(row.dataset.readProgress);
        if (isNaN(pct)) pct = (status === 'Finished') ? 100 : 0;
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
        var cls = status === 'Finished' ? 'cover-progress finished' : 'cover-progress';
        html += '<div class="' + cls + '"><span class="fill" style="width:' + pct + '%"></span></div>';
        if (status === 'Finished') {
            html += '<span class="cover-check" title="Finished">✓</span>';
        }
        return html;
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
        var readSt    = row.dataset.readStatus || 'ReadyToRead';
        var readPct   = row.dataset.readProgress || '';
        var seq       = _renderSeq++;

        var imgStyle = coverSrc ? '' : 'display:none;';
        var phStyle  = coverSrc ? 'display:none;' : 'display:flex;';

        var badgeHtml = seriesIdx
            ? '<span class="series-index-badge">' + _esc(_formatIdx(seriesIdx)) + '</span>'
            : '';

        var readHtml = _readStateHtml(row);

        return '<div class="grid-card"'
            +    ' data-item-id="' + _esc(itemId) + '"'
            +    ' data-series="' + _esc(series) + '"'
            +    ' data-series-index="' + _esc(seriesIdx) + '"'
            +    ' data-read-status="' + _esc(readSt) + '"'
            +    ' data-read-progress="' + _esc(readPct) + '"'
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
            +      readHtml
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

    /* Smallest row count that lets the series fit in <= `cols` columns —
     * gives a balanced rectangle instead of one wide row + a short remainder.
     *   n=10, cols=8 → span 5 (rows 2, 5+5)
     *   n=12, cols=8 → span 6 (rows 2, 6+6)
     *   n= 9, cols=8 → span 5 (rows 2, 5+4)
     */
    function _calcSeriesSpan(n, cols) {
        if (n <= cols) return n;
        for (var rows = 2; rows <= n; rows++) {
            var span = Math.ceil(n / rows);
            if (span <= cols) return span;
        }
        return cols;
    }

    function removeSkriptorium() {
        var grid = _grid();
        if (!grid) return;

        /* Move cards out of any wrapper, then restore original render order. */
        var frames = grid.querySelectorAll('.series-frame');
        for (var i = 0; i < frames.length; i++) {
            var f     = frames[i];
            var cards = f.querySelectorAll('.grid-card');
            for (var j = 0; j < cards.length; j++) grid.appendChild(cards[j]);
            f.parentNode.removeChild(f);
        }

        var all = Array.from(grid.querySelectorAll('.grid-card'));
        all.sort(function (a, b) {
            return (parseInt(a.dataset.renderSeq, 10) || 0) - (parseInt(b.dataset.renderSeq, 10) || 0);
        });
        var sentinel = document.getElementById('shelfSentinel');
        if (sentinel && sentinel.parentNode) sentinel.parentNode.removeChild(sentinel);
        for (var k = 0; k < all.length; k++) grid.appendChild(all[k]);
        if (sentinel) grid.appendChild(sentinel);

        grid.classList.remove('series-grouping-active');
    }
    window.removeSkriptorium = removeSkriptorium;

    function applySkriptorium() {
        var grid = _grid();
        if (!grid) return;

        removeSkriptorium();

        /* Collect groups in DOM order. */
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

        /* Drop singletons. */
        var validGroups = [];
        for (var g = 0; g < order.length; g++) {
            if (groups[order[g]].length >= 2) validGroups.push(order[g]);
        }

        grid.classList.add('series-grouping-active');
        if (validGroups.length === 0) return;

        var cols = _computeCols();
        _prevCols = cols;

        /* Sort each group by series_index (numeric, ascending). Index-less last,
         * alphabetically by title. */
        for (var sg = 0; sg < validGroups.length; sg++) {
            groups[validGroups[sg]].sort(function (a, b) {
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
        }

        /* Build a wrapper for each valid group; insert at the position of its
         * first-encountered member in the current DOM order. */
        var wrappedSeries = Object.create(null);

        for (var oi = 0; oi < allCards.length; oi++) {
            var ca = allCards[oi];
            if (ca.parentNode !== grid) continue; /* already moved by earlier group */
            var gnm = (ca.dataset.series || '').trim();
            if (!gnm || !groups[gnm] || groups[gnm].length < 2) continue;
            if (wrappedSeries[gnm]) continue;
            wrappedSeries[gnm] = true;

            var members = groups[gnm];
            var span    = _calcSeriesSpan(members.length, cols);
            var rowSpan = Math.ceil(members.length / span);

            var frame = document.createElement('div');
            frame.className        = 'series-frame';
            frame.dataset.series   = gnm;
            frame.style.gridColumn = 'span ' + span;
            if (rowSpan > 1) frame.style.gridRow = 'span ' + rowSpan;

            var inner = document.createElement('div');
            inner.className = 'series-inner';

            var tag = document.createElement('div');
            tag.className = 'series-tag';
            tag.innerHTML =
                '<span class="series-flourish">' + FLOURISH_SVG + '</span>' +
                '<span class="series-name">' + _esc(gnm) + '</span>' +
                '<span class="series-flourish" style="transform: scaleX(-1)">' + FLOURISH_SVG + '</span>';

            frame.appendChild(tag);
            frame.appendChild(inner);

            /* Anchor the wrapper at the first member's current position, then
             * move all members (in series-index order) into the inner grid. */
            grid.insertBefore(frame, ca);
            for (var m = 0; m < members.length; m++) inner.appendChild(members[m]);
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
