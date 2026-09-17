/* Colophon – "Downloaded" overview for the library view
 *
 * Talks to the service worker (see app/templates/sw.js) so the bulk view can
 * show which rows are already saved for offline reading, offer a
 * "Downloaded" filter chip, and let the book modal save/remove a book
 * without opening the reader first. The server has no idea what's in the
 * browser's Cache Storage, so every fact here comes from a postMessage round
 * trip to the SW — there is no client-side truth kept independently.
 *
 * Published on window.colophonOffline: { refreshDownloaded, saveForOffline,
 * removeOffline, isSaved, swReady }. book-modal.js calls these directly.
 */
(function (window, document) {
    'use strict';

    var _i18n = (window.__colophonConfig && window.__colophonConfig.i18n) || {};
    function t(key, fallback) { return _i18n[key] || fallback; }

    function shellAssets() {
        return (window.__colophonConfig && window.__colophonConfig.shellAssets) || [];
    }

    function coverUrlFor(id) {
        var base = window.__colophonConfig && window.__colophonConfig.urls
            && window.__colophonConfig.urls.coverItemBase;
        return (base || '') + '/' + id + '?w=320';
    }

    function assetsFor(id) {
        return ['/reader/' + id, '/reader/' + id + '/file', coverUrlFor(id)].concat(shellAssets());
    }

    // One-shot request/response to the controlling SW over a dedicated
    // MessageChannel port. Copied from reader.js's swRequest — more reliable
    // on iOS Safari than an event.source reply, which can be null there.
    function swRequest(message, timeoutMs) {
        return new Promise(function (resolve) {
            var sw = ('serviceWorker' in navigator) && navigator.serviceWorker.controller;
            if (!sw) { resolve(null); return; }
            var done = false;
            var ch = new MessageChannel();
            ch.port1.onmessage = function (ev) {
                if (done) return;
                done = true;
                resolve(ev.data || null);
            };
            try {
                sw.postMessage(message, [ch.port2]);
            } catch (e) { resolve(null); return; }
            setTimeout(function () { if (!done) { done = true; resolve(null); } }, timeoutMs || 60000);
        });
    }

    function swReady() {
        return ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller;
    }

    // Ask the SW what it has, then reflect that onto the table (per-row
    // dataset for the filter) and the chip (count + a rough size estimate).
    function refreshDownloaded() {
        return swRequest({ type: 'listCachedBooks' }, 8000).then(function (res) {
            var books = (res && res.books) || [];
            var ids = books.map(function (b) { return String(b.id); });
            var idSet = {};
            ids.forEach(function (id) { idSet[id] = true; });

            document.querySelectorAll('#bookTableBody tr').forEach(function (row) {
                row.dataset.offlineCached = idSet[row.dataset.itemId] ? '1' : '';
            });

            var wrap = document.getElementById('downloadedChipWrap');
            var chip = document.getElementById('libraryChipDownloaded');
            if (ids.length > 0) {
                if (chip) chip.textContent = t('downloadedChip', '{count} downloaded').replace('{count}', ids.length);
                if (wrap) wrap.style.display = '';
                if (chip && navigator.storage && navigator.storage.estimate) {
                    navigator.storage.estimate().then(function (est) {
                        if (!est || est.usage == null) return;
                        var mb = Math.round(est.usage / 1048576);
                        chip.title = ids.length + ' offline · ' + mb + ' MB';
                    }).catch(function () { /* estimate unavailable */ });
                }
            } else {
                if (wrap) wrap.style.display = 'none';
                // The filter can't point at nothing — drop it so the table
                // doesn't stay stuck on an empty "downloaded" view.
                if (window._getBadgeFilter && window._getBadgeFilter() === 'downloaded:1' && window.setBadgeFilter) {
                    window.setBadgeFilter(null);
                }
            }

            if (window.applyFilters) window.applyFilters();
            return books;
        });
    }

    function saveForOffline(id, meta) {
        meta = meta || {};
        return swRequest({
            type: 'cacheBook', id: id,
            title: meta.title, author: meta.author, coverUrl: coverUrlFor(id),
            assets: assetsFor(id)
        }, 120000).then(function (res) {
            return !!(res && res.ok);
        });
    }

    function removeOffline(id) {
        // Shell assets are NOT removed — other saved books still need them,
        // exactly as in reader.js's toggleOffline.
        return swRequest({
            type: 'removeBook', id: id,
            assets: ['/reader/' + id, '/reader/' + id + '/file', coverUrlFor(id)]
        }, 15000).then(function () { return true; });
    }

    function isSaved(id) {
        return swRequest({ type: 'isBookCached', id: id, fileUrl: '/reader/' + id + '/file' }, 8000)
            .then(function (res) { return !!(res && res.cached); });
    }

    window.colophonOffline = {
        refreshDownloaded: refreshDownloaded,
        saveForOffline: saveForOffline,
        removeOffline: removeOffline,
        isSaved: isSaved,
        swReady: swReady
    };

    function init() {
        if (!('serviceWorker' in navigator)) return;
        if (navigator.serviceWorker.controller) refreshDownloaded();
        navigator.serviceWorker.addEventListener('controllerchange', refreshDownloaded);
    }

    init();
})(window, document);
