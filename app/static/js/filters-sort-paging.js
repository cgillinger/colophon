/* ------------------------------------------------------------------ *
 * filters-sort-paging.js — Toolbar chrome + table sort/filter/page/group
 *
 * Owns:
 *   - Filter panel toggle and the "any filter active" dot
 *   - The ⋯ actions menu (open/close + click-outside)
 *   - Initial UI-sync IIFE (density attr, series-sort select, filter
 *     panel open state)
 *   - Sorting (sortTable + th click handlers + initial title A→Z sort)
 *   - Filter dropdown population (extensions) + ?q= pre-fill
 *   - applyFilters (search/status/missing-field/ext + badge filter +
 *     active-series-filter via window._activeSeriesFilter)
 *   - Pagination (renderPagination, setPageSize, goToPage, page-size
 *     localStorage init)
 *   - Grouping (renderGroupedView, toggleGroup, toggleGroupView,
 *     _resetGrouping, updateGroupToggleButton)
 *   - Two layers of post-hoc patches that the original inline code
 *     applied as a layering pattern:
 *       1. getFilteredRows wrapped to also exclude `.group-hidden`
 *          rows (so paginated views don't show collapsed group
 *          children) — and sortTable click handlers re-bound to the
 *          regrouping wrapper.
 *       2. shelf-refresh wrappers around renderPagination, applyFilters,
 *          sortTable, renderGroupedView (so Hyllvy re-renders whenever
 *          the underlying state changes).
 *   - Bottom-of-script initial paint:
 *       updateGroupToggleButton → renderGroupedView → updateSelectedCount
 *       → updateBatchBar → applyViewMode → _updateFilterActiveDot
 *       → initShelfView (if shelf is the active paradigm).
 *     `initShelfView` is provided by shelf-view.js loaded at end of
 *     body; the guard `typeof initShelfView === 'function'` makes this
 *     no-op until the secondary shelf-bootstrap script at the end of
 *     body picks it up.
 *
 * Window-mirrored state (other modules read these):
 *   _grouped  — selection.js + batch.js  read window._grouped
 *
 * IIFE-local state (no external readers):
 *   _currentSort, _missingFieldAttr, _activeBadgeFilter, _pageSize,
 *   _currentPage
 *
 * Reads from window (set elsewhere):
 *   _viewMode, _density, _seriesSort, _hideOnlyOneSeries, _filterOpen
 *     — all owned by core.js
 *   _activeSeriesFilter — owned by series-view.js
 *
 * Reads i18n strings from window.__colophonConfig.i18n:
 *   noBooksMatch, showingNBooks
 *   (Hard-coded Swedish " grupper" / "filer redo att synka till
 *   bibliotek" preserved verbatim — pre-existing un-i18n'd labels.)
 *
 * Exposes globals consumed by the template (onclick / oninput / onchange):
 *   toggleFilterPanel, _updateFilterActiveDot, toggleActionsMenu,
 *   closeActionsMenu, sortTable, toggleBadgeFilter, applyFilters,
 *   getFilteredRows, renderPagination, setPageSize, goToPage,
 *   updateGroupToggleButton, renderGroupedView, toggleGroup,
 *   toggleGroupView
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    /* ============================================================ *
     * Filter panel + actions menu
     * ============================================================ */

    function toggleFilterPanel() {
        window._filterOpen = !window._filterOpen;
        localStorage.setItem('colophon-filterOpen', window._filterOpen ? '1' : '0');
        var panel = document.getElementById('filterPanel');
        if (panel) panel.style.display = window._filterOpen ? 'flex' : 'none';
    }
    window.toggleFilterPanel = toggleFilterPanel;

    function _updateFilterActiveDot() {
        var btn = document.getElementById('filterToggle');
        if (!btn) return;
        var anyActive = false;
        ['filterExtension', 'filterMissingField'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el && el.value) anyActive = true;
        });
        btn.classList.toggle('has-active-filter', anyActive);
    }
    window._updateFilterActiveDot = _updateFilterActiveDot;

    function toggleActionsMenu(ev) {
        if (ev) ev.stopPropagation();
        var m = document.getElementById('actionsMenu');
        if (!m) return;
        m.classList.toggle('open');
    }
    window.toggleActionsMenu = toggleActionsMenu;

    function closeActionsMenu() {
        var m = document.getElementById('actionsMenu');
        if (m) m.classList.remove('open');
    }
    window.closeActionsMenu = closeActionsMenu;

    document.addEventListener('click', function (ev) {
        var menu = document.getElementById('actionsMenu');
        if (!menu || !menu.classList.contains('open')) return;
        if (ev.target.closest('.menu-wrap')) return;
        menu.classList.remove('open');
    });

    /* ============================================================ *
     * Initial UI sync (density, series sort, hide-singleton, filter panel)
     * ============================================================ */

    (function _initialUiSync() {
        document.body.setAttribute('data-density', window._density);
        var sortSel = document.getElementById('seriesSortSelect');
        if (sortSel) sortSel.value = window._seriesSort;
        var hideCb = document.getElementById('hideOnlyOneSeriesCb');
        if (hideCb) hideCb.checked = window._hideOnlyOneSeries;
        var panel = document.getElementById('filterPanel');
        if (panel) panel.style.display = window._filterOpen ? 'flex' : 'none';
    })();

    /* ============================================================ *
     * Sorting
     * ============================================================ */

    var _currentSort = { key: 'title', dir: 1 };

    function sortTable(key) {
        if (_currentSort.key === key) {
            _currentSort.dir *= -1;
        } else {
            _currentSort.key = key;
            _currentSort.dir = 1;
        }
        document.querySelectorAll('#bookTable th[data-sort]').forEach(function (th) {
            var icon = th.querySelector('.sort-icon');
            if (th.dataset.sort === key) {
                icon.textContent = _currentSort.dir === 1 ? '▲' : '▼';
            } else {
                icon.textContent = '';
            }
        });

        var tbody = document.getElementById('bookTableBody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort(function (a, b) {
            var aVal = a.dataset[key] || '';
            var bVal = b.dataset[key] || '';
            if (key === 'status') {
                var order = { 'missing': 0, 'has': 1 };
                var aOrd = order[aVal] !== undefined ? order[aVal] : 2;
                var bOrd = order[bVal] !== undefined ? order[bVal] : 2;
                return (aOrd - bOrd) * _currentSort.dir;
            }
            if (aVal < bVal) return -1 * _currentSort.dir;
            if (aVal > bVal) return 1 * _currentSort.dir;
            return 0;
        });
        rows.forEach(function (row) { tbody.appendChild(row); });
        renderPagination();
    }
    /* `window.sortTable` is published below, after the second-pass patch. */

    document.querySelectorAll('#bookTable th[data-sort]').forEach(function (th) {
        th.addEventListener('click', function () { sortTable(th.dataset.sort); });
    });

    /* Default sort: title A→Z */
    (function () {
        var tbody = document.getElementById('bookTableBody');
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort(function (a, b) {
            var aVal = a.dataset.title || '';
            var bVal = b.dataset.title || '';
            return aVal < bVal ? -1 : (aVal > bVal ? 1 : 0);
        });
        rows.forEach(function (row) { tbody.appendChild(row); });
    })();

    /* ============================================================ *
     * Populate extension filter from rows
     * ============================================================ */

    (function () {
        var exts = new Set();
        document.querySelectorAll('#bookTableBody tr').forEach(function (row) {
            var ext = row.dataset.ext;
            if (ext) exts.add(ext);
        });
        var sel = document.getElementById('filterExtension');
        if (!sel) return;
        Array.from(exts).sort().forEach(function (ext) {
            var opt = document.createElement('option');
            opt.value = ext;
            opt.textContent = ext.replace('.', '').toUpperCase();
            sel.appendChild(opt);
        });
    })();

    /* Pre-fill search from ?q= URL param (navigated from sub-page topbar) */
    (function () {
        var q = new URLSearchParams(window.location.search).get('q');
        if (q) {
            var el = document.getElementById('filterSearch');
            if (el) { el.value = q; applyFilters(); }
        }
    })();

    /* ============================================================ *
     * Filtering
     * ============================================================ */

    var _missingFieldAttr = {
        'series':         'hasSeries',
        'description':    'hasDescription',
        'author':         'hasAuthor',
        'cover':          'hasCover',
        'isbn':           'hasIsbn',
        'publisher':      'hasPublisher',
        'genres':         'hasGenres',
        'published_date': 'hasPublished'
    };

    var _activeBadgeFilter = null;

    function toggleBadgeFilter(type, value, event) {
        var badges = document.querySelectorAll('.stats-badge');
        var key = type + ':' + value;

        if (_activeBadgeFilter === key) {
            _activeBadgeFilter = null;
            badges.forEach(function (b) { b.classList.remove('badge-active'); });
        } else {
            _activeBadgeFilter = key;
            badges.forEach(function (b) { b.classList.remove('badge-active'); });
            if (event && event.target) {
                var badge = event.target.closest('.stats-badge');
                if (badge) badge.classList.add('badge-active');
            }
        }
        applyFilters();
    }
    window.toggleBadgeFilter = toggleBadgeFilter;

    function applyFilters() {
        var search = document.getElementById('filterSearch').value.toLowerCase().trim();
        var missingField = document.getElementById('filterMissingField').value;
        var ext = document.getElementById('filterExtension').value;

        document.querySelectorAll('#bookTableBody tr').forEach(function (row) {
            var show = true;

            if (show && search) {
                var title = row.dataset.title || '';
                var author = row.dataset.author || '';
                var isbn = row.dataset.isbn || '';
                var genres = row.dataset.genres || '';
                if (title.indexOf(search) === -1
                    && author.indexOf(search) === -1
                    && isbn.indexOf(search) === -1
                    && genres.indexOf(search) === -1) show = false;
            }
            if (show && ext) {
                if ((row.dataset.ext || '') !== ext) show = false;
            }
            if (show && missingField) {
                var attrKey = _missingFieldAttr[missingField];
                if (attrKey && row.dataset[attrKey] !== '0') show = false;
            }

            // Mark "would this row be visible if there were no series filter".
            // Used by renderSeriesView so the chip filter doesn't hide series cards.
            row.dataset.filterHiddenSansSeries = show ? '' : '1';

            if (show && window._activeSeriesFilter) {
                if ((row.dataset.series || '') !== window._activeSeriesFilter) show = false;
            }

            if (show && _activeBadgeFilter) {
                var parts = _activeBadgeFilter.split(':');
                var filterType = parts[0];
                var filterValue = parts[1];
                if (filterType === 'format') {
                    var rowExt = (row.dataset.ext || '').replace(/^\./, '');
                    if (rowExt.toLowerCase() !== filterValue.toLowerCase()) show = false;
                } else if (filterType === 'missing_cover') {
                    if ((row.dataset.hasCover || '') !== '0') show = false;
                } else if (filterType === 'unsynced') {
                    if ((row.dataset.unsynced || '') !== '1') show = false;
                }
            }

            row.dataset.filterHidden = show ? '' : '1';
        });

        var syncBar = document.getElementById('syncBar');
        var syncBarText = document.getElementById('syncBarText');
        if (syncBar) {
            if (_activeBadgeFilter === 'unsynced:1') {
                var unsyncedRows = document.querySelectorAll('#bookTableBody tr[data-unsynced="1"]');
                syncBarText.textContent = unsyncedRows.length + ' filer redo att synka till bibliotek';
                syncBar.style.display = 'flex';
            } else {
                syncBar.style.display = 'none';
            }
        }

        renderPagination();
    }
    /* `window.applyFilters` published after second-pass patch. */

    /* ============================================================ *
     * Pagination
     * ============================================================ */

    var _pageSize = parseInt(localStorage.getItem('colophon-pageSize'));
    if (isNaN(_pageSize)) _pageSize = 20;
    var _currentPage = 1;
    (function () {
        var sel = document.getElementById('pageSizeSelect');
        if (sel) sel.value = _pageSize === 0 ? 'all' : _pageSize.toString();
    })();

    function getFilteredRows() {
        return Array.from(document.querySelectorAll('#bookTableBody tr'))
            .filter(function (r) { return r.dataset.filterHidden !== '1'; });
    }
    /* `window.getFilteredRows` published after first-pass patch. */

    function renderPagination() {
        var rows = getFilteredRows();
        var total = rows.length;
        var totalPages = _pageSize === 0 ? 1 : Math.max(1, Math.ceil(total / _pageSize));
        if (_currentPage > totalPages) _currentPage = totalPages;
        if (_currentPage < 1) _currentPage = 1;

        var start = _pageSize === 0 ? 0 : (_currentPage - 1) * _pageSize;
        var end = _pageSize === 0 ? total : Math.min(start + _pageSize, total);

        Array.from(document.querySelectorAll('#bookTableBody tr')).forEach(function (r) {
            r.style.display = 'none';
        });
        rows.forEach(function (row, i) {
            row.style.display = (i >= start && i < end) ? '' : 'none';
        });

        var info = document.getElementById('paginationInfo');
        if (info) {
            if (total === 0) {
                info.textContent = _i18n.noBooksMatch;
            } else {
                info.textContent = _i18n.showingNBooks
                    .replace('{start}', (start + 1))
                    .replace('{end}', end)
                    .replace('{total}', total);
            }
        }

        var emptyState = document.getElementById('emptyState');
        if (emptyState) {
            emptyState.style.display = (total === 0 && window._viewMode !== 'series') ? '' : 'none';
        }

        document.querySelectorAll('.page-size-link').forEach(function (a) {
            var s = parseInt(a.dataset.size);
            a.classList.toggle('active', s === _pageSize);
        });

        var pb = document.getElementById('pageButtons');
        if (!pb) return;
        pb.innerHTML = '';
        if (_pageSize === 0 || totalPages <= 1) return;

        function btn(label, page, opts) {
            opts = opts || {};
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'page-btn' + (opts.active ? ' active' : '');
            b.textContent = label;
            if (opts.disabled) b.disabled = true;
            else b.onclick = function () { goToPage(page); };
            return b;
        }
        function ell() {
            var s = document.createElement('span');
            s.className = 'page-ellipsis';
            s.textContent = '…';
            return s;
        }

        pb.appendChild(btn('‹', _currentPage - 1, { disabled: _currentPage <= 1 }));

        var pagesToShow = new Set([1, totalPages, _currentPage, _currentPage - 1, _currentPage + 1]);
        var prev = 0;
        Array.from(pagesToShow).filter(function (p) { return p >= 1 && p <= totalPages; })
            .sort(function (a, b) { return a - b; })
            .forEach(function (p) {
                if (p - prev > 1) pb.appendChild(ell());
                pb.appendChild(btn(p, p, { active: p === _currentPage }));
                prev = p;
            });

        pb.appendChild(btn('›', _currentPage + 1, { disabled: _currentPage >= totalPages }));
    }
    /* `window.renderPagination` published after second-pass patch. */

    function setPageSize(size) {
        _pageSize = size;
        _currentPage = 1;
        localStorage.setItem('colophon-pageSize', size);
        var sel = document.getElementById('pageSizeSelect');
        if (sel) sel.value = size === 0 ? 'all' : size.toString();
        renderPagination();
    }
    window.setPageSize = setPageSize;

    function goToPage(page) {
        _currentPage = page;
        renderPagination();
    }
    window.goToPage = goToPage;

    /* Initial: mark all rows as visible, then we'll render. */
    document.querySelectorAll('#bookTableBody tr').forEach(function (r) {
        r.dataset.filterHidden = '';
    });

    /* ============================================================ *
     * Grouping
     * ============================================================ */

    window._grouped = localStorage.getItem('colophon-grouped') === '1';

    function _gEsc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function updateGroupToggleButton() {
        var btn = document.getElementById('groupToggle');
        if (!btn) return;
        btn.classList.toggle('active', window._grouped);
        var label = document.getElementById('groupCountLabel');
        if (label) {
            if (window._grouped) {
                var groupCount = Object.keys(
                    Array.from(document.querySelectorAll('tr.group-parent[data-group-key]'))
                        .reduce(function (acc, r) { acc[r.dataset.groupKey] = 1; return acc; }, {})
                ).length;
                label.textContent = groupCount + ' grupper';
                label.style.display = '';
            } else {
                label.style.display = 'none';
            }
        }
    }
    window.updateGroupToggleButton = updateGroupToggleButton;

    function _resetGrouping() {
        var tbody = document.getElementById('bookTableBody');
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll('tr[data-group-key]'));
        rows.forEach(function (row) {
            row.classList.remove('group-child', 'group-hidden', 'group-parent');
            delete row.dataset.groupExpanded;
            var extCell = row.querySelector('td:last-child');
            if (extCell && extCell.dataset.originalContent !== undefined) {
                extCell.innerHTML = extCell.dataset.originalContent;
                delete extCell.dataset.originalContent;
            }
        });
    }

    function renderGroupedView() {
        _resetGrouping();
        if (!window._grouped) {
            renderPagination();
            return;
        }

        var tbody = document.getElementById('bookTableBody');
        if (!tbody) return;
        var rows = Array.from(tbody.querySelectorAll('tr[data-group-key]'));

        var groups = {};
        var groupOrder = [];
        rows.forEach(function (row) {
            var key = row.dataset.groupKey;
            if (!key) return;
            if (!groups[key]) {
                groups[key] = [];
                groupOrder.push(key);
            }
            groups[key].push(row);
        });

        groupOrder.forEach(function (key) {
            var group = groups[key];
            if (group.length <= 1) return;

            var primary = group[0];
            var formats = group.map(function (r) {
                return (r.dataset.ext || '').toUpperCase().replace('.', '');
            });

            var extCell = primary.querySelector('td:last-child');
            if (extCell) {
                extCell.dataset.originalContent = extCell.innerHTML;
                extCell.innerHTML = formats.map(function (f) {
                    return '<span class="format-badge">' + _gEsc(f) + '</span>';
                }).join(' ');

                var expandBtn = document.createElement('span');
                expandBtn.className = 'group-expand-btn';
                expandBtn.innerHTML = ' <i class="ti ti-chevron-down" style="font-size:12px;"></i>';
                expandBtn.onclick = function (e) {
                    e.stopPropagation();
                    toggleGroup(key);
                };
                extCell.appendChild(expandBtn);
            }

            primary.classList.add('group-parent');
            primary.dataset.groupExpanded = '0';

            for (var i = 1; i < group.length; i++) {
                group[i].classList.add('group-child', 'group-hidden');
            }
        });

        renderPagination();
    }
    /* `window.renderGroupedView` published after second-pass patch. */

    function toggleGroup(groupKey) {
        var tbody = document.getElementById('bookTableBody');
        if (!tbody) return;
        var children = tbody.querySelectorAll('tr.group-child[data-group-key="' + groupKey + '"]');
        var parent = tbody.querySelector('tr.group-parent[data-group-key="' + groupKey + '"]');

        var expanded = parent && parent.dataset.groupExpanded === '1';

        children.forEach(function (row) {
            row.classList.toggle('group-hidden', expanded);
        });

        if (parent) {
            parent.dataset.groupExpanded = expanded ? '0' : '1';
            var icon = parent.querySelector('.group-expand-btn i');
            if (icon) {
                icon.className = expanded ? 'ti ti-chevron-down' : 'ti ti-chevron-up';
            }
        }
        renderPagination();
    }
    window.toggleGroup = toggleGroup;

    function toggleGroupView() {
        window._grouped = !window._grouped;
        localStorage.setItem('colophon-grouped', window._grouped ? '1' : '0');
        renderGroupedView();
        updateGroupToggleButton();
        if (typeof updateSelectedCount === 'function') updateSelectedCount();
    }
    window.toggleGroupView = toggleGroupView;

    /* ============================================================ *
     * First-pass patches: getFilteredRows excludes .group-hidden,
     * sortTable re-runs grouping. (Originally written as a separate
     * "patch" section in the inline JS — kept structurally identical.)
     * ============================================================ */

    var _origGetFilteredRows = getFilteredRows;
    getFilteredRows = function () {
        return Array.from(document.querySelectorAll('#bookTableBody tr'))
            .filter(function (r) {
                return r.dataset.filterHidden !== '1' && !r.classList.contains('group-hidden');
            });
    };

    var _origSortTable = sortTable;
    sortTable = function (key) {
        _origSortTable(key);
        if (window._grouped) renderGroupedView();
    };
    /* Re-bind click handlers (so the latest sortTable is called) */
    document.querySelectorAll('#bookTable th[data-sort]').forEach(function (th) {
        var fresh = th.cloneNode(true);
        th.parentNode.replaceChild(fresh, th);
        fresh.addEventListener('click', function () { sortTable(fresh.dataset.sort); });
    });

    /* ============================================================ *
     * Second-pass patches: Hyllvy/series refresh on state changes.
     * (Originally written as a separate block in the bottom-of-script
     * init — kept structurally identical.)
     * ============================================================ */

    var _origRenderPagination = renderPagination;
    renderPagination = function () {
        _origRenderPagination.apply(this, arguments);
        if (window._viewMode === 'shelf' && typeof refreshShelfView === 'function') refreshShelfView();
    };
    var _origApplyFilters = applyFilters;
    applyFilters = function () {
        _origApplyFilters.apply(this, arguments);
        _updateFilterActiveDot();
        if (window._viewMode === 'shelf' && typeof refreshShelfView === 'function') refreshShelfView();
        if (window._viewMode === 'series' && typeof renderSeriesView === 'function') renderSeriesView();
    };
    var _origSortTable2 = sortTable;
    sortTable = function (key) {
        _origSortTable2.apply(this, arguments);
        if (window._viewMode === 'shelf' && typeof refreshShelfView === 'function') refreshShelfView();
    };
    /* Re-bind sort handlers AGAIN to point at the latest sortTable */
    document.querySelectorAll('#bookTable th[data-sort]').forEach(function (th) {
        var fresh = th.cloneNode(true);
        th.parentNode.replaceChild(fresh, th);
        fresh.addEventListener('click', function () { sortTable(fresh.dataset.sort); });
    });
    var _origRenderGroupedView = renderGroupedView;
    renderGroupedView = function () {
        _origRenderGroupedView.apply(this, arguments);
        if (window._viewMode === 'shelf' && typeof refreshShelfView === 'function') refreshShelfView();
    };

    /* Publish FINAL versions of the patched functions on window. */
    window.sortTable        = sortTable;
    window.applyFilters     = applyFilters;
    window.renderPagination = renderPagination;
    window.renderGroupedView = renderGroupedView;
    window.getFilteredRows  = getFilteredRows;

    /* ============================================================ *
     * Bottom-of-script initial paint
     * ============================================================ */

    updateGroupToggleButton();
    renderGroupedView();
    if (typeof updateSelectedCount === 'function') updateSelectedCount();
    if (typeof updateBatchBar       === 'function') updateBatchBar();
    if (typeof applyViewMode        === 'function') applyViewMode();
    _updateFilterActiveDot();
    if (window._viewMode === 'shelf' && typeof initShelfView === 'function') initShelfView();
})(window, document);
