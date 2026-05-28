// Colophon – e-book metadata manager
/* URL <-> view/filter state sync.
 *
 * The bulk view is a single page whose view mode, search, filters, sort and
 * pagination all live in JS — so the URL never changed and back/forward and
 * deep links didn't work. This module mirrors that state into the query
 * string and restores it on load / popstate.
 *
 * Loaded LAST so every window.* control function already exists. The control
 * functions themselves call window._writeUrlState() (guarded) after they run;
 * this file just provides the read/write/restore plumbing.
 *
 * Policy: pushState for discrete navigations (view switch, page change) so
 * back steps through them; replaceState for high-frequency changes (typing in
 * search, toggling filters/sort) so back doesn't walk every keystroke.
 *
 * The server-side `status` filter (sidebar links) is preserved verbatim — the
 * rows are rendered server-side for it, so dropping it would desync the URL.
 */
(function (window, document) {
    'use strict';

    var VIEWS = { table: 1, shelf: 1, series: 1 };
    var DEFAULT_SORT = 'title:asc';
    var _suppress = false;   // true while applying URL -> state (don't re-write)
    // The view at first paint (localStorage-hydrated). Used as the fallback
    // when a history entry has no view param, so "back" to the initial,
    // param-less URL restores the user's saved view rather than forcing table.
    var _initialView = (VIEWS[window._viewMode] ? window._viewMode : 'table');

    function _params() { return new URLSearchParams(window.location.search); }
    function _val(id) { var el = document.getElementById(id); return el ? el.value : ''; }

    function _sortString() {
        var cs = window._currentSort;
        if (!cs || !cs.key) return '';
        return cs.key + ':' + (cs.dir === -1 ? 'desc' : 'asc');
    }

    function _page() {
        return (typeof window._getCurrentPage === 'function') ? window._getCurrentPage() : 1;
    }

    function writeStateToUrl(push) {
        if (_suppress) return;

        var p = _params();
        var np = new URLSearchParams();

        // Preserve the server-rendered status filter; rebuild the rest.
        var status = p.get('status');
        if (status) np.set('status', status);

        // Always include the view so every entry is unambiguous (a missing
        // view param only ever means the very first, server-rendered entry).
        if (window._viewMode) np.set('view', window._viewMode);

        var q = _val('filterSearch').trim();
        if (q) np.set('q', q);

        var missing = _val('filterMissingField');
        if (missing) np.set('missing', missing);

        var ext = _val('filterExtension');
        if (ext) np.set('ext', ext);

        var sort = _sortString();
        if (sort && sort !== DEFAULT_SORT) np.set('sort', sort);

        var page = _page();
        if (page && page > 1) np.set('page', String(page));

        var qs = np.toString();
        var url = window.location.pathname + (qs ? '?' + qs : '');
        if (url === window.location.pathname + window.location.search) return;

        try {
            if (push) window.history.pushState({ colophon: true }, '', url);
            else window.history.replaceState({ colophon: true }, '', url);
        } catch (e) { /* non-http context */ }
    }
    window._writeUrlState = writeStateToUrl;

    function readStateFromUrl() {
        var p = _params();
        _suppress = true;
        try {
            // Every dimension is set explicitly (falling back to its default
            // when the param is absent) so back/forward fully restores a
            // state instead of leaving a stale view/sort/page behind.
            var view = p.get('view');
            if (!view || !VIEWS[view]) view = _initialView;
            if (window.setViewMode) window.setViewMode(view);

            var search = document.getElementById('filterSearch');
            if (search) search.value = p.get('q') || '';
            var missing = document.getElementById('filterMissingField');
            if (missing) missing.value = p.get('missing') || '';
            var ext = document.getElementById('filterExtension');
            if (ext) ext.value = p.get('ext') || '';

            // Filter first (hide/show rows), then sort, then paginate.
            if (window.applyFilters) window.applyFilters();

            var sort = p.get('sort') || DEFAULT_SORT;
            if (window.applySortFromDropdown) {
                var sortSel = document.getElementById('filterSort');
                if (sortSel) sortSel.value = sort;
                window.applySortFromDropdown(sort);
            }

            var page = parseInt(p.get('page'), 10);
            if (isNaN(page) || page < 1) page = 1;
            if (window.goToPage) window.goToPage(page);
        } finally {
            _suppress = false;
        }
    }
    window._readUrlState = readStateFromUrl;

    window.addEventListener('popstate', readStateFromUrl);

    // Apply any params present on first load, on top of the default paint.
    if (window.location.search) readStateFromUrl();
})(window, document);
