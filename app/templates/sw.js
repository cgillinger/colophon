/* Colophon service worker — version-driven caching.
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
                .filter(function (k) { return k.indexOf('colophon-') === 0 && k !== CACHE; })
                .map(function (k) { return caches.delete(k); })
        );
        await self.clients.claim();
    })());
});

self.addEventListener('message', function (event) {
    if (event.data === 'skipWaiting') self.skipWaiting();
});

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

self.addEventListener('fetch', function (event) {
    const req = event.request;
    if (req.method !== 'GET') return;

    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

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
