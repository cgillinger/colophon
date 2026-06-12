/* ------------------------------------------------------------------ *
 * author-combobox.js — registry-backed author field in the book modal
 *
 * Enhances #modalAuthor (markup in bulk_metadata.html) with:
 *   - type-ahead against /authors/search (canonical registry entries)
 *   - a preselected "Did you mean X?" hint for items flagged 'review'
 *   - a final "Create new: «text»" row; creation runs the fuzzy guard
 *     server-side and asks before creating a near-duplicate
 *
 * No DB writes happen here except via confirmAuthorCreateIfNeeded(),
 * which book-modal.js calls as part of Save — selection alone only
 * stages an author_id for the save payload.
 *
 * Reads i18n strings from window.__colophonConfig.i18n.
 * Exposes globals consumed by book-modal.js:
 *   initAuthorCombobox, getModalAuthorSelection,
 *   confirmAuthorCreateIfNeeded, updateRowAuthorFlag
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    var _itemId = null;
    var _chosenId = null;       // staged author_id for the save payload
    var _chosenName = '';
    var _createNew = false;     // user explicitly picked "Create new"
    var _status = null;         // item's author_status at modal open
    var _suggestions = [];      // fuzzy suggestions for review items
    var _bound = false;
    var _debounce = null;
    var _activeIndex = -1;

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _input()    { return document.getElementById('modalAuthor'); }
    function _dropdown() { return document.getElementById('modalAuthorDropdown'); }
    function _hint()     { return document.getElementById('modalAuthorHint'); }

    /* -------------------- state -------------------- */

    function initAuthorCombobox(itemId, data) {
        _itemId = itemId;
        _status = data.author_status || null;
        _chosenId = null;
        _chosenName = '';
        _createNew = false;
        _suggestions = [];
        _hideDropdown();
        _renderHint();
        _bindOnce();

        // Review case: fetch the fuzzy suggestions up front so the
        // "Did you mean X?" hint can render without a focus first.
        if (_status === 'review' || _status === 'missing' || _status === 'new') {
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

    function getModalAuthorSelection() {
        var input = _input();
        // The staged id only holds while the text still matches the pick.
        if (_chosenId && input && input.value.trim() === _chosenName) {
            return { author_id: _chosenId, create_new: false };
        }
        if (_createNew && input && input.value.trim()) {
            return { author_id: null, create_new: true };
        }
        return { author_id: null, create_new: false };
    }
    window.getModalAuthorSelection = getModalAuthorSelection;

    /* -------------------- hint line -------------------- */

    function _renderHint() {
        var hint = _hint();
        if (!hint) return;
        var html = '';
        if (_chosenId) {
            html = '<i class="ti ti-check"></i> ' +
                _esc((_i18n.authorLinkedOnSave || 'Will be linked to {name} on save.')
                    .replace('{name}', _chosenName));
        } else if (_status === 'review' && _suggestions.length) {
            var best = _suggestions[0];
            html = '<i class="ti ti-alert-triangle"></i> ' +
                _esc((_i18n.authorDidYouMean || 'Did you mean {name}?')
                    .replace('{name}', best.name)) +
                ' <button type="button" class="author-hint-btn" data-author-id="' + best.id +
                '" data-author-name="' + _esc(best.name) + '">' +
                _esc(_i18n.authorUseSuggestion || 'Use') + '</button>';
        } else if (_status === 'review') {
            html = '<i class="ti ti-alert-triangle"></i> ' + _esc(_i18n.authorStatusReview || '');
        } else if (_status === 'new') {
            html = '<i class="ti ti-user-plus"></i> ' + _esc(_i18n.authorStatusNew || '');
        } else if (_status === 'missing') {
            html = '<i class="ti ti-help"></i> ' + _esc(_i18n.authorStatusMissing || '');
        }
        hint.innerHTML = html;
        hint.style.display = html ? 'block' : 'none';
        var btn = hint.querySelector('.author-hint-btn');
        if (btn) {
            btn.addEventListener('click', function () {
                _select(parseInt(btn.dataset.authorId, 10), btn.dataset.authorName);
            });
        }
    }

    /* -------------------- dropdown -------------------- */

    function _hideDropdown() {
        var dd = _dropdown();
        if (dd) { dd.style.display = 'none'; dd.innerHTML = ''; }
        var input = _input();
        if (input) input.setAttribute('aria-expanded', 'false');
        _activeIndex = -1;
    }

    function _renderDropdown(authors, typed) {
        var dd = _dropdown();
        if (!dd) return;
        var rows = '';
        authors.forEach(function (a, i) {
            rows += '<div class="author-dropdown-item" role="option" data-index="' + i +
                '" data-author-id="' + a.id + '" data-author-name="' + _esc(a.name) + '">' +
                '<i class="ti ti-user"></i> ' + _esc(a.name) +
                (a.source === 'tentative'
                    ? ' <span class="author-chip author-chip-tentative">?</span>' : '') +
                (typeof a.score === 'number'
                    ? ' <span class="author-chip">' + Math.round(a.score * 100) + '%</span>' : '') +
                '</div>';
        });
        if (typed) {
            rows += '<div class="author-dropdown-item author-dropdown-create" role="option" data-index="' +
                authors.length + '" data-create="1">' +
                '<i class="ti ti-plus"></i> ' +
                _esc((_i18n.authorCreateNew || 'Create new: “{name}”').replace('{name}', typed)) +
                '</div>';
        }
        if (!rows) { _hideDropdown(); return; }
        dd.innerHTML = rows;
        dd.style.display = 'block';
        var input = _input();
        if (input) input.setAttribute('aria-expanded', 'true');
        _activeIndex = -1;

        dd.querySelectorAll('.author-dropdown-item').forEach(function (el) {
            // mousedown, not click: fires before the input's blur hides us.
            el.addEventListener('mousedown', function (e) {
                e.preventDefault();
                if (el.dataset.create === '1') {
                    _markCreateNew();
                } else {
                    _select(parseInt(el.dataset.authorId, 10), el.dataset.authorName);
                }
            });
        });
    }

    function _select(authorId, name) {
        _chosenId = authorId;
        _chosenName = name;
        _createNew = false;
        var input = _input();
        if (input) input.value = name;
        _hideDropdown();
        _renderHint();
    }

    function _markCreateNew() {
        _chosenId = null;
        _chosenName = '';
        _createNew = true;
        _hideDropdown();
        _renderHint();
    }

    function _search(q) {
        var typed = q.trim();
        // Merge the review suggestions in so they stay visible while typing.
        var fromSuggestions = _suggestions.slice(0, 3);
        if (!typed) {
            _renderDropdown(fromSuggestions, '');
            return;
        }
        fetch('/authors/search?q=' + encodeURIComponent(typed), { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (body) {
                var input = _input();
                if (!input || input.value.trim() !== typed) return; // stale
                var seen = {};
                var merged = [];
                fromSuggestions.concat((body.ok && body.authors) || [])
                    .forEach(function (a) {
                        if (!seen[a.id]) { seen[a.id] = true; merged.push(a); }
                    });
                _renderDropdown(merged.slice(0, 8), typed);
            })
            .catch(function () { _hideDropdown(); });
    }

    /* -------------------- create-on-save guard -------------------- */

    /* Called by saveMetadata() before the main save when the user picked
       "Create new". Runs the server-side fuzzy guard (design guard 2):
       a near-match asks for confirmation before forcing creation.
       Resolves true when the save may proceed. */
    function confirmAuthorCreateIfNeeded(itemId, name) {
        if (!_createNew || !name) return Promise.resolve(true);
        var attempt = function (force) {
            return fetch('/authors/items/' + itemId + '/assign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, force: force })
            }).then(function (r) { return r.json(); });
        };
        return attempt(false).then(function (body) {
            if (body.ok) { _createNew = false; return true; }
            if (body.error === 'similar_exists' && body.similar && body.similar.length) {
                var existing = body.similar[0].name;
                var msg = (_i18n.authorSimilarConfirm ||
                    '“{name}” is very similar to “{existing}”. Create as a new author anyway?')
                    .replace('{name}', name).replace('{existing}', existing);
                if (window.confirm(msg)) {
                    return attempt(true).then(function (b2) {
                        if (b2.ok) { _createNew = false; return true; }
                        return false;
                    });
                }
                return false; // user backed out — let them pick instead
            }
            return false;
        }).catch(function () { return false; });
    }
    window.confirmAuthorCreateIfNeeded = confirmAuthorCreateIfNeeded;

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

    function _bindOnce() {
        if (_bound) return;
        var input = _input();
        if (!input) return;
        _bound = true;

        input.addEventListener('input', function () {
            // Manual typing invalidates a staged pick.
            if (_chosenId && input.value.trim() !== _chosenName) {
                _chosenId = null; _chosenName = ''; _renderHint();
            }
            _createNew = false;
            if (_debounce) clearTimeout(_debounce);
            _debounce = setTimeout(function () { _search(input.value); }, 250);
        });

        input.addEventListener('focus', function () {
            if (_suggestions.length && !_chosenId) _renderDropdown(_suggestions.slice(0, 5), input.value.trim());
        });

        input.addEventListener('blur', function () {
            setTimeout(_hideDropdown, 150);
        });

        input.addEventListener('keydown', function (e) {
            var dd = _dropdown();
            if (!dd || dd.style.display === 'none') return;
            var items = dd.querySelectorAll('.author-dropdown-item');
            if (!items.length) return;
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                _activeIndex += (e.key === 'ArrowDown' ? 1 : -1);
                if (_activeIndex < 0) _activeIndex = items.length - 1;
                if (_activeIndex >= items.length) _activeIndex = 0;
                items.forEach(function (el, i) {
                    el.classList.toggle('active', i === _activeIndex);
                });
            } else if (e.key === 'Enter' && _activeIndex >= 0) {
                e.preventDefault();
                var el = items[_activeIndex];
                if (el.dataset.create === '1') _markCreateNew();
                else _select(parseInt(el.dataset.authorId, 10), el.dataset.authorName);
            } else if (e.key === 'Escape') {
                _hideDropdown();
            }
        });
    }
})(window, document);
