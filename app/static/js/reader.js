// Colophon – e-book metadata manager
//
// In-browser reader controller. Loads an EPUB into foliate-js, resumes by
// percent, and syncs progress back to the server through the same canonical
// reading-state fields the Kobo sync uses (POST /reader/<id>/progress →
// services/reading_state.py). Supports offline reading: a "save for offline"
// button caches the book + reader shell via the service worker, and progress
// is mirrored to localStorage so it resumes (and re-syncs) without a network.
//
// ES module: imports the vendored foliate-js <foliate-view> custom element.
import './../vendor/foliate-js/view.js';

(function () {
    'use strict';

    var cfg = window.__readerConfig || {};
    var i18n = cfg.i18n || {};

    var main = document.querySelector('.reader-main');
    var overlay = document.getElementById('readerOverlay');
    var percentEl = document.getElementById('readerPercent');
    var backBtn = document.getElementById('readerBack');
    var prevZone = document.getElementById('readerPrev');
    var nextZone = document.getElementById('readerNext');

    var offlineBtn = document.getElementById('readerOfflineBtn');
    var settingsBtn = document.getElementById('readerSettingsBtn');
    var sheet = document.getElementById('readerSheet');
    var backdrop = document.getElementById('readerSheetBackdrop');
    var sizeVal = document.getElementById('rsSizeVal');
    var sizeDown = document.getElementById('rsSizeDown');
    var sizeUp = document.getElementById('rsSizeUp');

    var view = null;
    var saveTimer = null;
    var latest = null;           // { percent, status } pending save
    var lastSaved = null;        // last successfully sent { percent, status }
    var FINISHED_FRACTION = 0.999;
    var SAVE_DEBOUNCE_MS = 1500;

    // --- Reading settings (typography/theme) --------------------------------
    // Persisted globally in localStorage (not per-book, matching Kobo/Kindle)
    // and applied to the foliate content via renderer.setStyles() + layout
    // attributes. No server round-trip — these are pure presentation prefs.
    var PREFS_KEY = 'colophon-reader-prefs';
    var DEFAULT_PREFS = {
        theme: 'light', fontSize: 100, fontFamily: 'publisher',
        lineSpacing: 'normal', margins: 'normal', flow: 'paginated'
    };
    var FONT_MIN = 70, FONT_MAX = 220, FONT_STEP = 10;
    var FONT_STACKS = {
        serif: "Georgia, 'Iowan Old Style', 'Times New Roman', serif",
        sans: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        dyslexic: "'OpenDyslexic', sans-serif"
    };
    var LINE_HEIGHTS = { tight: 1.3, normal: 1.6, loose: 2.0 };
    var MARGINS = {
        narrow: { gap: '4%', maxInline: '900px' },
        normal: { gap: '7%', maxInline: '720px' },
        wide:   { gap: '12%', maxInline: '580px' }
    };
    var THEMES = {
        light: { bg: '#ffffff', fg: '#1a1a1a', link: '#1a6dd0' },
        sepia: { bg: '#f4ecd8', fg: '#5b4636', link: '#9a6f3f' },
        dark:  { bg: '#1b1f24', fg: '#cfd6dc', link: '#6cb6ff' }
    };

    function loadPrefs() {
        try {
            var saved = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}');
            var p = Object.assign({}, DEFAULT_PREFS, saved);
            p.fontSize = Math.max(FONT_MIN, Math.min(FONT_MAX, Number(p.fontSize) || 100));
            return p;
        } catch (e) { return Object.assign({}, DEFAULT_PREFS); }
    }
    function savePrefs() {
        try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (e) { /* private mode */ }
    }
    var prefs = loadPrefs();

    // Absolute woff2 URLs — the book iframe's base is a blob:, so relative
    // paths won't resolve; qualify against the app origin.
    function _fontUrl(path) {
        if (!path) return '';
        return /^https?:/i.test(path) ? path : (window.location.origin + path);
    }
    function dyslexicFontFace() {
        var u = (cfg.fontUrls || {});
        var r400 = _fontUrl(u.dyslexic400), r700 = _fontUrl(u.dyslexic700);
        if (!r400) return '';
        return "@font-face { font-family: 'OpenDyslexic'; font-style: normal; font-weight: 400; font-display: swap; src: url('"
            + r400 + "') format('woff2'); }\n"
            + (r700 ? "@font-face { font-family: 'OpenDyslexic'; font-style: normal; font-weight: 700; font-display: swap; src: url('"
                + r700 + "') format('woff2'); }\n" : '');
    }

    function buildBookCSS() {
        var theme = THEMES[prefs.theme] || THEMES.light;
        var lh = LINE_HEIGHTS[prefs.lineSpacing] || LINE_HEIGHTS.normal;
        var rules = [
            // Scale rem/em/%-based text (the bulk of modern EPUBs).
            'html { font-size: ' + prefs.fontSize + '% !important; }',
            // Normalise to the chosen theme — forcing is what makes sepia/dark
            // legible over arbitrary publisher colours (matches Kindle/Kobo).
            'html { background: ' + theme.bg + ' !important; }',
            'body { background: ' + theme.bg + ' !important; color: ' + theme.fg + ' !important; }',
            'p, li, blockquote, dd, dt, h1, h2, h3, h4, h5, h6, span, div, td, th, figcaption { color: ' + theme.fg + ' !important; }',
            'a, a * { color: ' + theme.link + ' !important; }',
            'p, li, blockquote, dd { line-height: ' + lh + ' !important; }'
        ];
        // Publisher = leave the book's own fonts alone.
        if (prefs.fontFamily !== 'publisher' && FONT_STACKS[prefs.fontFamily]) {
            // OpenDyslexic must be declared inside the book document itself.
            if (prefs.fontFamily === 'dyslexic') rules.unshift(dyslexicFontFace());
            rules.push('html, body, p, li, blockquote, dd, dt, h1, h2, h3, h4, h5, h6, '
                + 'span, div, td, th, a, figcaption { font-family: '
                + FONT_STACKS[prefs.fontFamily] + ' !important; }');
        }
        return rules.join('\n');
    }

    function applyReaderStyles() {
        document.documentElement.setAttribute('data-reader-theme', prefs.theme);
        // Page-turn tap zones only make sense when paginated; in scroll mode
        // they'd block edge scrolling, so hide them.
        var paged = prefs.flow !== 'scrolled';
        if (prevZone) prevZone.style.display = paged ? '' : 'none';
        if (nextZone) nextZone.style.display = paged ? '' : 'none';
        if (!view || !view.renderer) return;
        // Fixed-layout (pre-paginated) books render with foliate's foliate-fxl
        // renderer, which has none of the reflowable styling controls
        // (setStyles/flow/gap/max-inline-size — those live on the paginator).
        // Calling setStyles() there throws and the catch in start() surfaces it
        // as "Could not open this book." Typography/theme prefs don't apply to
        // page-image spreads anyway, so skip them for fixed-layout.
        if (view.isFixedLayout || typeof view.renderer.setStyles !== 'function') return;
        view.renderer.setAttribute('flow', paged ? 'paginated' : 'scrolled');
        var m = MARGINS[prefs.margins] || MARGINS.normal;
        view.renderer.setAttribute('gap', m.gap);
        view.renderer.setAttribute('max-inline-size', m.maxInline);
        view.renderer.setStyles(buildBookCSS());
    }

    // Fixed-layout books are pre-paginated page images: text size, font,
    // line spacing, margins and reading mode have no effect (only Theme, which
    // tints the reader chrome, still applies). Hide the reflowable-only rows so
    // the settings sheet doesn't offer controls that silently do nothing.
    function adaptControlsForLayout() {
        if (!view || !view.isFixedLayout) return;
        document.querySelectorAll('#readerSheet [data-flow-only]')
            .forEach(function (el) { el.hidden = true; });
    }

    function syncPanelUI() {
        if (!sheet) return;
        sheet.querySelectorAll('.rs-seg').forEach(function (seg) {
            var pref = seg.getAttribute('data-pref');
            seg.querySelectorAll('button').forEach(function (b) {
                b.setAttribute('aria-pressed',
                    String(b.getAttribute('data-value') === String(prefs[pref])));
            });
        });
        if (sizeVal) sizeVal.textContent = prefs.fontSize + '%';
    }

    function openSheet() {
        if (backdrop) backdrop.hidden = false;
        if (sheet) sheet.hidden = false;
        if (settingsBtn) settingsBtn.setAttribute('aria-expanded', 'true');
        syncPanelUI();
    }
    function closeSheet() {
        if (backdrop) backdrop.hidden = true;
        if (sheet) sheet.hidden = true;
        if (settingsBtn) settingsBtn.setAttribute('aria-expanded', 'false');
    }
    function sheetOpen() { return sheet && !sheet.hidden; }

    function setFontSize(v) {
        prefs.fontSize = Math.max(FONT_MIN, Math.min(FONT_MAX, v));
        savePrefs(); applyReaderStyles(); syncPanelUI();
    }

    function bindSettings() {
        if (settingsBtn) settingsBtn.addEventListener('click', function () {
            sheetOpen() ? closeSheet() : openSheet();
        });
        if (backdrop) backdrop.addEventListener('click', closeSheet);
        if (sheet) sheet.addEventListener('click', function (e) {
            var segBtn = e.target.closest('.rs-seg button');
            if (segBtn) {
                var pref = segBtn.closest('.rs-seg').getAttribute('data-pref');
                prefs[pref] = segBtn.getAttribute('data-value');
                savePrefs(); applyReaderStyles(); syncPanelUI();
            }
        });
        if (sizeDown) sizeDown.addEventListener('click', function () { setFontSize(prefs.fontSize - FONT_STEP); });
        if (sizeUp) sizeUp.addEventListener('click', function () { setFontSize(prefs.fontSize + FONT_STEP); });
    }

    function goHome() {
        // Prefer Back so the library keeps its scroll/filter state; fall back
        // to the index when the reader was opened as the first history entry
        // (e.g. a direct link), so "Back" never leaves the site.
        if (window.history.length > 1) window.history.back();
        else window.location.href = cfg.homeUrl || '/';
    }

    function fractionToState(fraction) {
        var percent = Math.max(0, Math.min(100, fraction * 100));
        var status = fraction >= FINISHED_FRACTION ? 'Finished' : 'Reading';
        return { percent: percent, status: status };
    }

    function sameState(a, b) {
        return a && b && a.status === b.status && Math.round(a.percent) === Math.round(b.percent);
    }

    // --- Offline-safe progress -------------------------------------------
    // Progress is always mirrored to localStorage so the book resumes at the
    // right place even when opened offline (the server-rendered initial
    // progress is then stale). A copy that failed to reach the server is kept
    // marked unsynced and retried on reconnect.
    var PROGRESS_KEY = 'colophon-reader-progress-' + (cfg.itemId != null ? cfg.itemId : 'x');

    function persistLocal(state, synced) {
        try {
            localStorage.setItem(PROGRESS_KEY, JSON.stringify({
                percent: state.percent, status: state.status, synced: !!synced
            }));
        } catch (e) { /* private mode / quota */ }
    }
    function readLocalProgress() {
        try { return JSON.parse(localStorage.getItem(PROGRESS_KEY) || 'null'); }
        catch (e) { return null; }
    }

    function flush(useBeacon) {
        if (!latest || sameState(latest, lastSaved)) return;
        var payload = latest;
        persistLocal(payload, false);     // keep a local copy regardless of network
        var body = JSON.stringify(payload);
        if (useBeacon && navigator.sendBeacon) {
            var ok = navigator.sendBeacon(cfg.progressUrl, new Blob([body], { type: 'application/json' }));
            if (ok) { lastSaved = payload; persistLocal(payload, true); }
            return;
        }
        fetch(cfg.progressUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body,
            keepalive: true
        }).then(function (r) {
            if (r && r.ok) { lastSaved = payload; persistLocal(payload, true); }
        }).catch(function () { /* stays unsynced; retried on 'online' / next change */ });
    }

    // On reconnect, push up any progress made while offline.
    function flushUnsynced() {
        var local = readLocalProgress();
        if (local && local.synced === false) {
            latest = { percent: local.percent, status: local.status };
            flush(false);
        }
    }

    function scheduleSave(state, immediate) {
        latest = state;
        if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
        // Reaching the end is worth persisting right away; page-to-page reading
        // is debounced so we don't hammer the DB on every turn.
        if (immediate || state.status === 'Finished') { flush(false); return; }
        saveTimer = setTimeout(function () { flush(false); }, SAVE_DEBOUNCE_MS);
    }

    function onRelocate(e) {
        var detail = e.detail || {};
        var fraction = typeof detail.fraction === 'number' ? detail.fraction : 0;
        if (percentEl) percentEl.textContent = Math.round(fraction * 100) + '%';
        scheduleSave(fractionToState(fraction));
    }

    function bindControls() {
        if (backBtn) backBtn.addEventListener('click', goHome);
        if (prevZone) prevZone.addEventListener('click', function () { if (view) view.goLeft(); });
        if (nextZone) nextZone.addEventListener('click', function () { if (view) view.goRight(); });
        document.addEventListener('keydown', function (ev) {
            // Escape closes the settings sheet first; only leaves the reader
            // when nothing is open.
            if (ev.key === 'Escape') { if (sheetOpen()) closeSheet(); else goHome(); return; }
            if (!view || sheetOpen()) return;
            if (ev.key === 'ArrowLeft') { view.goLeft(); }
            else if (ev.key === 'ArrowRight' || ev.key === ' ') { view.goRight(); }
        });
        // Persist the latest position when the tab is hidden or the page is
        // being unloaded — covers backgrounding on mobile and closing the tab.
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'hidden') flush(true);
        });
        window.addEventListener('pagehide', function () { flush(true); });
    }

    function fail() {
        if (overlay) { overlay.hidden = false; overlay.textContent = i18n.loadError || 'Could not open this book.'; }
    }

    // --- Save for offline -------------------------------------------------
    // Talks to the service worker: cache the book file + reader page + shared
    // shell assets so the whole reader works with no connection. The SW also
    // stale-while-revalidates foliate's module graph as the book renders.
    var offlineSaved = false;
    var offlineBusy = false;

    function swReady() {
        return ('serviceWorker' in navigator) && navigator.serviceWorker.controller;
    }

    function setOfflineUI(state) {
        if (!offlineBtn) return;
        offlineBtn.classList.toggle('is-saved', state === 'saved');
        offlineBtn.classList.toggle('is-busy', state === 'busy');
        var icon = offlineBtn.querySelector('i');
        var label = state === 'saved' ? (i18n.savedOffline || 'Saved')
                  : state === 'busy' ? (i18n.saving || 'Saving…')
                  : (i18n.saveOffline || 'Save for offline');
        offlineBtn.setAttribute('aria-label', label);
        offlineBtn.setAttribute('title', label);
        if (icon) {
            icon.className = state === 'saved' ? 'ti ti-circle-check'
                          : state === 'busy' ? 'ti ti-loader-2'
                          : 'ti ti-download';
        }
    }

    // One-shot request/response to the controlling SW over a dedicated
    // MessageChannel port. More reliable on iOS Safari than listening on
    // navigator.serviceWorker for an event.source reply (which can be null).
    function swRequest(message, timeoutMs) {
        return new Promise(function (resolve) {
            var sw = ('serviceWorker' in navigator) && navigator.serviceWorker.controller;
            if (!sw) { resolve(null); return; }
            var done = false;
            var ch = new MessageChannel();
            ch.port1.onmessage = function (ev) {
                if (done) return;
                done = true;
                resolve(ev.data || null);
            };
            try {
                sw.postMessage(message, [ch.port2]);
            } catch (e) { resolve(null); return; }
            setTimeout(function () { if (!done) { done = true; resolve(null); } }, timeoutMs || 60000);
        });
    }

    function bookAssets() {
        // Per-book first (removed on un-save), then shared shell (kept).
        var shell = Array.isArray(cfg.shellAssets) ? cfg.shellAssets : [];
        return [cfg.pageUrl, cfg.fileUrl].concat(shell).filter(Boolean);
    }

    async function toggleOffline() {
        if (offlineBusy || !swReady()) return;
        offlineBusy = true;
        if (offlineSaved) {
            // Remove only the per-book assets so other saved books survive.
            setOfflineUI('busy');
            await swRequest({ type: 'removeBook', id: cfg.itemId, assets: [cfg.pageUrl, cfg.fileUrl] }, 15000);
            offlineSaved = false;
            setOfflineUI('idle');
        } else {
            setOfflineUI('busy');
            var res = await swRequest({ type: 'cacheBook', id: cfg.itemId, assets: bookAssets() }, 120000);
            offlineSaved = !!(res && res.ok);
            setOfflineUI(offlineSaved ? 'saved' : 'idle');
            if (!offlineSaved && offlineBtn) {
                offlineBtn.setAttribute('title', i18n.saveFailed || 'Could not save for offline');
            }
        }
        offlineBusy = false;
    }

    var offlineWired = false;
    async function enableOfflineButton() {
        if (offlineWired || !offlineBtn) return;
        offlineWired = true;
        offlineBtn.hidden = false;
        offlineBtn.addEventListener('click', toggleOffline);
        var res = await swRequest({ type: 'isBookCached', id: cfg.itemId, fileUrl: cfg.fileUrl }, 8000);
        offlineSaved = !!(res && res.cached);
        setOfflineUI(offlineSaved ? 'saved' : 'idle');
    }

    function initOffline() {
        if (!offlineBtn || !('serviceWorker' in navigator)) return;
        // Enable as soon as a SW controls the page. On first load the controller
        // can still be null (registration/activation in flight) or a stale
        // worker may be handing over after skipWaiting — both surface as a
        // controllerchange, so wire up then too. The button stays hidden until
        // a controller exists, so we never message into the void.
        if (navigator.serviceWorker.controller) {
            enableOfflineButton();
        }
        navigator.serviceWorker.addEventListener('controllerchange', function () {
            enableOfflineButton();
        });
    }

    async function start() {
        bindControls();
        bindSettings();
        window.addEventListener('online', flushUnsynced);
        initOffline();
        flushUnsynced();   // a previous offline session may have pending progress
        try {
            view = document.createElement('foliate-view');
            main.insertBefore(view, overlay);
            view.addEventListener('relocate', onRelocate);
            await view.open(cfg.fileUrl);

            // Tailor the settings sheet to the book's layout before showing it.
            adaptControlsForLayout();
            // Apply saved typography/theme before positioning so the resume
            // fraction maps to the final paginated layout.
            applyReaderStyles();

            var initial = Number(cfg.initialProgress) || 0;
            var status = cfg.readStatus;
            // Prefer locally-stored progress when it's further along — covers
            // resuming offline, where the server-rendered initial value is
            // stale (it can't have received progress made without a connection).
            var local = readLocalProgress();
            if (local && Number(local.percent) > initial) {
                initial = Number(local.percent);
                status = local.status || status;
            }
            var frac = 0;
            // Resume by percent. Don't jump to the end of a finished book —
            // start it over instead. Exact paragraph resume across devices is
            // out of scope (Kobo KEPUB spans vs EPUB CFI differ); percent is
            // the shared coordinate.
            if (initial > 0 && initial < 100 && status !== 'Finished') {
                frac = initial / 100;
            }
            await view.goToFraction(frac);

            if (overlay) overlay.hidden = true;
        } catch (err) {
            console.error('Reader failed to open book:', err);
            fail();
        }
    }

    start();
})();
