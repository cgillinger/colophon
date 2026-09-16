/* Colophon – language check
 *
 * Reads the text out of every EPUB, compares it with the stored language,
 * and lists only the books worth a look: no language recorded, or a
 * recorded language the text disagrees with.
 *
 * The stream previews. Nothing is written until the user ticks rows and
 * presses Apply — and writing the files themselves is a separate, visible
 * choice. It is pre-ticked here, and only here, because the Kobo picks its
 * dictionary and hyphenation from this field, so the re-download is the
 * point rather than a side effect.
 */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    function t(key, fallback) { return _i18n[key] || fallback; }

    var _source = null;
    var _rows = [];

    function _el(id) { return document.getElementById(id); }
    function _setStatus(text) {
        var el = _el('langCheckStatus');
        if (el) el.textContent = text;
    }

    function _esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/[']/g, '&#39;');
    }

    /* ---------------------------------------------------------------- *
     * Rendering
     * ---------------------------------------------------------------- */

    function _renderRows() {
        var host = _el('langCheckResults');
        if (!host) return;
        if (_rows.length === 0) { host.innerHTML = ''; return; }

        var html = '<table class="lang-table"><thead><tr>' +
            '<th style="width:34px;"></th>' +
            '<th>' + t('book', 'Book') + '</th>' +
            '<th>' + t('languageStored', 'Recorded') + '</th>' +
            '<th></th>' +
            '<th>' + t('languageDetected', 'Detected') + '</th>' +
            '<th>' + t('languageConfidence', 'Confidence') + '</th>' +
            '</tr></thead><tbody>';

        _rows.forEach(function (row, index) {
            // Nothing recorded and both samples agreed: safe to tick by
            // default, there is no human decision being overwritten. A
            // disagreement is different — someone may have set it on
            // purpose — so it starts unticked and the user opts in.
            var preTicked = row.status === 'missing' && row.agree;
            html +=
                '<tr' + (row.agree ? '' : ' class="lang-uncertain"') + '>' +
                  '<td><input type="checkbox" class="lang-row-check" ' +
                      'data-index="' + index + '"' + (preTicked ? ' checked' : '') + '></td>' +
                  '<td><div class="lang-title">' + _esc(row.title) + '</div>' +
                      '<div class="lang-author">' + _esc(row.author) + '</div></td>' +
                  '<td>' + (row.stored ? _esc(row.stored) : '<span class="lang-none">—</span>') + '</td>' +
                  '<td class="lang-arrow">&rarr;</td>' +
                  '<td><strong>' + _esc(row.detected) + '</strong></td>' +
                  '<td>' + Math.round((row.prob || 0) * 100) + '%' +
                      (row.agree ? '' : ' <span class="lang-warn" title="' +
                        _esc(t('languageSamplesDisagree', 'The two samples disagreed')) +
                        '">&#9888;</span>') +
                  '</td>' +
                '</tr>';
        });

        host.innerHTML = html + '</tbody></table>';
        Array.prototype.forEach.call(
            host.querySelectorAll('.lang-row-check'),
            function (cb) { cb.onchange = _refreshApply; }
        );
        _refreshApply();
    }

    function _ticked() {
        var host = _el('langCheckResults');
        if (!host) return [];
        return Array.prototype.filter
            .call(host.querySelectorAll('.lang-row-check'), function (cb) {
                return cb.checked;
            })
            .map(function (cb) { return _rows[parseInt(cb.dataset.index, 10)]; })
            .filter(Boolean);
    }

    function _refreshApply() {
        var count = _ticked().length;
        var btn = _el('langCheckApply');
        var wrap = _el('langCheckWriteWrap');
        var label = _el('langCheckWriteLabel');
        if (btn) {
            btn.disabled = count === 0;
            btn.textContent = count === 0
                ? t('apply', 'Apply')
                : t('apply', 'Apply') + ' (' + count + ')';
        }
        if (wrap) wrap.style.display = count === 0 ? 'none' : '';
        if (label) {
            // Say the cost out loud: writing the files is what makes a
            // synced Kobo archive and re-download the book.
            label.textContent = t('languageWriteFiles', 'Write to the files too') +
                ' (' + count + ' ' + t('languageReloadOnKobo', 'reload on Kobo') + ')';
        }
    }

    /* ---------------------------------------------------------------- *
     * Running the check
     * ---------------------------------------------------------------- */

    function openLanguageCheck(itemIds) {
        var modal = _el('languageCheckModal');
        if (!modal) return;
        modal.style.display = 'flex';

        _rows = [];
        _el('langCheckResults').innerHTML = '';
        _el('langCheckFootnote').textContent = '';
        _el('langCheckBarWrap').style.display = 'block';
        _el('langCheckBar').style.width = '0%';
        _setStatus(t('languageCheckRunning', 'Reading the books...'));
        _refreshApply();

        var url = '/metadata/language-check/stream';
        if (itemIds && itemIds.length) url += '?item_ids=' + itemIds.join(',');

        _closeSource();
        _source = new EventSource(url);
        _source.onmessage = function (event) {
            var data;
            try { data = JSON.parse(event.data); } catch (e) { return; }
            _handleEvent(data);
        };
        _source.onerror = function () {
            _closeSource();
            _el('langCheckBarWrap').style.display = 'none';
            _setStatus(t('languageCheckFailed', 'The check could not finish.'));
        };
    }

    function _handleEvent(data) {
        if (data.type === 'progress') {
            var pct = data.total ? Math.round((data.done / data.total) * 100) : 0;
            _el('langCheckBar').style.width = pct + '%';
            _setStatus(t('languageCheckRunning', 'Reading the books...') +
                ' ' + data.done + '/' + data.total);
        } else if (data.type === 'finding') {
            _rows.push(data);
            _renderRows();
        } else if (data.type === 'done') {
            _closeSource();
            _el('langCheckBarWrap').style.display = 'none';
            _setStatus(_rows.length === 0
                ? t('languageCheckAllGood', 'Every book agrees with its recorded language.')
                : _rows.length + ' ' + t('languageCheckFound', 'books to look at'));
            if (data.unreadable) {
                _el('langCheckFootnote').textContent = data.unreadable + ' ' +
                    t('languageCheckUnreadable', 'files could not be read (PDF, MOBI or no text).');
            }
            _refreshApply();
        } else if (data.type === 'error') {
            _closeSource();
            _el('langCheckBarWrap').style.display = 'none';
            _setStatus(t('languageCheckFailed', 'The check could not finish.'));
        }
    }

    function _closeSource() {
        if (_source) { _source.close(); _source = null; }
    }

    function closeLanguageCheck() {
        _closeSource();
        var modal = _el('languageCheckModal');
        if (modal) modal.style.display = 'none';
    }

    /* ---------------------------------------------------------------- *
     * Applying
     * ---------------------------------------------------------------- */

    function applyLanguageCheck() {
        var ticked = _ticked();
        if (ticked.length === 0) return;

        var writeFiles = _el('langCheckWriteFiles').checked;
        var btn = _el('langCheckApply');
        btn.disabled = true;
        _setStatus(t('saving', 'Saving...'));

        fetch('/metadata/language-check/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                write_files: writeFiles,
                changes: ticked.map(function (row) {
                    return { item_id: row.item_id, code: row.detected };
                })
            })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data.ok) throw new Error('failed');
            var msg = data.updated + ' ' + t('languageCheckUpdated', 'books updated');
            if (data.errors && data.errors.length) {
                msg += ' · ' + data.errors.length + ' ' +
                    t('languageCheckErrors', 'could not be written');
            }
            _setStatus(msg);
            // Applied rows are no longer findings; reload so the table,
            // the counters and the filters all agree again.
            setTimeout(function () { window.location.reload(); }, 900);
        })
        .catch(function () {
            btn.disabled = false;
            _setStatus(t('languageCheckFailed', 'The check could not finish.'));
        });
    }

    window.openLanguageCheck = openLanguageCheck;
    window.closeLanguageCheck = closeLanguageCheck;
    window.applyLanguageCheck = applyLanguageCheck;
})(window, document);
