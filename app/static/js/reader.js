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
import { initDictLookup } from './reader-dict.js';

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

    var scrubEl = document.getElementById('readerScrub');
    var scrubLabel = document.getElementById('readerScrubLabel');
    var snapbackBtn = document.getElementById('readerSnapback');
    var snapbackLabel = document.getElementById('readerSnapbackLabel');
    var restartBtn = document.getElementById('rsRestart');

    var offlineBtn = document.getElementById('readerOfflineBtn');
    var shareBtn = document.getElementById('readerShareBtn');
    var toastEl = document.getElementById('readerToast');
    var settingsBtn = document.getElementById('readerSettingsBtn');
    var sheet = document.getElementById('readerSheet');
    var backdrop = document.getElementById('readerSheetBackdrop');
    var sizeVal = document.getElementById('rsSizeVal');
    var sizeDown = document.getElementById('rsSizeDown');
    var sizeUp = document.getElementById('rsSizeUp');

    var view = null;
    var dictCtl = null;          // dictionary-sheet controller (reader-dict.js)
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
        return a && b && a.status === b.status
            && Math.round(a.percent) === Math.round(b.percent)
            && a.href === b.href && a.offset === b.offset;
    }

    // --- Exact position: the character bridge ----------------------------
    // The Kobo positions a book by span ids that kepubify injects; those don't
    // exist here. But kepubify preserves the text itself character for
    // character, so "how many non-whitespace characters into this chapter am
    // I" means the same thing on both sides, and the server turns it into the
    // span the device would have used. app/services/kobo_location.py holds the
    // other half of this rule — the two must not drift apart.

    function dense(text) { return (text || '').replace(/\s+/g, ''); }

    function textWalker(doc) {
        return doc.createTreeWalker(doc.body || doc, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                for (var p = node.parentNode; p; p = p.parentNode) {
                    var tag = (p.nodeName || '').toLowerCase();
                    if (tag === 'script' || tag === 'style') return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            }
        });
    }

    // Characters (whitespace excluded) from the top of the document to a point.
    function denseOffsetOf(doc, container, offsetInNode) {
        if (!doc || !container) return null;
        // A range can start on an element rather than a text node; the first
        // text node at or after it is the honest interpretation.
        if (container.nodeType !== 3) {
            var probe = textWalker(doc);
            var found = null;
            var n;
            while ((n = probe.nextNode())) {
                if (container.contains && container.contains(n)) { found = n; break; }
            }
            if (!found) return null;
            container = found;
            offsetInNode = 0;
        }
        var walker = textWalker(doc);
        var count = 0;
        var node;
        while ((node = walker.nextNode())) {
            if (node === container) {
                return count + dense(String(node.data).slice(0, offsetInNode)).length;
            }
            count += dense(node.data).length;
        }
        return null;
    }

    // The inverse: a DOM Range at `offset` dense characters into `doc`.
    function rangeAtDenseOffset(doc, offset) {
        if (!doc || offset == null) return null;
        var walker = textWalker(doc);
        var seen = 0;
        var node;
        var last = null;
        while ((node = walker.nextNode())) {
            var text = String(node.data);
            var len = dense(text).length;
            last = node;
            if (seen + len > offset) {
                // Advance through this node until we've passed `need`
                // non-whitespace characters.
                var need = offset - seen;
                var pos = 0;
                var counted = 0;
                while (pos < text.length && counted < need) {
                    if (!/\s/.test(text[pos])) counted++;
                    pos++;
                }
                var range = doc.createRange();
                range.setStart(node, Math.min(pos, text.length));
                range.collapse(true);
                return range;
            }
            seen += len;
        }
        if (last) {
            var end = doc.createRange();
            end.setStart(last, 0);
            end.collapse(true);
            return end;
        }
        return null;
    }

    // The archive-relative path of a spine section ("OEBPS/chapter061.xhtml"),
    // which is the form the Kobo uses for Location.Source.
    function sectionHref(index) {
        try {
            var section = view && view.book && view.book.sections
                && view.book.sections[index];
            var href = section && (section.id || section.href);
            return typeof href === 'string' ? href.split('#')[0] : null;
        } catch (e) { return null; }
    }

    function anchorFromRelocate(detail) {
        try {
            var index = detail && detail.section && typeof detail.section.current === 'number'
                ? detail.section.current : null;
            var range = detail && detail.range;
            if (index == null || !range || !range.startContainer) return null;
            var doc = range.startContainer.ownerDocument;
            var href = sectionHref(index);
            if (!doc || !href) return null;
            var offset = denseOffsetOf(doc, range.startContainer, range.startOffset);
            if (offset == null) return null;
            return { href: href, offset: offset };
        } catch (e) { return null; }
    }

    // --- Virtual page numbers ----------------------------------------------
    // A percentage means something different on every screen; a virtual page
    // is a fixed number of dense characters (app/services/page_map.py), so
    // page 212 is the same place everywhere. The three helpers below mirror
    // page_for_position / position_for_page / print_page_for_position there
    // exactly — same clamping, same section lookup — and must change together.
    var pageMap = null;        // parsed /pagemap JSON, or null (none / not loaded)
    var lastAnchor = null;     // { href, offset } of the last relocate
    // True while start() positions the book. The relocates that placement
    // itself fires report the top of the rendered spread, which can sit a
    // screen *before* the exact anchor when pagination differs slightly
    // between loads (fonts, viewport). Saving those would walk the stored
    // position backwards a little on every open; the user's own first page
    // turn is the first thing worth recording.
    var placing = false;

    function fmt(template, vars) {
        return String(template).replace(/\{(\w+)\}/g, function (m, k) {
            return vars && vars[k] != null ? vars[k] : m;
        });
    }

    // posixpath.normpath(source.split('#')[0]) — compare sections by this.
    function normSource(source) {
        if (!source) return null;
        var parts = String(source).split('#')[0].split('/');
        var out = [];
        parts.forEach(function (p) {
            if (p === '' || p === '.') return;
            if (p === '..') { if (out.length) out.pop(); return; }
            out.push(p);
        });
        return out.join('/');
    }

    function findSection(source) {
        if (!pageMap) return null;
        var src = normSource(source);
        var secs = pageMap.sections || [];
        for (var i = 0; i < secs.length; i++) {
            if (secs[i].source === src) return secs[i];
        }
        return null;
    }

    function pageOf(href, offset) {
        if (!pageMap) return null;
        var sec = findSection(href);
        if (!sec) return null;
        var off = Math.max(0, parseInt(offset, 10) || 0);
        var page = Math.floor((sec.start + off) / pageMap.page_chars) + 1;
        return Math.max(1, Math.min(page, pageMap.total_pages));
    }

    function anchorForPage(page) {
        if (!pageMap || !pageMap.sections || !pageMap.sections.length) return null;
        var n = parseInt(page, 10);
        if (isNaN(n)) return null;
        n = Math.max(1, Math.min(n, pageMap.total_pages));
        var target = (n - 1) * pageMap.page_chars;
        var populated = pageMap.sections.filter(function (s) { return s.chars > 0; });
        if (!populated.length) return { href: pageMap.sections[0].source, offset: 0 };
        for (var i = 0; i < populated.length; i++) {
            var s = populated[i];
            if (target < s.start + s.chars) {
                return { href: s.source, offset: Math.max(0, target - s.start) };
            }
        }
        var last = populated[populated.length - 1];
        return { href: last.source, offset: Math.max(0, last.chars - 1) };
    }

    // Label of the last print page break at or before the position, or null.
    function printPageAt(href, offset) {
        if (!pageMap || !pageMap.page_list || !pageMap.page_list.length) return null;
        var order = {};
        pageMap.sections.forEach(function (s, i) { order[s.source] = i; });
        var src = normSource(href);
        if (!(src in order)) return null;
        var off = parseInt(offset, 10) || 0;
        var found = null;
        pageMap.page_list.forEach(function (entry) {
            var idx = order[entry.source];
            if (idx === undefined) return;
            if (idx < order[src] || (idx === order[src] && entry.offset <= off)) {
                found = entry.label;
            }
        });
        return found;
    }

    // Total pages, known from the loaded map or (before it lands) from the
    // count the server cached with the page; fixed-layout books have none.
    function virtualTotal() {
        if (view && view.isFixedLayout) return null;
        if (pageMap) return pageMap.total_pages;
        return Number(cfg.totalPages) || null;
    }
    function approxPage(fraction, total) {
        return Math.min(total, Math.floor(fraction * total) + 1);
    }

    // The top-bar readout: "p. 212 / 540 (198)" when the page map and the
    // relocate anchor are known, plain percent otherwise. The percent stays in
    // the tooltip so it is never lost.
    function renderPosition() {
        if (!percentEl) return;
        var pct = Math.round(lastFraction * 100) + '%';
        var text = pct;
        if (pageMap && lastAnchor && !(view && view.isFixedLayout)) {
            var page = pageOf(lastAnchor.href, lastAnchor.offset);
            if (page != null) {
                text = fmt(i18n.pageOf || 'p. {page} / {total}',
                    { page: page, total: pageMap.total_pages });
                var printed = printPageAt(lastAnchor.href, lastAnchor.offset);
                if (printed) text += ' (' + printed + ')';
            }
        }
        percentEl.textContent = text;
        percentEl.title = pct;
    }

    var gotoRow = document.getElementById('rsGotoRow');
    var gotoInput = document.getElementById('rsGotoPage');
    var gotoGo = document.getElementById('rsGotoGo');
    var gotoTotal = document.getElementById('rsGotoTotal');

    function syncGotoRow() {
        if (!gotoRow) return;
        var show = !!pageMap && !(view && view.isFixedLayout);
        gotoRow.hidden = !show;
        if (!show) return;
        if (gotoInput) gotoInput.max = String(pageMap.total_pages);
        if (gotoTotal) gotoTotal.textContent = '/ ' + pageMap.total_pages;
    }

    // Non-blocking: a missing/offline map just means "no page numbers".
    function loadPageMap() {
        if (!cfg.pageMapUrl) return;
        fetch(cfg.pageMapUrl).then(function (r) {
            return r && r.ok ? r.json() : null;
        }).then(function (m) {
            pageMap = m && m.available && !(view && view.isFixedLayout) ? m : null;
            syncGotoRow();
            renderPosition();
            if (scrubLabel && !scrubbing && lastDetail) scrubLabel.textContent = positionLabel(lastDetail);
        }).catch(function () { pageMap = null; });
    }

    async function goToPageFromInput() {
        if (!gotoInput || !view) return;
        var anchor = anchorForPage(gotoInput.value);
        if (!anchor) { showToast(i18n.gotoPageFailed || 'Could not find that page.'); return; }
        setSnapback();   // before the jump, so the chip can bring us back
        var ok = await goToAnchor(anchor.href, anchor.offset);
        if (!ok) {
            clearSnapback();
            showToast(i18n.gotoPageFailed || 'Could not find that page.');
            return;
        }
        closeSheet();
    }

    function bindGoto() {
        if (gotoGo) gotoGo.addEventListener('click', goToPageFromInput);
        if (gotoInput) gotoInput.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); goToPageFromInput(); }
        });
        // The readout doubles as a shortcut: tap it to type a page number.
        function openGoto() {
            openSheet();
            if (gotoRow && !gotoRow.hidden && gotoInput) gotoInput.focus();
        }
        if (percentEl) {
            percentEl.addEventListener('click', openGoto);
            percentEl.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openGoto(); }
            });
        }
    }

    // Move to "N non-whitespace characters into this section". Returns true
    // when the exact placement worked; callers fall back to a fraction.
    async function goToAnchor(href, offset) {
        try {
            await view.goTo(href);
            var contents = view.renderer && view.renderer.getContents
                ? view.renderer.getContents() : null;
            var doc = contents && contents[0] && contents[0].doc;
            var range = rangeAtDenseOffset(doc, Number(offset));
            var want = normSource(href);
            var index = view.book.sections.findIndex(function (s) {
                return normSource(s.id || s.href || '') === want;
            });
            if (range && index >= 0) {
                var cfi = view.getCFI(index, range);
                if (cfi) { await view.goTo(cfi); return true; }
            }
        } catch (e) {
            console.warn('Reader: exact placement failed', e);
        }
        return false;
    }

    // --- Offline-safe progress -------------------------------------------
    // Progress is always mirrored to localStorage so the book resumes at the
    // right place even when opened offline (the server-rendered initial
    // progress is then stale). A copy that failed to reach the server is kept
    // marked unsynced and retried on reconnect.
    var PROGRESS_KEY = 'colophon-reader-progress-' + (cfg.itemId != null ? cfg.itemId : 'x');

    function persistLocal(state, synced, savedAt) {
        try {
            // savedAt lets resume compare this copy against the server's
            // read_last_modified, so a library-side reset isn't undone by a
            // stale-but-further local copy. The same savedAt is sent in the
            // POST body so the server can drop a stale offline flush too, and
            // so the global flusher (offline-progress-sync.js) can tell whether
            // the copy it posted is still the current one before marking synced.
            localStorage.setItem(PROGRESS_KEY, JSON.stringify({
                percent: state.percent, status: state.status, synced: !!synced,
                savedAt: savedAt != null ? savedAt : Date.now(),
                // The exact position, so the offline copy resumes (and flushes)
                // to the same sentence, not just the same percent.
                href: state.href || null,
                offset: state.offset != null ? state.offset : null
            }));
        } catch (e) { /* private mode / quota */ }
    }
    function readLocalProgress() {
        try { return JSON.parse(localStorage.getItem(PROGRESS_KEY) || 'null'); }
        catch (e) { return null; }
    }

    function flush(useBeacon, keepSavedAt) {
        if (!latest || sameState(latest, lastSaved)) return;
        var payload = latest;
        // A reconnect flush of progress made offline (flushUnsynced) must keep
        // the ORIGINAL savedAt: re-stamping it with Date.now() would make the
        // stale post look newer than a reset done meanwhile and defeat the
        // server's reset guard. A live flush has no keepSavedAt and stamps now.
        var savedAt = keepSavedAt != null ? keepSavedAt : Date.now();
        persistLocal(payload, false, savedAt);   // keep a local copy regardless of network
        // Carry savedAt so the server can drop a stale offline post that would
        // otherwise undo a reset (see reader.py update_progress); href/offset
        // from payload still give the exact position when online.
        var body = JSON.stringify(Object.assign({}, payload, { savedAt: savedAt }));
        if (useBeacon && navigator.sendBeacon) {
            var ok = navigator.sendBeacon(cfg.progressUrl, new Blob([body], { type: 'application/json' }));
            if (ok) { lastSaved = payload; persistLocal(payload, true, savedAt); }
            return;
        }
        fetch(cfg.progressUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body,
            keepalive: true
        }).then(function (r) {
            if (r && r.ok) { lastSaved = payload; persistLocal(payload, true, savedAt); }
        }).catch(function () { /* stays unsynced; retried on 'online' / next change */ });
    }

    // On reconnect, push up any progress made while offline.
    function flushUnsynced() {
        var local = readLocalProgress();
        if (local && local.synced === false) {
            latest = { percent: local.percent, status: local.status };
            // Post the exact position too: a percent-only post makes the
            // server clear the stored Kobo location (see update_progress).
            if (local.href && local.offset != null) {
                latest.href = local.href;
                latest.offset = local.offset;
            }
            flush(false, local.savedAt);   // keep the original stamp for the reset guard
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

    // --- Scrub bar + snapback ---------------------------------------------
    // The slider makes big jumps one drag instead of hundreds of taps (the
    // original pain point was long PDFs). Jumping around is safe: the server's
    // reading state is monotonic (furthest-read-wins), so browsing backward
    // never regresses real progress, and the snapback chip returns to the
    // pre-jump position.
    var lastFraction = 0;    // last relocate fraction (pre-jump baseline)
    var lastDetail = null;   // last relocate detail (for the position label)
    var scrubbing = false;   // finger down on the slider — don't fight it
    var snapTarget = null;   // { fraction, label } to return to, or null
    var SNAP_DONE_EPSILON = 0.002;   // "close enough to be back" (0.2%)

    // Pre-paginated books (PDF / fixed-layout EPUB) get real page numbers —
    // foliate maps 1 section = 1 page there; reflowable books get percent.
    function positionLabel(detail) {
        var fraction = detail && typeof detail.fraction === 'number' ? detail.fraction : 0;
        var sec = detail && detail.section;
        if (view && view.isFixedLayout && sec && sec.total) {
            return (sec.current + 1) + ' / ' + sec.total;
        }
        var total = virtualTotal();
        if (total) {
            // onRelocate has already walked the DOM for this detail; reuse it.
            var anchor = detail === lastDetail ? lastAnchor : anchorFromRelocate(detail);
            var page = anchor ? pageOf(anchor.href, anchor.offset) : null;
            if (page == null) page = approxPage(fraction, total);
            return fmt(i18n.pageOf || 'p. {page} / {total}', { page: page, total: total });
        }
        return Math.round(fraction * 100) + '%';
    }

    // Label preview while dragging (before any relocate has happened).
    function previewLabel(fraction) {
        var total = view && view.isFixedLayout && lastDetail
            && lastDetail.section && lastDetail.section.total;
        if (total) return Math.min(total, Math.floor(fraction * total) + 1) + ' / ' + total;
        // Reflowable: the virtual page, approximated from the fraction (the
        // real page needs a relocate to know which section the drag lands in).
        var vt = virtualTotal();
        if (vt) {
            return fmt(i18n.pageOf || 'p. {page} / {total}',
                { page: approxPage(fraction, vt), total: vt });
        }
        return Math.round(fraction * 100) + '%';
    }

    function clearSnapback() {
        snapTarget = null;
        if (snapbackBtn) snapbackBtn.hidden = true;
    }

    // Remember where we are before a jump (scrub bar, "Go to page") so the
    // chip can bring the reader back. Only the first jump of a series sets it.
    function setSnapback() {
        if (snapTarget) return;
        snapTarget = { fraction: lastFraction, label: positionLabel(lastDetail) };
        if (snapbackLabel) snapbackLabel.textContent = snapTarget.label;
        if (snapbackBtn) snapbackBtn.hidden = false;
    }

    function bindNav() {
        if (scrubEl) {
            scrubEl.addEventListener('input', function () {
                scrubbing = true;
                if (scrubLabel) scrubLabel.textContent = previewLabel(Number(scrubEl.value) / 1000);
            });
            // Navigate on release only — live-seeking would re-render a PDF
            // page for every pixel of the drag.
            scrubEl.addEventListener('change', function () {
                scrubbing = false;
                if (!view) return;
                setSnapback();
                view.goToFraction(Number(scrubEl.value) / 1000);
            });
        }
        if (snapbackBtn) snapbackBtn.addEventListener('click', function () {
            var t = snapTarget;
            clearSnapback();
            if (t && view) view.goToFraction(t.fraction);
        });
        if (restartBtn) restartBtn.addEventListener('click', restartBook);
    }

    // One-tap "start over": must reset the server state first — the reading
    // state is furthest-read-wins, so merely jumping to 0 would be undone by
    // the next sync resurrecting the old position.
    function restartBook() {
        if (!window.confirm(i18n.restartConfirm || 'Start over from the beginning?')) return;
        closeSheet();
        fetch(cfg.resetUrl, { method: 'POST' })
            .then(function (r) {
                if (!r || !r.ok) throw new Error('reset failed');
                latest = null;
                lastSaved = null;
                try { localStorage.removeItem(PROGRESS_KEY); } catch (e) { /* ignore */ }
                clearSnapback();
                if (view) view.goToFraction(0);
            })
            .catch(function () {
                showToast(i18n.restartFailed || 'Could not reset reading progress.');
            });
    }

    function onRelocate(e) {
        var detail = e.detail || {};
        var fraction = typeof detail.fraction === 'number' ? detail.fraction : 0;
        lastFraction = fraction;
        lastDetail = detail;
        lastAnchor = anchorFromRelocate(detail);
        renderPosition();
        if (!scrubbing) {
            if (scrubEl) scrubEl.value = String(Math.round(fraction * 1000));
            if (scrubLabel) scrubLabel.textContent = positionLabel(detail);
        }
        // Landing back at (or next to) the snapback target means we're home —
        // the chip has done its job.
        if (snapTarget && Math.abs(fraction - snapTarget.fraction) < SNAP_DONE_EPSILON) {
            clearSnapback();
        }
        if (placing) return;   // resume's own relocates: nothing new to record
        var state = fractionToState(fraction);
        var anchor = lastAnchor;
        if (anchor) { state.href = anchor.href; state.offset = anchor.offset; }
        scheduleSave(state);
    }

    function bindControls() {
        if (backBtn) backBtn.addEventListener('click', goHome);
        if (prevZone) prevZone.addEventListener('click', function () { if (view) view.goLeft(); });
        if (nextZone) nextZone.addEventListener('click', function () { if (view) view.goRight(); });
        document.addEventListener('keydown', function (ev) {
            // Escape closes the dictionary sheet first, then the settings
            // sheet; only leaves the reader when nothing is open.
            if (ev.key === 'Escape') {
                if (dictCtl && dictCtl.isOpen()) dictCtl.close();
                else if (sheetOpen()) closeSheet();
                else goHome();
                return;
            }
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
        // Per-book first (removed on un-save), then shared shell (kept). The
        // cover rides along too, so the offline index (see sw.js) can show it
        // on the "Downloaded books" shelf with no connection.
        var shell = Array.isArray(cfg.shellAssets) ? cfg.shellAssets : [];
        // pageMapUrl follows the two essential assets (the SW treats the first two as must-have).
        return [cfg.pageUrl, cfg.fileUrl, cfg.coverUrl, cfg.pageMapUrl].concat(shell).filter(Boolean);
    }

    async function toggleOffline() {
        if (offlineBusy || !swReady()) return;
        offlineBusy = true;
        if (offlineSaved) {
            // Remove only the per-book assets so other saved books survive.
            setOfflineUI('busy');
            await swRequest({ type: 'removeBook', id: cfg.itemId, assets: [cfg.pageUrl, cfg.fileUrl, cfg.pageMapUrl].filter(Boolean) }, 15000);
            offlineSaved = false;
            setOfflineUI('idle');
        } else {
            setOfflineUI('busy');
            var res = await swRequest({
                type: 'cacheBook', id: cfg.itemId,
                title: cfg.bookTitle, author: cfg.bookAuthor, coverUrl: cfg.coverUrl,
                assets: bookAssets()
            }, 120000);
            offlineSaved = !!(res && res.ok);
            if (res && res.ok && res.failed && res.failed.length) {
                console.warn('Reader: some offline assets were not cached', res.failed);
            }
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

    // --- Give this book to someone ---------------------------------------
    // Hand the raw file (EPUB or MOBI/AZW3) to the OS share sheet (AirDrop /
    // Nearby Share / Messages / mail) via the Web Share API. The point is the in-person
    // "you can have it from me" handoff. Three things can stop it — each gets
    // a clear toast rather than a dead button or a silent failure:
    //   1. DRM        — server says the book isn't shareable (cfg.canShare).
    //   2. not HTTPS  — Web Share with files needs a secure context.
    //   3. no support — browser lacks file sharing → fall back to a download.
    var toastTimer = null;
    function showToast(msg) {
        if (!toastEl || !msg) return;
        toastEl.textContent = msg;
        toastEl.hidden = false;
        // Force reflow so the .is-visible transition runs on re-show.
        void toastEl.offsetWidth;
        toastEl.classList.add('is-visible');
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            toastEl.classList.remove('is-visible');
            setTimeout(function () { toastEl.hidden = true; }, 220);
        }, 6000);
    }

    // A reason the share can't proceed at all, or null if it can be attempted.
    function shareBlockReason() {
        if (!cfg.canShare) return i18n.shareDrm || 'This book can’t be shared.';
        if (!window.isSecureContext) return i18n.shareNeedsHttps || 'Sharing needs HTTPS.';
        return null;
    }

    function downloadFile(blob, name) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = name || 'book.epub';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    }

    var sharing = false;
    async function doShare() {
        if (sharing) return;
        var reason = shareBlockReason();
        if (reason) { showToast(reason); return; }

        sharing = true;
        if (shareBtn) shareBtn.classList.add('is-busy');
        try {
            var resp = await fetch(cfg.fileUrl);
            if (!resp || !resp.ok) throw new Error('fetch failed');
            var blob = await resp.blob();
            var name = cfg.shareFileName || 'book.epub';
            var file = new File([blob], name, { type: cfg.shareMime || 'application/epub+zip' });

            if (navigator.canShare && navigator.canShare({ files: [file] })) {
                await navigator.share({ files: [file], title: cfg.bookTitle || name });
            } else {
                // Secure context but no file-level Web Share (e.g. desktop
                // Firefox): download so the user can send it themselves.
                downloadFile(blob, name);
                showToast(i18n.shareUnsupported || 'Downloading instead.');
            }
        } catch (err) {
            // The user dismissing the native share sheet is not an error.
            if (err && err.name === 'AbortError') { /* cancelled */ }
            else {
                console.error('Share failed:', err);
                showToast(i18n.shareError || 'Could not share this book.');
            }
        } finally {
            sharing = false;
            if (shareBtn) shareBtn.classList.remove('is-busy');
        }
    }

    function initShare() {
        if (!shareBtn) return;
        // Dim the button up-front when it can't actually share, but keep it
        // tappable so the toast can explain why (transparency over a hidden
        // or greyed-out dead control).
        if (shareBlockReason()) shareBtn.classList.add('is-blocked');
        shareBtn.addEventListener('click', doShare);
    }

    async function start() {
        bindControls();
        bindNav();
        bindSettings();
        bindGoto();
        window.addEventListener('online', flushUnsynced);
        initOffline();
        initShare();
        flushUnsynced();   // a previous offline session may have pending progress
        try {
            view = document.createElement('foliate-view');
            main.insertBefore(view, overlay);
            view.addEventListener('relocate', onRelocate);
            // Before open(): the per-section 'load' events the dictionary
            // module listens for start firing as soon as the book renders.
            dictCtl = initDictLookup({ view: view, cfg: cfg });
            await view.open(cfg.fileUrl);
            loadPageMap();   // non-blocking; no map just means no page numbers

            // Tailor the settings sheet to the book's layout before showing it.
            adaptControlsForLayout();
            // Apply saved typography/theme before positioning so the resume
            // fraction maps to the final paginated layout.
            applyReaderStyles();

            // Newest position wins: the server's stored position (reader or
            // Kobo) against this browser's local copy, by timestamp. Progress
            // (furthest read) is a separate field and does not take part —
            // stepping back a page must resume on that page. Ties go to the
            // server; an unsynced local copy is pushed up by flushUnsynced
            // either way.
            var chosen = {
                href: cfg.resumeHref, offset: cfg.resumeOffset,
                percent: cfg.resumePercent != null ? cfg.resumePercent : cfg.initialProgress,
                at: cfg.resumeAt != null ? cfg.resumeAt : cfg.progressModifiedAt
            };
            var status = cfg.readStatus;
            var local = readLocalProgress();
            if (local && (Number(local.savedAt) || 0) > (Number(chosen.at) || 0)) {
                chosen = {
                    href: local.href, offset: local.offset,
                    percent: local.percent, at: local.savedAt
                };
                status = local.status || status;
            }
            var initial = Number(chosen.percent) || 0;
            var finished = status === 'Finished';   // a finished book starts over
            var frac = 0;
            if (initial > 0 && initial < 100 && !finished) frac = initial / 100;
            // Exact placement when the candidate carries an anchor; percent is
            // the fallback, and the only route for entries that predate it.
            var placed = false;
            placing = true;
            try {
                if (!finished && chosen.href && chosen.offset != null) {
                    placed = await goToAnchor(chosen.href, chosen.offset);
                }
                if (!placed) await view.goToFraction(frac);
            } finally {
                // foliate dispatches the placement's relocate *after* goTo
                // resolves (its view-level event carries no reason to tell it
                // apart), so hold the guard a moment longer. A page turn
                // inside this window is recorded by the next one.
                setTimeout(function () { placing = false; }, 400);
            }
            if (scrubEl) scrubEl.disabled = false;

            if (overlay) overlay.hidden = true;
        } catch (err) {
            console.error('Reader failed to open book:', err);
            fail();
        }
    }

    start();
})();
