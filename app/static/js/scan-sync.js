/* ------------------------------------------------------------------ *
 * scan-sync.js — File scan + push-sync SSE drivers
 *
 * Owns: /scan and /sync/push EventSource consumers, plus the inline
 * progress text in the actions menu and the upstream-sync bar.
 *
 * Reads i18n strings from window.__colophonConfig.i18n.
 *
 * Exposes globals consumed by the template (onclick handlers):
 *   startScan, startPushSync
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    function startPushSync() {
        var bar = document.getElementById('syncBar');
        var text = document.getElementById('syncBarText');
        var btn = bar.querySelector('button');
        // Force the bar visible — the sidebar entry point bypasses the
        // pagination-filter click path that previously toggled it.
        bar.style.display = 'flex';
        btn.disabled = true;
        text.textContent = _i18n.syncing;
        bar.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        var source = new EventSource('/sync/push');
        source.onmessage = function (e) {
            var d = JSON.parse(e.data);
            if (d.type === 'progress') {
                text.textContent = _i18n.syncingFile
                    .replace('{current}', d.current)
                    .replace('{total}', d.total)
                    .replace('{file}', d.file);
            } else if (d.type === 'file_error') {
                console.error('[Colophon sync]', d.file, d.error);
            } else if (d.type === 'done') {
                source.close();
                var msg = _i18n.syncDone.replace('{synced}', d.synced);
                if (d.errors > 0) msg += ' ' + _i18n.syncErrors.replace('{errors}', d.errors);
                text.textContent = msg;
                var pill = document.getElementById('libraryChipUnsynced');
                if (pill) {
                    pill.textContent = _i18n.zeroUnsynced;
                    pill.style.display = 'none';
                }
                setTimeout(function () { location.reload(); }, 1500);
            }
        };
        source.onerror = function () {
            source.close();
            text.textContent = _i18n.connectionLost;
            btn.disabled = false;
        };
    }
    window.startPushSync = startPushSync;

    function startScan() {
        var inline = document.getElementById('scanInline');
        var inlineText = document.getElementById('scanInlineText');
        if (inline) inline.style.display = 'inline-flex';
        if (inlineText) inlineText.textContent = _i18n.searchingEbooks;

        var source = new EventSource('/scan?progress=1');
        source.onmessage = function (e) {
            var d = JSON.parse(e.data);
            if (d.type === 'upstream_pull') {
                if (inlineText) inlineText.textContent = _i18n.fetchingFromLibrary + ' ' + d.file;
            } else if (d.type === 'progress') {
                if (inlineText) inlineText.textContent = _i18n.scanningFile + ' ' + d.file;
            } else if (d.type === 'done') {
                if (inlineText) inlineText.textContent = _i18n.scanDone
                    .replace('{added}', d.added)
                    .replace('{updated}', d.updated)
                    .replace('{removed}', d.removed);
                source.close();
                setTimeout(function () { location.reload(); }, 1200);
            } else if (d.type === 'error') {
                if (inlineText) inlineText.textContent = _i18n.scanError + ' ' + d.message;
                source.close();
            }
        };
        source.onerror = function () {
            if (inlineText) inlineText.textContent = _i18n.connectionLost;
            source.close();
        };
    }
    window.startScan = startScan;
})(window, document);
