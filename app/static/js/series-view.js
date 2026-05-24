/* ------------------------------------------------------------------ *
 * series-view.js — The Series paradigm + the series detail modal
 *
 * Owns:
 *   - renderSeriesView() — builds the series-card grid from #bookTableBody
 *   - The series detail modal (openSeriesModal / closeSeriesModal /
 *     seriesModalToTable / _renderSeriesModal)
 *   - filterBySeries() / clearSeriesFilter() — sets a structured filter
 *     read by applyFilters in the inline JS
 *   - Two document-level click delegations:
 *       1. clicks on `.series-card` (open series modal or book modal)
 *       2. clicks on a book row inside the series modal (open book modal)
 *   - Backdrop click on the series modal closes it
 *
 * Reads from window.* mirrored state:
 *   _viewMode, _seriesSort, _hideOnlyOneSeries  (set by core.js)
 *   _activeSeriesFilter is OWNED HERE but mirrored on window so the
 *   inline applyFilters() can read it.
 *
 * Writes to window.* mirrored state:
 *   _viewMode is briefly flipped to 'shelf' around openBookModal() so
 *   the book modal opens in display mode — strict-mode IIFE requires
 *   explicit `window._viewMode = X` (bare assignment would throw).
 *
 * Reads i18n strings from window.__colophonConfig.i18n:
 *   seriesBooks, seriesRead, seriesAuthors, seriesReading,
 *   standaloneBooks, statusUnread, statusReading, statusFinished
 *
 * Exposes globals consumed by the template (onclick / inline calls):
 *   setSeriesSort, toggleHideOnlyOneSeries, renderSeriesView,
 *   openSeriesModal, closeSeriesModal, seriesModalToTable,
 *   filterBySeries, clearSeriesFilter, _renderSeriesFilterChip
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    /* Mirrored state — applyFilters() in inline JS reads this. */
    window._activeSeriesFilter = null;

    /* Local state for the modal (no external readers). */
    var _seriesModalName = null;

    function _seriesEsc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
    /* _esc inside the modal renderer uses _seriesEsc — same job. */
    var _esc = _seriesEsc;

    /* ============================================================ *
     * Series view (the #seriesView card grid)
     * ============================================================ */

    function setSeriesSort(val) {
        if (val !== 'alpha' && val !== 'count') return;
        window._seriesSort = val;
        localStorage.setItem('colophon-seriesSort', val);
        renderSeriesView();
    }
    window.setSeriesSort = setSeriesSort;

    function toggleHideOnlyOneSeries(cb) {
        window._hideOnlyOneSeries = !!cb.checked;
        localStorage.setItem('colophon-hideOnlyOneSeries', window._hideOnlyOneSeries ? '1' : '0');
        renderSeriesView();
    }
    window.toggleHideOnlyOneSeries = toggleHideOnlyOneSeries;

    function renderSeriesView() {
        var container = document.getElementById('seriesView');
        if (!container) return;

        // Series view should show ALL series regardless of an active series
        // filter (that filter only makes sense in the table). We use the
        // parallel filterHiddenSansSeries attribute set by applyFilters so we
        // still honour the other filters (search/status/ext).
        var rows = Array.from(document.querySelectorAll('#bookTableBody tr'))
            .filter(function (r) { return r.dataset.filterHiddenSansSeries !== '1'; });
        var seriesMap = {};
        var standalone = [];

        rows.forEach(function (row) {
            var seriesName = (row.dataset.series || '').trim();
            var titleEl = row.querySelector('.book-title');
            var title = titleEl ? titleEl.textContent.trim() : (row.dataset.title || '');
            var coverImg = row.querySelector('.cover img');
            var coverSrc = coverImg ? coverImg.getAttribute('src') : '';
            var itemId = row.dataset.itemId || '';
            var idx = row.dataset.seriesIndex || '';

            if (!seriesName) {
                standalone.push({ title: title, coverSrc: coverSrc, itemId: itemId });
                return;
            }

            if (!seriesMap[seriesName]) seriesMap[seriesName] = [];
            seriesMap[seriesName].push({
                index:      idx,
                indexNum:   parseFloat(idx) || 9999,
                title:      title,
                coverSrc:   coverSrc,
                itemId:     itemId,
                readStatus: row.dataset.readStatus || 'ReadyToRead'
            });
        });

        Object.keys(seriesMap).forEach(function (key) {
            seriesMap[key].sort(function (a, b) { return a.indexNum - b.indexNum; });
        });

        var seriesNames = Object.keys(seriesMap);
        if (window._hideOnlyOneSeries) {
            seriesNames = seriesNames.filter(function (n) { return seriesMap[n].length > 1; });
        }
        if (window._seriesSort === 'count') {
            seriesNames.sort(function (a, b) { return seriesMap[b].length - seriesMap[a].length; });
        } else {
            seriesNames.sort(function (a, b) {
                return a.toLowerCase().localeCompare(b.toLowerCase());
            });
        }

        var html = '';

        seriesNames.forEach(function (name) {
            var books = seriesMap[name];
            /* Use the first available cover in series order so missing #1
               covers don't fall back to the placeholder when later volumes
               do have covers. */
            var coverFor = null;
            for (var ci = 0; ci < books.length; ci++) {
                if (books[ci].coverSrc) { coverFor = books[ci]; break; }
            }
            var coverHtml = coverFor
                ? '<img src="' + _seriesEsc(coverFor.coverSrc) + '" alt="' + _seriesEsc(name) + '">'
                : '📚';

            var listHtml = '';
            books.forEach(function (b) {
                var num = b.index || '?';
                listHtml += '<li>'
                    + '<span class="series-num">#' + _seriesEsc(num) + '</span>'
                    + '<span class="series-book-title">' + _seriesEsc(b.title) + '</span>'
                    + '</li>';
            });

            var finishedInSeries = 0;
            for (var bi = 0; bi < books.length; bi++) {
                if (books[bi].readStatus === 'Finished') finishedInSeries++;
            }
            var readBadge = finishedInSeries > 0
                ? ' <span class="series-card-read">' + finishedInSeries + '/' + books.length + ' '
                  + _seriesEsc(_i18n.seriesRead) + '</span>'
                : '';

            var nameAttr = _seriesEsc(name);
            html += '<div class="series-card" data-series-name="' + nameAttr + '">'
                + '<div class="series-card-cover">' + coverHtml + '</div>'
                + '<div class="series-card-body">'
                + '<div class="series-card-title">' + nameAttr + '</div>'
                + '<div class="series-card-count">' + books.length + ' '
                + _seriesEsc(books.length === 1 ? _i18n.bookSingular : _i18n.bookPlural)
                + readBadge + '</div>'
                + '<ul class="series-card-list">' + listHtml + '</ul>'
                + '</div></div>';
        });

        if (standalone.length > 0 && !window._hideOnlyOneSeries) {
            html += '<div class="series-standalone-header">'
                + _seriesEsc(_i18n.standaloneBooks) + ' (' + standalone.length + ')</div>';
            standalone.forEach(function (b) {
                var coverHtml = b.coverSrc
                    ? '<img src="' + _seriesEsc(b.coverSrc) + '" alt="' + _seriesEsc(b.title) + '">'
                    : '📖';
                html += '<div class="series-card" data-item-id="' + _seriesEsc(b.itemId) + '">'
                    + '<div class="series-card-cover">' + coverHtml + '</div>'
                    + '<div class="series-card-body">'
                    + '<div class="series-card-title">' + _seriesEsc(b.title) + '</div>'
                    + '</div></div>';
            });
        }

        container.innerHTML = html;
    }
    window.renderSeriesView = renderSeriesView;

    /* Delegated click on a series card opens the series modal, OR opens
       the book modal directly for a standalone card. */
    document.addEventListener('click', function (ev) {
        var card = ev.target.closest && ev.target.closest('#seriesView .series-card');
        if (!card) return;
        var seriesName = card.getAttribute('data-series-name');
        if (seriesName) {
            openSeriesModal(seriesName);
            return;
        }
        var itemId = card.getAttribute('data-item-id');
        if (itemId && typeof openBookModal === 'function') {
            openBookModal(parseInt(itemId, 10));
        }
    });

    /* ============================================================ *
     * Series detail modal
     * ============================================================ */

    function openSeriesModal(seriesName) {
        _seriesModalName = seriesName;
        _renderSeriesModal(seriesName);
        document.getElementById('seriesModal').style.display = 'flex';
    }
    window.openSeriesModal = openSeriesModal;

    function closeSeriesModal() {
        document.getElementById('seriesModal').style.display = 'none';
        document.getElementById('seriesModal').classList.remove('with-book-modal');
        _seriesModalName = null;
    }
    window.closeSeriesModal = closeSeriesModal;

    /* From the series modal, jump to the table view filtered to this
       series (useful for bulk operations on the whole series). */
    function seriesModalToTable() {
        var name = _seriesModalName;
        closeSeriesModal();
        if (name) filterBySeries(name);
    }
    window.seriesModalToTable = seriesModalToTable;

    function _renderSeriesModal(seriesName) {
        // Collect every row whose series matches (exact). Deliberately reads
        // ALL rows here, not just filtered ones — the series modal is a
        // detail view; other filters shouldn't subset it.
        var rows = Array.from(document.querySelectorAll('#bookTableBody tr'))
            .filter(function (r) { return (r.dataset.series || '') === seriesName; });

        var books = rows.map(function (row) {
            var titleEl  = row.querySelector('.book-title');
            var title    = titleEl ? titleEl.textContent.trim() : '';
            var authorEl = row.querySelector('.author-cell');
            var author   = authorEl ? authorEl.textContent.trim() : '';
            var coverImg = row.querySelector('.cover img');
            var coverSrc = coverImg ? coverImg.getAttribute('src') : '';
            var idx      = row.dataset.seriesIndex || '';
            var status   = row.dataset.readStatus || 'ReadyToRead';
            var progress = parseFloat(row.dataset.readProgress);
            return {
                itemId:    row.dataset.itemId,
                title:     title,
                author:    author,
                coverSrc:  coverSrc,
                index:     idx,
                indexNum:  parseFloat(idx) || 9999,
                status:    status,
                progress:  isNaN(progress) ? null : progress
            };
        });
        books.sort(function (a, b) { return a.indexNum - b.indexNum; });

        // Hero text
        document.getElementById('seriesModalTitle').textContent = seriesName;
        var authorSet = {};
        books.forEach(function (b) { if (b.author) authorSet[b.author] = 1; });
        var authors = Object.keys(authorSet);
        var metaParts = [books.length + ' '
            + (books.length === 1 ? _i18n.bookSingular : _i18n.bookPlural)];
        if (authors.length === 1) {
            metaParts.unshift(authors[0]);
        } else if (authors.length > 1) {
            metaParts.unshift(authors.length + ' ' + _i18n.seriesAuthors);
        }
        document.getElementById('seriesModalMeta').textContent = metaParts.join(' · ');

        // Hero cover = first book's cover (same convention as the series card).
        var coverEl = document.getElementById('seriesModalCover');
        if (books.length > 0 && books[0].coverSrc) {
            coverEl.innerHTML = '<img src="' + _esc(books[0].coverSrc)
                + '" alt="" onerror="this.parentNode.innerHTML=\'📚\';">';
        } else {
            coverEl.innerHTML = '📚';
        }

        // Aggregate progress: count finished + sum progress for in-progress.
        var finished = 0;
        var reading = 0;
        books.forEach(function (b) {
            if (b.status === 'Finished') finished++;
            else if (b.status === 'Reading') reading++;
        });
        var pct = books.length > 0 ? (finished / books.length) * 100 : 0;
        document.getElementById('seriesModalProgressFill').style.width = pct + '%';
        var progressText = finished + '/' + books.length + ' ' + _i18n.seriesRead;
        if (reading > 0) progressText += ' · ' + reading + ' ' + _i18n.seriesReading;
        document.getElementById('seriesModalProgressText').textContent = progressText;

        // Book list
        var STATUS_LABEL = {
            'ReadyToRead': _i18n.statusUnread,
            'Reading':     _i18n.statusReading,
            'Finished':    _i18n.statusFinished
        };
        var listEl = document.getElementById('seriesModalList');
        listEl.innerHTML = '';
        books.forEach(function (b) {
            var li = document.createElement('li');
            li.className = 'series-modal-book';
            li.setAttribute('data-item-id', b.itemId);
            li.setAttribute('data-read-status', b.status || 'ReadyToRead');

            var altCover = b.title + (b.author ? ' — ' + b.author : '');
            var coverHtml = b.coverSrc
                ? '<img src="' + _esc(b.coverSrc) + '" alt="' + _esc(altCover) + '" onerror="this.parentNode.innerHTML=\'📖\';">'
                : '📖';

            var progressHtml = '';
            if (b.status === 'Reading' && b.progress !== null) {
                progressHtml = '<div class="series-modal-book-progress">'
                    + Math.round(b.progress) + '%</div>';
            }

            var idxHtml = b.index
                ? '<span class="series-modal-book-idx">#' + _esc(b.index) + '</span>'
                : '';

            li.innerHTML =
                '<div class="series-modal-book-cover">' + coverHtml + '</div>' +
                '<div class="series-modal-book-info">' +
                    '<div class="series-modal-book-title">' +
                        idxHtml + _esc(b.title) +
                    '</div>' +
                    (b.author
                        ? '<div class="series-modal-book-author">' + _esc(b.author) + '</div>'
                        : '') +
                '</div>' +
                '<div class="series-modal-book-status">' +
                    '<span class="badge s-' + b.status + '">' +
                        _esc(STATUS_LABEL[b.status] || b.status) +
                    '</span>' +
                    progressHtml +
                '</div>';

            listEl.appendChild(li);
        });
    }

    /* Click on a book row inside the series modal opens the book modal
       on top. Closing the book modal returns to the series spread. */
    document.addEventListener('click', function (ev) {
        var bookRow = ev.target.closest && ev.target.closest('#seriesModalList .series-modal-book');
        if (!bookRow) return;
        var id = bookRow.getAttribute('data-item-id');
        if (!id) return;
        // Drop the series modal's z-index below the book modal.
        document.getElementById('seriesModal').classList.add('with-book-modal');
        // Open the book modal in display mode regardless of current view —
        // we're already inside a "browsing" context.
        if (typeof openBookModal === 'function') {
            var prevViewMode = window._viewMode;
            // Trick: openBookModal picks display-mode when _viewMode === 'shelf'.
            // Temporarily flip to shelf so the book opens in display mode,
            // then restore. Strict mode: must go through window explicitly.
            window._viewMode = 'shelf';
            openBookModal(parseInt(id, 10));
            window._viewMode = prevViewMode;
        }
    });

    /* Backdrop click on the series modal closes it (matches book modal). */
    document.addEventListener('DOMContentLoaded', function () {
        var sm = document.getElementById('seriesModal');
        if (sm) {
            sm.addEventListener('click', function (e) {
                if (e.target === sm) closeSeriesModal();
            });
        }
    });

    /* ============================================================ *
     * Series filter chip (read by inline applyFilters)
     * ============================================================ */

    function filterBySeries(seriesName) {
        window._activeSeriesFilter = (seriesName || '').trim();
        // Don't pollute the general search input — the chip in the filter row
        // is the source of truth for this filter.
        var searchInput = document.getElementById('filterSearch');
        if (searchInput && searchInput.value) {
            searchInput.value = '';
        }
        _renderSeriesFilterChip();
        if (typeof setViewMode === 'function') setViewMode('table');
        if (typeof applyFilters === 'function') applyFilters();
    }
    window.filterBySeries = filterBySeries;

    function clearSeriesFilter() {
        window._activeSeriesFilter = null;
        _renderSeriesFilterChip();
        if (typeof applyFilters === 'function') applyFilters();
    }
    window.clearSeriesFilter = clearSeriesFilter;

    function _renderSeriesFilterChip() {
        var chip = document.getElementById('seriesFilterChip');
        var nameEl = document.getElementById('seriesFilterChipName');
        if (!chip || !nameEl) return;
        if (window._activeSeriesFilter) {
            nameEl.textContent = window._activeSeriesFilter;
            chip.style.display = 'inline-flex';
        } else {
            chip.style.display = 'none';
            nameEl.textContent = '';
        }
    }
    window._renderSeriesFilterChip = _renderSeriesFilterChip;
})(window, document);
