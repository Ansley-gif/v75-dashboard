/* ================================================================
   V75 Dashboard — Service Worker (PWA offline support)
   ================================================================ */

const CACHE_NAME = 'v75-dash-v1';
const STATIC_ASSETS = [
  '/',
  '/static/css/dashboard.css',
  '/static/js/dashboard.js',
  '/static/manifest.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg'
];

// Install: cache static shell
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API, cache-first for static assets
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API calls — always network, no cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request).catch(() =>
      new Response(JSON.stringify({ error: 'Offline' }), {
        headers: { 'Content-Type': 'application/json' }
      })
    ));
    return;
  }

  // Static assets — cache first, fallback to network
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        // Cache successful GET responses
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    }).catch(() =>
      // Ultimate fallback for navigation
      event.request.mode === 'navigate' ? caches.match('/') : undefined
    )
  );
});
