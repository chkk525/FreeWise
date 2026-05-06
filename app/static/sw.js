// FreeWise Service Worker — network-first for dynamic content, cache-first for static assets.
// Bump CACHE on any change to a precached file (fonts.css, vendored libs) to
// force-evict stale copies on the QNAP/Cloudflare-fronted deploy. v5 adds
// Crimson Pro back to fonts.css (Minna restoration); v6 expects Inter +
// Noto Sans JP under /static/fonts/minna/.
const CACHE = 'freewise-v6';

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
  if (!e.request.url.startsWith(self.location.origin)) return;
  const url = new URL(e.request.url);

  // tailwind.css is rebuilt frequently — let the browser handle it natively,
  // bypassing the SW cache entirely so updates are always visible immediately.
  if (url.pathname === '/static/css/tailwind.css') return;

  // Precached static assets (fonts, vendor libs) — cache-first.
  // User uploads under /static/uploads/ should stay network-handled.
  if (PRECACHE.includes(url.pathname)) {
    e.respondWith(caches.match(e.request).then(cached => cached || fetch(e.request)));
    return;
  }

  // Navigation — network-first (always fresh server data)
  e.respondWith(fetch(e.request));
});
