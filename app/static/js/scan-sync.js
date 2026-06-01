/* ------------------------------------------------------------------ *
 * scan-sync.js — File scan + push-sync SSE drivers
 *
 * Owns: /scan and /sync/push EventSource consumers, plus the inline
 * progress text in the actions menu and the sync-preview modal.
 *
 * Reads i18n strings from window.__colophonConfig.i18n.
 *
 * Exposes globals consumed by the template (onclick handlers):
 *   startScan, openSyncPreview, confirmPushSync, closeSyncPreview
 *   (startPushSync kept as an alias to openSyncPreview)
 *
 * Sync flow mirrors duplicates.js: GET /sync/pending → render a modal
 * listing the books → confirm starts the existing /sync/push SSE stream.
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    function _escSync(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /* Short, human-friendly relative time, e.g. "3h ago" / "2d ago".
       Falls back to a locale date string for older changes. */
    function _relTime(iso) {
        if (!iso) return '';
        var then = new Date(iso);
        if (isNaN(then.getTime())) return '';
        var diff = Math.floor((Date.now() - then.getTime()) / 1000);
        if (diff < 0) diff = 0;
        if (diff < 60) return diff + 's';
        if (diff < 3600) return Math.floor(diff / 60) + 'm';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h';
        if (diff < 7 * 86400) return Math.floor(diff / 86400) + 'd';
        return then.toLocaleDateString();
    }

    function closeSyncPreview() {
        var modal = document.getElementById('syncModal');
        if (modal) modal.style.display = 'none';
    }
    window.closeSyncPreview = closeSyncPreview;

    var _syncModalRoot = document.getElementById('syncModal');
    if (_syncModalRoot) {
        _syncModalRoot.addEventListener('click', function (e) {
            if (e.target === this) closeSyncPreview();
        });
    }

    function openSyncPreview() {
        var modal = document.getElementById('syncModal');
        if (!modal) return;
        var header = document.getElementById('syncHeader');
        var itemsEl = document.getElementById('syncItems');
        var feedback = document.getElementById('syncFeedback');
        var progress = document.getElementById('syncProgress');
        var confirmBtn = document.getElementById('syncConfirmBtn');
        var cancelBtn = document.getElementById('syncCancelBtn');

        feedback.style.display = 'none';
        progress.style.display = 'none';
        progress.textContent = '';
        confirmBtn.style.display = 'none';
        confirmBtn.disabled = false;
        cancelBtn.disabled = false;
        modal.style.display = 'flex';
        header.textContent = _i18n.syncLoading;
        itemsEl.innerHTML = '<div class="sync-empty"><i class="ti ti-loader ti-rotate"></i> ' + _escSync(_i18n.syncLoading) + '</div>';

        fetch('/sync/pending', {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var items = (data && data.items) || [];
                if (!items.length) {
                    header.textContent = '';
                    itemsEl.innerHTML = '<div class="sync-empty">' + _escSync(_i18n.syncNothing) + '</div>';
                    return;
                }
                header.textContent = _i18n.syncPreviewHeader.replace('{count}', items.length);
                var html = '';
                for (var i = 0; i < items.length; i++) {
                    var it = items[i];
                    var when = _relTime(it.file_modified);
                    var whenLabel = when ? _i18n.syncModifiedAt.replace('{time}', when) : '';
                    html += '<div class="sync-item">';
                    html +=   '<div class="sync-item-meta">';
                    html +=     '<div class="sync-item-title">' + _escSync(it.title) + '</div>';
                    html +=     '<div class="sync-item-author">' + _escSync(it.author || _i18n.syncUnknownAuthor) + '</div>';
                    html +=   '</div>';
                    if (whenLabel) html += '<div class="sync-item-time">' + _escSync(whenLabel) + '</div>';
                    html += '</div>';
                }
                itemsEl.innerHTML = html;
                document.getElementById('syncConfirmLabel').textContent =
                    _i18n.syncConfirmLabel.replace('{count}', items.length);
                confirmBtn.style.display = 'inline-flex';
            })
            .catch(function (err) {
                itemsEl.innerHTML = '';
                header.textContent = '';
                feedback.className = 'modal-feedback modal-feedback-error';
                feedback.textContent = _i18n.syncErrorLoading + ' ' + err;
                feedback.style.display = 'block';
            });
    }
    window.openSyncPreview = openSyncPreview;
    // Backwards-compatible alias — old callers may still reference this.
    window.startPushSync = openSyncPreview;

    function confirmPushSync() {
        var itemsEl = document.getElementById('syncItems');
        var header = document.getElementById('syncHeader');
        var progress = document.getElementById('syncProgress');
        var confirmBtn = document.getElementById('syncConfirmBtn');
        var cancelBtn = document.getElementById('syncCancelBtn');

        // Switch the modal from preview to live-progress mode.
        if (itemsEl) itemsEl.innerHTML = '';
        if (header) header.textContent = '';
        if (confirmBtn) confirmBtn.disabled = true;
        if (cancelBtn) cancelBtn.disabled = true;
        progress.style.display = 'block';
        progress.textContent = _i18n.syncing;

        var source = new EventSource('/sync/push');
        source.onmessage = function (e) {
            var d = JSON.parse(e.data);
            if (d.type === 'progress') {
                progress.textContent = _i18n.syncingFile
                    .replace('{current}', d.current)
                    .replace('{total}', d.total)
                    .replace('{file}', d.file);
            } else if (d.type === 'file_error') {
                console.error('[Colophon sync]', d.file, d.error);
            } else if (d.type === 'done') {
                source.close();
                var msg = _i18n.syncDone.replace('{synced}', d.synced);
                if (d.errors > 0) msg += ' ' + _i18n.syncErrors.replace('{errors}', d.errors);
                progress.textContent = msg;
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
            progress.textContent = _i18n.connectionLost;
            if (cancelBtn) cancelBtn.disabled = false;
        };
    }
    window.confirmPushSync = confirmPushSync;

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

    // The non-library-page sidebar entry links to <library>#sync; honour it
    // by opening the preview modal once the library view has loaded.
    if (window.location.hash === '#sync' && document.getElementById('syncModal')) {
        window.addEventListener('load', function () { openSyncPreview(); });
    }
})(window, document);
