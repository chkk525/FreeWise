// FreeWise Service Worker — cache-first for vendored static assets only.
// Navigation and dynamic requests fall through to the browser's native
// fetch path so Cloudflare Access redirects (cross-origin 302 to
// chikaki.cloudflareaccess.com) don't trip CORS in the SW. Bumped to v5
// to force-evict the v4 SW that intercepted every navigation.
const CACHE = 'freewise-v5';

// Vendor/font files that never change — served cache-first for offline support
const PRECACHE = [
  '/static/css/fonts.css',
  '/static/vendor/htmx/htmx.min.js',
  '/static/vendor/lucide/lucide.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  // Same-origin only — leave third-party (Cloudflare Insights, etc.) alone.
  if (!e.request.url.startsWith(self.location.origin)) return;

  // Only intercept GETs to /static/. Everything else (navigation, HTMX
  // POSTs, /api/v2/*, /static/css/tailwind.css, the manifest) falls through
  // to the browser, which handles Access redirects natively.
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (!url.pathname.startsWith('/static/')) return;
  // tailwind.css rebuilds; manifest must follow Access 302 cross-origin.
  if (url.pathname === '/static/css/tailwind.css') return;
  if (url.pathname === '/static/favicons/site.webmanifest') return;

  // Cache-first with a network fallback that itself falls back to cache
  // on error (Access expired, offline, …) so a refresh doesn't break.
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).catch(() => caches.match(e.request));
    })
  );
});
