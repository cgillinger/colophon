/* Colophon – order the series
 *
 * Proposes the correct reading-order index (and, where the library's
 * spelling has drifted, the series name) for one or more series at once.
 * The proposal is a read: nothing is written until the user ticks rows
 * and presses Apply, and writing the files themselves is a separate,
 * visible choice — unlike the language check, it starts unticked here,
 * because a series rewrite touches more books at once and is easier to
 * get wrong.
 *
 * Built for a LIST of groups from the start: step 4 sends one series,
 * step 5 (multi-series) sends several, and the renderer already loops.
 */
(function (window, document) {
    'use strict';

    // Captured now, not inside a DOMContentLoaded handler: url-state.js
    // loads after this file and rewrites the query string (mirroring
    // filters/sort/page into the URL), so by the time DOMContentLoaded
    // fires the param this deep link relies on may already be gone.
    var _boot = new URLSearchParams(window.location.search);
    var _bootAuthor = _boot.get('order_series') === '1' ? _boot.get('author') : null;

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    function t(key, fallback) { return _i18n[key] || fallback; }

    var _groups = [];

    function _el(id) { return document.getElementById(id); }
    function _setStatus(text) {
        var el = _el('seriesOrderStatus');
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

    var _STATUS_KEYS = {
        confirmed:     'seriesOrderStatusConfirmed',
        ai_only:       'seriesOrderStatusAiOnly',
        conflict:      'seriesOrderStatusConflict',
        unchanged:     'seriesOrderStatusUnchanged',
        not_in_series: 'seriesOrderStatusNotInSeries',
        unknown:       'seriesOrderStatusUnknown',
        standalone:    'seriesOrderStatusStandalone'
    };

    var _ERROR_KEYS = {
        not_configured: 'seriesOrderNotConfigured',
        too_many:       'seriesOrderTooMany',
        no_books:       'seriesOrderNoBooks',
        no_author:      'seriesOrderNoAuthor'
    };

    // Shared "AI is rate-limited" message picker: quota exhaustion beats a
    // retry hint, which beats the generic limit message. Used wherever a
    // response can carry {error: 'rate_limit', retry_after, quota}.
    function _rateLimitText(data) {
        if (data.allowance_zero === true) {
            return t('aiNoAllowance', 'The provider allows no requests for this model on your plan. Pick another model in Settings → AI.');
        }
        if (data.quota === true) {
            return t('aiQuotaSpent', 'The AI quota is used up. Topping up the account is what helps, not waiting.');
        }
        if (data.retry_after) {
            var minutes = Math.max(1, Math.ceil(data.retry_after / 60));
            return t('aiBusyRetry', 'The AI is busy. Try again in N min.').replace('N', minutes);
        }
        return t('aiRateLimited', 'The AI limit has been reached. Try again later.');
    }

    function _hasCheckbox(status) {
        return status !== 'not_in_series' && status !== 'unknown' && status !== 'standalone';
    }

    function _preTicked(row) {
        if (row.status === 'confirmed') return true;
        if (row.status === 'ai_only') return row.confidence === 'high';
        return false;
    }

    /* ---------------------------------------------------------------- *
     * Rendering
     * ---------------------------------------------------------------- */

    function _renderGroups() {
        var host = _el('seriesOrderResults');
        if (!host) return;
        if (_groups.length === 0) { host.innerHTML = ''; _refreshApply(); return; }

        var html = '';
        _groups.forEach(function (group, groupIndex) {
            var warningBits = [];
            if (group.warnings && group.warnings.duplicate_indexes && group.warnings.duplicate_indexes.length) {
                warningBits.push(group.warnings.duplicate_indexes.length + ' ' + t('seriesOrderDuplicates', 'duplicate numbers'));
            }
            if (group.warnings && group.warnings.gaps && group.warnings.gaps.length) {
                warningBits.push(t('seriesOrderGaps', 'gap at') + ' ' + group.warnings.gaps.join(', '));
            }
            var warningsHtml = warningBits.length
                ? '<div class="so-warnings">' + _esc(warningBits.join(' · ')) + '</div>'
                : '';
            var snappedHtml = group.series_name_snapped
                ? '<div class="so-warnings">' + _esc(t('seriesOrderSnapped', 'Spelling follows the library.')) + '</div>'
                : '';
            // The standalone group has no series name to rename, so it gets
            // a fixed heading and no rename-all checkbox — that control
            // would mean nothing for books the AI placed in no series.
            var headingText = group.standalone
                ? t('seriesOrderStandaloneGroup', 'Not in a series')
                : group.series_name;
            var renameToggleHtml = group.standalone
                ? ''
                : '<label class="so-rename-toggle">' +
                      '<input type="checkbox" class="so-rename-all" data-group-index="' + groupIndex + '">' +
                      '<span>' + _esc(t('seriesOrderRenameAll', 'Change the series spelling on all of them')) + '</span>' +
                  '</label>';

            html += '<div class="so-group" data-group-index="' + groupIndex + '">' +
                '<div class="so-group-head">' +
                    '<div>' +
                        '<strong>' + _esc(headingText) + '</strong>' +
                        warningsHtml + snappedHtml +
                    '</div>' +
                    renameToggleHtml +
                '</div>' +
                '<table class="so-table"><thead><tr>' +
                    '<th style="width:34px;"></th>' +
                    '<th>' + t('book', 'Book') + '</th>' +
                    '<th>' + t('seriesOrderCurrent', 'Recorded') + '</th>' +
                    '<th></th>' +
                    '<th>' + t('seriesOrderProposed', 'Proposed') + '</th>' +
                    '<th></th>' +
                '</tr></thead><tbody>';

            group.rows.forEach(function (row, rowIndex) {
                var dimClass = (row.status === 'unchanged' || row.status === 'not_in_series' ||
                    row.status === 'unknown' || row.status === 'standalone') ? ' so-dim' : '';
                var checkboxHtml = _hasCheckbox(row.status)
                    ? '<input type="checkbox" class="so-row-check" data-group-index="' + groupIndex +
                      '" data-row-index="' + rowIndex + '"' + (_preTicked(row) ? ' checked' : '') + '>'
                    : '';
                // "Serien #3", or just "Serien" when no number is recorded —
                // a "#?" would read as a value someone had entered.
                var currentText = row.current_series
                    ? _esc(row.current_series) + (row.current_index ? ' #' + _esc(row.current_index) : '')
                    : '<span class="so-none">&mdash;</span>';
                var proposedText = (row.status === 'not_in_series' || row.status === 'unknown' || row.status === 'standalone')
                    ? '<span class="so-none">&mdash;</span>'
                    : _esc(row.proposed_series) + (row.proposed_index ? ' #' + _esc(row.proposed_index) : '');
                var formatsHtml = row.group_size > 1
                    ? ' <span class="so-formats">' + _esc(t('seriesOrderFormats', 'applies to N formats').replace('N', row.group_size)) + '</span>'
                    : '';
                var coauthoredHtml = row.co_authored
                    ? ' <span class="so-coauthored">' + _esc(t('seriesOrderCoAuthored', 'co-written')) + '</span>'
                    : '';
                var titleAttrBits = [];
                if (row.reason) titleAttrBits.push(row.reason);
                if (row.wikidata_index) titleAttrBits.push(t('seriesOrderWikidata', 'Wikidata') + ': ' + row.wikidata_index);
                var statusTitle = _esc(titleAttrBits.join(' — '));
                var statusClass = 'so-status so-' + (row.status || 'unknown').replace(/_/g, '-');
                var statusLabel = t(_STATUS_KEYS[row.status] || 'seriesOrderStatusUnknown', row.status);

                html +=
                    '<tr class="' + dimClass.trim() + '">' +
                      '<td>' + checkboxHtml + '</td>' +
                      '<td><div class="lang-title">' + _esc(row.title) + formatsHtml + '</div>' +
                          '<div class="lang-author">' + _esc(row.author) + coauthoredHtml + '</div></td>' +
                      '<td>' + currentText + '</td>' +
                      '<td class="lang-arrow">&rarr;</td>' +
                      '<td>' + proposedText + '</td>' +
                      '<td class="' + statusClass + '" title="' + statusTitle + '">' + _esc(statusLabel) + '</td>' +
                    '</tr>';
            });

            html += '</tbody></table></div>';
        });

        host.innerHTML = html;
        Array.prototype.forEach.call(
            host.querySelectorAll('.so-row-check'),
            function (cb) { cb.onchange = _refreshApply; }
        );
        Array.prototype.forEach.call(
            host.querySelectorAll('.so-rename-all'),
            function (cb) { cb.onchange = _refreshApply; }
        );
        _refreshApply();
    }

    function _ticked() {
        var host = _el('seriesOrderResults');
        if (!host) return [];
        return Array.prototype.filter
            .call(host.querySelectorAll('.so-row-check'), function (cb) {
                return cb.checked;
            })
            .map(function (cb) {
                var groupIndex = parseInt(cb.dataset.groupIndex, 10);
                var rowIndex = parseInt(cb.dataset.rowIndex, 10);
                var group = _groups[groupIndex];
                if (!group) return null;
                var row = group.rows[rowIndex];
                if (!row) return null;
                return { group: group, row: row };
            })
            .filter(Boolean);
    }

    function _refreshApply() {
        var count = _ticked().length;
        var btn = _el('seriesOrderApply');
        var wrap = _el('seriesOrderWriteWrap');
        var label = _el('seriesOrderWriteLabel');
        var note = _el('seriesOrderNote');
        if (btn) {
            btn.disabled = count === 0;
            btn.textContent = count === 0
                ? t('apply', 'Apply')
                : t('apply', 'Apply') + ' (' + count + ')';
        }
        if (wrap) wrap.style.display = count === 0 ? 'none' : '';
        if (label) {
            label.textContent = t('seriesOrderWriteFiles', 'Write to the files too') +
                ' (' + count + ' ' + t('seriesOrderReloadOnKobo', 'reload on Kobo') + ')';
        }
        if (note) {
            note.textContent = t('seriesOrderKoboNote', 'A series change reloads the book on a synced Kobo.');
            note.style.display = _groups.some(function (g) { return g.rows.length > 0; }) ? '' : 'none';
        }
    }

    /* ---------------------------------------------------------------- *
     * Running the proposal
     * ---------------------------------------------------------------- */

    function _setHeading(text) {
        var el = _el('seriesOrderTitle');
        if (el) el.textContent = text;
    }

    // Shared by both entry points: the single-series card and the
    // author-wide button post different bodies to different URLs but the
    // modal bootstrap, error handling and rendering are identical.
    function _run(url, body, heading) {
        var modal = _el('seriesOrderModal');
        if (!modal) return;
        modal.style.display = 'flex';

        _groups = [];
        _el('seriesOrderResults').innerHTML = '';
        _el('seriesOrderNote').style.display = 'none';
        _setHeading(heading);
        _setStatus(t('seriesOrderRunning', 'Reading the series...'));
        _refreshApply();

        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data.ok) {
                if (data.error === 'rate_limit') {
                    _setStatus(_rateLimitText(data));
                    return;
                }
                var key = _ERROR_KEYS[data.error] || 'seriesOrderFailed';
                _setStatus(t(key, 'The proposal could not be made.'));
                return;
            }
            if (data.author_name) _setHeading(_authorHeading(data.author_name));
            _groups = data.groups || [];
            _setStatus(_groups.length === 0
                ? t('seriesOrderEmpty', 'Nothing to change.')
                : '');
            _renderGroups();
        })
        .catch(function () {
            _setStatus(t('seriesOrderFailed', 'The proposal could not be made.'));
        });
    }

    function _authorHeading(authorName) {
        var base = t('seriesOrderAuthorTitle', 'Order the series');
        return authorName ? base + ' — ' + authorName : base;
    }

    function openSeriesOrder(itemIds, seriesName) {
        _run('/metadata/series/propose', { item_ids: itemIds }, t('seriesOrderTitle', 'Order the series'));
    }
    window.openSeriesOrder = openSeriesOrder;

    function openAuthorSeriesOrder(authorId, authorName) {
        _run('/metadata/series/propose-author', { author_id: authorId }, _authorHeading(authorName));
    }
    window.openAuthorSeriesOrder = openAuthorSeriesOrder;

    function closeSeriesOrder() {
        var modal = _el('seriesOrderModal');
        if (modal) modal.style.display = 'none';
    }
    window.closeSeriesOrder = closeSeriesOrder;

    /* ---------------------------------------------------------------- *
     * Applying
     * ---------------------------------------------------------------- */

    function applySeriesOrder() {
        var ticked = _ticked();
        if (ticked.length === 0) return;

        var host = _el('seriesOrderResults');
        var writeFiles = _el('seriesOrderWriteFiles').checked;
        var btn = _el('seriesOrderApply');
        btn.disabled = true;
        _setStatus(t('saving', 'Saving...'));

        var changes = ticked.map(function (entry) {
            var group = entry.group;
            var row = entry.row;
            var groupIndex = _groups.indexOf(group);
            var renameCb = host.querySelector('.so-rename-all[data-group-index="' + groupIndex + '"]');
            var renameAll = !!(renameCb && renameCb.checked);
            var series = (renameAll || !row.current_series)
                ? group.series_name
                : row.current_series;
            return { item_id: row.item_id, series: series, series_index: row.proposed_index };
        });

        fetch('/metadata/series/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ write_files: writeFiles, changes: changes })
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
            btn.disabled = false;
            _setStatus(t('seriesOrderFailed', 'The proposal could not be made.'));
        });
    }
    window.applySeriesOrder = applySeriesOrder;

    // The /authors "Order series" button lands here as a plain link
    // (?order_series=1&author=<id>); open the modal for it once the DOM
    // exists, using the query value captured at load time above.
    function _openFromBootParam() {
        if (_bootAuthor) openAuthorSeriesOrder(parseInt(_bootAuthor, 10));
    }
    if (document.readyState === 'interactive' || document.readyState === 'complete') {
        _openFromBootParam();
    } else {
        document.addEventListener('DOMContentLoaded', _openFromBootParam);
    }
})(window, document);
