/* ------------------------------------------------------------------ *
 * cleanup-misc.js — Misc UI bits that didn't fit any feature module
 *
 * Owns:
 *   - The global Escape-key handler that closes whichever modal is
 *     currently open (batch / bulk-result / book / series).
 *   - The resizable-column drag handles for the main #bookTable (and
 *     localStorage persistence of column widths).
 *
 * Pure event-bindings; no external API. Just loaded once at end of
 * body (after all feature modules).
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    /* ============================================================ *
     * Esc closes the topmost open modal
     * ============================================================ */

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var batchModal      = document.getElementById('batchModal');
        var bulkResultModal = document.getElementById('bulkResultModal');
        var bookModal       = document.getElementById('bookModal');
        var seriesModal     = document.getElementById('seriesModal');

        if (batchModal && batchModal.style.display === 'flex') {
            if (typeof closeBatchModal === 'function') closeBatchModal();
        } else if (bulkResultModal && bulkResultModal.style.display === 'flex') {
            if (typeof closeBulkResultModal === 'function') closeBulkResultModal();
        } else if (bookModal && bookModal.style.display === 'flex') {
            if (typeof closeBookModal === 'function') closeBookModal();
        } else if (seriesModal && seriesModal.style.display === 'flex') {
            if (typeof closeSeriesModal === 'function') closeSeriesModal();
        }
    });

    /* ============================================================ *
     * Resizable columns in #bookTable
     * ============================================================ */

    (function () {
        var table = document.getElementById('bookTable');
        if (!table) return;
        var ths = table.querySelectorAll('thead th');

        ths.forEach(function (th, i) {
            if (i === ths.length - 1) return;

            var handle = document.createElement('div');
            handle.className = 'col-resize-handle';
            handle.addEventListener('mousedown', function (e) {
                e.preventDefault();
                var startX = e.pageX;
                var startW = th.offsetWidth;
                var next = ths[i + 1];
                var nextW = next ? next.offsetWidth : 0;

                function onMove(ev) {
                    var diff = ev.pageX - startX;
                    th.style.width = Math.max(50, startW + diff) + 'px';
                    if (next) next.style.width = Math.max(50, nextW - diff) + 'px';
                }
                function onUp() {
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    var widths = Array.from(ths).map(function (t) { return t.style.width || ''; });
                    localStorage.setItem('colophon-col-widths', JSON.stringify(widths));
                }
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });
            th.style.position = 'relative';
            th.appendChild(handle);
        });

        var saved = JSON.parse(localStorage.getItem('colophon-col-widths') || 'null');
        if (saved) {
            ths.forEach(function (th, i) {
                if (saved[i]) th.style.width = saved[i];
            });
        }
    })();
})(window, document);
