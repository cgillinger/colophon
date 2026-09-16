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

    // Shared "AI is rate-limited" message picker: quota exhaustion beats a
    // retry hint, which beats the generic limit message. Used wherever a
    // response can carry {error: 'rate_limit', retry_after, quota}.
    function _rateLimitText(data) {
        if (data.allowance_zero === true) {
            return _i18n.aiNoAllowance || 'The provider allows no requests for this model on your plan. Pick another model in Settings → AI.';
        }
        if (data.quota === true) {
            return _i18n.aiQuotaSpent || 'The AI quota is used up. Topping up the account is what helps, not waiting.';
        }
        if (data.retry_after) {
            var minutes = Math.max(1, Math.ceil(data.retry_after / 60));
            return (_i18n.aiBusyRetry || 'The AI is busy. Try again in N min.').replace('N', minutes);
        }
        return _i18n.aiRateLimited || 'The AI limit has been reached. Try again later.';
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

    // Mirrors the two-line cell authors.html renders on load: a description
    // (or, failing that, the label) above the register links. Built with
    // createElement/textContent rather than innerHTML — the description is
    // Wikidata's text, not ours, and doesn't belong spliced into markup.
    function _renderAuthorityCell(td, author) {
        while (td.firstChild) td.removeChild(td.firstChild);
        var text = author.authority_description || author.authority_label;
        if (text) {
            var desc = document.createElement('div');
            desc.className = 'authority-desc';
            desc.textContent = text;
            td.appendChild(desc);
        }
        var links = [
            ['wikidata_qid', 'Wikidata', 'https://www.wikidata.org/wiki/', 'authorityWikidataTitle'],
            ['viaf_id', 'VIAF', 'https://viaf.org/viaf/', 'authorityViafTitle'],
            ['libris_id', 'LIBRIS', 'https://libris.kb.se/', 'authorityLibrisTitle']
        ];
        var row = document.createElement('div');
        row.className = 'authority-links';
        var any = false;
        links.forEach(function (spec) {
            var id = author[spec[0]];
            if (!id) return;
            any = true;
            var a = document.createElement('a');
            a.href = spec[2] + id;
            a.target = '_blank';
            a.rel = 'noopener';
            a.title = _fmt(spec[3], { id: id }, spec[1] + ': {id}');
            a.textContent = spec[1];
            row.appendChild(a);
        });
        if (any) {
            td.appendChild(row);
        } else if (!text) {
            var dash = document.createElement('span');
            dash.className = 'dup-count';
            dash.textContent = '—';
            td.appendChild(dash);
        }
    }

    /* A successful verify moves the entry to 'authority_linked' server
       side. The row used to catch up via location.reload(); now that the
       authority cell is patched in place, the rest of the row has to be
       patched too — otherwise the badge keeps saying "Tentative", the
       "show only unconfirmed" filter still matches it, and an inline
       Confirm button sits there offering something already done. */
    function _markAuthorityLinked(tr) {
        tr.dataset.source = 'authority_linked';

        var badge = tr.querySelector('td .badge');
        if (badge) {
            badge.className = 'badge info';
            badge.textContent = _i18n.statusAuthorityLinked || 'Authority-linked';
        }

        var confirmBtn = tr.querySelector('[data-act="confirm"]');
        if (confirmBtn) confirmBtn.remove();

        // There is something to undo now, so offer the undo.
        var unlinkBtn = tr.querySelector('[data-act="unlink"]');
        if (unlinkBtn) unlinkBtn.hidden = false;

        if (typeof _refreshBulkBar === 'function') _refreshBulkBar();
    }

    function _verify(tr, id, btn) {
        var original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="ti ti-loader-2 upload-spin"></i> ' + (_i18n.verifying || 'Looking up…');
        _post('/authors/' + id + '/verify').then(function (b) {
            btn.disabled = false;
            btn.innerHTML = original;
            if (b.ok && b.matched) {
                var td = tr.querySelector('.author-ids');
                if (td) _renderAuthorityCell(td, b.author || {});
                _markAuthorityLinked(tr);
                return;
            }
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

    /* Verify can anchor the wrong person — Wikidata ranks by notability,
       not by which "Dennis Taylor" is the one on the shelf. Since
       source === 'authority_linked' gates writing the name into ebook
       files, a wrong anchor is worse than no anchor: this is the only
       way to take one back off without touching the canonical name. */
    function _unlink(tr, id) {
        var name = _rowName(tr);
        if (!window.confirm(_fmt('unlinkConfirm', { name: name },
                'Remove the authority link from “{name}”?'))) return;
        _post('/authors/' + id + '/unlink', {}).then(function (b) {
            if (!b.ok) { alert(_i18n.actionFailed || 'The action failed.'); return; }
            var td = tr.querySelector('.author-ids');
            if (td) _renderAuthorityCell(td, b.author || {});
            tr.dataset.source = 'user_confirmed';
            var badge = tr.querySelector('td .badge');
            if (badge) {
                badge.className = 'badge ok';
                badge.textContent = _i18n.statusConfirmed || 'Confirmed';
            }
            var unlinkBtn = tr.querySelector('[data-act="unlink"]');
            if (unlinkBtn) unlinkBtn.hidden = true;
            if (typeof _refreshBulkBar === 'function') _refreshBulkBar();
        }).catch(function () {
            alert(_i18n.actionFailed || 'The action failed.');
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
            else if (act === 'unlink') _unlink(tr, id);
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

    /* Bulk verify: the Authority column stays empty until someone fills
       it, and until now the only way was Verify in one row's menu at a
       time — so on a real library it simply never got filled. Confirm
       does not fill it either; that only records that the spelling is
       right.

       The loop runs in the browser, one author at a time, rather than as
       a bulk route: each verify is a SPARQL round trip to Wikidata, and
       a few hundred of them serially on the server would run past
       Gunicorn's 300 s with nothing to show. Here the user sees progress
       and the work survives being slow. One at a time is also the polite
       rate for a public endpoint. */
    var bulkVerify = document.getElementById('authorsBulkVerify');
    if (bulkVerify) {
        bulkVerify.addEventListener('click', function () {
            // Skip only what is fully looked up. The description line is
            // the right test, not the links: an entry verified before
            // v1.57.0 has ids but no description, and re-verifying is
            // exactly how it gets one.
            var rows = _checkedRows().filter(function (tr) {
                return !tr.querySelector('.author-ids .authority-desc');
            });
            if (!rows.length) {
                window.alert(_i18n.bulkVerifyAllDone
                    || 'The selected authors already have authority ids.');
                return;
            }

            var msg = _fmt('bulkVerifyPrompt', { count: rows.length },
                'Look up {count} selected authors in Wikidata?');
            if (!window.confirm(msg)) return;

            var countEl = document.getElementById('authorsBulkCount');
            var bulkConfirmBtn = document.getElementById('authorsBulkConfirm');
            bulkVerify.disabled = true;
            if (bulkConfirmBtn) bulkConfirmBtn.disabled = true;

            var matched = 0;
            var failed = 0;

            function step(i) {
                if (i >= rows.length) {
                    window.alert(_fmt('bulkVerifyDone', {
                        matched: matched, count: rows.length, failed: failed
                    }, '{matched} of {count} were found. {failed} lookups failed.'));
                    location.reload();
                    return;
                }
                if (countEl) {
                    countEl.textContent = _fmt('bulkVerifyProgress',
                        { done: i + 1, count: rows.length }, 'Looking up {done} of {count}…');
                }
                var id = parseInt(rows[i].dataset.authorId, 10);
                _post('/authors/' + id + '/verify', {})
                    .then(function (body) {
                        if (body && body.ok && body.matched) matched++;
                        else if (!body || !body.ok) failed++;
                    })
                    .catch(function () { failed++; })
                    .then(function () { step(i + 1); });
            }
            step(0);
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
                            b.error === 'not_configured' ? (_i18n.aiUnavailable || 'AI is not configured.')
                                : b.error === 'rate_limit' ? _rateLimitText(b)
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

    /* -------------------- row overflow menu --------------------
     * Six actions per row (Confirm/Verify/Rename/Merge/Split/Order
     * series, +Delete) wrapped raggedly at 17 authors and was unusable
     * on a phone. Confirm stays inline; the rest live in a "⋯" popover.
     * Every item is still a plain data-act button/link inside the
     * row's <tr>, so the delegated table click handler above (and the
     * Order-series link's own navigation) keep working untouched —
     * this section only opens, closes and positions the popover.
     * Position is `fixed`, computed from the toggle's rect, because a
     * menu opening on the table's last row must not get clipped by an
     * ancestor's overflow. -------------------------------------------------------------- */

    var _openRowMenu = null; // { toggle, list }

    function _closeRowMenu(returnFocus) {
        if (!_openRowMenu) return;
        var entry = _openRowMenu;
        _openRowMenu = null;
        entry.list.hidden = true;
        entry.toggle.setAttribute('aria-expanded', 'false');
        if (returnFocus) entry.toggle.focus();
    }

    function _positionRowMenu(toggle, list) {
        var margin = 8;
        var tRect = toggle.getBoundingClientRect();
        var lRect = list.getBoundingClientRect();
        var left = tRect.right - lRect.width;
        left = Math.max(margin, Math.min(left, window.innerWidth - lRect.width - margin));
        var spaceBelow = window.innerHeight - tRect.bottom;
        var top = (spaceBelow >= lRect.height + margin) ? tRect.bottom + 4 : tRect.top - lRect.height - 4;
        top = Math.max(margin, Math.min(top, window.innerHeight - lRect.height - margin));
        list.style.left = left + 'px';
        list.style.top = top + 'px';
    }

    function _openRowMenuFor(toggle) {
        var list = toggle.nextElementSibling;
        if (!list) return;
        if (_openRowMenu) _closeRowMenu(false);
        list.hidden = false;
        toggle.setAttribute('aria-expanded', 'true');
        _positionRowMenu(toggle, list);
        _openRowMenu = { toggle: toggle, list: list };
    }

    document.addEventListener('click', function (e) {
        var toggle = e.target.closest('.row-menu-toggle');
        if (toggle) {
            e.preventDefault();
            if (_openRowMenu && _openRowMenu.toggle === toggle) _closeRowMenu(false);
            else _openRowMenuFor(toggle);
            return;
        }
        if (_openRowMenu && _openRowMenu.list.contains(e.target)) {
            // A menu item (button[data-act] or the "Order series" link):
            // the delegated table handler above already ran its action
            // during bubbling (it's bound closer to the target than this
            // document listener), so just close the popover behind it.
            _closeRowMenu(false);
            return;
        }
        if (_openRowMenu) _closeRowMenu(false);
    });

    document.addEventListener('keydown', function (e) {
        if (!_openRowMenu) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            _closeRowMenu(true);
            return;
        }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            var items = Array.prototype.slice.call(_openRowMenu.list.querySelectorAll('.row-menu-item'));
            if (!items.length) return;
            var idx = items.indexOf(document.activeElement);
            var next = e.key === 'ArrowDown'
                ? items[(idx + 1) % items.length]
                : items[(idx - 1 + items.length) % items.length];
            e.preventDefault();
            next.focus();
        }
    });

    window.addEventListener('scroll', function () {
        if (_openRowMenu) _closeRowMenu(false);
    }, true);

    window.addEventListener('resize', function () {
        if (_openRowMenu) _closeRowMenu(false);
    });
})(window, document);
