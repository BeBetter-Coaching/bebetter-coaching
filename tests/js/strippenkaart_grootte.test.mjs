// Strippenkaart — kaart aanpassen (10 ↔ 20). EXECUTEERBARE clienttests.
//
//   node tests/js/strippenkaart_grootte.test.mjs
//
// Zelfde harnas als strippenkaart_cockpit.test.mjs: de ECHTE module verbatim uit app.js.
// Bewijst: keuze 10/20 in het bestaande detailpaneel, bevestiging vóór opslaan, de stand die de
// coach zag gaat mee (stale-safe), 20→10 bij >10 gebruikt stuurt niets, dezelfde grootte stuurt
// niets, na aanpassen blijven 'Ongedaan maken', batch-afboeken en selectie gewoon werken.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = readFileSync(join(ROOT, "pwa", "static", "app.js"), "utf8");

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

// ── DOM-shim ────────────────────────────────────────────────────────────────
// `querySelector` zoekt in de ECHT gerenderde markup: een haak die er niet in staat
// levert null en dus een harde fout, in plaats van een stil verkeerd resultaat.
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
    this._html = String(v == null ? "" : v); this._q = new Map();
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

const els = {};
const el = id => (els[id] = els[id] || new El("div"));
const document = {
  createElement: t => new El(t),
  querySelector: sel => {
    if (els[sel]) return els[sel];
    for (const k of Object.keys(els)) { const t = els[k].querySelector ? null : null; }
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: () => {},
};
["#lijst", "#sk-bar", "#sk-af", "#sk-bar-let", "#sk-telling", "#sk-alles", "#sk-wis",
 "#sk-uitkomst", "#sk-bar-actie", "#sk-q", "#bron", "#msg"].forEach(el);
document.querySelector = sel => {
  if (els[sel]) return els[sel];
  // val terug op de geneste zoeker van de uitkomstbox (voor $("[data-undo]", box))
  return null;
};

// ── Stubs rond de module ────────────────────────────────────────────────────
let meldingen = [], calls = [], wachtrij = [], antwoord = null, bevestigAntwoord = true;
// `lijst` = wat GET /api/kaarten teruggeeft (de serverstand), `antwoord` = wat de
// eerstvolgende schrijfactie teruggeeft. Gescheiden, precies zoals in de echte app:
// een mislukte batch mag de lijst-read niet vervuilen.
let lijstAntwoord = { kaarten: [], cloud: true };
const navigator = { onLine: true, vibrate: () => {} };
const self = { crypto: { randomUUID: () => "cid-" + (calls.length + 1) } };
const api = async (u, o) => {
  calls.push({ url: u, method: (o && o.method) || "GET" });
  return u === "/api/kaarten" ? { ...lijstAntwoord, kaarten: lijstAntwoord.kaarten.map(k => ({ ...k })) } : antwoord;
};
const jpost = async (u, body) => { calls.push({ url: u, body }); return antwoord; };
const melding = (t, err) => meldingen.push({ t, err });
const enqueue = it => wachtrij.push(it);
const bevestigActie = async opts => { calls.push({ bevestig: opts }); return bevestigAntwoord; };
const skeleton = () => {}, bronStatus = () => {}, foutState = () => {};
const leegState = (i, t) => `<div class="leeg">${t}</div>`;
const haptic = () => {};
// Eigen opslag-stub: de module mag nooit de echte (node-)localStorage raken.
const _opslag = new Map();
const localStorage = { getItem: k => (_opslag.has(k) ? _opslag.get(k) : null),
  setItem: (k, v) => _opslag.set(k, String(v)), removeItem: k => _opslag.delete(k) };

// ── De ECHTE module ─────────────────────────────────────────────────────────
const bron = [
  "const $ = (s, r = document) => (r === document ? document.querySelector(s) : r.querySelector(s));",
  "const $$ = () => [];",
  'const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));',
  sliceLine("const _NL_MND = ["),
  sliceFrom("function nlDatum("),
  sliceFrom("function nlAantal("),
  'const ic = n => `<svg class="ic"><use href="#ic-${n}"/></svg>`;',
  sliceBetween("const KAART_BIJNA = 1;", '$("#n-add").addEventListener'),
  "return { laad, skToggle, skAfboeken, skUndo, skDetail, skGrootte, skGrootteHtml,"
  + " kaarten: () => skKaarten, sel: () => skSel, batch: () => skLaatsteBatch, wa: () => skWa };",
].join("\n");

const maak = new Function(
  "document", "navigator", "self", "api", "jpost", "melding", "enqueue", "bevestigActie",
  "skeleton", "bronStatus", "foutState", "leegState", "haptic", "localStorage",
  '"use strict";\n' + bron);
const m = maak(document, navigator, self, api, jpost, melding, enqueue, bevestigActie,
               skeleton, bronStatus, foutState, leegState, haptic, localStorage);

// ── Fixtures ────────────────────────────────────────────────────────────────
const kaart = (naam, totaal, gebruikt, tel = "0612345678") => ({
  naam, totaal, gebruikt, rest: Math.max(0, totaal - gebruikt), telefoon: tel,
  laatst: gebruikt ? "2026-08-12" : null, historie: gebruikt ? ["2026-08-12"] : [],
});
const VIJF = [kaart("Anna Bos", 10, 3), kaart("Bram Willems", 10, 7), kaart("Cas de Wit", 20, 0),
              kaart("Dana Vos", 10, 10), kaart("Eva Smit", 10, 9, "")];
const veel = n => Array.from({ length: n }, (_, i) =>
  kaart(`Deelnemer ${String(i + 1).padStart(2, "0")}`, 10, i % 11));

async function laadMet(kaarten) {
  calls = []; meldingen = []; wachtrij = [];
  lijstAntwoord = { kaarten: kaarten.map(k => ({ ...k })), cloud: true };
  els["#lijst"].children = [];
  m.sel().clear();
  await m.laad();
  antwoord = null;
}
const rij = naam => els["#lijst"].children.find(r => r.dataset.naam === naam);
const zichtbaar = () => els["#lijst"].children.filter(r => !r._cls.has("sk-uit")).map(r => r.dataset.naam);


const bodies = () => calls.filter(c => c.url && c.url.endsWith("/grootte"));
const kaartVan = n => m.kaarten().find(k => k.naam === n);

// ── A. keuze in het detailpaneel ─────────────────────────────────────────────
await laadMet([kaart("Anna Bos", 10, 3), kaart("Cas de Wit", 20, 12)]);
ok(/data-grootte="10"[^>]*class="on"/.test(m.skGrootteHtml(kaartVan("Anna Bos"))), "A: huidige grootte (10) staat aan");
ok(!/disabled/.test(m.skGrootteHtml(kaartVan("Anna Bos"))), "A: 3 gebruikt → beide keuzes mogelijk");
const cas = m.skGrootteHtml(kaartVan("Cas de Wit"));
ok(/data-grootte="10"[^>]*disabled/.test(cas) && /Al 12 gebruikt/.test(cas), "A: 12 gebruikt → 10 uitgeschakeld mét uitleg", cas);
rij("Anna Bos").querySelector(".sk-detail").hidden = true;   // zoals de markup: dicht
m.skDetail("Anna Bos");
ok(/Kaart aanpassen/.test(rij("Anna Bos").querySelector(".sk-detail").innerHTML), "A: de actie staat in het bestaande detailpaneel");
ok(!/style=/.test(m.skGrootteHtml(kaartVan("Anna Bos"))), "A: geen vaste breedtes in de markup");

// ── B. 10 → 20 met bevestiging, stand die de coach zag gaat mee ─────────────
calls = []; bevestigAntwoord = true;
antwoord = { ok: true, kaart: { naam: "Anna Bos", totaal: 20, gebruikt: 3, rest: 17, laatst: "2026-08-12" } };
await m.skGrootte("Anna Bos", 20);
ok(calls.some(c => c.bevestig && /wordt 20 strippen/.test(c.bevestig.tekst) && /Gebruikt blijft 3/.test(c.bevestig.detail)),
   "B: eerst een bevestiging met het effect");
ok(bodies().length === 1 && JSON.stringify(bodies()[0].body) === '{"totaal":20,"verwacht_totaal":10,"verwacht_gebruikt":3}',
   "B: één request met de stand die de coach zag", JSON.stringify(bodies()));
ok(kaartVan("Anna Bos").totaal === 20 && kaartVan("Anna Bos").gebruikt === 3 && rij("Anna Bos").querySelector(".sk-saldo").textContent === "17 over",
   "B: 3/20, 17 over — uit het serverantwoord");

// annuleren schrijft niets
calls = []; bevestigAntwoord = false;
await m.skGrootte("Anna Bos", 10);
ok(bodies().length === 0, "B: annuleren schrijft niets");
bevestigAntwoord = true;

// ── C. 20 → 10 bij >10 gebruikt: geen request, duidelijke melding ────────────
calls = []; meldingen = [];
await m.skGrootte("Cas de Wit", 10);
ok(bodies().length === 0 && !calls.some(c => c.bevestig), "C: >10 gebruikt → geen bevestiging, geen request");
ok(meldingen.some(x => x.err && /12 strippen gebruikt/.test(x.t)), "C: duidelijke melding", JSON.stringify(meldingen));

// ── D. dezelfde grootte → niets ───────────────────────────────────────────────
calls = [];
await m.skGrootte("Cas de Wit", 20);
ok(bodies().length === 0 && !calls.some(c => c.bevestig), "D: al 20 → geen request");

// ── E. server weigert (stale) → echte stand ophalen, niets verzonnen ───────────
calls = []; meldingen = [];
antwoord = { ok: false, err: "De kaart van Anna Bos is inmiddels gewijzigd.", conflict: "stale" };
await m.skGrootte("Anna Bos", 10);
ok(meldingen.some(x => x.err && /gewijzigd/.test(x.t)) && calls.some(c => c.url === "/api/kaarten" && c.method === "GET"),
   "E: stale → melding en een verse read");

// ── F. undo en batch-afboeken blijven werken na aanpassen ──────────────────────
await laadMet([kaart("Anna Bos", 10, 3), kaart("Bram Willems", 10, 7)]);
m.skToggle("Anna Bos");
antwoord = { ok: true, batch_id: "b1", aantal: 1, datum: "2026-09-11",
             deelnemers: [{ naam: "Anna Bos", rest: 6, totaal: 10, gebruikt: 4, wa_link: "" }] };
await m.skAfboeken();
antwoord = { ok: true, kaart: { naam: "Anna Bos", totaal: 20, gebruikt: 4, rest: 16, laatst: "2026-09-11" } };
await m.skGrootte("Anna Bos", 20);
ok(m.batch() && m.batch().batch_id === "b1" && els["#sk-uitkomst"].hidden === false,
   "F: 'Ongedaan maken' blijft beschikbaar na aanpassen");
calls = [];
antwoord = { ok: true, aantal: 1, kaarten: [{ naam: "Anna Bos", rest: 17, totaal: 20, gebruikt: 3, laatst: "2026-08-12" }] };
await m.skUndo();
ok(calls.some(c => c.url === "/api/kaarten/terugdraaien" && c.body.batch_id === "b1") && kaartVan("Anna Bos").rest === 17,
   "F: undo draait de batch terug op de nieuwe grootte");
m.skToggle("Bram Willems"); calls = [];
antwoord = { ok: true, batch_id: "b2", aantal: 1, datum: "2026-09-11",
             deelnemers: [{ naam: "Bram Willems", rest: 2, totaal: 10, gebruikt: 8, wa_link: "" }] };
await m.skAfboeken();
ok(calls.filter(c => c.url === "/api/kaarten/afboeken").length === 1 && kaartVan("Bram Willems").rest === 2,
   "F: batch-afboeken werkt daarna gewoon");

if (failures.length) {
  console.error(`\n✗ ${failures.length} fout(en):`);
  failures.forEach(f => console.error("  - " + f));
  process.exit(1);
}
console.log("✓ strippenkaart_grootte: kaart aanpassen — alle clientcontracten groen");
