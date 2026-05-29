/* ------------------------------------------------------------------ *
 * reading-now.js — "Reading now" + "Resume?" hero sections
 *
 * Fetches /reading-now and renders two card sections above the table:
 *   - Reading now: books with read_status='Reading' that have progress
 *     in the last 30 days. Most-recently-updated at top. Hero card for
 *     #1, smaller side-cards for the rest.
 *   - Resume?: stale Reading books (no activity in 30+ days) that the
 *     user hasn't dismissed. Each gets a dismiss-X.
 *
 * Visibility: only in table view. Switched off via CSS in shelf/series.
 * Refresh: triggered on page load, and whenever the active sidebar
 * status filter changes (handled by full page reload anyway).
 * ------------------------------------------------------------------ */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _relativeDate(iso) {
        if (!iso) return _i18n.readingNoActivity || '';
        var then = new Date(iso);
        var now = new Date();
        var diffMs = now - then;
        var diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        if (diffDays < 1) {
            var hours = Math.floor(diffMs / (1000 * 60 * 60));
            if (hours < 1) return _i18n.readingJustNow || 'just nu';
            return (_i18n.readingHoursAgo || '{n} h sen').replace('{n}', hours);
        }
        if (diffDays < 7) return (_i18n.readingDaysAgo || '{n} dagar sen').replace('{n}', diffDays);
        if (diffDays < 30) {
            var weeks = Math.floor(diffDays / 7);
            return (_i18n.readingWeeksAgo || '{n} v sen').replace('{n}', weeks);
        }
        var months = Math.floor(diffDays / 30);
        return (_i18n.readingMonthsAgo || '{n} mån sen').replace('{n}', months);
    }

    function _renderCard(book, options) {
        options = options || {};
        var seriesLine = book.series
            ? _esc(book.series) + (book.series_index ? ' · ' + _esc(book.series_index) : '')
            : '';
        var pct = (book.progress != null) ? Math.round(book.progress) : 0;
        var dismissBtn = options.dismissable
            ? '<button type="button" class="reading-now-dismiss" data-item-id="' + book.id +
              '" aria-label="' + _esc(_i18n.dismiss || 'Avfärda') + '">×</button>'
            : '';
        return (
            '<div class="reading-now-card ' + (options.hero ? 'reading-now-hero' : '') +
            '" data-item-id="' + book.id + '">' +
                '<img class="reading-now-cover" src="' + _esc(book.cover_url) + '" alt="' + _esc(book.title) + '" ' +
                     'onclick="openBookModal(' + book.id + ', true)">' +
                '<div class="reading-now-body">' +
                    '<div class="reading-now-title" onclick="openBookModal(' + book.id + ', true)">' + _esc(book.title) + '</div>' +
                    (seriesLine ? '<div class="reading-now-series">' + seriesLine + '</div>' : '') +
                    '<div class="reading-now-author">' + _esc(book.author) + '</div>' +
                    '<div class="reading-now-progress"><div class="reading-now-progress-bar" style="width:' + pct + '%"></div></div>' +
                    '<div class="reading-now-meta">' +
                        '<span>' + pct + '%</span>' +
                        '<span class="reading-now-sep">·</span>' +
                        '<span>' + (book.last_modified ? _relativeDate(book.last_modified) : (_i18n.readingNoActivity || 'ingen aktivitet')) + '</span>' +
                    '</div>' +
                '</div>' +
                dismissBtn +
            '</div>'
        );
    }

    function _render(data) {
        var activeSec = document.getElementById('readingNowSection');
        var forgottenSec = document.getElementById('forgottenSection');
        if (!activeSec || !forgottenSec) return;

        var active = data.active || [];
        var forgotten = data.forgotten || [];

        if (active.length === 0) {
            activeSec.style.display = 'none';
        } else {
            activeSec.style.display = '';
            var list = document.getElementById('readingNowList');
            list.innerHTML = active.map(function (b, i) {
                return _renderCard(b, { hero: i === 0, dismissable: false });
            }).join('');
        }

        if (forgotten.length === 0) {
            forgottenSec.style.display = 'none';
        } else {
            forgottenSec.style.display = '';
            var fList = document.getElementById('forgottenList');
            fList.innerHTML = forgotten.map(function (b) {
                return _renderCard(b, { hero: false, dismissable: true });
            }).join('');
            var overflowEl = document.getElementById('forgottenOverflow');
            if (data.forgotten_overflow > 0) {
                overflowEl.textContent = ' · ' + (_i18n.readingMoreOnPause || '+{n} till pausade')
                    .replace('{n}', data.forgotten_overflow);
            } else {
                overflowEl.textContent = '';
            }
        }
    }

    function _fetch() {
        fetch('/reading-now', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(_render)
            .catch(function () { /* silent — non-critical surface */ });
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('.reading-now-dismiss');
        if (!btn) return;
        e.stopPropagation();
        var itemId = btn.dataset.itemId;
        if (!itemId) return;
        var card = btn.closest('.reading-now-card');
        if (card) card.style.opacity = '0.4';
        fetch('/reading-now/dismiss/' + itemId, { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function () {
                if (card) card.remove();
                /* If that was the last forgotten card, hide the section. */
                var list = document.getElementById('forgottenList');
                if (list && list.children.length === 0) {
                    document.getElementById('forgottenSection').style.display = 'none';
                }
            })
            .catch(function () {
                if (card) card.style.opacity = '';
            });
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _fetch);
    } else {
        _fetch();
    }
    window._refreshReadingNow = _fetch;
})(window, document);
