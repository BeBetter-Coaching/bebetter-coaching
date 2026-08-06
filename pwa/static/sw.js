// Service worker: maakt de PWA installeerbaar en werkt offline.
// - app-shell (html/js/css/icons): uit cache, snel.
// - GET /api/kaarten: network-first, met cache-fallback -> je ziet offline de
//   laatste stand van je strippenkaarten.
// - overige /api (afboeken/toevoegen): altijd netwerk; offline handelt de app dit
//   zelf af met een wachtrij die verstuurt zodra je weer online bent.
const CACHE = "bebetter-shell-v4";
const SHELL = ["/", "/static/styles.css", "/static/app.js",
  "/static/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.pathname === "/api/kaarten" && e.request.method === "GET") {
    e.respondWith(
      fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  if (url.pathname.startsWith("/api/")) return; // schrijf-acties: altijd netwerk
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
