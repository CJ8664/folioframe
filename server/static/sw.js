/* SpectraFrame service worker: app-shell caching + offline fallback. */
const CACHE = "spectraframe-v2";
const SHELL = [
  "/",
  "/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/icon-180.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  // API calls, device endpoints, and the firmware flasher always go to the
  // network. /flash/* must never be served from cache: a stale cached
  // manifest or firmware binary would silently flash an outdated build.
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/v1/") ||
      url.pathname.startsWith("/flash")) return;
  e.respondWith(
    (async () => {
      // Navigations: network first, fall back to the cached shell offline.
      if (e.request.mode === "navigate") {
        try {
          const res = await fetch(e.request);
          const cache = await caches.open(CACHE);
          cache.put("/", res.clone());
          return res;
        } catch (_) {
          const cached = await caches.match("/");
          return cached || Response.error();
        }
      }
      // Static assets: cache first, then network.
      const cached = await caches.match(e.request);
      if (cached) return cached;
      try {
        const res = await fetch(e.request);
        const cache = await caches.open(CACHE);
        cache.put(e.request, res.clone());
        return res;
      } catch (_) {
        return cached || Response.error();
      }
    })()
  );
});
