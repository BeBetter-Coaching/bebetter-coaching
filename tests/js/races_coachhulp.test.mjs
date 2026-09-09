// Races Coachhulp v2 — EXECUTEERBARE clienttests.
//
//   node tests/js/races_coachhulp.test.mjs
//
// Snijdt de ECHTE functies verbatim uit pwa/static/app.js en draait ze tegen een DOM-shim
// die de werkelijk gerenderde markup leest. Bewijst:
//   C1  de kaart toont Coachhulp gesloten; openen laadt de context één keer (lazy).
//   C2  alleen aanwezige feiten worden getoond; ontbrekende velden geven GEEN lege kopjes.
//   C3  een actuele klacht mag compact mee; de strook zegt er zelf bij dat het geen oordeel is.
//   C4  onzekere context wordt als onzeker getoond, niet als 'niets aan de hand'.
//   C5  openen, genereren en sluiten sturen NOOIT iets naar FinalSurge.
//   C6  een voorstel komt in een EIGEN blok en niet automatisch in de composer.
//   C7  overnemen in een lege composer gaat direct; over bestaande tekst pas na bevestiging,
//       en bij weigeren blijft de tekst van de coach exact staan.
//   C8  openen/sluiten van Coachhulp laat getypte tekst ongemoeid.
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

// `rcHulpToggle` start het laden als een LOSSE promise (zoals de UI dat doet). Even de
// microtask-wachtrij doorlaten zodat de strook echt gevuld is voordat we hem lezen.
const tick = () => new Promise(r => setTimeout(r, 0));

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };

// ── DOM-shim ────────────────────────────────────────────────────────────────
// `querySelector` kijkt in de ECHT gerenderde markup: een selector die er niet in staat
// levert null (en dus een harde fout in de aanroeper), zodat hernoemde/verdwenen haken
// opvallen in plaats van weggemoffeld te worden. Gevonden knopen worden gecachet, zodat
// een textarea zijn waarde houdt tussen twee queries door — precies waar C7/C8 over gaan.
class El {
  constructor(tag) {
    this.tag = tag || "div"; this.children = []; this.parent = null;
    this.dataset = new Proxy({}, { set: (o, k, v) => { o[k] = String(v); return true; } });
    this.attrs = {}; this.disabled = false; this.value = "";
    this._html = ""; this._q = new Map(); this._on = {}; this._cls = new Set();
    const s = this._cls;
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
  get textContent() { return this._html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim(); }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this._on[t] = this._on[t] || []).push(f); }
  async vuur(t, ev) { for (const f of (this._on[t] || [])) await f(ev || {}); }
  focus() {}
  _haak(sel) {
    const s = String(sel);
    const m = /^[.[]?([a-z0-9_-]+)\]?$/i.exec(s);
    return m ? m[1] : s;
  }
  // Zoekt zoals de echte DOM: eerst in de eigen markup, daarna in de AFSTAMMELINGEN
  // (elementen waarvan de inhoud later met innerHTML is gevuld). Zonder die afdaling
  // zou een knop in een lazy geladen strook onvindbaar zijn.
  _zoek(sel) {
    const s = String(sel);
    const haak = this._haak(s);
    if (this._html.includes(haak)) {
      if (!this._q.has(s)) this._q.set(s, new El(haak === "fb-tekst" ? "textarea" : "button"));
      return this._q.get(s);
    }
    for (const kind of this._q.values()) {
      const hit = kind._zoek(s);
      if (hit) return hit;
    }
    return null;
  }
  querySelector(sel) { return this._zoek(sel); }
  querySelectorAll(sel) { const e = this._zoek(sel); return e ? [e] : []; }
}
const document = { createElement: t => new El(t), body: new El("body"), activeElement: null };

// ── waarnemingen ────────────────────────────────────────────────────────────
let posts, meldingen, bevestigAntwoord, bevestigGevraagd, kaartVoor;
function verse() { posts = []; meldingen = []; bevestigAntwoord = true; bevestigGevraagd = 0; kaartVoor = null; }

const PRIMS = [
  sliceLine("const esc = "), sliceLine("const _NL_MND = "),
  sliceFrom("function dagenTot("), sliceFrom("function nlDatum("), sliceFrom("function nlDagenTot("),
  sliceFrom("function initialen("), sliceFrom("function athleteNav("),
].join("\n");

function bouw(hulpRespons, voorstelRespons) {
  const api = async url => { posts.push({ url, method: "GET" }); return hulpRespons; };
  const jpost = async (url, body) => { posts.push({ url, body, method: "POST" }); return voorstelRespons; };
  const env = {
    document, api, jpost,
    ic: () => "", melding: t => meldingen.push(t),
    rcKaart: () => kaartVoor,
    bevestigActie: async () => { bevestigGevraagd++; return bevestigAntwoord; },
    rcPlaats: () => { throw new Error("rcPlaats mag hier niet draaien"); },
    openAthleteModule: () => {}, openWorkspace: () => {},
  };
  const namen = Object.keys(env);
  const body = PRIMS + "\n"
    + sliceLine("const rcHulp = new Map();") + "\n"
    + sliceFrom("function raceItem(") + "\n"
    + sliceFrom("function rcHulpToggle(") + "\n"
    + sliceFrom("async function rcHulpLaad(") + "\n"
    + sliceFrom("function rcHulpHtml(") + "\n"
    + sliceFrom("function rcHulpBind(") + "\n"
    + sliceFrom("async function rcVoorstel(") + "\n"
    + sliceFrom("async function rcNeemVoorstel(") + "\n"
    + "return { raceItem, rcHulpToggle, rcVoorstel, rcNeemVoorstel };";
  return new Function(...namen, body)(...namen.map(k => env[k]));
}

const IT = { id: "W1", naam: "Sanne de Vries", voornaam: "Sanne", atleet_key: "uk-sanne",
             datum: "2026-09-20", race: "Dam tot Damloop", type: "10 km",
             wens_gegeven: false, wens: "" };
const HULP = {
  ok: true, id: "W1", naam: "Sanne de Vries", voornaam: "Sanne", atleet_key: "uk-sanne",
  race: "Dam tot Damloop", type: "10 km", datum: "2026-09-20", dagen_tot: 4,
  beschrijving: "Vlak parcours, ga voor een PR.", wens: "",
  doel: "Onder de 50 minuten", belasting: "~42 km/week (trend: stabiel)",
  klachten: [{ area: "achilles", status: "ACTIVE", laatst_dagen: 3, aantal: 1 }],
  context_onzeker: false,
};
const VOORSTEL = { ok: true, tekst: "Veel succes zaterdag Sanne, je bent er klaar voor.",
                   persoonlijk: true, context_onzeker: false };

console.log("== Races Coachhulp: context bij de race, voorstel op verzoek, nooit een write ==\n");

// ══ C1 — lazy openen ═════════════════════════════════════════════════════════
{
  verse();
  const mod = bouw(HULP, VOORSTEL);
  const kaart = mod.raceItem(IT); kaartVoor = kaart;
  ok(/data-hulp\b/.test(kaart.innerHTML), "C1a de kaart heeft een Coachhulp-opener");
  ok(posts.length === 0, "C1b gesloten laadt niets", posts.length);

  const box = kaart.querySelector("[data-hulpbox]");
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  ok(box.classList.contains("open"), "C1c openen zet de strook open");
  ok(posts.filter(p => /coachhulp/.test(p.url)).length === 1, "C1d en laadt de context één keer",
     JSON.stringify(posts.map(p => p.url)));

  await mod.rcHulpToggle(kaart, IT);                          // sluiten
  await tick();
  await mod.rcHulpToggle(kaart, IT);                          // opnieuw openen
  await tick();
  ok(posts.filter(p => /coachhulp/.test(p.url)).length === 1, "C1e opnieuw openen laadt niet nog eens");
}

// ══ C2/C3 — feiten tonen, niets invullen ════════════════════════════════════
{
  verse();
  const mod = bouw(HULP, VOORSTEL);
  const kaart = mod.raceItem(IT); kaartVoor = kaart;
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  const html = kaart.querySelector("[data-hulpbox]").innerHTML;
  ok(/Dam tot Damloop/.test(html) && /10 km/.test(html), "C2a race en type");
  ok(/Onder de 50 minuten/.test(html), "C2b doel");
  ok(/Vlak parcours/.test(html), "C2c wat er bij de race genoteerd staat");
  ok(/42 km\/week/.test(html), "C2d recente belasting");
  ok(/achilles/.test(html), "C3a de actuele klacht mag compact mee");
  ok(/geen medisch oordeel/.test(html), "C3b met de grens erbij", html.slice(0, 80));
  ok(/anav/.test(html), "C2e navigatie naar de atleetpagina's");

  // Ontbrekende velden geven GEEN lege kopjes: een leeg kopje leest als 'niets aan de hand'.
  verse();
  const kaal = { ...HULP, doel: "", beschrijving: "", belasting: "", klachten: [] };
  const m2 = bouw(kaal, VOORSTEL);
  const k2 = m2.raceItem(IT); kaartVoor = k2;
  await m2.rcHulpToggle(k2, IT);
  await tick();
  const h2 = k2.querySelector("[data-hulpbox]").innerHTML;
  ok(!/Doel:/.test(h2) && !/Recente belasting/.test(h2), "C2f geen lege kopjes", h2.slice(0, 120));
  ok(!/Speelt nu/.test(h2), "C2g geen klachtregel zonder klacht");
  ok(/Dam tot Damloop/.test(h2), "C2h de racefeiten staan er nog wel");
}

// ══ C4 — onzekere context ════════════════════════════════════════════════════
{
  verse();
  const mod = bouw({ ...HULP, context_onzeker: true, doel: "", klachten: [] }, VOORSTEL);
  const kaart = mod.raceItem(IT); kaartVoor = kaart;
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  const html = kaart.querySelector("[data-hulpbox]").innerHTML;
  ok(/niet beschikbaar/.test(html), "C4a onzekerheid wordt benoemd", html.slice(0, 100));
  ok(!/Speelt nu/.test(html), "C4b en er worden geen klachten geclaimd");
}

// ══ C5 — nooit een write ═════════════════════════════════════════════════════
{
  verse();
  const mod = bouw(HULP, VOORSTEL);
  const kaart = mod.raceItem(IT); kaartVoor = kaart;
  await mod.rcHulpToggle(kaart, IT);                          // openen
  await tick();
  await mod.rcVoorstel(kaart, IT);                            // genereren
  await mod.rcHulpToggle(kaart, IT);                          // sluiten
  await tick();
  const schrijf = posts.filter(p => /\/api\/races\/wens/.test(p.url));
  ok(schrijf.length === 0, "C5a openen, genereren en sluiten posten geen wens",
     JSON.stringify(posts.map(p => p.method + " " + p.url)));
  ok(posts.some(p => p.url === "/api/races/voorstel" && p.body.id === "W1"),
     "C5b het voorstel vraagt alleen om tekst");
}

// ══ C6/C7 — voorstel in een eigen blok, overnemen is een eigen stap ══════════
{
  verse();
  const mod = bouw(HULP, VOORSTEL);
  const kaart = mod.raceItem(IT); kaartVoor = kaart;
  const ta = kaart.querySelector(".fb-tekst");
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  await mod.rcVoorstel(kaart, IT);
  const vb = kaart.querySelector("[data-voorstelbox]").innerHTML;
  ok(/Voorstel/.test(vb) && /klaar voor/.test(vb), "C6a het voorstel staat in een eigen blok");
  ok(ta.value === "", "C6b en NIET automatisch in de composer", JSON.stringify(ta.value));
  ok(/data-neem/.test(vb), "C6c overnemen is een aparte knop");

  // lege composer → direct overnemen, geen vraag
  await mod.rcNeemVoorstel(kaart, VOORSTEL.tekst, kaart.querySelector("[data-neem]"));
  ok(ta.value === VOORSTEL.tekst, "C7a lege composer krijgt het voorstel", ta.value);
  ok(bevestigGevraagd === 0, "C7b zonder onnodige vraag");

  // bestaande tekst → eerst bevestigen; weigeren laat de coachtekst staan
  ta.value = "Eigen wens die ik al had getypt.";
  bevestigAntwoord = false;
  await mod.rcNeemVoorstel(kaart, VOORSTEL.tekst, kaart.querySelector("[data-neem]"));
  ok(bevestigGevraagd === 1, "C7c bestaande tekst vraagt eerst om bevestiging");
  ok(ta.value === "Eigen wens die ik al had getypt.", "C7d en blijft bij weigeren exact staan", ta.value);

  bevestigAntwoord = true;
  await mod.rcNeemVoorstel(kaart, VOORSTEL.tekst, kaart.querySelector("[data-neem]"));
  ok(ta.value === VOORSTEL.tekst, "C7e na bevestigen wordt hij vervangen");
}

// ══ C8 — Coachhulp raakt de composer niet ════════════════════════════════════
{
  verse();
  const mod = bouw(HULP, VOORSTEL);
  const kaart = mod.raceItem(IT); kaartVoor = kaart;
  const ta = kaart.querySelector(".fb-tekst");
  ta.value = "Half getypte wens.";
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  await mod.rcVoorstel(kaart, IT);
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  await mod.rcHulpToggle(kaart, IT);
  await tick();
  ok(ta.value === "Half getypte wens.", "C8a openen/genereren/sluiten laat de tekst staan", ta.value);
}

// ══ bestaande wens blijft zichtbaar ══════════════════════════════════════════
{
  verse();
  const mod = bouw({ ...HULP, wens: "Heel veel succes zondag!" }, VOORSTEL);
  const kaart = mod.raceItem({ ...IT, wens_gegeven: true, wens: "Heel veel succes zondag!" });
  ok(/Heel veel succes zondag!/.test(kaart.innerHTML), "D1 de gegeven wens staat op de kaart");
  ok(/Wens bijwerken/.test(kaart.innerHTML), "D2 met het bestaande bijwerk-label");
}

if (failures.length) { console.log("FAIL\n - " + failures.join("\n - ")); process.exit(1); }
console.log("alle Races Coachhulp-tests groen");
