/* Colophon – fetch covers for the "missing cover" filter
 *
 * The fifth scenario flow, and the only one that still drives the generic
 * enrichment engine. The shared fact is the filter itself: every book in
 * it lacks a cover, so one run answers one question for all of them.
 *
 * The stream runs with `dry_run=1`, like every other scenario. The cover
 * URL reaches the browser either way — the pipeline downloads a
 * `preview_<id>` file whether or not anything is applied — so there is
 * nothing to gain by letting the engine write, and everything to lose:
 * without the dry run it would also write auto-applied *text* fields to
 * the files with no review at all.
 *
 * Applying is per book, one at a time and in the browser. Each apply is a
 * download plus an `ebook-meta` write, and a hundred of them in parallel
 * against two sync workers would queue past Gunicorn's timeout with
 * nothing on screen.
 */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    function t(key, fallback) { return _i18n[key] || fallback; }

    // bulk_stream clamps max_items to 100. A larger filter runs in rounds.
    var MAX_PER_RUN = 100;

    var _source = null;
    var _rows = [];          // {itemId, title, coverUrl}
    var _queued = 0;         // books sent to this run
    var _overflow = 0;       // books the filter held beyond MAX_PER_RUN
    var _noCover = 0;        // books the run found nothing for

    function _el(id) { return document.getElementById(id); }

    function _esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/[']/g, '&#39;');
    }

    function _setStatus(text) {
        var el = _el('coverBatchStatus');
        if (el) el.textContent = text;
    }

    /* ---------------------------------------------------------------- *
     * The banner: shown only while the "missing cover" chip is lit
     * ---------------------------------------------------------------- */

    function _coverFilterActive() {
        return typeof window._getBadgeFilter === 'function'
            && window._getBadgeFilter() === 'missing_cover:1';
    }

    /* Every row the filter holds — not the page, and not only the rows
       the current view happens to show. `getFilteredRows` also drops the
       siblings a grouped or series view has collapsed, and those books
       lack a cover just as much: a cover is applied per file, so each
       format needs its own. Reading `filterHidden` directly keeps "these"
       meaning the same thing in the table, the shelf and the series view.
       The `has-cover` check is belt and braces — the chip already did it,
       but "these" must never mean a book that has a cover. */
    function _filteredIds() {
        return Array.prototype.filter
            .call(document.querySelectorAll('#bookTableBody tr'), function (row) {
                return row.dataset.filterHidden !== '1'
                    && (row.dataset.hasCover || '') === '0';
            })
            .map(function (row) { return row.dataset.itemId; })
            .filter(Boolean);
    }

    function refreshCoverBatchBanner() {
        var banner = _el('coverBatchBanner');
        if (!banner) return;
        if (!_coverFilterActive()) { banner.style.display = 'none'; return; }

        var count = _filteredIds().length;
        banner.style.display = count > 0 ? '' : 'none';
        var text = _el('coverBatchBannerText');
        if (text) {
            text.textContent = t('coverBatchBanner', '{count} books with no cover')
                .replace('{count}', count);
        }
    }

    /* ---------------------------------------------------------------- *
     * Running the search
     * ---------------------------------------------------------------- */

    function openCoverBatch() {
        var modal = _el('coverBatchModal');
        if (!modal) return;

        var ids = _filteredIds();
        if (ids.length === 0) return;
        _overflow = Math.max(0, ids.length - MAX_PER_RUN);
        ids = ids.slice(0, MAX_PER_RUN);
        _queued = ids.length;

        _rows = [];
        _noCover = 0;
        modal.style.display = 'flex';
        _el('coverBatchResults').innerHTML = '';
        _el('coverBatchNote').style.display = 'none';
        _el('coverBatchBarWrap').style.display = 'block';
        _el('coverBatchBar').style.width = '0%';
        _el('coverBatchAbort').style.display = '';
        _setStatus(t('coverBatchRunning', 'Looking for covers...'));
        _refreshApply();

        // dry_run: the stream previews only. Covers are applied per book
        // from the review grid below, never by the engine.
        var url = '/metadata/bulk/stream?item_ids=' + ids.join(',')
            + '&max_items=' + _queued
            + '&dry_run=1';

        _closeSource();
        _source = new EventSource(url);
        _source.onmessage = function (event) {
            var data;
            try { data = JSON.parse(event.data); } catch (e) { return; }
            _handleEvent(data);
        };
        _source.onerror = function () {
            _closeSource();
            _finish(t('coverBatchFailed', 'The cover search could not finish.'));
        };
    }

    function _handleEvent(data) {
        if (data.type === 'book_start' || data.type === 'book_done') {
            var done = data.type === 'book_done' ? data.index : (data.index - 1);
            var total = data.total || _queued;
            var pct = total ? Math.round((done / total) * 100) : 0;
            _el('coverBatchBar').style.width = pct + '%';
            _setStatus(t('coverBatchRunning', 'Looking for covers...') +
                ' ' + done + '/' + total);
        }

        if (data.type === 'book_done') {
            if (data.has_cover_fetched && data.cover_url_fetched) {
                _rows.push({
                    itemId: data.item_id,
                    title: data.title || String(data.item_id),
                    coverUrl: data.cover_url_fetched
                });
                _renderRows();
            } else {
                _noCover++;
            }
        } else if (data.type === 'done') {
            _closeSource();
            _finish(_rows.length === 0
                ? t('coverBatchNone', 'No covers were found.')
                : _rows.length + ' ' + t('coverBatchFound', 'covers to review'));
        } else if (data.type === 'aborted') {
            _closeSource();
            _finish(_rows.length === 0
                ? t('coverBatchNone', 'No covers were found.')
                : _rows.length + ' ' + t('coverBatchFound', 'covers to review'));
        } else if (data.type === 'error') {
            _closeSource();
            _finish(t('coverBatchFailed', 'The cover search could not finish.'));
        }
    }

    function _finish(status) {
        _el('coverBatchBarWrap').style.display = 'none';
        _el('coverBatchAbort').style.display = 'none';
        _setStatus(status);
        _renderNote();
        _refreshApply();
    }

    function _renderNote() {
        var note = _el('coverBatchNote');
        if (!note) return;
        var lines = [];
        if (_noCover > 0) {
            lines.push(_noCover + ' ' +
                t('coverBatchNotFound', 'books had no cover to fetch.'));
        }
        if (_overflow > 0) {
            lines.push(t('coverBatchLimited',
                'The run took the first {max}; {rest} are left. Run it again for those.')
                .replace('{max}', MAX_PER_RUN).replace('{rest}', _overflow));
        }
        note.textContent = lines.join(' ');
        note.style.display = lines.length ? '' : 'none';
    }

    function abortCoverBatch() {
        _closeSource();
        fetch('/metadata/abort', { method: 'POST' }).catch(function () {});
        _finish(_rows.length === 0
            ? t('coverBatchNone', 'No covers were found.')
            : _rows.length + ' ' + t('coverBatchFound', 'covers to review'));
    }

    function _closeSource() {
        if (_source) { try { _source.close(); } catch (e) {} _source = null; }
    }

    function closeCoverBatch() {
        _closeSource();
        var modal = _el('coverBatchModal');
        if (modal) modal.style.display = 'none';
    }

    /* ---------------------------------------------------------------- *
     * Review
     * ---------------------------------------------------------------- */

    function _renderRows() {
        var host = _el('coverBatchResults');
        if (!host) return;

        var cards = _rows.map(function (row, index) {
            var title = row.title.length > 40
                ? row.title.substring(0, 40) + '…'
                : row.title;
            return '<div class="cover-review-card">' +
                '<div class="cover-pair">' +
                  '<div class="cover-thumb"><div class="cover-placeholder">📖</div>' +
                    '<div class="cover-label">' + _esc(t('coverBatchNow', 'Now')) + '</div></div>' +
                  '<div class="cover-arrow">→</div>' +
                  '<div class="cover-thumb">' +
                    '<img src="' + _esc(row.coverUrl) + '" alt="" ' +
                      'onerror="this.outerHTML=\'<div class=&quot;cover-placeholder&quot;>&#9888;</div>\'">' +
                    '<div class="cover-label">' + _esc(t('coverBatchFetched', 'Fetched')) + '</div></div>' +
                '</div>' +
                '<div class="cover-meta"><label>' +
                  '<input type="checkbox" class="cover-batch-check" data-index="' + index + '" checked>' +
                  '<span title="' + _esc(row.title) + '">' + _esc(title) + '</span>' +
                '</label></div>' +
            '</div>';
        });

        host.innerHTML = '<div class="cover-review-grid">' + cards.join('') + '</div>';
        Array.prototype.forEach.call(
            host.querySelectorAll('.cover-batch-check'),
            function (cb) { cb.onchange = _refreshApply; }
        );
        _refreshApply();
    }

    function _ticked() {
        var host = _el('coverBatchResults');
        if (!host) return [];
        return Array.prototype.filter
            .call(host.querySelectorAll('.cover-batch-check'), function (cb) {
                return cb.checked;
            })
            .map(function (cb) { return _rows[parseInt(cb.dataset.index, 10)]; })
            .filter(Boolean);
    }

    function _refreshApply() {
        var count = _ticked().length;
        var btn = _el('coverBatchApply');
        if (btn) {
            btn.disabled = count === 0;
            btn.textContent = count === 0
                ? t('apply', 'Apply')
                : t('apply', 'Apply') + ' (' + count + ')';
        }
        // `cover_path` is a device content column, so a new cover reloads
        // the book on a synced Kobo. Say it rather than hide it.
        var kobo = _el('coverBatchKobo');
        if (kobo) {
            kobo.style.display = count === 0 ? 'none' : '';
            kobo.textContent = count + ' ' +
                t('coverBatchReloadOnKobo', 'books reload on Kobo.');
        }
    }

    /* ---------------------------------------------------------------- *
     * Applying — one book at a time
     * ---------------------------------------------------------------- */

    function applyCoverBatch() {
        var ticked = _ticked();
        if (ticked.length === 0) return;

        var btn = _el('coverBatchApply');
        if (btn) btn.disabled = true;
        _el('coverBatchAbort').style.display = 'none';
        _el('coverBatchBarWrap').style.display = 'block';
        _el('coverBatchBar').style.width = '0%';

        var saved = 0;
        var failed = 0;

        function _step(index) {
            if (index >= ticked.length) {
                var msg = saved + ' ' + t('coverBatchSaved', 'covers saved');
                if (failed) {
                    msg += ' · ' + failed + ' ' +
                        t('coverBatchErrors', 'could not be saved');
                }
                _setStatus(msg);
                _el('coverBatchBarWrap').style.display = 'none';
                // The applied books leave the filter; reload so the table,
                // the chip and the traffic light agree again.
                setTimeout(function () { window.location.reload(); }, 900);
                return;
            }

            var row = ticked[index];
            _setStatus(t('coverBatchSaving', 'Saving covers...') +
                ' ' + (index + 1) + '/' + ticked.length);
            _el('coverBatchBar').style.width =
                Math.round((index / ticked.length) * 100) + '%';

            fetch('/metadata/' + row.itemId + '/cover/apply-json', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cover_url: row.coverUrl, source: 'batch' })
            })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data && data.ok) saved++; else failed++;
            })
            .catch(function () { failed++; })
            .then(function () { _step(index + 1); });
        }

        _step(0);
    }

    window.openCoverBatch = openCoverBatch;
    window.closeCoverBatch = closeCoverBatch;
    window.abortCoverBatch = abortCoverBatch;
    window.applyCoverBatch = applyCoverBatch;
    window._refreshCoverBatchBanner = refreshCoverBatchBanner;

    refreshCoverBatchBanner();
})(window, document);
