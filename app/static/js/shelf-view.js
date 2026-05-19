/* ------------------------------------------------------------------ *
 * shelf-view.js — Hyllvy paradigm for the bulk metadata page
 *
 * Owns: grid card rendering, infinite scroll, Skriptorium series grouping.
 * Reads from the shared layer in bulk_metadata.html via globals:
 *   getFilteredRows()  → table rows in current filter+sort order
 *   isSkriptoriumOn()  → boolean toggle state
 * Exposes globals consumed by the template:
 *   initShelfView, destroyShelfView, refreshShelfView,
 *   applySkriptorium, removeSkriptorium, updateGridSelectionState
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var INITIAL_BATCH = 60;
    var SCROLL_BATCH  = 40;
    var GAP_X         = 20;   /* must match #gridView { gap: 20px } */
    var COVER_DEFAULT = 160;

    var FLOURISH_SVG =
        '<svg viewBox="0 0 22 10" width="22" height="10" xmlns="http://www.w3.org/2000/svg">' +
            '<path d="M21 5c-3 0-4-3.6-7-3.6S10 5 7 5 4 1.4 1 1.4" fill="none" stroke="rgba(76,175,80,0.55)" stroke-width="0.7" stroke-linecap="round"/>' +
            '<path d="M21 5c-3 0-4 3.6-7 3.6S10 5 7 5 4 8.6 1 8.6" fill="none" stroke="rgba(76,175,80,0.55)" stroke-width="0.7" stroke-linecap="round"/>' +
        '</svg>';

    var _renderedCount = 0;
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
        var w = grid.clientWidth;
        var cw = _coverWidth();
        return Math.max(1, Math.floor((w + GAP_X) / (cw + GAP_X)));
    }

    function _rows() {
        if (typeof window.getFilteredRows !== 'function') return [];
        return window.getFilteredRows();
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

        var imgStyle = coverSrc ? '' : 'display:none;';
        var phStyle  = coverSrc ? 'display:none;' : 'display:flex;';

        return '<div class="grid-card"'
            +    ' data-item-id="' + _esc(itemId) + '"'
            +    ' data-series="' + _esc(series) + '"'
            +    ' data-series-index="' + _esc(seriesIdx) + '">'
            +    '<div class="grid-card-cover" onclick="openBookModal(' + _esc(itemId) + ')">'
            +      '<img src="' + _esc(coverSrc) + '" alt="" loading="lazy" style="' + imgStyle + '"'
            +        ' onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'flex\';">'
            +      '<div class="grid-card-placeholder" style="' + phStyle + '">'
            +        '<i class="ti ti-book"></i>'
            +        '<span class="grid-card-placeholder-title">' + _esc(title) + '</span>'
            +        '<span class="grid-card-placeholder-author">' + _esc(author) + '</span>'
            +      '</div>'
            +      '<input type="checkbox" class="grid-card-checkbox" value="' + _esc(value) + '"' + checked + '>'
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

    function _renderBatch(count) {
        var grid = _grid();
        if (!grid) return;
        var rows = _rows();
        var end  = Math.min(_renderedCount + count, rows.length);
        if (end <= _renderedCount) {
            _ensureSentinel();
            return;
        }

        var html = '';
        for (var i = _renderedCount; i < end; i++) html += _cardHtml(rows[i]);

        var sentinel = document.getElementById('shelfSentinel');
        if (sentinel) {
            sentinel.insertAdjacentHTML('beforebegin', html);
        } else {
            grid.insertAdjacentHTML('beforeend', html);
        }
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

    function _stripBadges(card) {
        var badges = card.querySelectorAll('.series-index-badge');
        for (var i = 0; i < badges.length; i++) badges[i].parentNode.removeChild(badges[i]);
    }

    function _addBadge(card) {
        var idx = card.dataset.seriesIndex || '';
        if (!idx) return;
        var cover = card.querySelector('.grid-card-cover');
        if (!cover) return;
        _stripBadges(card);
        var b = document.createElement('span');
        b.className = 'series-index-badge';
        b.textContent = '#' + idx;
        cover.appendChild(b);
    }

    function removeSkriptorium() {
        var grid = _grid();
        if (!grid) return;
        var frames = grid.querySelectorAll('.series-frame');
        for (var i = 0; i < frames.length; i++) {
            var frame    = frames[i];
            var cards    = frame.querySelectorAll('.grid-card');
            for (var j = 0; j < cards.length; j++) {
                _stripBadges(cards[j]);
                grid.insertBefore(cards[j], frame);
            }
            frame.parentNode.removeChild(frame);
        }
        /* Strip any leftover badges on standalone cards too. */
        var standalone = grid.querySelectorAll('.grid-card');
        for (var k = 0; k < standalone.length; k++) _stripBadges(standalone[k]);
        grid.classList.remove('series-grouping-active');
    }
    window.removeSkriptorium = removeSkriptorium;

    function applySkriptorium() {
        var grid = _grid();
        if (!grid) return;

        removeSkriptorium();

        var cols  = _computeCols();
        _prevCols = cols;

        /* Collect groups in DOM order. */
        var allCards = grid.querySelectorAll('.grid-card');
        var groups   = {};       /* series → { firstAnchor, cards: [] } */
        var order    = [];       /* series names in first-seen order */
        for (var i = 0; i < allCards.length; i++) {
            var card   = allCards[i];
            var series = (card.dataset.series || '').trim();
            if (!series) continue;
            if (!groups[series]) {
                groups[series] = { anchor: card, cards: [] };
                order.push(series);
            }
            groups[series].cards.push(card);
        }

        /* Build wrappers for groups with ≥ 2 cards. */
        for (var s = 0; s < order.length; s++) {
            var name = order[s];
            var g    = groups[name];
            if (g.cards.length < 2) continue;

            /* Sort by parsed series_index; index-less items last (alpha by title). */
            g.cards.sort(function (a, b) {
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

            var span = Math.min(g.cards.length, cols);

            var frame = document.createElement('div');
            frame.className     = 'series-frame';
            frame.style.gridColumn = 'span ' + span;
            frame.dataset.series = name;

            var tag = document.createElement('div');
            tag.className = 'series-tag';
            tag.innerHTML =
                '<span class="series-flourish">' + FLOURISH_SVG + '</span>' +
                '<span class="series-name">' + _esc(name) + '</span>' +
                '<span class="series-flourish" style="transform: scaleX(-1)">' + FLOURISH_SVG + '</span>';

            var inner = document.createElement('div');
            inner.className = 'series-inner';

            for (var c = 0; c < g.cards.length; c++) {
                _addBadge(g.cards[c]);
                inner.appendChild(g.cards[c]);   /* moves the node */
            }

            frame.appendChild(tag);
            frame.appendChild(inner);

            /* Insert wrapper where the anchor used to be. */
            if (g.anchor.parentNode === grid) {
                grid.insertBefore(frame, g.anchor);
            } else {
                /* Anchor was already moved by an earlier group; append at end. */
                grid.appendChild(frame);
            }
        }

        grid.classList.add('series-grouping-active');

        /* Sentinel must stay at the end so the IntersectionObserver still fires. */
        var sentinel = document.getElementById('shelfSentinel');
        if (sentinel) grid.appendChild(sentinel);
    }
    window.applySkriptorium = applySkriptorium;

    /* -------------------- Lifecycle -------------------- */

    function initShelfView() {
        var grid = _grid();
        if (!grid) return;
        document.body.classList.add('shelf-active');
        _renderedCount = 0;
        grid.innerHTML = '';
        _renderBatch(INITIAL_BATCH);
        _setupResizeObserver();
        if (window.isSkriptoriumOn && window.isSkriptoriumOn()) applySkriptorium();
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
    }
    window.destroyShelfView = destroyShelfView;

    function refreshShelfView() {
        var grid = _grid();
        if (!grid) return;
        removeSkriptorium();
        if (_io) _io.disconnect();
        _renderedCount = 0;
        grid.innerHTML = '';
        _renderBatch(INITIAL_BATCH);
        if (window.isSkriptoriumOn && window.isSkriptoriumOn()) applySkriptorium();
    }
    window.refreshShelfView = refreshShelfView;
})(window, document);
