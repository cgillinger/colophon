/* ------------------------------------------------------------------ *
 * duplicates.js — Duplicate-detection modal
 *
 * Owns: the #duplicatesModal flow — fetches /metadata/duplicates,
 * renders groups, lets the user pick which copies to delete.
 *
 * Reads i18n strings from window.__colophonConfig.i18n (dup* keys).
 *
 * Exposes globals consumed by the template (onclick / onchange):
 *   openDuplicatesModal, closeDuplicatesModal,
 *   _dupOnCheckChange, _dupSkipGroup, _dupDeleteSelected
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    var _dupGroups = [];

    function openDuplicatesModal() {
        var modal = document.getElementById('duplicatesModal');
        var groupsEl = document.getElementById('dupGroups');
        var headerEl = document.getElementById('dupHeader');
        var feedback = document.getElementById('dupFeedback');
        feedback.style.display = 'none';
        modal.style.display = 'flex';
        headerEl.textContent = _i18n.dupSearching;
        groupsEl.innerHTML = '<div class="dup-empty"><i class="ti ti-loader ti-rotate"></i> ' + _i18n.dupSearching + '</div>';

        fetch('/metadata/duplicates', {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _dupGroups = (data && data.groups) || [];
                _renderDuplicateGroups();
            })
            .catch(function (err) {
                groupsEl.innerHTML = '';
                feedback.className = 'modal-feedback modal-feedback-error';
                feedback.textContent = _i18n.dupErrorLoading + ' ' + err;
                feedback.style.display = 'block';
            });
    }
    window.openDuplicatesModal = openDuplicatesModal;

    function closeDuplicatesModal() {
        document.getElementById('duplicatesModal').style.display = 'none';
    }
    window.closeDuplicatesModal = closeDuplicatesModal;

    var _modalRoot = document.getElementById('duplicatesModal');
    if (_modalRoot) {
        _modalRoot.addEventListener('click', function (e) {
            if (e.target === this) closeDuplicatesModal();
        });
    }

    function _escDup(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _dupBadgeLabel(type, confidence, detail) {
        if (type === 'isbn')        return _i18n.dupSameIsbn;
        if (type === 'exact_title') return _i18n.dupSameTitle;
        var pct = Math.round((confidence || 0) * 100);
        return _i18n.dupSimilarTitle + ' (' + pct + '%)';
    }

    function _formatSize(bytes) {
        if (!bytes) return '';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    /* Shorten a long file path so the dup-modal stays scannable.
       Keeps the last two path segments (parent dir + filename), e.g.
       "/books/Year's Best SF/2020/file.epub" → "2020/file.epub".
       The full path lives in the title attribute for hover/inspection. */
    function _dupShortPath(p) {
        if (!p) return '';
        var parts = String(p).split('/').filter(function (s) { return s.length > 0; });
        if (parts.length <= 2) return p;
        return '…/' + parts.slice(-2).join('/');
    }

    function _renderDuplicateGroups() {
        var groupsEl = document.getElementById('dupGroups');
        var headerEl = document.getElementById('dupHeader');

        if (!_dupGroups.length) {
            headerEl.textContent = '';
            groupsEl.innerHTML = '<div class="dup-empty">' + _i18n.dupNoDuplicates + '</div>';
            return;
        }

        headerEl.textContent = _i18n.dupPotentialGroups + ': ' + _dupGroups.length;

        var html = '';
        for (var gi = 0; gi < _dupGroups.length; gi++) {
            var g = _dupGroups[gi];
            var badge = _dupBadgeLabel(g.match_type, g.confidence, g.match_detail);
            html += '<div class="dup-group" data-group-index="' + gi + '">';
            html += '<div class="dup-group-header">';
            html +=   '<span class="dup-badge ' + _escDup(g.match_type) + '">' + _escDup(badge) + '</span>';
            if (g.match_detail) {
                html += '<span class="dup-group-detail">' + _escDup(g.match_detail) + '</span>';
            }
            html += '</div>';

            for (var ii = 0; ii < g.items.length; ii++) {
                var it = g.items[ii];
                var coverHtml = it.cover_url
                    ? '<img src="' + _escDup(it.cover_url) + '" alt="" loading="lazy" onerror="this.parentNode.innerHTML=\'<i class=\\\'ti ti-book\\\'></i>\'">'
                    : '<i class="ti ti-book"></i>';
                var extras = [];
                if (it.file_ext) extras.push(it.file_ext.toUpperCase());
                if (it.file_size) extras.push(_formatSize(it.file_size));
                if (it.isbn) extras.push('ISBN ' + it.isbn);
                if (it.series) {
                    var s = it.series + (it.series_index ? ' #' + it.series_index : '');
                    extras.push(s);
                }
                if (it.published_date) extras.push(it.published_date);

                var fullPath = it.filepath || it.filename || '';
                var shortPath = _dupShortPath(fullPath);

                html += '<div class="dup-item" data-item-id="' + it.id + '">';
                html +=   '<input type="checkbox" class="dup-check" data-group-index="' + gi + '" data-item-id="' + it.id + '" onchange="_dupOnCheckChange(' + gi + ')">';
                html +=   '<div class="dup-cover">' + coverHtml + '</div>';
                html +=   '<div class="dup-meta">';
                html +=     '<div class="dup-title">' + _escDup(it.title) + '</div>';
                html +=     '<div class="dup-author">' + _escDup(it.author) + '</div>';
                html +=     '<div class="dup-path" title="' + _escDup(fullPath) + '">' + _escDup(shortPath) + '</div>';
                html +=     '<div class="dup-extras">' + _escDup(extras.join(' · ')) + '</div>';
                html +=   '</div>';
                html += '</div>';
            }

            html += '<div class="dup-actions">';
            html +=   '<button type="button" class="btn ghost" onclick="_dupSkipGroup(' + gi + ')">' + _i18n.dupSkipNotDuplicates + '</button>';
            html +=   '<button type="button" class="btn-danger small" data-dup-delete-btn="' + gi + '" onclick="_dupDeleteSelected(' + gi + ')" disabled>';
            html +=     '<i class="ti ti-trash"></i> ' + _i18n.dupDeleteSelected;
            html +=   '</button>';
            html += '</div>';
            html += '</div>';
        }
        groupsEl.innerHTML = html;
    }

    function _dupOnCheckChange(groupIndex) {
        var groupEl = document.querySelector('.dup-group[data-group-index="' + groupIndex + '"]');
        if (!groupEl) return;
        var checks = groupEl.querySelectorAll('.dup-check');
        var liveItems = [];
        var checkedItems = [];
        for (var i = 0; i < checks.length; i++) {
            var row = checks[i].closest('.dup-item');
            if (row && row.classList.contains('removed')) continue;
            liveItems.push(checks[i]);
            if (checks[i].checked) checkedItems.push(checks[i]);
        }
        var btn = groupEl.querySelector('[data-dup-delete-btn]');
        if (!btn) return;
        var anyChecked = checkedItems.length > 0;
        var allChecked = checkedItems.length === liveItems.length;
        btn.disabled = !anyChecked || allChecked;
        if (allChecked && liveItems.length > 0) {
            btn.title = _i18n.dupAtLeastOneKept;
        } else {
            btn.title = '';
        }
    }
    window._dupOnCheckChange = _dupOnCheckChange;

    function _dupSkipGroup(groupIndex) {
        var groupEl = document.querySelector('.dup-group[data-group-index="' + groupIndex + '"]');
        if (groupEl && groupEl.parentNode) groupEl.parentNode.removeChild(groupEl);
        var remaining = document.querySelectorAll('#dupGroups .dup-group').length;
        var headerEl = document.getElementById('dupHeader');
        if (remaining === 0) {
            headerEl.textContent = '';
            document.getElementById('dupGroups').innerHTML = '<div class="dup-empty">' + _i18n.dupNoDuplicates + '</div>';
        } else {
            headerEl.textContent = _i18n.dupPotentialGroups + ': ' + remaining;
        }
    }
    window._dupSkipGroup = _dupSkipGroup;

    function _dupDeleteSelected(groupIndex) {
        var groupEl = document.querySelector('.dup-group[data-group-index="' + groupIndex + '"]');
        if (!groupEl) return;
        var checks = groupEl.querySelectorAll('.dup-check:checked');
        var toDelete = [];
        for (var i = 0; i < checks.length; i++) {
            var row = checks[i].closest('.dup-item');
            if (row && row.classList.contains('removed')) continue;
            toDelete.push({id: parseInt(checks[i].dataset.itemId, 10), row: row});
        }
        if (!toDelete.length) return;

        var msg = toDelete.length === 1
            ? _i18n.dupConfirmDeleteOne
            : _i18n.dupConfirmDeleteMany.replace('{count}', toDelete.length);
        if (!confirm(msg)) return;

        var btn = groupEl.querySelector('[data-dup-delete-btn]');
        if (btn) { btn.disabled = true; btn.classList.add('btn-save-saving'); }

        var promises = toDelete.map(function (entry) {
            return fetch('/metadata/delete-item/' + entry.id, {method: 'DELETE'})
                .then(function (r) { return r.json().then(function (j) { return {ok: r.ok && j.ok, entry: entry, data: j}; }); })
                .catch(function (err) { return {ok: false, entry: entry, data: {error: String(err)}}; });
        });

        Promise.all(promises).then(function (results) {
            var failures = [];
            results.forEach(function (res) {
                if (res.ok) {
                    if (res.entry.row) res.entry.row.classList.add('removed');
                    var cb = res.entry.row && res.entry.row.querySelector('.dup-check');
                    if (cb) { cb.checked = false; cb.disabled = true; }
                    var tableRow = document.querySelector('#bookTableBody tr[data-item-id="' + res.entry.id + '"]');
                    if (tableRow && tableRow.parentNode) tableRow.parentNode.removeChild(tableRow);
                } else {
                    failures.push(res);
                }
            });

            if (btn) { btn.disabled = false; btn.classList.remove('btn-save-saving'); }

            var liveRows = groupEl.querySelectorAll('.dup-item:not(.removed)');
            if (liveRows.length < 2) {
                groupEl.classList.add('resolved');
            }
            _dupOnCheckChange(groupIndex);

            if (failures.length) {
                var feedback = document.getElementById('dupFeedback');
                feedback.className = 'modal-feedback modal-feedback-error';
                feedback.textContent = _i18n.dupCouldNotDelete.replace('{count}', failures.length);
                feedback.style.display = 'block';
            }
        });
    }
    window._dupDeleteSelected = _dupDeleteSelected;
})(window, document);
