/* Mors service worker (MVP-offline, spec §19 / review fix list).
   Rules:
   - cache-first  : immutable static assets (/_next/static, mascots, icons, fonts)
   - network-first: content API (/api/media/*) with cache fallback
   - network-first: page navigations, small page cache + /offline.html fallback
   - never cached : auth, AI, exams, chat, voice, progress writes — anything else.
*/
const VERSION = "mors-v1";
const STATIC_CACHE = VERSION + "-static";
const CONTENT_CACHE = VERSION + "-content";
const PAGE_CACHE = VERSION + "-pages";
const KEEP = [STATIC_CACHE, CONTENT_CACHE, PAGE_CACHE];
const PAGE_CACHE_MAX = 8;

function isContent(url) {
  return url.pathname.startsWith("/api/media/");
}

function isStatic(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/mors/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname === "/manifest.json" ||
    /\.(?:png|jpe?g|webp|svg|ico|woff2?|ttf|otf)$/i.test(url.pathname)
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) =>
        cache.addAll([
          "/offline.html",
          "/manifest.json",
          "/mors/neutral.png",
          "/icons/icon-192.png",
        ])
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => KEEP.indexOf(key) === -1).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

async function trim(cache, max) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirstContent(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CONTENT_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(
      JSON.stringify({ detail: "تحتاج اتصالاً بالإنترنت لعرض هذا المحتوى." }),
      { status: 503, headers: { "Content-Type": "application/json; charset=utf-8" } }
    );
  }
}

async function networkFirstPage(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(PAGE_CACHE);
      cache.put(request, response.clone());
      await trim(cache, PAGE_CACHE_MAX);
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    const offline = await caches.match("/offline.html");
    if (offline) return offline;
    return new Response("Offline", { status: 503 });
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/") && !isContent(url)) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request));
    return;
  }
  if (isContent(url)) {
    event.respondWith(networkFirstContent(request));
    return;
  }
  if (isStatic(url)) {
    event.respondWith(cacheFirst(request));
    return;
  }
  // anything else: straight to the network, never cached.
});
