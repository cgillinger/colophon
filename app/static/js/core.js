/* ------------------------------------------------------------------ *
 * core.js — Theme, view modes, density, skriptorium, language
 *
 * Owns the persisted view-state vars and the functions that mutate
 * them. State lives on `window` (not closed over) so that the inline
 * code remaining in bulk_metadata.html can both read AND write the
 * same values — the inline JS still has assignments like
 *   _viewMode = 'shelf'
 * inside other modules (e.g. the series detail flow). Those bare
 * assignments resolve to `window._viewMode` and stay in sync with
 * core.js's reads.
 *
 * Self-running on load:
 *   - One-time migration of legacy localStorage keys
 *   - Hydrate window._viewMode / _density / _skriptorium / _seriesSort
 *     / _hideOnlyOneSeries / _filterOpen from localStorage
 *   - Sync the theme icon to whatever the head <script> picked
 *
 * Exposes globals consumed by the template / other modules:
 *   toggleTheme, setViewMode, setDensity, _syncDensityRadios,
 *   setSkriptorium, isSkriptoriumOn, applyViewMode, setLanguage
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    /* ---- View state (window-mirrored; see header comment) ---------- */
    window._viewMode          = 'table';
    window._density           = 'compact';
    window._skriptorium       = false;
    window._seriesSort        = 'alpha';
    window._hideOnlyOneSeries = false;
    window._filterOpen        = false;

    /* ---- One-time migration of legacy localStorage keys ----------- */
    (function _migrateViewState() {
        var legacy     = localStorage.getItem('colophon-viewMode');
        var newMode    = localStorage.getItem('colophon-view-mode');
        var newModeNew = localStorage.getItem('colophon-viewMode-v2');

        if (!newModeNew) {
            if (legacy === 'compact' || legacy === 'gallery') {
                localStorage.setItem('colophon-viewMode-v2', 'table');
                if (legacy === 'gallery') localStorage.setItem('colophon-density', 'airy');
            } else if (legacy === 'grid') {
                localStorage.setItem('colophon-viewMode-v2', 'shelf');
            } else if (newMode === 'shelf' || newMode === 'table') {
                localStorage.setItem('colophon-viewMode-v2', newMode);
            }

            var oldDensity = localStorage.getItem('colophon-table-density');
            if (oldDensity === 'gallery') {
                localStorage.setItem('colophon-density', 'airy');
            } else if (oldDensity === 'compact' && !localStorage.getItem('colophon-density')) {
                localStorage.setItem('colophon-density', 'compact');
            }

            if (localStorage.getItem('colophon-orgMode') === 'series') {
                localStorage.setItem('colophon-viewMode-v2', 'series');
            }

            localStorage.removeItem('colophon-viewMode');
            localStorage.removeItem('colophon-view-mode');
            localStorage.removeItem('colophon-table-density');
            localStorage.removeItem('colophon-orgMode');
        }
    })();

    /* ---- Hydrate window.* from localStorage ----------------------- */
    (function _loadViewState() {
        var v = localStorage.getItem('colophon-viewMode-v2');
        if (v === 'table' || v === 'shelf' || v === 'series') window._viewMode = v;
        var d = localStorage.getItem('colophon-density');
        if (d === 'compact' || d === 'airy') window._density = d;
        window._skriptorium = (localStorage.getItem('colophon-skriptorium') === '1');
        var s = localStorage.getItem('colophon-seriesSort');
        if (s === 'alpha' || s === 'count') window._seriesSort = s;
        window._hideOnlyOneSeries = (localStorage.getItem('colophon-hideOnlyOneSeries') === '1');
        window._filterOpen        = (localStorage.getItem('colophon-filterOpen') === '1');
    })();

    /* ---- Theme toggle --------------------------------------------- */
    function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme');
        var next    = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('colophon-theme', next);
        var icon = document.getElementById('themeIcon');
        if (icon) icon.className = next === 'dark' ? 'ti ti-moon' : 'ti ti-sun';
    }
    window.toggleTheme = toggleTheme;

    /* Initial icon sync (head <script> already set data-theme) */
    (function _initThemeIcon() {
        var t = document.documentElement.getAttribute('data-theme');
        var icon = document.getElementById('themeIcon');
        if (icon) icon.className = t === 'dark' ? 'ti ti-moon' : 'ti ti-sun';
    })();

    /* ---- View mode ------------------------------------------------- */
    function setViewMode(mode) {
        if (mode !== 'table' && mode !== 'shelf' && mode !== 'series') return;
        if (mode === window._viewMode) return;
        var prev = window._viewMode;
        window._viewMode = mode;
        localStorage.setItem('colophon-viewMode-v2', mode);
        applyViewMode();
        if (prev === 'shelf' && typeof destroyShelfView === 'function') destroyShelfView();
        if (mode === 'shelf' && typeof initShelfView   === 'function') initShelfView();
        if (window._writeUrlState) window._writeUrlState(true);
    }
    window.setViewMode = setViewMode;

    /* ---- Density --------------------------------------------------- */
    function setDensity(val) {
        if (val !== 'compact' && val !== 'airy') return;
        window._density = val;
        localStorage.setItem('colophon-density', val);
        document.body.setAttribute('data-density', val);
        _syncDensityRadios();
        /* When entering airy, drop any inline widths from compact-mode
           saved column widths so the CSS-driven layout takes over.
           Re-apply saved widths when going back to compact. */
        var ths = document.querySelectorAll('#bookTable thead th');
        if (val === 'airy') {
            ths.forEach(function (th) { th.style.width = ''; });
        } else {
            var saved = JSON.parse(localStorage.getItem('colophon-col-widths') || 'null');
            if (saved) {
                ths.forEach(function (th, i) {
                    if (saved[i]) th.style.width = saved[i];
                });
            }
        }
    }
    window.setDensity = setDensity;

    function _syncDensityRadios() {
        document.querySelectorAll('input[name="density"]').forEach(function (r) {
            r.checked = (r.value === window._density);
        });
    }
    window._syncDensityRadios = _syncDensityRadios;

    /* ---- Skriptorium (series-grouping overlay in shelf view) ------ */
    function setSkriptorium(on) {
        window._skriptorium = !!on;
        localStorage.setItem('colophon-skriptorium', window._skriptorium ? '1' : '0');
        if (window._viewMode !== 'shelf') return;
        if (window._skriptorium && typeof applySkriptorium === 'function') applySkriptorium();
        else if (!window._skriptorium && typeof removeSkriptorium === 'function') removeSkriptorium();
    }
    window.setSkriptorium = setSkriptorium;

    function isSkriptoriumOn() { return window._skriptorium; }
    window.isSkriptoriumOn = isSkriptoriumOn;

    /* ---- Render the chosen view + its chrome ---------------------- */
    function applyViewMode() {
        document.querySelectorAll('#viewSegGroup .seg-btn, .sidebar-view-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.mode === window._viewMode);
        });
        document.body.classList.toggle('shelf-active',  window._viewMode === 'shelf');
        document.body.classList.toggle('series-active', window._viewMode === 'series');
        document.body.setAttribute('data-density', window._density);

        var tableWrap       = document.querySelector('.table-wrap');
        var gridView        = document.getElementById('gridView');
        var seriesView      = document.getElementById('seriesView');
        var paginationBar   = document.getElementById('paginationBar');
        var groupToggle     = document.getElementById('groupToggle');
        var densityRadios   = document.getElementById('densityRadios');
        var skriptoriumWrap = document.getElementById('skriptoriumToggleWrap');
        var seriesControls  = document.getElementById('seriesControls');

        if (tableWrap)       tableWrap.style.display       = 'none';
        if (gridView)        gridView.style.display        = 'none';
        if (seriesView)      seriesView.style.display      = 'none';
        if (seriesControls)  seriesControls.style.display  = 'none';
        if (skriptoriumWrap) skriptoriumWrap.style.display = 'none';

        function dim(el, on) {
            if (!el) return;
            el.classList.toggle('toolbar-dim', !!on);
        }

        if (groupToggle)   groupToggle.style.display   = '';
        if (densityRadios) densityRadios.style.display = '';

        if (window._viewMode === 'table') {
            if (tableWrap)     tableWrap.style.display     = '';
            if (paginationBar) paginationBar.style.display = '';
            dim(groupToggle,   false);
            dim(densityRadios, false);
        } else if (window._viewMode === 'shelf') {
            if (gridView)        gridView.style.display        = 'grid';
            if (paginationBar)   paginationBar.style.display   = '';
            if (skriptoriumWrap) skriptoriumWrap.style.display = '';
            dim(groupToggle,   true);
            dim(densityRadios, true);
        } else if (window._viewMode === 'series') {
            if (seriesView)     seriesView.style.display    = '';
            if (seriesControls) seriesControls.style.display = 'inline-flex';
            if (paginationBar)  paginationBar.style.display  = 'none';
            /* Hide rather than dim — density/grouping have no meaning in
               series view, and a dimmed-but-visible control invites clicks. */
            if (groupToggle)   groupToggle.style.display   = 'none';
            if (densityRadios) densityRadios.style.display = 'none';
            if (typeof renderSeriesView === 'function') renderSeriesView();
        }

        _syncDensityRadios();
        var sk = document.getElementById('skriptoriumToggle');
        if (sk) sk.checked = window._skriptorium;
    }
    window.applyViewMode = applyViewMode;

    /* ---- Language switcher (cookie + reload) ---------------------- */
    function setLanguage(lang) {
        document.cookie = 'colophon_lang=' + lang + ';path=/;max-age=31536000;SameSite=Lax';
        location.reload();
    }
    window.setLanguage = setLanguage;

    /* ---- Sidebar (mobile drawer) ---------------------------------- *
     * On <=900px viewports the sidebar slides in from the left over a
     * backdrop. toggleSidebar / closeSidebar own the body class that
     * drives the transform and the backdrop's visibility. */
    function toggleSidebar() {
        document.body.classList.toggle('sidebar-open');
    }
    window.toggleSidebar = toggleSidebar;
    function closeSidebar() {
        document.body.classList.remove('sidebar-open');
    }
    window.closeSidebar = closeSidebar;
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
            closeSidebar();
        }
    });

    /* ---- Plural helper -------------------------------------------- *
     * Picks a singular or plural i18n key based on `count`, substitutes
     * {count} with the number, and any extra placeholders from `extras`.
     * Used to avoid string-concat plurals like "1 boker" — Swedish has
     * irregular plurals (bok→böcker) and participle agreement
     * (vald/valda) that hand-built concat cannot express.
     */
    function _pluralize(count, singularKey, pluralKey, extras) {
        var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
        var tpl = (count === 1 ? _i18n[singularKey] : _i18n[pluralKey]) || '';
        var out = tpl.split('{count}').join(count);
        if (extras) {
            Object.keys(extras).forEach(function (k) {
                out = out.split('{' + k + '}').join(extras[k]);
            });
        }
        return out;
    }
    window._pluralize = _pluralize;
})(window, document);
