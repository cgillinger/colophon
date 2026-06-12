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
            else if (act === 'verify') _verify(tr, id, btn);
            else if (act === 'delete') _delete(tr, id);
        });
    }

    /* -------------------- quick filter -------------------- */

    var filter = document.getElementById('authorsFilter');
    if (filter && table) {
        filter.addEventListener('input', function () {
            var q = filter.value.toLowerCase().trim();
            table.querySelectorAll('tbody tr').forEach(function (tr) {
                tr.style.display = (!q || (tr.dataset.name || '').indexOf(q) !== -1) ? '' : 'none';
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
