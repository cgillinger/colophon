/* Colophon – global offline reading-progress flush.
 *
 * The in-browser reader (reader.js) mirrors reading progress to localStorage,
 * marked `synced:false` while it hasn't reached the server, and re-syncs its
 * OWN book on reconnect. But a book read offline whose reader you then leave —
 * returning to the library, or opening a different book — used to keep its
 * unsynced progress until you happened to reopen that exact book online. This
 * closes that gap: it scans EVERY `colophon-reader-progress-<id>` entry and
 * pushes the unsynced ones up, so all books you read offline keep their sync
 * with the mother system, not just the last one open.
 *
 * Loaded on the main app (via _layout.html) and in the reader (reader.html),
 * so wherever you regain a connection, everything drains. Runs at load and on
 * the 'online' event. Safe to double-post with reader.js: the server merge is
 * monotonic / furthest-read-wins, so a late or slightly-stale post can never
 * move a book backwards. Only touches entries the reader itself wrote.
 */
(function (window, document) {
    'use strict';

    var KEY_RE = /^colophon-reader-progress-(\d+)$/;

    function pendingEntries() {
        var out = [];
        var ls;
        try { ls = window.localStorage; } catch (e) { return out; }
        if (!ls) return out;
        for (var i = 0; i < ls.length; i++) {
            var key = ls.key(i);
            var m = key && key.match(KEY_RE);
            if (!m) continue;
            try {
                var val = JSON.parse(ls.getItem(key) || 'null');
                if (val && val.synced === false &&
                    (val.percent != null || val.status)) {
                    out.push({ key: key, id: m[1], val: val });
                }
            } catch (e) { /* skip a corrupt entry */ }
        }
        return out;
    }

    // Mark synced only if the stored copy is still the one we posted. On a
    // reader page, reader.js may write newer unsynced progress between our POST
    // and its response; blindly writing synced:true would strand that newer
    // progress (never flushed until some later relocate rewrites it). Compare
    // savedAt (+ percent) and leave a changed entry alone — it goes on the next
    // load/online tick.
    function markSyncedIfUnchanged(key, postedSavedAt, postedPercent) {
        try {
            var cur = JSON.parse(window.localStorage.getItem(key) || 'null');
            if (!cur || cur.synced === true) return;
            if (String(cur.savedAt) === String(postedSavedAt) && cur.percent === postedPercent) {
                cur.synced = true;
                window.localStorage.setItem(key, JSON.stringify(cur));
            }
        } catch (e) { /* private mode / quota — will retry next time */ }
    }

    // The book currently open in the reader (if any) is reader.js's to sync: it
    // posts the exact location (href/offset) and runs its own flushUnsynced.
    // Skipping it here avoids clobbering that exact position with a
    // percent-only post — and avoids a redundant double-post.
    function currentReaderBookId() {
        try {
            var cfg = window.__readerConfig;
            return cfg && cfg.itemId != null ? String(cfg.itemId) : null;
        } catch (e) { return null; }
    }

    function flushAll() {
        if (!navigator.onLine) return;
        var selfId = currentReaderBookId();
        pendingEntries().forEach(function (p) {
            if (selfId && p.id === selfId) return;
            // Percent + status only: the exact location (href/offset) isn't
            // mirrored to localStorage, and the server derives a chapter from
            // the percent when none is sent — same as reader.js's own reconnect
            // flush. savedAt lets the server drop a stale post that would undo a
            // reset. keepalive lets it complete through a navigation.
            var savedAt = p.val.savedAt, percent = p.val.percent;
            fetch('/reader/' + p.id + '/progress', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ percent: percent, status: p.val.status, savedAt: savedAt }),
                keepalive: true
            }).then(function (r) {
                if (r && r.ok) markSyncedIfUnchanged(p.key, savedAt, percent);
            }).catch(function () { /* stays unsynced; retried on next load / online */ });
        });
    }

    window.addEventListener('online', flushAll);
    // A previous offline session may have left pending progress for any number
    // of books; drain them as soon as any page loads with a connection.
    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', flushAll);
    } else {
        flushAll();
    }
})(window, document);
