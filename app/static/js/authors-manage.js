/* ------------------------------------------------------------------ *
 * authors-manage.js — the "Manage authors" page (/authors)
 *
 * Inline actions on the registry table: confirm / rename / merge /
 * verify-against-Wikidata / delete-unused, plus one-click merges and
 * the AI adjudicator on the "Likely duplicates" pairs. Rename and
 * merge cascade server-side (all linked books are relabelled).
 *
 * Reads i18n strings from window.__authorsConfig.i18n (set by
 * authors.html — static JS must stay Jinja-free).
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__authorsConfig && window.__authorsConfig.i18n) || {};

    function _fmt(key, vars, fallback) {
        var s = _i18n[key] || fallback || key;
        Object.keys(vars || {}).forEach(function (k) {
            s = s.split('{' + k + '}').join(vars[k]);
        });
        return s;
    }

    function _post(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        }).then(function (r) { return r.json(); });
    }

    function _rowName(tr) {
        var cell = tr.querySelector('.author-name');
        return cell ? cell.childNodes[0].textContent.trim() : '';
    }

    /* -------------------- registry table actions -------------------- */

    function _confirm(tr, id) {
        _post('/authors/' + id + '/confirm').then(function (b) {
            if (b.ok) location.reload();
            else alert(_i18n.actionFailed || 'The action failed.');
        });
    }

    function _rename(tr, id) {
        var name = _rowName(tr);
        var entered = prompt(_fmt('renamePrompt', { name: name }, 'New name for “{name}”:'), name);
        if (!entered || entered.trim() === '' || entered.trim() === name) return;
        _post('/authors/' + id + '/rename', { name: entered.trim() }).then(function (b) {
            if (b.ok) location.reload();
            else if (b.error === 'name_taken') alert(_i18n.nameTaken || 'Name already taken — merge instead.');
            else alert(_i18n.actionFailed || 'The action failed.');
        });
    }

    function _merge(tr, id) {
        var name = _rowName(tr);
        var entered = prompt(_fmt('mergePrompt', { name: name }, 'Merge “{name}” into which author?'));
        if (!entered || !entered.trim()) return;
        var typed = entered.trim();
        fetch('/authors/search?q=' + encodeURIComponent(typed))
            .then(function (r) { return r.json(); })
            .then(function (b) {
                var target = (b.ok && b.authors || []).filter(function (a) { return a.id !== id; })[0];
                if (!target) {
                    alert(_fmt('mergeNotFound', { name: typed }, 'No registered author matches “{name}”.'));
                    return;
                }
                _mergeInto(id, name, target.id, target.name, tr);
            });
    }

    function _mergeInto(sourceId, sourceName, targetId, targetName, tr) {
        var count = '?';
        var countCell = tr && tr.querySelector('td.count');
        if (countCell) count = countCell.textContent.trim();
        var msg = _fmt('mergeConfirm',
            { count: count, source: sourceName, target: targetName },
            'Move {count} books from “{source}” to “{target}”?');
        if (!window.confirm(msg)) return;
        _post('/authors/' + sourceId + '/merge', { target_id: targetId }).then(function (b) {
            if (b.ok) location.reload();
            else alert(_i18n.actionFailed || 'The action failed.');
        });
    }

    function _verify(tr, id, btn) {
        var original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="ti ti-loader-2 upload-spin"></i> ' + (_i18n.verifying || 'Looking up…');
        _post('/authors/' + id + '/verify').then(function (b) {
            if (b.ok && b.matched) { location.reload(); return; }
            btn.disabled = false;
            btn.innerHTML = original;
            alert(b.ok ? (_i18n.verifyNoMatch || 'No confident match found in Wikidata.')
                       : (_i18n.actionFailed || 'The action failed.'));
        }).catch(function () {
            btn.disabled = false;
            btn.innerHTML = original;
            alert(_i18n.actionFailed || 'The action failed.');
        });
    }

    /* -------------------- split dialog -------------------- *
     * One free-text field per person (prefilled from the server's
     * separator guess). Typed names resolve server-side against the
     * registry (layers 1-2), so existing entries are reused; the split
     * is remembered as rules keyed on the fused string. */

    var _splitState = null; // { id, name }

    function _splitDialog() { return document.getElementById('splitDialog'); }

    function _splitAddField(value) {
        var fields = document.getElementById('splitDialogFields');
        if (!fields) return;
        var row = document.createElement('div');
        row.className = 'split-field-row';
        row.innerHTML =
            '<input type="text" autocomplete="off">' +
            '<button type="button" class="split-field-remove" title="&times;">' +
                '<i class="ti ti-x"></i></button>';
        row.querySelector('input').value = value || '';
        row.querySelector('.split-field-remove').addEventListener('click', function () {
            if (fields.children.length > 2) row.remove();
        });
        fields.appendChild(row);
    }

    /* "No, this is one person" — permanently dismiss the looks-multi
       badge (sort-form names trip the comma heuristic by design). */
    function _dismissSplit(tr, id) {
        var name = _rowName(tr);
        if (!window.confirm(_fmt('dismissSplitConfirm', { name: name },
                '“{name}” is one person — hide the split badge?'))) return;
        _post('/authors/' + id + '/dismiss-split').then(function (b) {
            if (!b.ok) { alert(_i18n.actionFailed || 'The action failed.'); return; }
            var flag = tr.querySelector('.multi-flag');
            if (flag) flag.remove();
        });
    }

    function _split(tr, id, btn) {
        var dlg = _splitDialog();
        if (!dlg || typeof dlg.showModal !== 'function') return;
        var name = _rowName(tr);
        _splitState = { id: id, name: name };

        var source = document.getElementById('splitDialogSource');
        if (source) source.textContent = name;
        var fields = document.getElementById('splitDialogFields');
        if (fields) fields.innerHTML = '';

        var guess = [];
        try {
            guess = JSON.parse(btn.dataset.splitGuess || '[]');
        } catch (e) { /* fall through to empty fields */ }
        if (!guess || guess.length < 2) guess = ['', ''];
        guess.forEach(function (part) { _splitAddField(part); });

        dlg.showModal();
        var first = fields && fields.querySelector('input');
        if (first) first.focus();
    }

    (function _bindSplitDialog() {
        var dlg = _splitDialog();
        if (!dlg) return;
        var addBtn = document.getElementById('splitDialogAdd');
        var cancelBtn = document.getElementById('splitDialogCancel');
        var saveBtn = document.getElementById('splitDialogSave');
        if (addBtn) addBtn.addEventListener('click', function () { _splitAddField(''); });
        if (cancelBtn) cancelBtn.addEventListener('click', function () { dlg.close(); });
        if (saveBtn) saveBtn.addEventListener('click', function () {
            if (!_splitState) return;
            var names = Array.prototype.map.call(
                dlg.querySelectorAll('#splitDialogFields input'),
                function (inp) { return inp.value.trim(); }
            ).filter(Boolean);
            if (names.length < 2) {
                alert(_i18n.splitNeedTwo || 'Enter at least two author names.');
                return;
            }
            var msg = _fmt('splitConfirm',
                { name: _splitState.name, parts: names.join(' + ') },
                'Split “{name}” into {parts}?');
            if (!window.confirm(msg)) return;
            saveBtn.disabled = true;
            _post('/authors/' + _splitState.id + '/split', {
                parts: names.map(function (n) { return { name: n }; })
            }).then(function (b) {
                saveBtn.disabled = false;
                if (b.ok) { dlg.close(); location.reload(); }
                else alert(_i18n.actionFailed || 'The action failed.');
            }).catch(function () {
                saveBtn.disabled = false;
                alert(_i18n.actionFailed || 'The action failed.');
            });
        });
    })();

    function _delete(tr, id) {
        var name = _rowName(tr);
        if (!window.confirm(_fmt('deleteConfirm', { name: name }, 'Remove the unused entry “{name}”?'))) return;
        _post('/authors/' + id + '/delete').then(function (b) {
            if (b.ok) location.reload();
            else alert(_i18n.actionFailed || 'The action failed.');
        });
    }

    var table = document.getElementById('authorsTable');
    if (table) {
        table.addEventListener('click', function (e) {
            var btn = e.target.closest('button[data-act]');
            if (!btn) return;
            var tr = btn.closest('tr');
            var id = parseInt(tr.dataset.authorId, 10);
            var act = btn.dataset.act;
            if (act === 'confirm') _confirm(tr, id);
            else if (act === 'rename') _rename(tr, id);
            else if (act === 'merge') _merge(tr, id);
            else if (act === 'split') _split(tr, id, btn);
            else if (act === 'dismiss-split') _dismissSplit(tr, id);
            else if (act === 'verify') _verify(tr, id, btn);
            else if (act === 'delete') _delete(tr, id);
        });
    }

    /* -------------------- quick filter -------------------- */

    var filter = document.getElementById('authorsFilter');
    var unconfirmedOnly = document.getElementById('authorsUnconfirmedOnly');
    if (table && (filter || unconfirmedOnly)) {
        var applyFilter = function () {
            var q = filter ? filter.value.toLowerCase().trim() : '';
            var tentativeOnly = unconfirmedOnly && unconfirmedOnly.checked;
            table.querySelectorAll('tbody tr').forEach(function (tr) {
                var matchesText = !q || (tr.dataset.name || '').indexOf(q) !== -1;
                var matchesStatus = !tentativeOnly || tr.dataset.source === 'tentative';
                tr.style.display = (matchesText && matchesStatus) ? '' : 'none';
            });
            if (typeof _refreshBulkBar === 'function') _refreshBulkBar();
        };
        if (filter) filter.addEventListener('input', applyFilter);
        if (unconfirmedOnly) unconfirmedOnly.addEventListener('change', applyFilter);
    }

    /* -------------------- bulk selection + confirm -------------------- */

    var bulkBar = document.getElementById('authorsBulkBar');
    var bulkCount = document.getElementById('authorsBulkCount');
    var selectAll = document.getElementById('authorsSelectAll');

    function _visibleRows() {
        if (!table) return [];
        return Array.prototype.filter.call(
            table.querySelectorAll('tbody tr'),
            function (tr) { return tr.style.display !== 'none'; }
        );
    }

    function _checkedRows() {
        if (!table) return [];
        return Array.prototype.filter.call(
            table.querySelectorAll('tbody tr'),
            function (tr) {
                var cb = tr.querySelector('.author-select');
                return cb && cb.checked;
            }
        );
    }

    function _refreshBulkBar() {
        var checked = _checkedRows();
        if (bulkBar) bulkBar.hidden = checked.length === 0;
        if (bulkCount) bulkCount.textContent = _fmt('selectedCount', { count: checked.length }, '{count} selected');
        if (selectAll) {
            var visible = _visibleRows();
            var visibleChecked = visible.filter(function (tr) {
                var cb = tr.querySelector('.author-select');
                return cb && cb.checked;
            });
            selectAll.checked = visible.length > 0 && visibleChecked.length === visible.length;
            selectAll.indeterminate = visibleChecked.length > 0 && visibleChecked.length < visible.length;
        }
    }

    if (table && bulkBar) {
        table.addEventListener('change', function (e) {
            if (e.target && e.target.classList.contains('author-select')) _refreshBulkBar();
        });
    }

    if (selectAll) {
        selectAll.addEventListener('change', function () {
            _visibleRows().forEach(function (tr) {
                var cb = tr.querySelector('.author-select');
                if (cb) cb.checked = selectAll.checked;
            });
            _refreshBulkBar();
        });
    }

    var bulkClear = document.getElementById('authorsBulkClear');
    if (bulkClear) {
        bulkClear.addEventListener('click', function () {
            _checkedRows().forEach(function (tr) {
                var cb = tr.querySelector('.author-select');
                if (cb) cb.checked = false;
            });
            _refreshBulkBar();
        });
    }

    var bulkConfirm = document.getElementById('authorsBulkConfirm');
    if (bulkConfirm) {
        bulkConfirm.addEventListener('click', function () {
            var tentative = _checkedRows().filter(function (tr) {
                return tr.dataset.source === 'tentative';
            });
            if (!tentative.length) {
                alert(_i18n.bulkNoTentative || 'None of the selected entries are unconfirmed.');
                return;
            }
            var msg = _fmt('bulkConfirmPrompt', { count: tentative.length },
                'Confirm {count} selected authors?');
            if (!window.confirm(msg)) return;
            var ids = tentative.map(function (tr) { return parseInt(tr.dataset.authorId, 10); });
            bulkConfirm.disabled = true;
            _post('/authors/confirm-bulk', { ids: ids }).then(function (b) {
                if (b.ok) location.reload();
                else { bulkConfirm.disabled = false; alert(_i18n.actionFailed || 'The action failed.'); }
            }).catch(function () {
                bulkConfirm.disabled = false;
                alert(_i18n.actionFailed || 'The action failed.');
            });
        });
    }

    /* -------------------- duplicate pairs -------------------- */

    document.querySelectorAll('.dup-pair').forEach(function (pair) {
        var aId = parseInt(pair.dataset.aId, 10);
        var bId = parseInt(pair.dataset.bId, 10);
        var names = pair.querySelectorAll('.dup-name');
        var aName = names[0] ? names[0].textContent.trim() : '';
        var bName = names[1] ? names[1].textContent.trim() : '';

        pair.addEventListener('click', function (e) {
            var btn = e.target.closest('button[data-act]');
            if (!btn) return;
            if (btn.dataset.act === 'merge-into-a') {
                _mergeInto(bId, bName, aId, aName, null);
            } else if (btn.dataset.act === 'merge-into-b') {
                _mergeInto(aId, aName, bId, bName, null);
            } else if (btn.dataset.act === 'adjudicate') {
                var verdictEl = pair.querySelector('[data-verdict]');
                var original = btn.innerHTML;
                btn.disabled = true;
                btn.innerHTML = '<i class="ti ti-loader-2 upload-spin"></i> ' + (_i18n.aiThinking || 'Asking…');
                _post('/authors/adjudicate', { a_id: aId, b_id: bId }).then(function (b) {
                    btn.disabled = false;
                    btn.innerHTML = original;
                    if (!b.ok) {
                        if (verdictEl) verdictEl.textContent =
                            b.error === 'not_configured'
                                ? (_i18n.aiUnavailable || 'AI is not configured.')
                                : (_i18n.actionFailed || 'The action failed.');
                        return;
                    }
                    var key = b.verdict === 'same' ? 'aiSame'
                            : b.verdict === 'different' ? 'aiDifferent' : 'aiUnsure';
                    if (verdictEl) verdictEl.textContent =
                        _fmt(key, { reason: b.reason || '' }, 'AI: {reason}');
                }).catch(function () {
                    btn.disabled = false;
                    btn.innerHTML = original;
                });
            }
        });
    });
})(window, document);
