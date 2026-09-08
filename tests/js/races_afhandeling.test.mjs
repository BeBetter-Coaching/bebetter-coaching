// Races-afhandeling — EXECUTEERBARE tests.
//
//   node tests/js/races_afhandeling.test.mjs
//
// Snijdt de ECHTE functies verbatim uit pwa/static/app.js en draait ze tegen een
// minimale DOM-shim. Bewijst de belofte van deze batch:
//   R1  bevestigActie   — app-eigen bevestiging i.p.v. native confirm(); ELKE uitgang
//                         behalve de bevestigknop is `false`, en er komt één antwoord.
//   R2  rcPlaats        — zonder bevestiging geen post; met bevestiging precies één post;
//                         een lopend verzoek blokkeert een tweede klik.
//   R3  foutpad         — tekst blijft staan, race blijft open, eigen actielabel terug.
//   R4  rcNaPlaatsing   — 7-dagenfilter: rij weg + telling bij; volledig overzicht: kaart
//                         blijft met wens en 'Wens bijwerken'.
//   R5  rcHomeChipBij   — Home-chip telt af, verdwijnt op 0, negeert races buiten het venster.
//   R6  rcInfoTeken     — de inforegel is een afgeleide van rcItems, niet van het laadmoment.
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
const sliceLine = (p) => {
  const i = SRC.indexOf(p);
  if (i < 0) throw new Error("not found: " + p);
  return SRC.slice(i, SRC.indexOf("\n", i));
};

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };

// ── Minimale DOM-shim ────────────────────────────────────────────────────────
// `querySelector` kijkt in de ECHT gerenderde markup: een selector die niet in de
// HTML voorkomt levert null (en dus een harde fout in de aanroeper). Zo vangt de
// shim selector-drift i.p.v. hem te verbergen achter een altijd-werkende stub.
class El {
  constructor(tag) {
    this.tag = tag || "div"; this.children = []; this.parent = null;
    // Echte DOMStringMap coerceert elke schrijf naar een string; de code leest 'm terug
    // met `+…`. Die coercie meenemen, anders test je een vriendelijkere DOM dan de echte.
    this.dataset = new Proxy({}, { set: (o, k, v) => { o[k] = String(v); return true; } });
    this.textContent = ""; this.attrs = {}; this.disabled = false;
    this._html = ""; this._q = {}; this._on = {}; this._cls = new Set();
    const s = this._cls;
    this.classList = { add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
                       toggle: (c, on) => { if (on) s.add(c); else s.delete(c); } };
  }
  get className() { return [...this._cls].join(" "); }
  set className(v) { this._cls.clear(); String(v || "").split(/\s+/).filter(Boolean).forEach(c => this._cls.add(c)); }
  get innerHTML() { return this._html; }
  // Zoals de echte DOM: innerHTML zetten gooit bestaande kindknopen weg. Zonder dit
  // stapelen herbouwde lijsten op en vind je oude kaarten terug die er niet meer zijn.
  set innerHTML(v) {
    this._html = String(v == null ? "" : v); this._q = {};
    this.children.forEach(c => { c.parent = null; }); this.children = [];
  }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  // Alleen class-selectors over ECHTE kindelementen (genoeg voor rcKaart). Inhoud die
  // via innerHTML is gezet heeft geen knopen, dus daarvoor levert dit bewust niets op.
  querySelectorAll(sel) {
    const cls = String(sel).replace(/^\./, "");
    const uit = [];
    const loop = n => n.children.forEach(c => { if (c._cls.has(cls)) uit.push(c); loop(c); });
    loop(this);
    return uit;
  }
  addEventListener(t, f) { (this._on[t] = this._on[t] || []).push(f); }
  vuur(t, ev) { (this._on[t] || []).forEach(f => f(ev || {})); }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(x => x !== this);
    this.parent = null;
  }
  replaceWith(node) {
    if (!this.parent) return;
    const i = this.parent.children.indexOf(this);
    if (i >= 0) this.parent.children[i] = node;
    node.parent = this.parent; this.parent = null;
  }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n === document.body; }
  focus() { document.activeElement = this; }
  querySelector(sel) {
    const key = String(sel).replace(/^[.[]/, "").replace(/]$/, "");
    if (!this._html.includes(key)) return null;         // staat niet in de echte markup
    return (this._q[sel] = this._q[sel] || new El("button"));
  }
}
let byId = {}, docKeys = [];
const document = {
  activeElement: null,
  createElement: t => new El(t),
  body: new El("body"),
  addEventListener: (t, f) => { if (t === "keydown") docKeys.push(f); },
  removeEventListener: (t, f) => { if (t === "keydown") docKeys = docKeys.filter(x => x !== f); },
};
const $ = sel => byId[String(sel).replace(/^#/, "")] || null;
const esc = s => String(s == null ? "" : s);
const ic = () => "";
const haptic = () => {};

// Gedeelde echte primitieven die de races-code gebruikt.
const PRIMS = [
  sliceFrom("function dagenTot("), sliceFrom("function nlDagenTot("),
  sliceLine("const _NL_MND = "), sliceFrom("function nlDatum("), sliceFrom("function nlAantal("),
  sliceFrom("function leegState("), sliceLine("let _bevestigSeq = "),
  sliceFrom("function bevestigActie("),
].join("\n\n");

const RACES = [
  sliceLine("const RC_CHIP_DAGEN = "), sliceLine("const rcBezig = "),
  sliceLine("let rcLaadSeq = "), sliceLine("const rcGeplaatst = "), sliceLine("const rcOnzeker = "),
  sliceFrom("function rcChipHtml("),
  sliceFrom("function rcInfoTeken("), sliceFrom("function rcLeegHtml("),
  sliceFrom("function rcZelfdeWens("), sliceFrom("function rcPasGeplaatstToe("),
  sliceFrom("function rcKaart("),
  sliceFrom("function initialen("), sliceFrom("function raceItem("),
  sliceFrom("async function laadRaces("),
  sliceFrom("async function rcPlaats("), sliceFrom("async function rcVerstuur("),
  sliceFrom("async function rcControleer("),
  sliceFrom("function rcNaPlaatsing("), sliceFrom("function rcNaMislukking("),
  sliceFrom("function rcFocusNa("), sliceFrom("function rcHomeChipBij("),
].join("\n\n");

// Bouwt een verse races-omgeving. `scope`/`items` zijn de client-stand; `post` is de
// server-stub. Retourneert de echte functies plus wat de test moet kunnen inspecteren.
function maakRaces({ scope = "7d", items = [], post = () => Promise.resolve({ ok: true }),
                     haal = () => ({ fs: true, items: [] }) } = {}) {
  const posts = [];
  const meldingen = [];
  const jpost = (u, b) => { posts.push({ u, b }); return Promise.resolve(post(u, b)); };
  const melding = (t, err) => meldingen.push({ t, err: !!err });
  const gets = [];
  const api = u => { gets.push(u); return Promise.resolve(haal(u)); };
  const mod = new Function(
    "document", "$", "esc", "ic", "haptic", "jpost", "api", "melding", "skeleton",
    "rcScope", "rcItems",
    PRIMS + "\n\n" + RACES +
    "\nreturn { raceItem, rcPlaats, rcNaPlaatsing, rcNaMislukking, rcHomeChipBij, rcInfoTeken," +
    " rcLeegHtml, rcChipHtml, bevestigActie, laadRaces, rcPasGeplaatstToe, rcKaart," +
    " rcVerstuur, rcControleer, rcFocusNa, rcZelfdeWens," +
    " zetScope: s => { rcScope = s; }, stand: () => rcItems, geplaatst: () => rcGeplaatst," +
    " onzeker: () => rcOnzeker };"
  )(document, $, esc, ic, haptic, jpost, api, melding, () => {}, scope, items);
  return { ...mod, posts, meldingen, gets };
}

// Laat de eerstvolgende bevestigingsdialoog beantwoorden met `akkoord`.
// Grijpt de knoppen uit de ECHTE overlay die bevestigActie zelf heeft gebouwd.
function beantwoordDialoog(akkoord) {
  dialoogKnop(akkoord ? ".pk-confirm" : ".pk-cancel").onclick();
}
// De overlay-structuur: bevestigActie zet één innerHTML op de overlay. Onze shim geeft
// per selector één stub terug, dus .pk-confirm hangt direct aan de overlay.
function dialoogKnop(sel) {
  const ov = laatsteOverlay();
  if (!ov) throw new Error("geen dialoog geopend");
  const k = ov.querySelector(sel);
  if (!k) throw new Error("knop niet in de markup: " + sel);
  return k;
}
const openOverlays = () => document.body.children.filter(c => c.className.includes("pk-overlay"));
const laatsteOverlay = () => openOverlays().slice(-1)[0] || null;
// Beantwoord ELKE open dialoog. Zou een regressie er een tweede openen, dan settelen
// beide promises alsnog en faalt de bijbehorende check zichtbaar (i.p.v. een hang).
function beantwoordAlleDialogen(akkoord) {
  let n = 0;
  while (openOverlays().length && n++ < 5) beantwoordDialoog(akkoord);
  return n;
}
const tick = () => new Promise(r => setTimeout(r, 0));
// Datums RELATIEF aan vandaag: het chipvenster is 7 dagen, dus een vaste datum
// als "2099-01-01" zou de vensterlogica stilletjes overslaan.
const isoOver = d => { const x = new Date(); x.setDate(x.getDate() + d); return x.toISOString().slice(0, 10); };

console.log("== Races-afhandeling: bevestiging, afhandeling, telling ==\n");

// ══ R1 — bevestigActie: elke uitgang behalve 'bevestigen' is false ═══════════
{
  const { bevestigActie } = maakRaces();

  // 1a bevestigen
  {
    document.body.children = [];
    const p = bevestigActie({ titel: "T", tekst: "t", bevestig: "Plaats wens" });
    ok(document.body.children.length === 1, "R1.1 dialoog hangt in de body");
    const ov = laatsteOverlay();
    ok(ov.className.includes("pk-overlay"), "R1.2 hergebruikt de bestaande overlay-chrome", ov.className);
    ok(ov.innerHTML.includes('role="dialog"') && ov.innerHTML.includes('aria-modal="true"'),
       "R1.3 is een echte dialoog voor hulptechnologie");
    ok(ov.innerHTML.includes("Plaats wens"), "R1.4 bevestigknop draagt het meegegeven label");
    dialoogKnop(".pk-confirm").onclick();
    ok(await p === true, "R1.5 bevestigen levert true");
    ok(document.body.children.length === 0, "R1.6 dialoog is opgeruimd", document.body.children.length);
  }
  // 1b annuleren / kruisje / backdrop / Escape → allemaal false
  for (const [naam, sluit] of [
    ["Annuleren", () => dialoogKnop(".pk-cancel").onclick()],
    ["kruisje", () => dialoogKnop(".pk-x").onclick()],
    ["backdrop", () => { const ov = laatsteOverlay(); ov.vuur("click", { target: ov }); }],
    ["Escape", () => docKeys.slice().forEach(f => f({ key: "Escape", preventDefault() {} }))],
  ]) {
    document.body.children = [];
    const p = bevestigActie({ tekst: "t" });
    sluit();
    ok(await p === false, `R1.7 ${naam} levert false (geen actie)`);
    ok(document.body.children.length === 0, `R1.8 ${naam} ruimt de dialoog op`);
  }
  // 1c backdrop-klik OP de modal (niet de overlay) sluit niet — anders sluit elke klik erin
  {
    document.body.children = [];
    let af = false;
    bevestigActie({ tekst: "t" }).then(() => { af = true; });
    const ov = laatsteOverlay();
    ov.vuur("click", { target: new El("div") });      // klik binnen de modal
    await tick();
    ok(af === false, "R1.9 klik binnen de dialoog sluit hem niet");
    dialoogKnop(".pk-cancel").onclick();
  }
  // 1d precies één antwoord, ook bij twee uitgangen achter elkaar
  {
    document.body.children = [];
    let n = 0;
    const p = bevestigActie({ tekst: "t" }).then(v => { n++; return v; });
    const esc1 = docKeys.slice();
    dialoogKnop(".pk-cancel").onclick();
    esc1.forEach(f => f({ key: "Escape", preventDefault() {} }));   // tweede uitgang
    await p; await tick();
    ok(n === 1, "R1.10 één vraag levert precies één antwoord", n);
    ok(docKeys.length === 0, "R1.11 keydown-listener is opgeruimd (geen lek)", docKeys.length);
  }
}

// ══ R2 — rcPlaats: bevestiging is een echte poort, dubbelklik telt één keer ══
{
  // 2a geannuleerd → geen enkele post, tekst blijft staan
  {
    const it = { id: "r1", voornaam: "Sanne", race: "10 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const R = maakRaces({ items: [it] });
    const kaart = R.raceItem(it);
    document.body.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "Rustig starten.";
    const p = R.rcPlaats(kaart, it);
    await tick();
    beantwoordDialoog(false);
    await p;
    ok(R.posts.length === 0, "R2.1 annuleren post niets", R.posts.length);
    ok(kaart.querySelector(".fb-tekst").value === "Rustig starten.", "R2.2 getypte tekst blijft staan");
    ok(it.wens_gegeven === false, "R2.3 race blijft open na annuleren");
    ok(kaart.querySelector("[data-post]").disabled === false, "R2.4 knop is weer bruikbaar");
  }
  // 2b bevestigd → precies één post met de juiste payload
  {
    const it = { id: "r2", voornaam: "Tim", race: "Marathon", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const R = maakRaces({ scope: "alle", items: [it] });
    byId["rc-lijst"] = new El("div");
    const kaart = R.raceItem(it);
    document.body.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "Negatieve split.";
    const p = R.rcPlaats(kaart, it);
    await tick();
    beantwoordDialoog(true);
    await p;
    ok(R.posts.length === 1, "R2.5 bevestigen post precies één keer", R.posts.length);
    ok(R.posts[0].u === "/api/races/wens", "R2.6 ongewijzigd endpoint", R.posts[0].u);
    ok(R.posts[0].b.id === "r2" && R.posts[0].b.tekst === "Negatieve split.",
       "R2.7 payload = deze race + de getypte tekst", JSON.stringify(R.posts[0].b));
  }
  // 2c dubbelklik tijdens een lopend verzoek → nog steeds één post
  {
    const it = { id: "r3", voornaam: "Eva", race: "15 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    // Poort die OPEN BLIJFT: `los()` lost de lopende post op én laat elke latere post
    // meteen slagen. Zou een regressie een tweede post doen (ook ná `los`), dan settelt
    // die ook en faalt de TELLING zichtbaar — i.p.v. een hangende await die niets zegt.
    const wachters = [];
    let losgelaten = false;
    const los = v => { losgelaten = true; wachters.splice(0).forEach(r => r(v)); };
    const R = maakRaces({ scope: "alle", items: [it],
      post: () => losgelaten ? Promise.resolve({ ok: true }) : new Promise(r => wachters.push(r)) });
    byId["rc-lijst"] = new El("div");
    const kaart = R.raceItem(it);
    document.body.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "Ga ervoor.";
    const p1 = R.rcPlaats(kaart, it);
    await tick();
    beantwoordDialoog(true);
    await tick();                                     // request loopt nu
    const p2 = R.rcPlaats(kaart, it);                 // tweede klik
    await tick();
    ok(document.body.children.filter(c => c.className.includes("pk-overlay")).length === 0,
       "R2.8 tweede klik opent geen tweede bevestiging");
    beantwoordAlleDialogen(true);          // een regressie-dialoog mag niet blijven hangen
    los({ ok: true });
    await p1; await p2;
    ok(R.posts.length === 1, "R2.9 dubbelklik levert één FinalSurge-comment", R.posts.length);
  }
  // 2d dubbelklik terwijl de BEVESTIGING openstaat → ook één dialoog
  {
    const it = { id: "r4", voornaam: "Noor", race: "5 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const R = maakRaces({ scope: "alle", items: [it] });
    byId["rc-lijst"] = new El("div");
    const kaart = R.raceItem(it);
    document.body.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "Tempo vasthouden.";
    const p1 = R.rcPlaats(kaart, it);
    await tick();
    const p2 = R.rcPlaats(kaart, it);                 // dialoog staat nog open
    await tick();
    const overlays = document.body.children.filter(c => c.className.includes("pk-overlay"));
    ok(overlays.length === 1, "R2.10 openstaande bevestiging blokkeert een tweede", overlays.length);
    beantwoordAlleDialogen(true);
    await p1; await p2;
    ok(R.posts.length === 1, "R2.11 en levert één post", R.posts.length);
  }
  // 2e lege tekst → geen dialoog, geen post
  {
    const it = { id: "r5", voornaam: "Bo", race: "10 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const R = maakRaces({ items: [it] });
    const kaart = R.raceItem(it);
    document.body.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "   ";
    await R.rcPlaats(kaart, it);
    ok(R.posts.length === 0, "R2.12 lege wens post niets");
    ok(R.meldingen.some(m => m.err && /Schrijf eerst/.test(m.t)), "R2.13 en zegt wat er moet gebeuren");
  }
}

// ══ R3 — foutpad: expliciete afwijzing vs ONBEKENDE uitkomst ═══════════════
{
  // 3a de server WIJST AF → 'niet geplaatst' is een feit; eigen actielabel terug.
  {
    const it = { id: "e1", voornaam: "Jur", race: "Halve", datum: "2099-01-01",
                 wens: "Vorige wens", wens_gegeven: true };
    const R = maakRaces({ scope: "alle", items: [it],
                          post: () => Promise.resolve({ ok: false, err: "Posten mislukt: 500" }) });
    byId["rc-lijst"] = new El("div"); byId["rc-info"] = new El("div");
    const kaart = R.raceItem(it); byId["rc-lijst"].appendChild(kaart);
    document.body.appendChild(byId["rc-lijst"]);
    const veld = kaart.querySelector(".fb-tekst");
    veld.value = "Nieuwe wens die niet verloren mag gaan.";
    const btn = kaart.querySelector("[data-post]");
    const labelVoor = btn.innerHTML;
    const p = R.rcPlaats(kaart, it);
    await tick(); beantwoordDialoog(true); await p;
    ok(veld.value === "Nieuwe wens die niet verloren mag gaan.", "R3.1 afgewezen: tekst blijft staan");
    ok(it.wens === "Vorige wens" && it.wens_gegeven === true, "R3.2 afgewezen: stand ongewijzigd");
    ok(btn.disabled === false, "R3.3 afgewezen: knop weer bruikbaar");
    ok(btn.innerHTML === labelVoor, "R3.4 afgewezen: eigen actielabel terug", btn.innerHTML);
    ok(R.meldingen.some(m => m.err && /niet geplaatst|mislukt/i.test(m.t)),
       "R3.5 afgewezen: eerlijke foutmelding");
    ok(R.onzeker().size === 0, "R3.6 afgewezen: geen onzekerheid — dit is bewezen mislukt");
    ok(kaart.isConnected, "R3.7 afgewezen: kaart blijft staan");
  }
  // 3b NETWERKFOUT + controle vindt niets → onbekend, GEEN bewering dat het mislukt is.
  {
    const it = { id: "e2", voornaam: "Ann", race: "10 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const R = maakRaces({ scope: "alle", items: [it],
                          post: () => Promise.reject(new Error("offline")),
                          haal: () => ({ fs: true, items: [{ ...it }] }) });   // server: nog geen wens
    byId["rc-lijst"] = new El("div"); byId["rc-info"] = new El("div");
    const kaart = R.raceItem(it); byId["rc-lijst"].appendChild(kaart);
    document.body.appendChild(byId["rc-lijst"]);
    kaart.querySelector(".fb-tekst").value = "Onzekere wens.";
    const p = R.rcPlaats(kaart, it);
    await tick(); beantwoordDialoog(true); await p;
    const btn = kaart.querySelector("[data-post]");
    ok(kaart.querySelector(".fb-tekst").value === "Onzekere wens.", "R3.8 onbekend: tekst blijft staan");
    ok(it.wens_gegeven === false, "R3.9 onbekend: race niet afgehandeld");
    ok(R.onzeker().has("e2"), "R3.10 onbekend: race is als onzeker gemarkeerd");
    ok(/Opnieuw proberen/.test(btn.innerHTML), "R3.11 onbekend: knop biedt geen gewone herhaling",
       btn.innerHTML);
    const st = kaart.querySelector("[data-poststatus]").textContent;
    ok(/Onbekend of deze wens is aangekomen/.test(st), "R3.12 onbekend: onzekerheid staat op de kaart", st);
    ok(R.meldingen.some(m => /Mogelijk is de wens wél geplaatst/.test(m.t)),
       "R3.13 onbekend: nooit beweren dat er niets is geplaatst");
    ok(R.geplaatst().size === 0, "R3.14 onbekend: niet als geplaatst geboekt");

    // Opnieuw proberen = een EIGEN, expliciete bevestiging (geen blinde herhaling).
    R.rcPlaats(kaart, it);
    await tick();
    const ov = laatsteOverlay();
    ok(/Toch opnieuw plaatsen/.test(ov.innerHTML), "R3.15 herhaling vraagt expliciete bevestiging");
    ok(/niet bevestigd of hij is aangekomen/.test(ov.innerHTML),
       "R3.16 en benoemt dat de vorige poging al aangekomen kan zijn");
    beantwoordDialoog(false);
    await tick();
  }
  // 3c server HEEFT VERWERKT maar de respons ging verloren → controle bevestigt succes.
  {
    const it = { id: "e3", voornaam: "Bram", race: "5 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const R = maakRaces({ scope: "alle", items: [it],
                          post: () => Promise.reject(new Error("connection reset")),
                          haal: () => ({ fs: true, items: [{ ...it, wens_gegeven: true, wens: "Aangekomen." }] }) });
    byId["rc-lijst"] = new El("div"); byId["rc-info"] = new El("div");
    const kaart = R.raceItem(it); byId["rc-lijst"].appendChild(kaart);
    document.body.appendChild(byId["rc-lijst"]);
    kaart.querySelector(".fb-tekst").value = "Aangekomen.";
    const p = R.rcPlaats(kaart, it);
    await tick(); beantwoordDialoog(true); await p;
    ok(R.gets.some(u => u === "/api/races"), "R3.17 onbekend → er wordt gecontroleerd", R.gets);
    ok(it.wens_gegeven === true, "R3.18 controle bevestigt: race is wél afgehandeld");
    ok(R.onzeker().size === 0, "R3.19 en er blijft geen valse onzekerheid staan");
    ok(R.geplaatst().get("e3") === "Aangekomen.", "R3.20 als geplaatst geboekt");
    ok(!R.meldingen.some(m => m.err), "R3.21 geen foutmelding voor iets dat gelukt is");
  }
  // 3d de controle mag NOOIT mislukking concluderen uit 'nog geen wens'.
  {
    const R = maakRaces({ haal: () => ({ fs: true, items: [{ id: "x", wens_gegeven: false, wens: "" }] }) });
    ok(await R.rcControleer("x", "B") === "onbekend", "R3.22 'nog geen wens' = onbekend, niet mislukt");
    const R2 = maakRaces({ haal: () => ({ fs: true, items: [{ id: "x", wens_gegeven: true, wens: "B" }] }) });
    ok(await R2.rcControleer("x", "B") === "geplaatst", "R3.23 wens aanwezig = bevestigd geplaatst");
    const R3 = maakRaces({ haal: () => ({ fs: false }) });
    ok(await R3.rcControleer("x", "B") === "onbekend", "R3.24 geen FinalSurge = geen uitspraak");
    const R4 = maakRaces({ haal: () => { throw new Error("stuk"); } });
    ok(await R4.rcControleer("x", "B") === "onbekend", "R3.25 mislukte controle = geen uitspraak");
  }
}

// ══ R4 — na een bevestigde plaatsing ════════════════════════════════════════
{
  // 4a 7-dagenfilter: de race hoort er niet meer thuis
  {
    const a = { id: "x1", voornaam: "Ilse", race: "10 km", datum: isoOver(3), wens: "", wens_gegeven: false };
    const b = { id: "x2", voornaam: "Rik", race: "5 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const items = [a, b];
    const R = maakRaces({ scope: "7d", items });
    const lijst = new El("div"); byId["rc-lijst"] = lijst;
    const info = new El("div"); byId["rc-info"] = info;
    const kaartA = R.raceItem(a); lijst.appendChild(kaartA);
    lijst.appendChild(R.raceItem(b));
    // Home staat open met dezelfde belofte: die chip moet meebewegen (wiring-bewijs).
    const strip = new El("div"), chip = new El("button");
    chip.dataset.races = "2";
    byId["home-info"] = strip; byId["home-race-chip"] = chip;
    R.rcNaPlaatsing(a.id, { voornaam: a.voornaam, datum: a.datum, wasOpen: true }, "Sterk finishen.");
    ok(chip.dataset.races === "1", "R4.0 afhandelen werkt de Home-chip bij", chip.dataset.races);
    byId["home-info"] = null; byId["home-race-chip"] = null;
    ok(!kaartA.isConnected && lijst.children.length === 1,
       "R4.1 7d: afgehandelde race verdwijnt uit de lijst", lijst.children.length);
    ok(items.length === 1 && items[0].id === "x2", "R4.2 7d: client-stand volgt de weergave",
       JSON.stringify(items.map(i => i.id)));
    ok(/1 race zonder wens/.test(info.textContent), "R4.3 7d: telling gaat 2 → 1", info.textContent);
    ok(a.wens_gegeven === true && a.wens === "Sterk finishen.", "R4.4 stand van de race is bijgewerkt");
  }
  // 4b laatste race weg → lege staat i.p.v. een lege lijst
  {
    const a = { id: "y1", voornaam: "Sam", race: "10 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const items = [a];
    const R = maakRaces({ scope: "7d", items });
    const lijst = new El("div"); byId["rc-lijst"] = lijst;
    const info = new El("div"); byId["rc-info"] = info;
    const kaart = R.raceItem(a); lijst.appendChild(kaart);
    R.rcNaPlaatsing(a.id, { voornaam: a.voornaam, datum: a.datum, wasOpen: true }, "Geniet ervan.");
    ok(/Geen races zonder wens/.test(lijst.innerHTML), "R4.5 7d: expliciete lege staat", lijst.innerHTML);
    ok(info.textContent === "", "R4.6 7d: geen telling meer bij een lege lijst", info.textContent);
  }
  // 4c volledig overzicht: kaart BLIJFT, met wens en 'Wens bijwerken'
  {
    const a = { id: "z1", voornaam: "Fleur", race: "Marathon", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const b = { id: "z2", voornaam: "Daan", race: "10 km", datum: "2099-01-01", wens: "Al gedaan", wens_gegeven: true };
    const items = [a, b];
    const R = maakRaces({ scope: "alle", items });
    const lijst = new El("div"); byId["rc-lijst"] = lijst;
    const info = new El("div"); byId["rc-info"] = info;
    const kaartA = R.raceItem(a); lijst.appendChild(kaartA);
    lijst.appendChild(R.raceItem(b));
    R.rcNaPlaatsing(a.id, { voornaam: a.voornaam, datum: a.datum, wasOpen: true }, "Blijf bij je tempo.");
    ok(lijst.children.length === 2, "R4.7 alle: de race blijft zichtbaar", lijst.children.length);
    const vers = lijst.children[0];
    ok(vers !== kaartA, "R4.8 alle: kaart is herbouwd uit de nieuwe stand");
    ok(vers.innerHTML.includes("Blijf bij je tempo."), "R4.9 alle: de geplaatste wens staat er");
    ok(vers.innerHTML.includes("wens gegeven"), "R4.10 alle: status is 'wens gegeven'");
    ok(vers.innerHTML.includes("Wens bijwerken"), "R4.11 alle: actie is nu bijwerken");
    ok(!/>\s*Plaats wens/.test(vers.innerHTML), "R4.12 alle: niet meer 'Plaats wens'");
    ok(/alle wensen gegeven/.test(info.textContent), "R4.13 alle: open telling is bij", info.textContent);
  }
  // 4d een tweede kaart met getypte tekst mag NIET gewist worden
  {
    const a = { id: "w1", voornaam: "Pim", race: "10 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const b = { id: "w2", voornaam: "Lot", race: "5 km", datum: "2099-01-01", wens: "", wens_gegeven: false };
    const items = [a, b];
    const R = maakRaces({ scope: "alle", items });
    const lijst = new El("div"); byId["rc-lijst"] = lijst;
    byId["rc-info"] = new El("div");
    const kaartA = R.raceItem(a); lijst.appendChild(kaartA);
    const kaartB = R.raceItem(b); lijst.appendChild(kaartB);
    kaartB.querySelector(".fb-tekst").value = "Nog niet geplaatst concept.";
    R.rcNaPlaatsing(a.id, { voornaam: a.voornaam, datum: a.datum, wasOpen: true }, "Ok.");
    ok(kaartB.querySelector(".fb-tekst").value === "Nog niet geplaatst concept.",
       "R4.14 concept in een ANDERE kaart blijft behouden");
  }
}

// ══ R5 — Home-chip volgt de afhandeling ═════════════════════════════════════
{
  const maakChip = n => {
    const strip = new El("div"), chip = new El("button");
    chip.dataset.races = String(n);
    byId["home-info"] = strip; byId["home-race-chip"] = chip;
    return { strip, chip };
  };

  {
    const R = maakRaces();
    const { strip, chip } = maakChip(3);
    R.rcHomeChipBij(isoOver(2), -1);
    ok(chip.dataset.races === "2", "R5.1 chip telt af", chip.dataset.races);
    ok(/2 races zonder wens/.test(chip.innerHTML), "R5.2 chiplabel volgt de telling", chip.innerHTML);
    ok(strip.innerHTML === "", "R5.3 strip blijft staan zolang er iets open is");
  }
  {
    const R = maakRaces();
    const { strip, chip } = maakChip(1);
    R.rcHomeChipBij(isoOver(0), -1);
    ok(strip.innerHTML === "", "R5.4 laatste open race weg → chip verdwijnt");
    void chip;
  }
  {
    const R = maakRaces();
    const { chip } = maakChip(4);
    R.rcHomeChipBij(isoOver(30), -1);
    ok(chip.dataset.races === "4", "R5.5 race BUITEN het 7-dagenvenster raakt de chip niet", chip.dataset.races);
  }
  {
    const R = maakRaces();
    const { chip } = maakChip(2);
    R.rcHomeChipBij("", -1);
    ok(chip.dataset.races === "2", "R5.6 race zonder datum raakt de chip niet");
  }
  {
    // Home nog niet opgebouwd: geen chip in de DOM → geen crash.
    const R = maakRaces();
    byId["home-info"] = null; byId["home-race-chip"] = null;
    let stuk = false;
    try { R.rcHomeChipBij(isoOver(1), -1); } catch { stuk = true; }
    ok(!stuk, "R5.7 zonder opgebouwde Home geen fout");
  }
  {
    // Chip-label = één formulering, gedeeld met Home.
    const R = maakRaces();
    ok(R.rcChipHtml(1).includes("1 race ") && R.rcChipHtml(2).includes("2 races "),
       "R5.8 Nederlands meervoud in het chiplabel", R.rcChipHtml(1) + " / " + R.rcChipHtml(2));
  }
}

// ══ R6 — inforegel is een afgeleide van de stand ════════════════════════════
{
  const info = new El("div"); byId["rc-info"] = info;
  {
    const items = [{ wens_gegeven: false }, { wens_gegeven: true }, { wens_gegeven: false }];
    const R = maakRaces({ scope: "alle", items });
    R.rcInfoTeken();
    ok(/3 aankomende races/.test(info.textContent) && /2 zonder wens/.test(info.textContent),
       "R6.1 alle: totaal + open telling", info.textContent);
    items.forEach(i => { i.wens_gegeven = true; });
    R.rcInfoTeken();
    ok(/alle wensen gegeven/.test(info.textContent), "R6.2 alles afgehandeld leest als klaar", info.textContent);
  }
  {
    const R = maakRaces({ scope: "7d", items: [{ wens_gegeven: false }] });
    R.rcInfoTeken();
    ok(/1 race zonder wens in de komende 7 dagen/.test(info.textContent),
       "R6.3 7d: enkelvoud + het venster van de chip", info.textContent);
  }
  {
    const R = maakRaces({ scope: "7d", items: [] });
    R.rcInfoTeken();
    ok(info.textContent === "", "R6.4 lege lijst = geen telling");
  }
}

// ══ R7 — veroudering: filterwissel / verversing tijdens een traag POST ══════
// De vier gevraagde scenario's. Steeds hetzelfde patroon: POST hangt, de lijst
// verandert onder de plaatsing door, en pas daarna komt het succes binnen.
{
  const races = () => ([
    { id: "s1", naam: "Sanne Vos", voornaam: "Sanne", datum: isoOver(3), race: "10 km", type: "", wens_gegeven: false, wens: "" },
    { id: "s2", naam: "Tom Rijk", voornaam: "Tom", datum: isoOver(5), race: "5 km", type: "", wens_gegeven: false, wens: "" },
    { id: "s3", naam: "Ida Blok", voornaam: "Ida", datum: isoOver(25), race: "Marathon", type: "", wens_gegeven: false, wens: "" },
  ]);
  // Bouwt een omgeving met een echte lijst-DOM en een ophaalbare serverstand.
  function omgeving(scope, serverstand) {
    const wachters = [];
    let losgelaten = false;
    const los = v => { losgelaten = true; wachters.splice(0).forEach(r => r(v)); };
    const lijst = new El("section"); lijst.className = "lijst";
    const info = new El("p"), strip = new El("div"), chip = new El("button");
    chip.dataset.races = "2";
    byId = { "rc-lijst": lijst, "rc-info": info, "home-info": strip, "home-race-chip": chip };
    document.body.children = [lijst];
    const R = maakRaces({
      scope, items: [],
      post: () => losgelaten ? Promise.resolve({ ok: true }) : new Promise(r => wachters.push(r)),
      haal: u => ({ fs: true, items: serverstand(u) }),
    });
    return { R, los, lijst, info, chip, strip };
  }
  const open7d = it => !it.wens_gegeven && dagenTotTest(it.datum) <= 7;
  const dagenTotTest = d => Math.round((new Date(d) - new Date(new Date().toDateString())) / 864e5);
  const serverAlles = () => races();
  const server7d = () => races().filter(open7d);

  // 7a  7d → alle tijdens het verzoek
  {
    const { R, los, lijst, info, chip } = omgeving("7d", u => u.includes("zonder_wens") ? server7d() : serverAlles());
    await R.laadRaces();
    const kaart = R.rcKaart("s1");
    kaart.querySelector(".fb-tekst").value = "Wens voor Sanne.";
    const p = R.rcPlaats(kaart, { id: "s1", voornaam: "Sanne", datum: races()[0].datum, race: "10 km", wens: "", wens_gegeven: false });
    await tick(); beantwoordDialoog(true); await tick();
    R.zetScope("alle"); await R.laadRaces();          // coach wisselt van filter
    los({ ok: true }); await p; await tick();
    const nieuw = R.rcKaart("s1");
    ok(!!nieuw, "R7.1 7d→alle: de race staat in het volledige overzicht");
    ok(/wens gegeven/.test(nieuw.innerHTML), "R7.2 7d→alle: kaart toont de geplaatste wens", nieuw.innerHTML.slice(0,80));
    ok(/Wens bijwerken/.test(nieuw.innerHTML), "R7.3 7d→alle: actie is bijwerken");
    ok(/3 aankomende races/.test(info.textContent) && /2 zonder wens/.test(info.textContent),
       "R7.4 7d→alle: telling klopt", info.textContent);
    ok(chip.dataset.races === "1", "R7.5 7d→alle: Home-chip is afgeteld", chip.dataset.races);
    ok(R.stand().find(x => x.id === "s1").wens === "Wens voor Sanne.", "R7.6 7d→alle: stand bijgewerkt");
    ok(lijst.querySelectorAll("rij-kaart").length === 3, "R7.7 7d→alle: lijst compleet");
  }
  // 7b  alle → 7d tijdens het verzoek
  {
    const { R, los, lijst, info, chip } = omgeving("alle", u => u.includes("zonder_wens") ? server7d() : serverAlles());
    await R.laadRaces();
    const kaart = R.rcKaart("s1");
    kaart.querySelector(".fb-tekst").value = "Wens voor Sanne.";
    const p = R.rcPlaats(kaart, { id: "s1", voornaam: "Sanne", datum: races()[0].datum, race: "10 km", wens: "", wens_gegeven: false });
    await tick(); beantwoordDialoog(true); await tick();
    R.zetScope("7d"); await R.laadRaces();            // coach wisselt naar 'zonder wens'
    los({ ok: true }); await p; await tick();
    ok(!R.rcKaart("s1"), "R7.8 alle→7d: afgehandelde race staat NIET in 'zonder wens'");
    ok(!R.stand().some(x => x.id === "s1"), "R7.9 alle→7d: ook niet in de client-stand");
    ok(/1 race zonder wens/.test(info.textContent), "R7.10 alle→7d: telling klopt", info.textContent);
    ok(chip.dataset.races === "1", "R7.11 alle→7d: Home-chip afgeteld", chip.dataset.races);
    ok(lijst.querySelectorAll("rij-kaart").length === 1, "R7.12 alle→7d: alleen de nog open race");
  }
  // 7c  verversen tijdens het plaatsen (zelfde filter)
  {
    const { R, los, info, chip } = omgeving("7d", u => u.includes("zonder_wens") ? server7d() : serverAlles());
    await R.laadRaces();
    const kaart = R.rcKaart("s1");
    kaart.querySelector(".fb-tekst").value = "Wens voor Sanne.";
    const p = R.rcPlaats(kaart, { id: "s1", voornaam: "Sanne", datum: races()[0].datum, race: "10 km", wens: "", wens_gegeven: false });
    await tick(); beantwoordDialoog(true); await tick();
    await R.laadRaces();                              // coach ververst
    los({ ok: true }); await p; await tick();
    ok(!R.rcKaart("s1"), "R7.13 verversen: afgehandelde race is weg uit 'zonder wens'");
    ok(/1 race zonder wens/.test(info.textContent), "R7.14 verversen: telling klopt", info.textContent);
    ok(chip.dataset.races === "1", "R7.15 verversen: Home-chip afgeteld");
  }
  // 7d  een laadrespons die VÓÓR de plaatsing startte en ERNA binnenkomt
  {
    const { R, los, info, chip } = omgeving("7d", u => u.includes("zonder_wens") ? server7d() : serverAlles());
    await R.laadRaces();
    // Trage listing die nog niets van de wens weet.
    let laatLos;
    const traag = new Promise(r => { laatLos = () => r({ fs: true, items: server7d() }); });
    R.__traag = traag;
    const kaart = R.rcKaart("s1");
    kaart.querySelector(".fb-tekst").value = "Wens voor Sanne.";
    const p = R.rcPlaats(kaart, { id: "s1", voornaam: "Sanne", datum: races()[0].datum, race: "10 km", wens: "", wens_gegeven: false });
    await tick(); beantwoordDialoog(true); await tick();
    los({ ok: true }); await p; await tick();
    ok(!R.rcKaart("s1"), "R7.16 race is afgehandeld en verdwenen");
    // Nu komt de OUDE listing alsnog binnen: hij mag de plaatsing niet terugdraaien.
    const naOverlay = R.rcPasGeplaatstToe(server7d(), true);
    ok(!naOverlay.some(x => x.id === "s1"),
       "R7.17 late oude respons herleeft de geplaatste race NIET", naOverlay.map(x => x.id));
    ok(/1 race zonder wens/.test(info.textContent), "R7.18 telling blijft kloppen", info.textContent);
    ok(chip.dataset.races === "1", "R7.19 Home-chip blijft kloppen");
    laatLos();
  }
  // 7e  overlay laat los zodra de server bijgetrokken is
  {
    const { R } = omgeving("alle", serverAlles);
    await R.laadRaces();
    R.rcNaPlaatsing("s1", { voornaam: "Sanne", datum: races()[0].datum, wasOpen: true }, "Klaar.");
    ok(R.geplaatst().has("s1"), "R7.20 overlay onthoudt de plaatsing");
    const bij = R.rcPasGeplaatstToe(races().map(x => x.id === "s1" ? { ...x, wens_gegeven: true, wens: "Klaar." } : x), false);
    ok(!R.geplaatst().has("s1"), "R7.21 server bijgetrokken → overlay laat los");
    ok(bij.find(x => x.id === "s1").wens_gegeven === true, "R7.22 en de serverwaarheid staat er");
  }
  // 7f  concepttekst in ANDERE kaarten overleeft een plaatsing
  {
    const { R } = omgeving("alle", serverAlles);
    await R.laadRaces();
    R.rcKaart("s2").querySelector(".fb-tekst").value = "Concept voor Tom.";
    R.rcNaPlaatsing("s1", { voornaam: "Sanne", datum: races()[0].datum, wasOpen: true }, "Klaar.");
    ok(R.rcKaart("s2").querySelector(".fb-tekst").value === "Concept voor Tom.",
       "R7.23 concept in een andere kaart blijft behouden");
  }
  // 7g  mislukking ná een herbouw schrijft de getypte tekst terug
  {
    const { R } = omgeving("alle", serverAlles);
    await R.laadRaces();
    const oud = R.rcKaart("s2");
    await R.laadRaces();                              // herbouw: `oud` is nu losgekoppeld
    R.rcNaMislukking("s2", oud, "Niet kwijtraken.", "LABEL", { status: "afgewezen", err: "nee" });
    ok(R.rcKaart("s2").querySelector(".fb-tekst").value === "Niet kwijtraken.",
       "R7.24 tekst staat terug op de ACTUELE kaart");
  }
}

// ══ R8 — laadvolgorde: alleen de nieuwste respons tekent ════════════════════
{
  const lijst = new El("section"), info = new El("p");
  byId = { "rc-lijst": lijst, "rc-info": info };
  const wachters = [];                                 // resolvers in aanroepvolgorde
  const R = maakRaces({ scope: "alle", items: [], haal: () => new Promise(r => wachters.push(r)) });
  const race = (id, naam) => ({ id, naam, voornaam: naam, datum: isoOver(2), race: "r", type: "",
                                wens_gegeven: false, wens: "" });
  const A = R.laadRaces();                             // laadactie A (ouder)
  await tick();
  const B = R.laadRaces();                             // laadactie B (nieuwer)
  await tick();
  ok(wachters.length === 2, "R8.0 twee verzoeken onderweg", wachters.length);
  wachters[1]({ fs: true, items: [race("nieuw", "Nieuw")] });   // B komt eerst binnen
  await B;
  ok(R.stand().map(x => x.id).join() === "nieuw", "R8.1 de nieuwste respons vult de lijst",
     R.stand().map(x => x.id));
  wachters[0]({ fs: true, items: [race("oud", "Oud")] });       // A komt ALSNOG binnen
  await A;
  ok(R.stand().map(x => x.id).join() === "nieuw",
     "R8.2 een oudere respons overschrijft de lijst daarna niet meer", R.stand().map(x => x.id));
  ok(lijst.querySelectorAll("rij-kaart").every(k => k.dataset.id !== "oud"),
     "R8.3 en tekent ook niets in de DOM");
}

// ══ R9 — de controle moet de VERSTUURDE wens herkennen ══════════════════════
// Bij bijwerken staat er al een wens. Het bestaan daarvan is geen bewijs dat de
// nieuwe tekst is aangekomen; anders meldt de app een plaatsing die niet gebeurd is.
{
  // 9a de vergelijking zelf
  {
    const { rcZelfdeWens } = maakRaces();
    ok(rcZelfdeWens("B", "B") === true, "R9.1 gelijke tekst telt");
    ok(rcZelfdeWens("A", "B") === false, "R9.2 andere tekst telt niet");
    ok(rcZelfdeWens("", "B") === false, "R9.3 lege wens telt niet");
    ok(rcZelfdeWens(null, "B") === false, "R9.4 ontbrekende wens telt niet");
    ok(rcZelfdeWens("", "") === false, "R9.5 twee keer leeg is geen bewijs");
    ok(rcZelfdeWens(" B \n met  ruimte ", "B met ruimte") === true,
       "R9.6 witruimteverschillen van de server tellen niet mee");
  }
  // 9b DE GEVRAAGDE REGRESSIE: wens A staat er, we plaatsen B, respons verloren,
  //    de controle leest A terug. Verwacht: onbekend, B als concept, geen succes.
  {
    const it = { id: "u1", voornaam: "Rik", race: "Halve", datum: isoOver(4),
                 wens: "A: rustig openen.", wens_gegeven: true };
    const R = maakRaces({
      scope: "alle", items: [it],
      post: () => Promise.reject(new Error("verbinding weg")),
      haal: () => ({ fs: true, items: [{ ...it }] }),          // server: nog steeds A
    });
    const lijst = new El("section"); byId["rc-lijst"] = lijst; byId["rc-info"] = new El("div");
    const strip = new El("div"), chip = new El("button"); chip.dataset.races = "2";
    byId["home-info"] = strip; byId["home-race-chip"] = chip;
    document.body.children = [lijst];
    const kaart = R.raceItem(it); lijst.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "B: negatieve split.";
    const p = R.rcPlaats(kaart, it);
    await tick(); beantwoordDialoog(true); await p;

    ok(R.gets.some(u => u === "/api/races"), "R9.7 er is gecontroleerd");
    ok(R.onzeker().has("u1"), "R9.8 uitkomst blijft ONBEKEND (oude wens is geen bewijs)");
    ok(R.geplaatst().size === 0, "R9.9 niet als geplaatst geboekt");
    ok(it.wens === "A: rustig openen." && it.wens_gegeven === true,
       "R9.10 de stand toont nog steeds de OUDE wens", it.wens);
    ok(R.rcKaart("u1").querySelector(".fb-tekst").value === "B: negatieve split.",
       "R9.11 B blijft als concept in het veld staan");
    ok(!R.meldingen.some(m => !m.err && /geplaatst bij/i.test(m.t)),
       "R9.12 geen succesmelding", R.meldingen.map(m => m.t));
    ok(R.meldingen.some(m => /Mogelijk is de wens wél geplaatst/.test(m.t)),
       "R9.13 wel de onzekerheid benoemd");
    ok(chip.dataset.races === "2", "R9.14 Home-chip onaangeroerd", chip.dataset.races);
    ok(/Opnieuw proberen/.test(R.rcKaart("u1").querySelector("[data-post]").innerHTML),
       "R9.15 geen blinde herhaling");
  }
  // 9c dezelfde situatie, maar de controle leest B terug → succes MAG bevestigd worden.
  {
    const it = { id: "u2", voornaam: "Rik", race: "Halve", datum: isoOver(4),
                 wens: "A: rustig openen.", wens_gegeven: true };
    const R = maakRaces({
      scope: "alle", items: [it],
      post: () => Promise.reject(new Error("verbinding weg")),
      haal: () => ({ fs: true, items: [{ ...it, wens: "B: negatieve split." }] }),
    });
    const lijst = new El("section"); byId["rc-lijst"] = lijst; byId["rc-info"] = new El("div");
    byId["home-info"] = new El("div"); byId["home-race-chip"] = null;
    document.body.children = [lijst];
    const kaart = R.raceItem(it); lijst.appendChild(kaart);
    kaart.querySelector(".fb-tekst").value = "B: negatieve split.";
    const p = R.rcPlaats(kaart, it);
    await tick(); beantwoordDialoog(true); await p;
    ok(R.onzeker().size === 0, "R9.16 controle met B bevestigt succes");
    ok(R.geplaatst().get("u2") === "B: negatieve split.", "R9.17 als geplaatst geboekt");
    ok(it.wens === "B: negatieve split.", "R9.18 stand toont de nieuwe wens");
  }
  // 9d overlay laat NIET los op een oude wens; wél op de onze.
  {
    const R = maakRaces({ scope: "alle", items: [] });
    R.geplaatst().set("z1", "B");
    let uit = R.rcPasGeplaatstToe([{ id: "z1", wens_gegeven: true, wens: "A" }], false);
    ok(R.geplaatst().has("z1"), "R9.19 oude wens laat de overlay NIET los");
    ok(uit[0].wens === "B", "R9.20 en de kaart toont onze tekst, niet A", uit[0].wens);
    uit = R.rcPasGeplaatstToe([{ id: "z1", wens_gegeven: true, wens: "B" }], false);
    ok(!R.geplaatst().has("z1"), "R9.21 onze wens laat de overlay wél los");
    ok(uit[0].wens === "B", "R9.22 serverwaarheid staat er");
  }
}

// ══ R10 — een GEFILTERDE lijst mag niets buiten zijn bereik opruimen ════════
{
  // 10a de gevraagde regressie: race over 30 dagen plaatsen in 'alle', dan 7d laden,
  //     dan 'alle' met een achterlopende server.
  {
    const ver = { id: "v1", naam: "Iris Wolf", voornaam: "Iris", datum: isoOver(30),
                  race: "Marathon", type: "", wens_gegeven: false, wens: "" };
    const dichtbij = { id: "v2", naam: "Joep Dam", voornaam: "Joep", datum: isoOver(4),
                       race: "10 km", type: "", wens_gegeven: false, wens: "" };
    // Server loopt achter: kent de wens op v1 niet.
    const serverAlles = () => [{ ...ver }, { ...dichtbij }];
    const server7d = () => [{ ...dichtbij }];               // v1 valt buiten het venster
    const R = maakRaces({ scope: "alle", items: [],
                          haal: u => ({ fs: true, items: u.includes("zonder_wens") ? server7d() : serverAlles() }) });
    const lijst = new El("section"); byId["rc-lijst"] = lijst;
    const info = new El("div"); byId["rc-info"] = info;
    const strip = new El("div"), chip = new El("button"); chip.dataset.races = "1";
    byId["home-info"] = strip; byId["home-race-chip"] = chip;
    document.body.children = [lijst];

    await R.laadRaces();
    R.rcNaPlaatsing("v1", { voornaam: "Iris", datum: ver.datum, wasOpen: true }, "Marathonwens.");
    ok(R.geplaatst().get("v1") === "Marathonwens.", "R10.1 plaatsing geboekt");
    ok(chip.dataset.races === "1",
       "R10.2 race BUITEN het chipvenster laat de Home-chip ongemoeid", chip.dataset.races);

    R.zetScope("7d"); await R.laadRaces();                  // 7d bevat v1 niet
    ok(R.geplaatst().has("v1"),
       "R10.3 een gefilterde lijst wist de plaatsing NIET", [...R.geplaatst().keys()]);

    R.zetScope("alle"); await R.laadRaces();                // server nog steeds achter
    const kaart = R.rcKaart("v1");
    ok(!!kaart, "R10.4 de race staat weer in het volledige overzicht");
    ok(/wens gegeven/.test(kaart.innerHTML), "R10.5 en geldt nog steeds als geplaatst");
    ok(/Marathonwens\./.test(kaart.innerHTML), "R10.6 met de JUISTE wenstekst");
    ok(R.stand().find(x => x.id === "v1").wens === "Marathonwens.", "R10.7 ook in de stand");
    ok(chip.dataset.races === "1", "R10.8 Home-chip onveranderd", chip.dataset.races);
    ok(/1 zonder wens/.test(info.textContent), "R10.9 telling klopt", info.textContent);
  }
  // 10b een ONGEFILTERDE lijst mag wél opruimen (race is echt weg).
  {
    const R = maakRaces({ scope: "alle", items: [] });
    R.geplaatst().set("weg", "X");
    R.rcPasGeplaatstToe([{ id: "ander", wens_gegeven: false, wens: "" }], false);
    ok(!R.geplaatst().has("weg"), "R10.10 ongefilterde lijst ruimt een verdwenen race op");
  }
  // 10c ... en de gefilterde lijst blijft de geplaatste race uit 'zonder wens' houden.
  {
    const R = maakRaces({ scope: "7d", items: [] });
    R.geplaatst().set("p1", "X");
    const uit = R.rcPasGeplaatstToe([{ id: "p1", wens_gegeven: false, wens: "" },
                                     { id: "p2", wens_gegeven: false, wens: "" }], true);
    ok(uit.map(x => x.id).join() === "p2", "R10.11 geplaatste race hoort niet in 'zonder wens'", uit.map(x => x.id));
    ok(R.geplaatst().has("p1"), "R10.12 en blijft geboekt");
  }
}

// ══ R11 — verse client (na refresh): serverwaarheid alleen houdt 'm afgehandeld ══
// De actiewachtrij mag een geplaatste wens niet opnieuw als open actie tonen. Binnen
// een sessie doet de overlay dat; na een refresh is die leeg en moet de SERVER het
// dragen. Hier dus expliciet zonder overlay.
{
  const races = () => ([
    { id: "r1", naam: "A", voornaam: "A", datum: isoOver(3), race: "10 km", type: "", wens_gegeven: true, wens: "Al geplaatst." },
    { id: "r2", naam: "B", voornaam: "B", datum: isoOver(5), race: "5 km", type: "", wens_gegeven: false, wens: "" },
  ]);
  const server = u => ({ fs: true, items: u.includes("zonder_wens")
    ? races().filter(x => !x.wens_gegeven) : races() });

  // 7d = de actiewachtrij.
  {
    const lijst = new El("section"), info = new El("p");
    byId = { "rc-lijst": lijst, "rc-info": info };
    const R = maakRaces({ scope: "7d", items: [], haal: server });
    await R.laadRaces();
    ok(R.geplaatst().size === 0, "R11.1 verse client heeft geen overlay");
    const ids = lijst.querySelectorAll("rij-kaart").map(k => k.dataset.id);
    ok(ids.join() === "r2", "R11.2 afgehandelde race staat NIET in de actiewachtrij", ids);
    ok(/1 race zonder wens/.test(info.textContent), "R11.3 telling telt alleen open acties", info.textContent);
  }
  // Alle aankomende: de race bestaat nog, maar niet als OPEN succeswensactie.
  {
    const lijst = new El("section"), info = new El("p");
    byId = { "rc-lijst": lijst, "rc-info": info };
    const R = maakRaces({ scope: "alle", items: [], haal: server });
    await R.laadRaces();
    const kaarten = lijst.querySelectorAll("rij-kaart");
    ok(kaarten.length === 2, "R11.4 racedata blijft bestaan in het volledige overzicht", kaarten.length);
    const af = kaarten.find(k => k.dataset.id === "r1");
    ok(/wens gegeven/.test(af.innerHTML), "R11.5 en leest als afgehandeld");
    ok(/Wens bijwerken/.test(af.innerHTML) && !/>\s*Plaats wens/.test(af.innerHTML),
       "R11.6 de actie is bijwerken, niet 'plaats wens'");
    ok(/1 zonder wens/.test(info.textContent), "R11.7 alleen de open race telt als open", info.textContent);
  }
  // Alles afgehandeld binnen het venster → rustige lege staat, geen composer.
  {
    const lijst = new El("section"), info = new El("p");
    byId = { "rc-lijst": lijst, "rc-info": info };
    const R = maakRaces({ scope: "7d", items: [],
      haal: () => ({ fs: true, items: [] }) });      // server: niets meer open
    await R.laadRaces();
    ok(lijst.querySelectorAll("rij-kaart").length === 0, "R11.8 geen actiekaarten meer");
    ok(/Geen races zonder wens/.test(lijst.innerHTML), "R11.9 rustige lege staat", lijst.innerHTML);
    ok(!/fb-tekst/.test(lijst.innerHTML), "R11.10 en geen lege composer");
    ok(info.textContent === "", "R11.11 geen telling bij een lege wachtrij");
  }
}

if (failures.length) {
  console.error("races_afhandeling: " + failures.length + " CHECK(S) FAILED\n");
  failures.forEach(f => console.error("  ✗ " + f));
  process.exit(1);
}
console.log("races_afhandeling: all checks passed");
