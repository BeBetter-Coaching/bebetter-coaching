// Minimale service worker: cache de app-shell zodat de PWA installeerbaar is en
// de interface ook zonder netwerk opent. Data (/api/*) gaat altijd live naar de
// server, zodat je nooit een verouderde strippenkaart te zien krijgt.
const CACHE = "bebetter-shell-v1";
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
  if (url.pathname.startsWith("/api/")) return; // data: altijd netwerk
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
