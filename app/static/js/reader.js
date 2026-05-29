// Colophon – e-book metadata manager
//
// In-browser reader controller. Loads an EPUB into foliate-js, resumes by
// percent, and syncs progress back to the server through the same canonical
// reading-state fields the Kobo sync uses (POST /reader/<id>/progress →
// services/reading_state.py). Step 1 is online-only; no offline caching.
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

    var view = null;
    var saveTimer = null;
    var latest = null;           // { percent, status } pending save
    var lastSaved = null;        // last successfully sent { percent, status }
    var FINISHED_FRACTION = 0.999;
    var SAVE_DEBOUNCE_MS = 1500;

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

    function flush(useBeacon) {
        if (!latest || sameState(latest, lastSaved)) return;
        var payload = latest;
        var body = JSON.stringify(payload);
        if (useBeacon && navigator.sendBeacon) {
            navigator.sendBeacon(cfg.progressUrl, new Blob([body], { type: 'application/json' }));
            lastSaved = payload;
            return;
        }
        fetch(cfg.progressUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body,
            keepalive: true
        }).then(function () { lastSaved = payload; }).catch(function () { /* retried on next relocate */ });
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
            if (!view) return;
            if (ev.key === 'ArrowLeft') { view.goLeft(); }
            else if (ev.key === 'ArrowRight' || ev.key === ' ') { view.goRight(); }
            else if (ev.key === 'Escape') { goHome(); }
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

    async function start() {
        bindControls();
        try {
            view = document.createElement('foliate-view');
            main.insertBefore(view, overlay);
            view.addEventListener('relocate', onRelocate);
            await view.open(cfg.fileUrl);

            var initial = Number(cfg.initialProgress) || 0;
            var frac = 0;
            // Resume by percent. Don't jump to the end of a finished book —
            // start it over instead. Exact paragraph resume across devices is
            // out of scope (Kobo KEPUB spans vs EPUB CFI differ); percent is
            // the shared coordinate.
            if (initial > 0 && initial < 100 && cfg.readStatus !== 'Finished') {
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
