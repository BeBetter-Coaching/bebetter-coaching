// WhatsApp Flow v1 — EXECUTEERBARE clienttests.
//
//   node tests/js/strippenkaart_whatsapp.test.mjs
//
// Snijdt de ECHTE strippenkaart-module (incl. de berichtenfase) verbatim uit
// pwa/static/app.js en draait hem tegen een DOM-shim. Bewijst:
//   A  batch van 1: openen → geopend → 1 van 1 → eindstaat → klaar
//   B  batches van 5 en 15: status per persoon, teller klopt, ook buiten volgorde
//   C  Volgende: eerstvolgende ongeopende, slaat geopende over, eindstaat
//   D  terugkeer: status overleeft hertekenen, verse read én een herstart van de app
//   E  nieuwe batch: geen lek van oude status; zelfde batch-id houdt de voortgang;
//      gewijzigde stand of verlopen lijst vervalt
//   F  tekst: naam en saldo uit het serverantwoord, kaart-op benoemd
//   G  semantiek: alleen 'geopend', nooit verstuurd/verzonden/afgeleverd/ontvangen
//   H  geen automatische messaging: geen server-write, geen programmatisch openen,
//      dubbeltik opent geen tweede gesprek
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = readFileSync(join(ROOT, "pwa", "static", "app.js"), "utf8");
const IDX = readFileSync(join(ROOT, "pwa", "static", "index.html"), "utf8");

function sliceFrom(header) {
  const i = SRC.indexOf(header);
  if (i < 0) throw new Error("not found: " + header);
  const b = SRC.indexOf("{", i);
  let d = 0;
  for (let j = b; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) return SRC.slice(i, j + 1); }
  }
  throw new Error("unbalanced: " + header);
}
const sliceLine = p => {
  const i = SRC.indexOf(p);
  if (i < 0) throw new Error("not found: " + p);
  return SRC.slice(i, SRC.indexOf("\n", i));
};
function sliceBetween(van, tot) {
  const i = SRC.indexOf(van), j = SRC.indexOf(tot, i);
  if (i < 0 || j < 0) throw new Error("not found: " + van + " .. " + tot);
  return SRC.slice(i, j);
}

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };
const tick = () => new Promise(r => setTimeout(r, 0));

// Een bestuurbare klok: de dubbeltik-grens (800 ms) en de houdbaarheid (18 u) zijn
// tijdsregels; de tests zetten de tijd zelf in plaats van te wachten.
let klok = 1_800_000_000_000;
Date.now = () => klok;
const later = (ms = 1000) => { klok += ms; };

// ── DOM-shim (zelfde principe als strippenkaart_cockpit.test.mjs) ───────────
class El {
  constructor(tag) {
    this.tag = tag || "div"; this.children = []; this.parent = null;
    this.dataset = {}; this.attrs = {}; this.disabled = false; this.hidden = false;
    this.value = ""; this._html = ""; this._txt = ""; this._q = new Map(); this._on = {};
    const s = this._cls = new Set();
    this.classList = {
      add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
      toggle: (c, on) => { const wil = on === undefined ? !s.has(c) : on; if (wil) s.add(c); else s.delete(c); return wil; },
    };
  }
  get className() { return [...this._cls].join(" "); }
  set className(v) { this._cls.clear(); String(v || "").split(/\s+/).filter(Boolean).forEach(c => this._cls.add(c)); }
  get innerHTML() { return this._html; }
  set innerHTML(v) {
    this._html = String(v == null ? "" : v); this._q = new Map(); this._txt = "";
    this.children.forEach(c => { c.parent = null; }); this.children = [];
  }
  get textContent() { return this._txt || this._html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim(); }
  set textContent(v) { this._txt = String(v == null ? "" : v); }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this._on[t] = this._on[t] || []).push(f); }
  async vuur(t, ev) { for (const f of (this._on[t] || [])) await f(ev || {}); }
  focus() {}
  scrollTo(o) { this.scrollTop = (o && o.top) || 0; }
  closest(sel) {
    const haak = String(sel).replace(/^[.#[]/, "").replace(/\]$/, "");
    let n = this;
    while (n) { if (n._cls.has(haak) || n.attrs[haak] !== undefined || n.id === haak) return n; n = n.parent; }
    return null;
  }
  _haak(sel) { const m = /^[.#[]?([a-z0-9_-]+)\]?$/i.exec(String(sel)); return m ? m[1] : String(sel); }
  querySelector(sel) {
    const haak = this._haak(sel);
    if (this._q.has(haak)) return this._q.get(haak);
    if (!this._html.includes(haak)) {
      for (const kind of this.children) { const t = kind.querySelector(sel); if (t) return t; }
      return null;
    }
    const el = new El("div"); el.className = haak; el.parent = this;
    this._q.set(haak, el);
    return el;
  }
  querySelectorAll(sel) { const e = this.querySelector(sel); return e ? [e] : []; }
}

const IDS = ["#lijst", "#sk-bar", "#sk-af", "#sk-bar-let", "#sk-telling", "#sk-alles", "#sk-wis",
  "#sk-uitkomst", "#sk-bar-actie", "#sk-q", "#bron", "#msg",
  "#sk-kaarten", "#sk-berichten", "#sk-b-bar", "#sk-b-hervat", "#sk-b-lijst", "#sk-b-teller",
  "#sk-b-meter", "#sk-volgende", "#sk-b-klaar", "#sk-b-terug", "#scroller"];
// Elke id die de module aanspreekt MOET in de echte markup staan — anders test deze
// suite een DOM die de app niet heeft.
IDS.filter(id => !["#msg", "#bron", "#scroller"].includes(id)).forEach(id =>
  ok(IDX.includes(`id="${id.slice(1)}"`), `markup: ${id} bestaat in index.html`));

let els = {};
function nieuweDom() {
  els = {};
  IDS.forEach(id => { els[id] = new El("div"); els[id].id = id.slice(1); });
  els["#sk-berichten"].hidden = true; els["#sk-b-bar"].hidden = true;
  els["#sk-b-hervat"].hidden = true; els["#sk-uitkomst"].hidden = true;
}
const document = {
  createElement: t => new El(t),
  querySelector: sel => els[sel] || null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};

// ── Stubs rond de module ────────────────────────────────────────────────────
let meldingen = [], calls = [], antwoord = null, bevestigAntwoord = true;
let lijstAntwoord = { kaarten: [], cloud: true };
const navigator = { onLine: true, vibrate: () => {} };
const self = { crypto: { randomUUID: () => "cid-" + (calls.length + 1) } };
const api = async (u, o) => {
  calls.push({ url: u, method: (o && o.method) || "GET" });
  return u === "/api/kaarten" ? { ...lijstAntwoord, kaarten: lijstAntwoord.kaarten.map(k => ({ ...k })) } : antwoord;
};
const jpost = async (u, body) => { calls.push({ url: u, body }); return antwoord; };
const melding = (t, err) => meldingen.push({ t, err });
const enqueue = () => {};
const bevestigActie = async opts => { calls.push({ bevestig: opts }); return bevestigAntwoord; };
const skeleton = () => {}, bronStatus = () => {}, foutState = () => {};
const leegState = (i, t) => `<div class="leeg">${t}</div>`;
const haptic = () => {};
// Toestelopslag: blijft bestaan over een 'herstart' (nieuwe module-instantie) heen,
// precies zoals localStorage wanneer iOS de PWA in WhatsApp wegzet.
const opslag = new Map();
const localStorage = { getItem: k => (opslag.has(k) ? opslag.get(k) : null),
  setItem: (k, v) => opslag.set(k, String(v)), removeItem: k => opslag.delete(k) };

// ── De ECHTE module ─────────────────────────────────────────────────────────
const bron = [
  "const $ = (s, r = document) => (r === document ? document.querySelector(s) : r.querySelector(s));",
  "const $$ = () => [];",
  sliceLine("const esc = s =>"),
  sliceLine("const _NL_MND = ["),
  sliceFrom("function nlDatum("),
  sliceFrom("function nlAantal("),
  sliceLine("const ic = n =>"),
  "let huidigeView = 'strippen';",
  sliceBetween("const KAART_BIJNA = 1;", '$("#n-add").addEventListener'),
  "return { laad, skToggle, skAfboeken, skUndo, skWaKlik, skWaModus, skWaStop,"
  + " SK_WA_STATUS, wa: () => skWa, sel: () => skSel };",
].join("\n");
const maakFn = new Function(
  "document", "navigator", "self", "api", "jpost", "melding", "enqueue", "bevestigActie",
  "skeleton", "bronStatus", "foutState", "leegState", "haptic", "localStorage",
  '"use strict";\n' + bron);
// Eén 'app-start': verse DOM en verse modulestaat, dezelfde toestelopslag.
const start = () => { nieuweDom(); return maakFn(document, navigator, self, api, jpost, melding, enqueue,
  bevestigActie, skeleton, bronStatus, foutState, leegState, haptic, localStorage); };

// ── Fixtures ────────────────────────────────────────────────────────────────
const kaart = (naam, totaal, gebruikt, tel = "0612345678") => ({
  naam, totaal, gebruikt, rest: Math.max(0, totaal - gebruikt), telefoon: tel,
  laatst: gebruikt ? "2026-09-01" : null, historie: gebruikt ? ["2026-09-01"] : [],
});
const naamVan = i => `Deelnemer ${String(i + 1).padStart(2, "0")}`;
const groep = n => Array.from({ length: n }, (_, i) => kaart(naamVan(i), 10, i % 5));
// Per persoon een ANDERE link: anders kan een test niet zien naar wie een anker wijst.
const link = naam => `https://wa.me/316${[...naam].map(c => c.charCodeAt(0) % 10).join("").slice(-8)}`
  + `?text=${encodeURIComponent("Hoi " + naam)}`;

// Het serverantwoord op een batch, afgeleid zoals strippen_core het doet.
function batchAntwoord(bid, kaarten, zonderNr = []) {
  return { ok: true, batch_id: bid, aantal: kaarten.length, datum: "2026-09-11",
    deelnemers: kaarten.map(k => {
      const geb = k.gebruikt + 1, rest = Math.max(0, k.totaal - geb);
      return { naam: k.naam, rest, totaal: k.totaal, gebruikt: geb,
               wa_link: zonderNr.includes(k.naam) ? "" : link(k.naam) };
    }) };
}
// De serverstand NA die batch (zoals GET /api/kaarten hem daarna geeft).
const naBatch = (kaarten, r) => kaarten.map(k => {
  const d = r.deelnemers.find(x => x.naam === k.naam);
  return d ? { ...k, gebruikt: d.gebruikt, rest: d.rest } : k;
});

let m;
async function boek(kaarten, bid, opts = {}) {
  lijstAntwoord = { kaarten: kaarten.map(k => ({ ...k })), cloud: true };
  if (!opts.zelfdeApp) m = start();
  await m.laad();
  kaarten.filter(k => k.rest > 0).forEach(k => m.skToggle(k.naam));
  const r = batchAntwoord(bid, kaarten.filter(k => k.rest > 0), opts.zonderNr || []);
  calls = []; meldingen = []; antwoord = r; bevestigAntwoord = true;
  await m.skAfboeken();
  lijstAntwoord = { kaarten: naBatch(kaarten, r), cloud: true };
  return r;
}

// Lees de gerenderde berichtenlijst terug uit de ECHTE markup.
function rijen() {
  return els["#sk-b-lijst"].innerHTML.split("<li ").slice(1).map(h => ({
    cls: (/class="([^"]*)"/.exec(h) || [])[1] || "",
    idx: (/data-wa="(\d+)"/.exec(h) || [])[1],
    href: (/<a [^>]*href="([^"]*)"/.exec(h) || [])[1] || "",
    naam: (/class="sk-naam">([^<]*)</.exec(h) || [])[1],
    sub: (/class="sk-sub">([^<]*)</.exec(h) || [])[1],
    status: (/class="sk-b-status">([^<]*)</.exec(h) || [])[1],
  }));
}
const rijVan = naam => rijen().find(r => r.naam === naam);
const teller = () => els["#sk-b-teller"].textContent;
// Een tik zoals de browser hem aflevert: target binnen het anker, preventDefault telbaar.
function tikEvent(anker) {
  const ev = { voorkomen: false, preventDefault() { this.voorkomen = true; },
    target: { closest: s => (s === "[data-wa]" ? anker : null) } };
  return ev;
}
function tikRij(naam) {
  const r = rijVan(naam);
  const anker = new El("a"); anker.dataset.wa = r.idx; anker.href = r.href;
  const ev = tikEvent(anker);
  m.skWaKlik(ev);
  return { ev, href: r.href };
}
function tikVolgende() {
  const vk = els["#sk-volgende"];
  const ev = tikEvent(vk);
  const hrefBijTik = vk.href;
  m.skWaKlik(ev);
  // De browser volgt de href NA de handler: die moet dan nog steeds dezelfde zijn.
  return { ev, hrefBijTik, hrefNaHandler: vk.href };
}
const inBerichten = () => els["#sk-berichten"].hidden === false && els["#sk-kaarten"].hidden === true
  && els["#sk-b-bar"].hidden === false && els["#sk-bar"].hidden === false;

// ══ A — batch van 1 ═════════════════════════════════════════════════════════
opslag.clear();
{
  const r = await boek([kaart("Anna Bos", 10, 3)], "a1");
  ok(inBerichten(), "A: na afboeken staat de berichtenfase open, de kaartenlijst is weg");
  ok(teller() === "0 van 1 geopend · nog 1", "A: teller vóór openen", teller());
  ok(els["#sk-volgende"].hidden === false && els["#sk-volgende"].href === r.deelnemers[0].wa_link,
     "A: de actie wijst naar precies Anna's bestaande wa.me-link", els["#sk-volgende"].href);
  ok(/Open WhatsApp: Anna Bos/.test(els["#sk-volgende"].innerHTML), "A: eerste actie benoemt de persoon",
     els["#sk-volgende"].innerHTML);
  ok(rijVan("Anna Bos").status === "nog te openen", "A: status vóór openen", rijVan("Anna Bos").status);
  const t = tikVolgende();
  ok(!t.ev.voorkomen, "A: de tik opent WhatsApp gewoon (geen preventDefault)");
  ok(m.wa().items[0].status === "geopend", "A: status is METEEN geopend (vóór terugkeer)");
  await tick();
  ok(teller() === "1 van 1 geopend · iedereen gehad", "A: teller 1/1 + eindstaat", teller());
  ok(rijVan("Anna Bos").status === "geopend" && /is-geopend/.test(rijVan("Anna Bos").cls),
     "A: de rij gaat zichtbaar naar geopend");
  ok(els["#sk-volgende"].hidden === true && els["#sk-b-klaar"].hidden === false,
     "A: eindstaat — geen volgende meer, wel 'Klaar'");
  m.skWaStop();
  ok(els["#sk-kaarten"].hidden === false && els["#sk-berichten"].hidden === true && m.wa() === null,
     "A: 'Klaar' brengt de kaartenlijst terug en ruimt de lijst op");
  ok(!opslag.has("bb_sk_wa"), "A: na 'Klaar' staat er niets meer in de toestelopslag");
}

// ══ B — batches van 5 en 15 ═════════════════════════════════════════════════
opslag.clear();
{
  const vijf = groep(5);
  await boek(vijf, "b5");
  ok(rijen().length === 5 && teller() === "0 van 5 geopend · nog 5", "B5: vijf rijen, teller 0/5", teller());
  later(); tikRij("Deelnemer 04"); await tick();
  later(); tikRij("Deelnemer 02"); await tick();
  ok(teller() === "2 van 5 geopend · nog 3", "B5: buiten volgorde geopend telt correct", teller());
  const st = Object.fromEntries(rijen().map(r => [r.naam, r.status]));
  ok(st["Deelnemer 02"] === "geopend" && st["Deelnemer 04"] === "geopend"
     && ["Deelnemer 01", "Deelnemer 03", "Deelnemer 05"].every(n => st[n] === "nog te openen"),
     "B5: status klopt per persoon", JSON.stringify(st));
}
opslag.clear();
{
  const vijftien = groep(15);
  await boek(vijftien, "b15");
  ok(rijen().length === 15, "B15: vijftien rijen", rijen().length);
  ok(teller() === "0 van 15 geopend · nog 15", "B15: teller 0/15", teller());
  for (let i = 0; i < 6; i++) { later(); tikVolgende(); await tick(); }
  ok(teller() === "6 van 15 geopend · nog 9", "B15: '6 van 15 geopend' — totaal, geopend én over", teller());
  ok(rijen().filter(r => /is-geopend/.test(r.cls)).length === 6, "B15: precies zes rijen geopend");
  ok(rijen().filter(r => /is-volgende/.test(r.cls)).map(r => r.naam).join() === "Deelnemer 07",
     "B15: de volgende persoon is in de lijst gemarkeerd");
  ok(els["#sk-b-meter"].max === 15 && els["#sk-b-meter"].value === 6, "B15: voortgangsbalk 6/15");
  ok(!/style=/.test(els["#sk-b-lijst"].innerHTML), "B15: geen vaste breedtes/stijlen in de rijen");
}

// ══ C — Volgende ════════════════════════════════════════════════════════════
opslag.clear();
{
  const zes = groep(6);
  await boek(zes, "c1");
  later(); tikRij("Deelnemer 01"); await tick();
  later(); tikRij("Deelnemer 02"); await tick();
  later(); tikRij("Deelnemer 04"); await tick();
  ok(/Volgende: Deelnemer 03/.test(els["#sk-volgende"].innerHTML),
     "C: Volgende = eerstvolgende ongeopende (03), geopende overgeslagen", els["#sk-volgende"].innerHTML);
  later();
  const t = tikVolgende();
  ok(t.hrefBijTik === link("Deelnemer 03") && t.hrefNaHandler === link("Deelnemer 03"),
     "C: tijdens de tik wijst het anker nog naar de aangetikte persoon", t.hrefNaHandler);
  await tick();
  ok(/Volgende: Deelnemer 05/.test(els["#sk-volgende"].innerHTML), "C: slaat de al geopende 04 over",
     els["#sk-volgende"].innerHTML);
  later(); tikVolgende(); await tick();
  later(); tikVolgende(); await tick();
  ok(teller() === "6 van 6 geopend · iedereen gehad" && els["#sk-volgende"].hidden === true
     && els["#sk-b-klaar"].hidden === false, "C: einde geeft een duidelijke eindstaat", teller());
  ok(rijVan("Deelnemer 03").status === "geopend", "C: de huidige persoon blijft gemarkeerd");
}

// ══ D — terugkeer uit WhatsApp ══════════════════════════════════════════════
opslag.clear();
{
  const tien = groep(10);
  await boek(tien, "d1");
  for (let i = 0; i < 3; i++) { later(); tikVolgende(); await tick(); }
  // (1) gewone hertekening + verse read (visibilitychange na > 20 s)
  await m.laad();
  ok(teller() === "3 van 10 geopend · nog 7" && inBerichten(), "D: verse read reset de voortgang niet", teller());
  // (2) naar de kaarten en terug
  m.skWaModus(false);
  ok(els["#sk-kaarten"].hidden === false && els["#sk-b-hervat"].hidden === false
     && /3 van 10 geopend/.test(els["#sk-b-hervat"].textContent),
     "D: buiten de fase blijft een onafgemaakte lijst met één tik bereikbaar", els["#sk-b-hervat"].textContent);
  m.skWaModus(true);
  ok(inBerichten() && teller() === "3 van 10 geopend · nog 7", "D: hervatten = dezelfde voortgang");
  // (3) iOS zet de PWA weg in WhatsApp → de app start opnieuw op (nieuwe modulestaat)
  later(60_000);
  m = start();
  await m.laad();
  ok(m.wa() && m.wa().batch_id === "d1" && inBerichten(), "D: na een herstart staat de berichtenfase er weer");
  ok(teller() === "3 van 10 geopend · nog 7", "D: …met precies de geopende status van vóór WhatsApp", teller());
  ok(/Volgende: Deelnemer 04/.test(els["#sk-volgende"].innerHTML), "D: en de juiste volgende persoon",
     els["#sk-volgende"].innerHTML);
}

// ══ E — nieuwe batch, zelfde batch, vervallen ═══════════════════════════════
opslag.clear();
{
  const vier = groep(4);
  await boek(vier, "e1");
  later(); tikVolgende(); await tick();
  later(); tikVolgende(); await tick();
  m.skWaModus(false);
  // Nieuwe batch in dezelfde app-sessie: de bevestiging waarschuwt, de lijst begint schoon.
  const laat = [kaart("Anna Bos", 10, 3), ...naBatch(vier, batchAntwoord("e1", vier))];
  lijstAntwoord = { kaarten: laat, cloud: true };
  await m.laad();
  m.skToggle("Anna Bos");
  const r2 = batchAntwoord("e2", [laat[0]]);
  calls = []; antwoord = r2;
  await m.skAfboeken();
  const bev = calls.find(c => c.bevestig);
  ok(bev && /nog niet geopend/.test(bev.bevestig.tekst) && /2 WhatsApp-berichten/.test(bev.bevestig.tekst),
     "E: de bevestiging zegt dat er van de vorige batch nog 2 berichten open staan", bev && bev.bevestig.tekst);
  ok(m.wa().batch_id === "e2" && m.wa().items.length === 1 && m.wa().items[0].status === "open",
     "E: de nieuwe batch erft geen enkele geopend-status", JSON.stringify(m.wa().items));
  ok(teller() === "0 van 1 geopend · nog 1", "E: teller begint opnieuw", teller());
  ok((JSON.parse(opslag.get("bb_sk_wa") || "null") || {}).batch_id === "e2", "E: de opslag draagt de nieuwe batch-id");
}
opslag.clear();
{
  // Idempotent herhaald serverantwoord (zelfde batch-id, `herhaald: true`): geen reset.
  const drie = groep(3);
  const r = await boek(drie, "e4");
  later(); tikVolgende(); await tick();
  m.skWaModus(false);
  lijstAntwoord = { kaarten: naBatch(drie, r), cloud: true };
  await m.laad();
  ["Deelnemer 01", "Deelnemer 02"].forEach(n => m.skToggle(n));
  calls = []; antwoord = { ...r, herhaald: true };
  await m.skAfboeken();
  ok(m.wa().batch_id === "e4" && m.wa().items.filter(i => i.status === "geopend").length === 1,
     "E: een herhaald antwoord van DEZELFDE batch houdt de voortgang", JSON.stringify(m.wa().items));
}
opslag.clear();
{
  // Stand intussen gewijzigd (undo elders, andere coach): de berichten noemen een
  // saldo dat niet meer klopt → de lijst vervalt, met een melding.
  const drie = groep(3);
  await boek(drie, "e5");
  later(); tikVolgende(); await tick();
  m = start();
  lijstAntwoord = { kaarten: drie.map(k => ({ ...k })), cloud: true };   // terug naar vóór de batch
  meldingen = [];
  await m.laad();
  ok(m.wa() === null && els["#sk-berichten"].hidden === true && !opslag.has("bb_sk_wa"),
     "E: gewijzigde stand → berichtenlijst vervalt, niets blijft in de opslag");
  ok(meldingen.some(x => /vervallen/.test(x.t)), "E: …en dat wordt gezegd");
}
opslag.clear();
{
  // Houdbaarheid: de volgende dag is een oude lijst geen opvolging meer.
  const drie = groep(3);
  const r = await boek(drie, "e6");
  later(19 * 3600 * 1000);
  m = start();
  lijstAntwoord = { kaarten: naBatch(drie, r), cloud: true };
  await m.laad();
  ok(m.wa() === null && !opslag.has("bb_sk_wa"), "E: een verlopen lijst wordt niet op een nieuwe dag geplakt");
}
opslag.clear();
{
  // …ook niet als de app al die tijd open bleef staan (geen herstart ertussen).
  const drie = groep(3);
  const r = await boek(drie, "e6b");
  later(19 * 3600 * 1000);
  lijstAntwoord = { kaarten: naBatch(drie, r), cloud: true };
  await m.laad();
  ok(m.wa() === null && els["#sk-berichten"].hidden === true,
     "E: verlopen terwijl de app open stond → ook weg na de volgende read");
}
opslag.clear();
{
  // Undo met al geopende berichten: bevestiging; weigeren doet niets, akkoord ruimt op.
  const drie = groep(3);
  await boek(drie, "e7");
  later(); tikVolgende(); await tick();
  calls = []; bevestigAntwoord = false;
  await m.skUndo();
  ok(calls.some(c => c.bevestig && /al geopend bij 1 deelnemer/.test(c.bevestig.tekst))
     && !calls.some(c => c.url === "/api/kaarten/terugdraaien"),
     "E: undo na openen vraagt eerst bevestiging; weigeren stuurt niets");
  bevestigAntwoord = true; calls = [];
  antwoord = { ok: true, aantal: 3, kaarten: drie.map(k => ({ ...k })) };
  await m.skUndo();
  ok(calls.filter(c => c.url === "/api/kaarten/terugdraaien").length === 1 && m.wa() === null
     && els["#sk-kaarten"].hidden === false, "E: na undo vervalt de berichtenlijst van die batch");
}

// ══ F — tekst en saldo ══════════════════════════════════════════════════════
opslag.clear();
{
  const mix = [kaart("Anna Bos", 10, 3), kaart("Bram Willems", 10, 9), kaart("Cas de Wit", 10, 8),
               kaart("Eva Smit", 10, 2, "")];
  const r = await boek(mix, "f1", { zonderNr: ["Eva Smit"] });
  ok(rijVan("Anna Bos").sub === "6 over", "F: saldo uit het serverantwoord", rijVan("Anna Bos").sub);
  ok(rijVan("Cas de Wit").sub === "1 over", "F: bijna leeg = het echte getal", rijVan("Cas de Wit").sub);
  ok(rijVan("Bram Willems").sub === "laatste strip, kaart op", "F: laatste strip benoemd", rijVan("Bram Willems").sub);
  ok(rijVan("Anna Bos").href === r.deelnemers.find(d => d.naam === "Anna Bos").wa_link,
     "F: de rij gebruikt de wa.me-link (en dus tekst) van de server ongewijzigd");
  const eva = rijVan("Eva Smit");
  ok(eva && !eva.idx && !eva.href && /geen telefoonnummer/.test(eva.sub),
     "F: zonder nummer geen actie, wel zichtbaar", JSON.stringify(eva));
  ok(teller() === "0 van 3 geopend · nog 3", "F: teller telt alleen wie je kúnt openen", teller());
  ok(rijen().slice(-1)[0].naam === "Eva Smit", "F: wie geen nummer heeft staat onderaan");
}
opslag.clear();
{
  // Niemand met nummer: geen berichtenfase, wel een eerlijke regel in de uitkomst.
  await boek([kaart("Eva Smit", 10, 2, "")], "f2", { zonderNr: ["Eva Smit"] });
  ok(m.wa() === null && els["#sk-kaarten"].hidden === false, "F: zonder nummers geen lege berichtenfase");
  ok(/Geen telefoonnummer bekend/.test(els["#sk-uitkomst"].innerHTML), "F: …maar wel gezegd waarom");
}

// ══ G — semantiek ═══════════════════════════════════════════════════════════
{
  const VERBODEN = /verstuurd|verzonden|afgeleverd|bezorgd|ontvangen|gelezen/i;
  ok(Object.values(m.SK_WA_STATUS).join("|") === "nog te openen|geopend",
     "G: de enige statussen zijn 'nog te openen' en 'geopend'", Object.values(m.SK_WA_STATUS).join("|"));
  opslag.clear();
  await boek(groep(4), "g1");
  const oppervlak = [];
  const verzamel = () => oppervlak.push(teller(), els["#sk-b-lijst"].innerHTML, els["#sk-volgende"].innerHTML,
    els["#sk-b-hervat"].textContent, els["#sk-uitkomst"].innerHTML);
  verzamel();
  for (let i = 0; i < 4; i++) { later(); tikVolgende(); await tick(); verzamel(); }
  m.skWaModus(true); verzamel();
  const tekst = oppervlak.join(" ");
  ok(/geopend/.test(tekst), "G: de UI zegt 'geopend'");
  ok(!VERBODEN.test(tekst), "G: nergens verstuurd/verzonden/afgeleverd/ontvangen in de berichtenstatus",
     (tekst.match(VERBODEN) || [])[0]);
  const sectie = IDX.slice(IDX.indexOf('id="sk-berichten"'), IDX.indexOf('id="sk-bar-actie"'));
  ok(sectie && !/verstuurd|verzonden|afgeleverd|ontvangen/i.test(sectie.replace(/<!--[\s\S]*?-->/g, "")),
     "G: ook de vaste markup van de berichtenfase claimt geen verzending");
  ok(/Versturen doe je zelf in WhatsApp/.test(sectie), "G: de fase zegt eerlijk wie verstuurt");
}

// ══ H — geen automatische messaging ═════════════════════════════════════════
opslag.clear();
{
  const acht = groep(8);
  await boek(acht, "h1");
  calls = [];
  for (let i = 0; i < 8; i++) { later(); tikVolgende(); await tick(); }
  ok(calls.length === 0, "H: de hele berichtenronde doet GEEN enkel netwerkverzoek", JSON.stringify(calls));
  // Dubbeltik: de tweede tik binnen 800 ms opent geen tweede gesprek en slaat niemand over.
  opslag.clear();
  await boek(groep(5), "h2");
  later();
  const e1 = tikVolgende();
  const e2 = tikVolgende();                  // zelfde moment
  await tick();
  ok(!e1.ev.voorkomen && e2.ev.voorkomen, "H: dubbeltik → de tweede tik wordt tegengehouden");
  ok(m.wa().items.filter(i => i.status === "geopend").length === 1, "H: …en markeert niemand extra");
  // Bron: de berichtenfase opent nooit zelf iets en praat niet met de server.
  const wa = SRC.slice(SRC.indexOf("// ── WhatsApp na afboeken"), SRC.indexOf("// ── Detail per persoon"));
  ok(wa.length > 500, "H: berichtenfase gevonden in de bron");
  const code = wa.replace(/\/\/.*$/gm, "");
  ok(!/window\.open|location\s*(\.href\s*)?=|location\.assign|\.click\(\)|jpost\(|api\(|fetch\(/.test(code),
     "H: geen window.open/location/click()/netwerk in de berichtenfase", (code.match(/window\.open|location\s*=|\.click\(\)|jpost\(|api\(|fetch\(/) || [])[0]);
  ok(!/for\s*\(|forEach\([^)]*skWaMarkeer|setInterval/.test(code.replace(/\.map\(|\.filter\(/g, "")),
     "H: geen lus of interval die meerdere gesprekken opent");
}

// ── uitkomst ────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error(`\n✗ ${failures.length} fout(en):`);
  failures.forEach(f => console.error("  - " + f));
  process.exit(1);
}
console.log("✓ strippenkaart_whatsapp: alle clientcontracten groen");
