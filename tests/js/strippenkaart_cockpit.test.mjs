// Strippenkaart Cockpit v2 — EXECUTEERBARE clienttests.
//
//   node tests/js/strippenkaart_cockpit.test.mjs
//
// Snijdt de ECHTE strippenkaart-module verbatim uit pwa/static/app.js en draait hem
// tegen een DOM-shim die de werkelijk gerenderde markup leest. Bewijst:
//   A1  5 deelnemers renderen; A2 30 deelnemers; A3 lege kaarten onderaan en niet kiesbaar
//   B1  één persoon selecteren/deselecteren; B2 meerdere; B3 wissen
//   B4  zoeken filtert zonder de selectie aan te tasten; B5 'alles' pakt alleen het zichtbare
//   C1  één batch-write voor de hele groep, met de stand die de coach ZAG
//   C2  dubbeltap levert precies één request
//   C3  weigeren in de bevestiging schrijft niets
//   C4  conflict → echte stand ophalen, geen verzonnen saldo, selectie blijft bruikbaar
//   D1  één persoon loopt via exact hetzelfde pad
//   E1  na succes komen de saldi uit het serverantwoord
//   F1  netwerkfout laat saldi ongemoeid en houdt de selectie
//   G1  ongedaan maken draait terug; G2 een tweede undo stuurt niets
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
  "return { laad, skTeken, skToggle, skZoek, skWis, skAllesZichtbaar, skAfboeken, skUndo,"
  + " skBalk, skTelling, skPasToe, skSorteer, skRijBinnen, skDetail,"
  + " kaarten: () => skKaarten, sel: () => skSel, batch: () => skLaatsteBatch };",
].join("\n");

const maak = new Function(
  "document", "navigator", "self", "api", "jpost", "melding", "enqueue", "bevestigActie",
  "skeleton", "bronStatus", "foutState", "leegState", "haptic",
  '"use strict";\n' + bron);
const m = maak(document, navigator, self, api, jpost, melding, enqueue, bevestigActie,
               skeleton, bronStatus, foutState, leegState, haptic);

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

// ══ A — render ══════════════════════════════════════════════════════════════
await laadMet(VIJF);
ok(els["#lijst"].children.length === 5, "A1: vijf deelnemers gerenderd", els["#lijst"].children.length);
ok(rij("Anna Bos").querySelector(".sk-saldo").textContent === "7 over", "A1: saldo als '7 over'",
   rij("Anna Bos").querySelector(".sk-saldo").textContent);
ok(rij("Anna Bos").querySelector(".sk-sub").textContent.startsWith("3/10"),
   "A1: gebruikt/totaal zichtbaar", rij("Anna Bos").querySelector(".sk-sub").textContent);
ok(rij("Dana Vos").querySelector(".sk-saldo").textContent === "OP", "A3: lege kaart zegt OP");
ok(rij("Dana Vos")._cls.has("is-critical") && rij("Dana Vos")._cls.has("sk-leeg"),
   "A3: lege kaart krijgt de kritieke toon");
ok(rij("Eva Smit")._cls.has("is-attention"), "A3: laatste strip = attentietoon");
ok(m.skSorteer(VIJF).map(k => k.naam).slice(-1)[0] === "Dana Vos",
   "A3: lege kaarten onderaan", m.skSorteer(VIJF).map(k => k.naam).join(","));
ok(rij("Dana Vos").querySelector(".sk-kies").disabled === true, "A3: lege kaart is niet kiesbaar");
ok(!/style=|width:\s*\d{3,}px|white-space:\s*nowrap/.test(m.skRijBinnen(VIJF[0])),
   "A1: de rij zet geen vaste breedtes in de markup (geen horizontale scroll)");

await laadMet(veel(30));
ok(els["#lijst"].children.length === 30, "A2: 30 deelnemers gerenderd");
ok(els["#sk-telling"].textContent.includes("actief"), "A2: telling toont hoeveel er actief zijn",
   els["#sk-telling"].textContent);

// ══ B — selectie ════════════════════════════════════════════════════════════
await laadMet(VIJF);
m.skToggle("Anna Bos");
ok(m.sel().size === 1 && rij("Anna Bos")._cls.has("sk-aan"), "B1: één tik selecteert");
ok(rij("Anna Bos").querySelector(".sk-kies").getAttribute("aria-pressed") === "true",
   "B1: selectie is ook voor een screenreader zichtbaar");
ok(els["#sk-bar"].hidden === false, "B1: de sticky balk verschijnt");
ok(els["#sk-af"].textContent === "1 strip afboeken bij 1 geselecteerd", "B1: hoofdactie benoemt de selectie",
   els["#sk-af"].textContent);
m.skToggle("Anna Bos");
ok(m.sel().size === 0 && !rij("Anna Bos")._cls.has("sk-aan"), "B1: nog een tik deselecteert");
ok(els["#sk-bar"].hidden === true, "B1: balk verdwijnt bij lege selectie");

m.skToggle("Anna Bos"); m.skToggle("Bram Willems"); m.skToggle("Cas de Wit");
ok(m.sel().size === 3 && els["#sk-af"].textContent === "1 strip afboeken bij 3 geselecteerd",
   "B2: meerdere deelnemers", els["#sk-af"].textContent);
m.skToggle("Dana Vos");
ok(m.sel().size === 3, "B2: een lege kaart kan niet meedoen");

m.skZoek("bram");
ok(zichtbaar().join(",") === "Bram Willems", "B4: zoeken filtert de lijst", zichtbaar().join(","));
ok(m.sel().size === 3, "B4: filteren raakt de selectie niet");
ok(els["#sk-bar-let"].hidden === false && /buiten het filter/.test(els["#sk-bar-let"].textContent),
   "B4: de balk zegt dat er selectie buiten beeld staat", els["#sk-bar-let"].textContent);
m.skAllesZichtbaar();
ok(m.sel().size === 3, "B5: 'alles' pakt alleen de zichtbare actieve lijst (Bram zat er al bij)");
m.skZoek("");
ok(els["#sk-bar-let"].hidden === true, "B4: zonder filter geen waarschuwing");
m.skAllesZichtbaar();
ok(m.sel().size === 4 && !m.sel().has("Dana Vos"), "B5: 'alles' slaat lege kaarten over", [...m.sel()].join(","));
m.skWis();
ok(m.sel().size === 0 && els["#sk-bar"].hidden === true, "B3: selectie wissen");

// ══ C/D/E — afboeken ════════════════════════════════════════════════════════
await laadMet(VIJF);
m.skToggle("Anna Bos"); m.skToggle("Bram Willems"); m.skToggle("Cas de Wit");
calls = []; bevestigAntwoord = true;
antwoord = { ok: true, batch_id: "b1", aantal: 3, datum: "2026-09-10", deelnemers: [
  { naam: "Anna Bos", rest: 6, totaal: 10, gebruikt: 4, wa_link: "https://wa.me/1?text=x" },
  { naam: "Bram Willems", rest: 2, totaal: 10, gebruikt: 8, wa_link: "" },
  { naam: "Cas de Wit", rest: 19, totaal: 20, gebruikt: 1, wa_link: "https://wa.me/3?text=x" }] };
await m.skAfboeken();
const posts = calls.filter(c => c.url === "/api/kaarten/afboeken");
ok(posts.length === 1, "C1: precies ÉÉN request voor de hele groep", posts.length);
ok(posts[0].body.namen.join(",") === "Anna Bos,Bram Willems,Cas de Wit", "C1: alle namen in één body");
ok(JSON.stringify(posts[0].body.verwacht) === '{"Anna Bos":3,"Bram Willems":7,"Cas de Wit":0}',
   "C1: de stand die de coach zag gaat mee (stale-detectie)", JSON.stringify(posts[0].body.verwacht));
ok(!!posts[0].body.client_id, "C2: elke actie draagt een idempotentiesleutel");
ok(calls.some(c => c.bevestig && /1 strip afboeken bij 3 deelnemers/.test(c.bevestig.titel)),
   "C1: expliciete bevestiging met het aantal");
ok(calls.find(c => c.bevestig).bevestig.detail === "Anna Bos · Bram Willems · Cas de Wit",
   "C1: de bevestiging noemt wie geraakt wordt");
ok(rij("Anna Bos").querySelector(".sk-saldo").textContent === "6 over", "E1: saldo uit het serverantwoord");
ok(rij("Cas de Wit").querySelector(".sk-sub").textContent.startsWith("1/20"), "E1: gebruikt/totaal bijgewerkt");
ok(m.sel().size === 0 && els["#sk-bar-actie"].hidden === true, "E1: selectie leeg, actie weg na succes");
ok(els["#sk-uitkomst"].hidden === false
   && /1 strip afgeboekt bij 3 deelnemers/.test(els["#sk-uitkomst"].innerHTML),
   "E1: uitkomst met aantal", els["#sk-uitkomst"].innerHTML.slice(0, 80));
ok(/data-undo/.test(els["#sk-uitkomst"].innerHTML), "G1: 'Ongedaan maken' staat er");
ok((els["#sk-uitkomst"].innerHTML.match(/sk-wa-btn/g) || []).length === 2,
   "E1: alleen deelnemers mét nummer krijgen een berichtknop");

// C2 — dubbeltap: de tweede tik mag geen tweede request worden
await laadMet(VIJF);
m.skToggle("Anna Bos");
calls = [];
let traag;
antwoord = { ok: true, batch_id: "b2", aantal: 1, datum: "2026-09-10",
             deelnemers: [{ naam: "Anna Bos", rest: 6, totaal: 10, gebruikt: 4, wa_link: "" }] };
const eerste = m.skAfboeken();
const tweede = m.skAfboeken();            // dubbeltap, vóór de eerste klaar is
await Promise.all([eerste, tweede]);
ok(calls.filter(c => c.url === "/api/kaarten/afboeken").length === 1,
   "C2: dubbeltap levert precies één request", calls.filter(c => c.url === "/api/kaarten/afboeken").length);

// C3 — weigeren in de bevestiging
await laadMet(VIJF);
m.skToggle("Anna Bos");
calls = []; bevestigAntwoord = false;
await m.skAfboeken();
ok(calls.filter(c => c.url === "/api/kaarten/afboeken").length === 0, "C3: annuleren schrijft niets");
ok(m.sel().size === 1, "C3: de selectie blijft na annuleren staan");
bevestigAntwoord = true;

// D1 — één persoon loopt via hetzelfde pad
await laadMet(VIJF);
m.skToggle("Bram Willems");
calls = [];
antwoord = { ok: true, batch_id: "b3", aantal: 1, datum: "2026-09-10",
             deelnemers: [{ naam: "Bram Willems", rest: 2, totaal: 10, gebruikt: 8, wa_link: "" }] };
await m.skAfboeken();
ok(calls.filter(c => c.url === "/api/kaarten/afboeken").length === 1
   && calls.find(c => c.url === "/api/kaarten/afboeken").body.namen.length === 1,
   "D1: één persoon gaat via dezelfde groepsactie");
ok(els["#sk-af"].textContent !== "" && rij("Bram Willems").querySelector(".sk-saldo").textContent === "2 over",
   "D1: saldo bijgewerkt");

// ══ C4/F — foutpaden ════════════════════════════════════════════════════════
await laadMet(VIJF);
m.skToggle("Anna Bos"); m.skToggle("Bram Willems");
calls = []; meldingen = [];
antwoord = { ok: false, err: "De stand is inmiddels gewijzigd bij: Anna Bos.", conflict: "stale" };
await m.skAfboeken();
ok(meldingen.some(x => x.err && /gewijzigd/.test(x.t)), "C4: conflict wordt eerlijk gemeld");
ok(rij("Anna Bos").querySelector(".sk-saldo").textContent === "7 over",
   "C4: geen verzonnen nieuw saldo", rij("Anna Bos").querySelector(".sk-saldo").textContent);
ok(m.sel().size === 2, "C4: de selectie blijft bruikbaar voor opnieuw proberen");
ok(calls.some(c => c.url === "/api/kaarten" && c.method === "GET"),
   "C4: bij conflict wordt de echte stand opgehaald");

await laadMet(VIJF);
m.skToggle("Anna Bos");
calls = []; meldingen = [];
antwoord = null;                          // netwerk weg: jpost geeft null terug
await m.skAfboeken();
ok(meldingen.some(x => x.err), "F1: netwerkfout wordt gemeld");
ok(rij("Anna Bos").querySelector(".sk-saldo").textContent === "7 over", "F1: saldo ongemoeid");
ok(m.sel().size === 1, "F1: selectie blijft staan voor een retry");
ok(els["#sk-uitkomst"].hidden === true, "F1: geen succesbalk bij een onzekere uitkomst");

// offline: wachtrij + zichtbaar merkteken
await laadMet(VIJF);
m.skToggle("Anna Bos"); m.skToggle("Cas de Wit");
calls = []; wachtrij = []; navigator.onLine = false;
await m.skAfboeken();
ok(calls.filter(c => c.url === "/api/kaarten/afboeken").length === 0, "F2: offline gaat er niets over de lijn");
ok(wachtrij.length === 1 && wachtrij[0].body.namen.length === 2, "F2: één wachtrij-item voor de groep");
ok(!("verwacht" in wachtrij[0].body), "F2: een wachtende batch draagt geen verouderde stand mee");
ok(/wordt verzonden/.test(rij("Anna Bos").querySelector(".sk-sub").textContent),
   "F2: de rij zegt dat het nog verzonden moet worden", rij("Anna Bos").querySelector(".sk-sub").textContent);
navigator.onLine = true;

// ══ G — ongedaan maken ══════════════════════════════════════════════════════
await laadMet(VIJF);
m.skToggle("Anna Bos");
antwoord = { ok: true, batch_id: "b9", aantal: 1, datum: "2026-09-10",
             deelnemers: [{ naam: "Anna Bos", rest: 6, totaal: 10, gebruikt: 4, wa_link: "" }] };
await m.skAfboeken();
calls = [];
antwoord = { ok: true, aantal: 1, kaarten: [
  { naam: "Anna Bos", rest: 7, totaal: 10, gebruikt: 3, laatst: "2026-08-12" }] };
const u1 = m.skUndo();
const u2 = m.skUndo();                    // tweede tik meteen erachteraan
await Promise.all([u1, u2]);
const undos = calls.filter(c => c.url === "/api/kaarten/terugdraaien");
ok(undos.length === 1, "G2: tweede undo stuurt niets", undos.length);
ok(undos[0].body.batch_id === "b9", "G1: undo noemt precies die batch");
ok(rij("Anna Bos").querySelector(".sk-saldo").textContent === "7 over", "G1: saldo teruggedraaid");
ok(els["#sk-uitkomst"].hidden === true, "G1: de undo-knop is daarna weg");

// ── uitkomst ────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error(`\n✗ ${failures.length} fout(en):`);
  failures.forEach(f => console.error("  - " + f));
  process.exit(1);
}
console.log("✓ strippenkaart_cockpit: alle clientcontracten groen");
