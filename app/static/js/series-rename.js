/* Colophon – rename a series
 *
 * Renames the series text across every book in a group; each book keeps
 * its own series_index (this only changes the name). series is a
 * device-content column, so a synced Kobo re-downloads the books even
 * when "Write to the files too" is off — the modal note says so plainly
 * rather than hiding it.
 */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    function t(key, fallback) { return _i18n[key] || fallback; }

    var _itemIds = [];

    function _el(id) { return document.getElementById(id); }

    function _setStatus(text) {
        var el = _el('seriesRenameStatus');
        if (el) el.textContent = text;
    }

    function openSeriesRename(itemIds, seriesName) {
        var modal = _el('seriesRenameModal');
        if (!modal) return;
        _itemIds = itemIds || [];

        var input = _el('seriesRenameInput');
        var count = _el('seriesRenameCount');
        var note = _el('seriesRenameNote');
        var writeLabel = _el('seriesRenameWriteLabel');
        var writeFiles = _el('seriesRenameWriteFiles');

        if (count) count.textContent = t('seriesRenameCount', 'N books').replace('N', _itemIds.length);
        if (note) note.textContent = t('seriesOrderKoboNote', 'A series change reloads the book on a synced Kobo.');
        if (writeLabel) writeLabel.textContent = t('seriesOrderWriteFiles', 'Write to the files too');
        if (writeFiles) writeFiles.checked = false;
        _setStatus('');

        modal.style.display = 'flex';

        if (input) {
            input.value = seriesName || '';
            input.focus();
            input.select();
        }
    }
    window.openSeriesRename = openSeriesRename;

    function closeSeriesRename() {
        var modal = _el('seriesRenameModal');
        if (modal) modal.style.display = 'none';
    }
    window.closeSeriesRename = closeSeriesRename;

    function applySeriesRename() {
        var input = _el('seriesRenameInput');
        var name = input ? input.value.trim() : '';
        if (!name) {
            _setStatus(t('seriesRenameEmpty', 'Give the series a name.'));
            return;
        }

        var btn = _el('seriesRenameApply');
        var writeFiles = _el('seriesRenameWriteFiles').checked;
        if (btn) btn.disabled = true;
        _setStatus(t('saving', 'Saving...'));

        fetch('/metadata/series/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ item_ids: _itemIds, series: name, write_files: writeFiles })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data.ok) throw new Error('failed');
            var msg = data.updated + ' ' + t('seriesOrderUpdated', 'books updated');
            if (data.errors && data.errors.length) {
                msg += ' · ' + data.errors.length + ' ' +
                    t('seriesOrderErrors', 'could not be written');
            }
            _setStatus(msg);
            setTimeout(function () { window.location.reload(); }, 900);
        })
        .catch(function () {
            if (btn) btn.disabled = false;
            _setStatus(t('seriesRenameFailed', 'The rename failed.'));
        });
    }
    window.applySeriesRename = applySeriesRename;

    document.addEventListener('DOMContentLoaded', function () {
        var input = _el('seriesRenameInput');
        if (!input) return;
        input.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') {
                ev.preventDefault();
                applySeriesRename();
            } else if (ev.key === 'Escape') {
                closeSeriesRename();
            }
        });
    });
})(window, document);
