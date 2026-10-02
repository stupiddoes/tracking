// Offline reading: keeps the app shell, album data and thumbnails so the album opens without a network.
// Cache names are shared with src/App.tsx, which clears the data caches on login and logout.
const SHELL = 'shell-v1';
const DATA = 'album-data-v1';
const THUMBS = 'thumbnails-v1';
const DATA_PATHS = [
  /^\/api\/v1\/auth\/me$/,
  /^\/api\/v1\/characters\/$/,
  /^\/api\/v1\/characters\/[^/]+\/conversations$/,
  /^\/api\/v1\/memory-assets\/$/,
  /^\/api\/v1\/memory-assets\/[^/]+\/$/,
];
const THUMBNAIL_PATH = /^\/api\/v1\/memory-assets\/[^/]+\/thumbnail\/$/;

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    const response = await fetch('/index.html', { cache: 'no-store' });
    const html = await response.clone().text();
    // Vite gives built files hashed names, so read them from the page instead of hard-coding them.
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((match) => match[1]);
    await cache.put('/index.html', response);
    await cache.addAll([...new Set(assets), '/manifest.webmanifest', '/icons/icon-192.png']);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = [SHELL, DATA, THUMBS];
    for (const name of await caches.keys()) if (!keep.includes(name)) await caches.delete(name);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') event.respondWith(networkFirst(request, SHELL, '/index.html'));
  else if (url.pathname.startsWith('/assets/')) event.respondWith(cacheFirst(request, SHELL));
  else if (THUMBNAIL_PATH.test(url.pathname)) event.respondWith(thumbnail(request));
  else if (DATA_PATHS.some((path) => path.test(url.pathname))) event.respondWith(networkFirst(request, DATA));
});

async function networkFirst(request, cacheName, key = request) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(key, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(key, { ignoreVary: true });
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

// Thumbnail URLs carry the image version, so a cached copy never goes stale. Chat attachments
// ask for the unversioned URL; offline, any cached version of that photo is good enough.
async function thumbnail(request) {
  const cache = await caches.open(THUMBS);
  const cached = await cache.match(request, { ignoreVary: true });
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const anyVersion = await cache.match(request, { ignoreSearch: true, ignoreVary: true });
    if (anyVersion) return anyVersion;
    throw error;
  }
}
