/* Colophon service worker — version-driven caching + offline reading.
 *
 * WHY THIS EXISTS (read before removing): Colophon is desktop-first and online
 * by default — over Tailscale/LAN the server is essentially always reachable —
 * but offline reading of a *downloaded* book is a real feature (v1.26.0, with
 * the landing page + book-modal save + "Downloaded" filter added v1.62.0; see
 * docs/TODO.md "Offline reading" and §12b of the handbooks). This worker does
 * three things: installability + a reliable update mechanism; caching a
 * saved book's file and reader shell into the persistent `colophon-offline`
 * cache (an explicit "save for offline" action, never silent); and a small
 * index of what's saved (OFFLINE_INDEX) that a precached /offline landing page
 * reads so a no-connection app launch lands on the "Downloaded books" shelf.
 * It stays conservative for the online case — navigations are network-first,
 * so an always-online client can never get stuck on a stale shell.
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

// Synthetic URL for the list of downloaded books (never a real route — the
// server can't know what's in the browser's cache). Read by offline.html and
// offline.js; written by indexUpsert/indexRemove below whenever a book is
// saved or removed.
const OFFLINE_INDEX = '/reader/offline-index.json';

self.addEventListener('install', function (event) {
    // Self-activate: a new worker that skipWaiting()s in its own install takes
    // over immediately — the OLD worker and the page don't have to allow it.
    // This is deliberate (it reverses the earlier "wait for a prompt" policy):
    // without it, a deploy leaves the old worker controlling an installed PWA
    // until the user happens to tap an update toast, and until then the new
    // offline-index code never runs — so "save for offline" caches the file
    // but writes no index entry and the Downloaded shelf stays empty. The
    // matching page-side change (app/templates/_layout.html) is what makes
    // this safe: it no longer reloads on controllerchange, so taking over
    // mid-edit can't lose work. The offline feature needs the new worker to
    // *control* the page (clients.claim below), not a reload.
    self.skipWaiting();
    // Precache the offline landing page so opening the PWA with no connection
    // always lands on the "Downloaded books" shelf instead of a dead
    // fallback. Deliberately in the persistent OFFLINE cache (not the
    // per-version one) so it survives version bumps.
    event.waitUntil(
        caches.open(OFFLINE).then(function (c) {
            return c.add(new Request('/offline', { cache: 'reload' }));
        }).catch(function () { /* first install may be offline itself */ })
    );
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

    // Offline-reader controls from the reader page / library view. Each
    // replies to the sender so the UI can reflect the result (saved /
    // removed / current state).
    if (data.type === 'cacheBook') {
        event.waitUntil(cacheBook(data.assets || []).then(function (ok) {
            // Only a successful cache earns a place on the "Downloaded
            // books" shelf — a partial failure must not claim the book is
            // available offline.
            var indexed = ok
                ? indexUpsert({ id: data.id, title: data.title, author: data.author, coverUrl: data.coverUrl })
                : Promise.resolve();
            return indexed.then(function () {
                reply(event, { type: 'cacheBook', id: data.id, ok: ok });
            });
        }));
    } else if (data.type === 'removeBook') {
        event.waitUntil(removeBook(data.assets || []).then(function () {
            return indexRemove(data.id);
        }).then(function () {
            reply(event, { type: 'removeBook', id: data.id, ok: true });
        }));
    } else if (data.type === 'isBookCached') {
        event.waitUntil(isBookCached(data.fileUrl).then(function (cached) {
            reply(event, { type: 'isBookCached', id: data.id, cached: cached });
        }));
    } else if (data.type === 'listCachedBooks') {
        event.waitUntil(readIndex().then(function (list) {
            reply(event, { type: 'listCachedBooks', books: list });
        }));
    }
});

function reply(event, msg) {
    // Prefer the dedicated MessageChannel port the page sent (reliable on iOS
    // Safari); fall back to event.source for older callers.
    if (event.ports && event.ports[0]) { event.ports[0].postMessage(msg); return; }
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

// The offline index: a small JSON list of {id,title,author,coverUrl}, stored
// as a synthetic Response at OFFLINE_INDEX inside the OFFLINE cache itself —
// no IndexedDB needed for something this small, and it lives in the same
// cache as the books it describes so it can never point at content that was
// evicted separately.
async function readIndex() {
    try {
        const cache = await caches.open(OFFLINE);
        const hit = await cache.match(OFFLINE_INDEX);
        if (!hit) return [];
        return await hit.json();
    } catch (e) { return []; }
}
async function writeIndex(list) {
    const cache = await caches.open(OFFLINE);
    await cache.put(OFFLINE_INDEX, new Response(JSON.stringify(list), {
        headers: { 'Content-Type': 'application/json' }
    }));
}
async function indexUpsert(book) {
    if (!book || book.id == null) return;
    const list = await readIndex();
    const rest = list.filter(function (b) { return String(b.id) !== String(book.id); });
    rest.push({
        id: book.id, title: book.title || String(book.id),
        author: book.author || '', coverUrl: book.coverUrl || ''
    });
    await writeIndex(rest);
}
async function indexRemove(id) {
    const list = await readIndex();
    await writeIndex(list.filter(function (b) { return String(b.id) !== String(id); }));
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
        // Last resort before the bare 503: the precached offline landing page,
        // so "no connection at all" opens on the "Downloaded books" shelf
        // instead of a dead end.
        const offline = await (await caches.open(OFFLINE)).match('/offline');
        if (offline) return offline;
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

    // Synthetic offline index: always from cache, never the network — an
    // empty list if nothing has been saved yet, so the shelf renders its
    // empty state rather than failing the fetch.
    if (url.pathname === OFFLINE_INDEX) {
        event.respondWith(readIndex().then(function (list) {
            return new Response(JSON.stringify(list), {
                headers: { 'Content-Type': 'application/json' }
            });
        }));
        return;
    }
    // The precached offline landing page: cache-first so it opens with no
    // network at all, even on a direct/first visit while offline.
    if (url.pathname === '/offline') {
        event.respondWith(offlineFirst(req));
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
