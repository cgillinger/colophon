/* Colophon service worker — version-driven caching.
 *
 * WHY THIS EXISTS (read before removing): Colophon is desktop-first and has no
 * offline use case today — the app is useless without the server. This worker
 * is deliberate groundwork for a possible future in-browser reader, where
 * offline reading of a downloaded book WOULD be a real feature (see
 * docs/TODO.md "In-browser reader + offline"). What it provides now is the
 * reusable plumbing: installability and a reliable update mechanism. It does
 * NOT cache book content — that is net-new work (explicit "download for
 * offline" into Cache Storage/IndexedDB + quota/eviction) to be built with the
 * reader, not something this file gives for free. It is intentionally
 * conservative (navigations are network-first, so an always-online LAN/Tailscale
 * client can never get stuck on a stale shell), so keeping it dormant is safe.
 *
 * Rendered by Flask (see /sw.js route) so {{ app_version }} is baked into
 * the file body. That matters twice over:
 *   1. The cache name is tied to the app version, so a version bump means a
 *      brand-new cache and the old one is purged in `activate`.
 *   2. Because the version string lives in the file *body*, bumping the
 *      version changes the bytes of this file. The browser byte-compares the
 *      SW on every check and treats a changed file as an update — which is
 *      what drives the "new version available" prompt. The /sw.js route also
 *      sends `Cache-Control: no-cache`, so this controlling file is never
 *      itself served stale.
 *
 * Strategy, by request type:
 *   - Versioned static assets (/static/...?v=X) -> cache-first. Safe because
 *     the URL changes on every version bump, so a cached entry can never be
 *     stale.
 *   - Navigations / HTML            -> network-first, falling back to cache
 *     only when offline. The app shell is always fresh when the server is
 *     reachable (which, over Tailscale/LAN, it essentially always is).
 *   - Everything else (SSE, /scan, /kobo, POSTs, cover fetches, the API) ->
 *     not intercepted at all. We never call respondWith for these, so the
 *     browser handles them normally and live event-streams are never cached.
 */
const VERSION = '{{ app_version }}';
const CACHE = 'colophon-v' + VERSION;

// Persistent cache for offline reading. Deliberately NOT version-tied: a
// downloaded book and its reader shell must survive app updates, so `activate`
// keeps this cache while purging the per-version one. Populated by an explicit
// "save for offline" action in the reader (postMessage 'cacheBook'); foliate's
// module graph is runtime-cached here too (see fetch handler) because those
// relative imports carry no ?v= and so escape the versioned-static rule.
const OFFLINE = 'colophon-offline';
const READER_FILE = /^\/reader\/\d+\/file$/;
const READER_PAGE = /^\/reader\/\d+$/;
const FOLIATE_PREFIX = '/static/vendor/foliate-js/';

self.addEventListener('install', function () {
    // Do NOT skipWaiting here. The new worker waits until the page tells it
    // to (via the "new version" prompt), so we never reload out from under
    // an in-progress edit.
});

self.addEventListener('activate', function (event) {
    event.waitUntil((async function () {
        const keys = await caches.keys();
        await Promise.all(
            keys
                .filter(function (k) { return k.indexOf('colophon-') === 0 && k !== CACHE && k !== OFFLINE; })
                .map(function (k) { return caches.delete(k); })
        );
        await self.clients.claim();
    })());
});

self.addEventListener('message', function (event) {
    const data = event.data;
    if (data === 'skipWaiting') { self.skipWaiting(); return; }
    if (!data || typeof data !== 'object') return;

    // Offline-reader controls from the reader page. Each replies to the sender
    // so the UI can reflect the result (saved / removed / current state).
    if (data.type === 'cacheBook') {
        event.waitUntil(cacheBook(data.assets || []).then(function (ok) {
            reply(event, { type: 'cacheBook', id: data.id, ok: ok });
        }));
    } else if (data.type === 'removeBook') {
        event.waitUntil(removeBook(data.assets || []).then(function () {
            reply(event, { type: 'removeBook', id: data.id, ok: true });
        }));
    } else if (data.type === 'isBookCached') {
        event.waitUntil(isBookCached(data.fileUrl).then(function (cached) {
            reply(event, { type: 'isBookCached', id: data.id, cached: cached });
        }));
    }
});

function reply(event, msg) {
    if (event.source) event.source.postMessage(msg);
}

// Cache a book's full offline bundle. Per-asset fetch+put (not cache.addAll)
// so one odd asset can't sink the whole download. `cache: 'reload'` bypasses
// the HTTP cache to snapshot a fresh, self-consistent set for the version
// that's live right now.
async function cacheBook(assets) {
    try {
        const cache = await caches.open(OFFLINE);
        await Promise.all(assets.map(async function (u) {
            try {
                const res = await fetch(u, { cache: 'reload' });
                if (res && res.ok) await cache.put(u, res.clone());
            } catch (e) { /* skip this asset; book may still be readable */ }
        }));
        return true;
    } catch (e) { return false; }
}

// Remove only the per-book assets (the EPUB + its reader page). Shared deps
// (foliate modules, reader.js, CSS, fonts) are left so other downloaded books
// keep working.
async function removeBook(assets) {
    const cache = await caches.open(OFFLINE);
    await Promise.all(assets.map(function (u) { return cache.delete(u); }));
}

async function isBookCached(fileUrl) {
    if (!fileUrl) return false;
    const cache = await caches.open(OFFLINE);
    const hit = await cache.match(fileUrl);
    return !!hit;
}

async function cacheFirst(req) {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req);
    if (hit) return hit;
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
}

async function networkFirst(req) {
    const cache = await caches.open(CACHE);
    try {
        const res = await fetch(req);
        if (res && res.ok) cache.put(req, res.clone());
        return res;
    } catch (err) {
        const hit = await cache.match(req);
        if (hit) return hit;
        const root = await cache.match('/');
        if (root) return root;
        return new Response(
            '<!doctype html><meta charset="utf-8">' +
            '<meta name="viewport" content="width=device-width, initial-scale=1">' +
            '<title>Colophon — offline</title>' +
            '<body style="font-family:system-ui;padding:2rem;text-align:center;color:#444">' +
            '<h1>Offline</h1><p>Colophon kan inte nås just nu och den här sidan finns inte i cachen än.</p></body>',
            { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
    }
}

// Serve from the persistent offline cache if present, else go to the network.
// Never writes — only an explicit "save for offline" populates this cache, so
// books the user didn't download are never silently stored.
async function offlineFirst(req) {
    const cache = await caches.open(OFFLINE);
    const hit = await cache.match(req);
    if (hit) return hit;
    return fetch(req);
}

// Reader page: prefer the network (fresh progress/markup), fall back to the
// downloaded copy when offline so a saved book still opens.
async function readerPage(req) {
    const cache = await caches.open(OFFLINE);
    try {
        return await fetch(req);
    } catch (err) {
        const hit = await cache.match(req);
        if (hit) return hit;
        throw err;
    }
}

// Stale-while-revalidate into a given cache: serve the cached copy instantly,
// refresh it in the background. Used for foliate's module graph so the reader
// shell is complete offline once it has run online at least once.
async function staleWhileRevalidate(req, cacheName) {
    const cache = await caches.open(cacheName);
    const hit = await cache.match(req);
    const net = fetch(req).then(function (res) {
        if (res && res.ok) cache.put(req, res.clone());
        return res;
    }).catch(function () { return hit; });
    return hit || net;
}

self.addEventListener('fetch', function (event) {
    const req = event.request;
    if (req.method !== 'GET') return;

    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    // Offline reading (checked before the generic rules below):
    //   - the book file        -> offline-cache-first (download-only)
    //   - the reader page       -> network-first, offline copy as fallback
    //   - foliate modules       -> stale-while-revalidate into the persistent
    //                              cache (relative imports, no ?v=)
    if (READER_FILE.test(url.pathname)) {
        event.respondWith(offlineFirst(req));
        return;
    }
    if (READER_PAGE.test(url.pathname)) {
        event.respondWith(readerPage(req));
        return;
    }
    if (url.pathname.indexOf(FOLIATE_PREFIX) === 0) {
        event.respondWith(staleWhileRevalidate(req, OFFLINE));
        return;
    }

    // Versioned static assets: cache-first.
    if (url.pathname.indexOf('/static/') === 0 && url.searchParams.has('v')) {
        event.respondWith(cacheFirst(req));
        return;
    }

    // Navigations / HTML documents: network-first with offline fallback.
    const accept = req.headers.get('accept') || '';
    if (req.mode === 'navigate' || accept.indexOf('text/html') !== -1) {
        event.respondWith(networkFirst(req));
        return;
    }

    // Anything else (SSE, /scan, /kobo, API, covers): leave to the browser.
});
