// Service worker: maakt de PWA installeerbaar en werkt offline.
// Strategie NETWORK-FIRST voor de app-schil (html/js/css) én voor GET /api/kaarten:
//   online zie je dus altijd meteen de nieuwste versie; offline valt hij terug op
//   de laatst gecachete kopie. Zo loop je na een update niet meer één laadbeurt
//   achter (dat gebeurde met de oude cache-first-aanpak).
// Schrijf-acties (POST/DELETE op /api/…) gaan altijd rechtstreeks naar het netwerk;
// de app zelf handelt offline af met een wachtrij die verstuurt zodra je online bent.
const CACHE = "bebetter-shell-v41";
const SHELL = ["/", "/static/styles.css", "/static/app.js",
  "/static/icon-192.png", "/static/logo.png", "/static/team.jpeg", "/manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

// Netwerk eerst; bij succes de cache verversen; bij geen netwerk uit cache serveren.
function networkFirst(req) {
  return fetch(req).then(res => {
    const copy = res.clone();
    caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
    return res;
  }).catch(() => caches.match(req).then(r => r || caches.match("/")));
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;                 // schrijf-acties: altijd netwerk
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;       // externe requests niet aanraken
  // Overige /api/-GETs (dossier, inbox, link): altijd netwerk, geen cache nodig.
  if (url.pathname.startsWith("/api/") && url.pathname !== "/api/kaarten") return;
  e.respondWith(networkFirst(req));                 // schil + /api/kaarten: network-first
});
