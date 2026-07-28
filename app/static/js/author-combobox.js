/* ------------------------------------------------------------------ *
 * author-combobox.js — registry-backed multi-author fields in the modal
 *
 * The book modal shows one input row per author plus an "add author"
 * button — the user never types separator syntax ('&', 'och', commas);
 * each person is their own field. Markup in bulk_metadata.html:
 *   #modalAuthor       hidden input, the joined ' & ' string. Legacy
 *                      flows (enrichment/AI apply, save payload, group
 *                      sync) read/write it; a value-setter hook keeps
 *                      the visible rows in sync with programmatic writes.
 *   #modalAuthorList   container the rows render into
 *   #modalAuthorAdd    "+ add author" button
 *   #modalAuthorHint   status/suggestion line (single-author books only)
 *
 * Each row is a combobox: type-ahead against /authors/search, a final
 * "Create new" row is implicit — any typed name is checked against the
 * server-side fuzzy guard on save (confirmAuthorCreatesIfNeeded) and
 * asks before creating a near-duplicate.
 *
 * No DB writes happen here — selection stages {author_id|name} entries
 * that ride the save payload as `authors` (ordered).
 *
 * Reads i18n strings from window.__colophonConfig.i18n.
 * Exposes globals consumed by book-modal.js:
 *   initAuthorCombobox, getModalAuthorSelections,
 *   confirmAuthorCreatesIfNeeded, focusModalAuthor, updateRowAuthorFlag
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    var SEP = ' & ';

    var _itemId = null;
    var _status = null;         // item's author_status at modal open
    var _suggestions = [];      // fuzzy suggestions (single-author books)
    var _rows = [];             // [{el, input, dd, chosenId, chosenName, activeIndex, debounce}]
    var _hiddenSet = null;      // native value setter for the hidden input
    var _hiddenBound = false;
    var _addBound = false;

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _hidden() { return document.getElementById('modalAuthor'); }
    function _list()   { return document.getElementById('modalAuthorList'); }
    function _addBtn() { return document.getElementById('modalAuthorAdd'); }
    function _hint()   { return document.getElementById('modalAuthorHint'); }

    function _splitString(s) {
        return String(s || '').split(SEP)
            .map(function (p) { return p.trim(); })
            .filter(Boolean);
    }

    /* -------------------- hidden-input sync -------------------- */

    /* Rows are authoritative while the user edits; the hidden input is
       authoritative when another flow (enrichment/AI apply) writes to it
       programmatically. The setter hook catches those writes — .value
       assignments fire no events. */
    function _bindHidden() {
        if (_hiddenBound) return;
        var hidden = _hidden();
        if (!hidden) return;
        _hiddenBound = true;
        var desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
        _hiddenSet = desc.set;
        Object.defineProperty(hidden, 'value', {
            get: function () { return desc.get.call(this); },
            set: function (v) {
                desc.set.call(this, v);
                _renderRows(_splitString(v).map(function (n) {
                    return { id: null, name: n };
                }));
            }
        });
    }

    function _syncHidden() {
        var hidden = _hidden();
        if (!hidden) return;
        var joined = _rows.map(function (r) {
            return r.input.value.trim();
        }).filter(Boolean).join(SEP);
        // Bypass our own setter — this direction must not re-render.
        if (_hiddenSet) _hiddenSet.call(hidden, joined);
        else hidden.value = joined;
    }

    /* -------------------- rows -------------------- */

    function _renderRows(authors) {
        var list = _list();
        if (!list) return;
        list.innerHTML = '';
        _rows = [];
        if (!authors.length) authors = [{ id: null, name: '' }];
        authors.forEach(function (a) { _addRow(a, false); });
        _updateRemoveButtons();
    }

    function _addRow(author, focus) {
        var list = _list();
        if (!list) return null;
        var el = document.createElement('div');
        el.className = 'author-row';
        el.innerHTML =
            '<div class="author-combobox">' +
                '<input type="text" class="modal-input author-row-input" autocomplete="off" ' +
                       'role="combobox" aria-expanded="false" ' +
                       'placeholder="' + _esc(_i18n.authorFieldPlaceholder || '') + '">' +
                '<div class="author-dropdown" role="listbox" style="display:none;"></div>' +
            '</div>' +
            '<button type="button" class="author-row-remove" tabindex="-1" ' +
                    'title="' + _esc(_i18n.authorRemove || 'Remove author') + '">' +
                '<i class="ti ti-x"></i></button>';
        list.appendChild(el);

        var row = {
            el: el,
            input: el.querySelector('.author-row-input'),
            dd: el.querySelector('.author-dropdown'),
            chosenId: (author && author.id) || null,
            chosenName: (author && author.id && author.name) || '',
            activeIndex: -1,
            debounce: null
        };
        row.input.value = (author && author.name) || '';
        _bindRow(row);
        _rows.push(row);
        _updateRemoveButtons();
        if (focus) row.input.focus();
        return row;
    }

    function _removeRow(row) {
        var idx = _rows.indexOf(row);
        if (idx === -1) return;
        _rows.splice(idx, 1);
        row.el.remove();
        if (!_rows.length) _addRow({ id: null, name: '' }, false);
        _updateRemoveButtons();
        _syncHidden();
        _renderHint();
    }

    function _updateRemoveButtons() {
        _rows.forEach(function (r) {
            var btn = r.el.querySelector('.author-row-remove');
            if (btn) btn.style.display = _rows.length > 1 ? '' : 'none';
        });
    }

    /* -------------------- state -------------------- */

    function initAuthorCombobox(itemId, data) {
        _itemId = itemId;
        _status = data.author_status || null;
        _suggestions = [];
        _bindHidden();
        _bindAddButton();

        var authors = (data.authors && data.authors.length)
            ? data.authors.map(function (a) { return { id: a.id, name: a.name }; })
            : _splitString(data.author).map(function (n) { return { id: null, name: n }; });
        _renderRows(authors);
        _syncHidden();
        _renderHint();

        // Suggestion hint ("Did you mean X?") is a single-author affair —
        // book-level proposals can't be attributed to one row of many.
        if (_rows.length === 1
                && (_status === 'review' || _status === 'missing' || _status === 'new')) {
            fetch('/authors/items/' + itemId + '/suggestions', { cache: 'no-store' })
                .then(function (r) { return r.json(); })
                .then(function (body) {
                    if (!body.ok || itemId !== _itemId) return;
                    _suggestions = body.suggestions || [];
                    _renderHint();
                })
                .catch(function () { /* hint is best-effort */ });
        }
    }
    window.initAuthorCombobox = initAuthorCombobox;

    /* Ordered selections for the save payload: registry picks carry
       their author_id (only while the text still matches the pick),
       typed entries just the name. */
    function getModalAuthorSelections() {
        var out = [];
        _rows.forEach(function (r) {
            var name = r.input.value.trim();
            if (!name) return;
            var id = (r.chosenId && name === r.chosenName) ? r.chosenId : null;
            out.push({ author_id: id, name: name });
        });
        return out;
    }
    window.getModalAuthorSelections = getModalAuthorSelections;

    function focusModalAuthor() {
        if (_rows.length) _rows[0].input.focus();
    }
    window.focusModalAuthor = focusModalAuthor;

    /* -------------------- hint line -------------------- */

    function _renderHint() {
        var hint = _hint();
        if (!hint) return;
        var html = '';
        var single = _rows.length === 1;
        var chosen = single && _rows[0].chosenId
            && _rows[0].input.value.trim() === _rows[0].chosenName;
        if (chosen) {
            html = '<i class="ti ti-check"></i> ' +
                _esc((_i18n.authorLinkedOnSave || 'Will be linked to {name} on save.')
                    .replace('{name}', _rows[0].chosenName));
        } else if (single && _status === 'review' && _suggestions.length) {
            var best = _suggestions[0];
            html = '<i class="ti ti-alert-triangle"></i> ' +
                _esc((_i18n.authorDidYouMean || 'Did you mean {name}?')
                    .replace('{name}', best.name)) +
                ' <button type="button" class="author-hint-btn" data-author-id="' + best.id +
                '" data-author-name="' + _esc(best.name) + '">' +
                _esc(_i18n.authorUseSuggestion || 'Use') + '</button>';
        } else if (single && _status === 'review') {
            html = '<i class="ti ti-alert-triangle"></i> ' + _esc(_i18n.authorStatusReview || '');
        } else if (single && _status === 'new') {
            html = '<i class="ti ti-user-plus"></i> ' + _esc(_i18n.authorStatusNew || '');
        } else if (single && _status === 'missing' && !_rows[0].input.value.trim()) {
            html = '<i class="ti ti-help"></i> ' + _esc(_i18n.authorStatusMissing || '');
        }
        hint.innerHTML = html;
        hint.style.display = html ? 'block' : 'none';
        var btn = hint.querySelector('.author-hint-btn');
        if (btn) {
            btn.addEventListener('click', function () {
                if (!_rows.length) return;
                _select(_rows[0],
                    parseInt(btn.dataset.authorId, 10), btn.dataset.authorName);
            });
        }
    }

    /* -------------------- dropdown (per row) -------------------- */

    function _hideDropdown(row) {
        row.dd.style.display = 'none';
        row.dd.innerHTML = '';
        row.input.setAttribute('aria-expanded', 'false');
        row.activeIndex = -1;
    }

    function _renderDropdown(row, authors, typed) {
        var rowsHtml = '';
        authors.forEach(function (a, i) {
            rowsHtml += '<div class="author-dropdown-item" role="option" data-index="' + i +
                '" data-author-id="' + a.id + '" data-author-name="' + _esc(a.name) + '">' +
                '<i class="ti ti-user"></i> ' + _esc(a.name) +
                (a.source === 'tentative'
                    ? ' <span class="author-chip author-chip-tentative">?</span>' : '') +
                (typeof a.score === 'number'
                    ? ' <span class="author-chip">' + Math.round(a.score * 100) + '%</span>' : '') +
                '</div>';
        });
        if (!rowsHtml) { _hideDropdown(row); return; }
        row.dd.innerHTML = rowsHtml;
        row.dd.style.display = 'block';
        row.input.setAttribute('aria-expanded', 'true');
        row.activeIndex = -1;

        row.dd.querySelectorAll('.author-dropdown-item').forEach(function (el) {
            // mousedown, not click: fires before the input's blur hides us.
            el.addEventListener('mousedown', function (e) {
                e.preventDefault();
                _select(row, parseInt(el.dataset.authorId, 10), el.dataset.authorName);
            });
        });
    }

    function _select(row, authorId, name) {
        row.chosenId = authorId;
        row.chosenName = name;
        row.input.value = name;
        _hideDropdown(row);
        _syncHidden();
        _renderHint();
    }

    function _search(row, q) {
        var typed = q.trim();
        // Merge the review suggestions in so they stay visible while
        // typing (single-author books only — that's when they exist).
        var fromSuggestions = _suggestions.slice(0, 3);
        if (!typed) {
            _renderDropdown(row, fromSuggestions, '');
            return;
        }
        fetch('/authors/search?q=' + encodeURIComponent(typed), { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (body) {
                if (row.input.value.trim() !== typed) return; // stale
                var seen = {};
                var merged = [];
                fromSuggestions.concat((body.ok && body.authors) || [])
                    .forEach(function (a) {
                        if (!seen[a.id]) { seen[a.id] = true; merged.push(a); }
                    });
                _renderDropdown(row, merged.slice(0, 8), typed);
            })
            .catch(function () { _hideDropdown(row); });
    }

    /* -------------------- create-on-save guard -------------------- */

    /* Called by saveMetadata() before the main save. Every typed name
       without a staged registry pick runs the server-side guard
       (/authors/check): a layer-1/2 match links silently; a fuzzy
       near-match asks before the save may create a new author (design
       guard 2). Resolves true when the save may proceed. */
    function confirmAuthorCreatesIfNeeded() {
        var pending = _rows.filter(function (r) {
            var name = r.input.value.trim();
            return name && !(r.chosenId && name === r.chosenName);
        });
        var chain = Promise.resolve(true);
        pending.forEach(function (row) {
            chain = chain.then(function (proceed) {
                if (!proceed) return false;
                var name = row.input.value.trim();
                return fetch('/authors/check', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name })
                }).then(function (r) { return r.json(); }).then(function (body) {
                    if (!body.ok) return true; // guard is best-effort
                    if (body.author) {
                        _select(row, body.author.id, body.author.name);
                        return true;
                    }
                    if (body.similar && body.similar.length) {
                        var msg = (_i18n.authorSimilarConfirm ||
                            '“{name}” is very similar to “{existing}”. Create as a new author anyway?')
                            .replace('{name}', name)
                            .replace('{existing}', body.similar[0].name);
                        if (window.confirm(msg)) return true;
                        row.input.focus();
                        return false; // user backed out — let them pick instead
                    }
                    return true;
                }).catch(function () { return true; });
            });
        });
        return chain;
    }
    window.confirmAuthorCreatesIfNeeded = confirmAuthorCreatesIfNeeded;

    /* -------------------- row flag sync -------------------- */

    /* After save, retint the row's author-cell flag to the new status so
       the table reflects reality without a reload. */
    function updateRowAuthorFlag(itemId, status) {
        var tbody = document.getElementById('bookTableBody');
        var row = (tbody || document).querySelector('tr[data-item-id="' + itemId + '"]');
        if (!row) return;
        row.dataset.authorStatus = status || '';
        var cell = row.querySelector('.author-cell');
        if (!cell) return;
        var flag = cell.querySelector('.author-flag');
        if (flag) flag.remove();
        if (status === 'review' || status === 'new' || status === 'missing') {
            var icon = status === 'review' ? 'ti-alert-triangle'
                     : status === 'new' ? 'ti-user-plus' : 'ti-help';
            var span = document.createElement('span');
            span.className = 'author-flag author-flag-' + status;
            span.innerHTML = '<i class="ti ' + icon + '"></i>';
            cell.insertBefore(span, cell.firstChild);
        }
    }
    window.updateRowAuthorFlag = updateRowAuthorFlag;

    /* -------------------- events -------------------- */

    function _bindAddButton() {
        if (_addBound) return;
        var btn = _addBtn();
        if (!btn) return;
        _addBound = true;
        btn.addEventListener('click', function () {
            _addRow({ id: null, name: '' }, true);
            _renderHint();
        });
    }

    function _bindRow(row) {
        row.el.querySelector('.author-row-remove')
            .addEventListener('click', function () { _removeRow(row); });

        row.input.addEventListener('input', function () {
            // Manual typing invalidates a staged pick.
            if (row.chosenId && row.input.value.trim() !== row.chosenName) {
                row.chosenId = null;
                row.chosenName = '';
                _renderHint();
            }
            _syncHidden();
            if (row.debounce) clearTimeout(row.debounce);
            row.debounce = setTimeout(function () { _search(row, row.input.value); }, 250);
        });

        row.input.addEventListener('focus', function () {
            if (_suggestions.length && !row.chosenId && _rows.length === 1) {
                _renderDropdown(row, _suggestions.slice(0, 5), row.input.value.trim());
            }
        });

        row.input.addEventListener('blur', function () {
            setTimeout(function () { _hideDropdown(row); }, 150);
        });

        row.input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && row.dd.style.display === 'none') return;
            var items = row.dd.querySelectorAll('.author-dropdown-item');
            if (row.dd.style.display === 'none' || !items.length) {
                if (e.key === 'Escape') _hideDropdown(row);
                return;
            }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                row.activeIndex += (e.key === 'ArrowDown' ? 1 : -1);
                if (row.activeIndex < 0) row.activeIndex = items.length - 1;
                if (row.activeIndex >= items.length) row.activeIndex = 0;
                items.forEach(function (el, i) {
                    el.classList.toggle('active', i === row.activeIndex);
                });
            } else if (e.key === 'Enter' && row.activeIndex >= 0) {
                e.preventDefault();
                var el = items[row.activeIndex];
                _select(row, parseInt(el.dataset.authorId, 10), el.dataset.authorName);
            } else if (e.key === 'Escape') {
                _hideDropdown(row);
            }
        });
    }
})(window, document);
