// Intake als ingang naar de coachflow — EXECUTEERBARE tests.
//
//   node tests/js/intake_flow.test.mjs
//
// Snijdt de ECHTE functies verbatim uit pwa/static/app.js en draait ze tegen een
// DOM-shim die de werkelijk gerenderde markup leest. Bewijst:
//   I1  nieuwe aanmelding zonder FinalSurge-match — flow ongewijzigd, en de zojuist
//       overgenomen intake wordt zichtbaar gemaakt (orphanlijst mee-verversen).
//   I2  aanmelding van iemand die AL atleet is — overnemen + koppelen in één actie,
//       met de sleutel die de SERVER teruggaf, en daarna de atleetroute mét id.
//   I3  'Bekijk atleet' navigeert naar `#workspace/<user_key>` (refresh-vast).
//   I4  geen match → geen koppel-write en geen atleetnavigatie; een eerder geopende
//       atleet lekt niet in deze intake.
//   I5  koppelen mislukt ná een geslaagde overname → dat wordt gezegd, geen navigatie.
//   I6  Intake vraagt de FS-match op (`match=1`); Home doet dat bewust niet.
//   I7  de bestaande Intake-render blijft intact (antwoordtabel, verwijderen, leegstand).
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

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };

// ── DOM-shim ────────────────────────────────────────────────────────────────
// De knoppen komen uit de ECHT gerenderde markup: `querySelectorAll` scant de HTML
// op het attribuut en geeft per treffer een knop met de werkelijke attribuutwaarde
// in `dataset`. Zo faalt een hernoemd/ontbrekend attribuut hard, in plaats van
// verborgen te worden door een stub die altijd iets teruggeeft.
const _camel = s => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
class El {
  constructor(tag) {
    this.tag = tag || "div"; this.children = []; this.parent = null;
    this.dataset = new Proxy({}, { set: (o, k, v) => { o[k] = String(v); return true; } });
    this.attrs = {}; this.disabled = false;
    this._html = ""; this._q = new Map(); this._on = {}; this._cls = new Set();
    const s = this._cls;
    this.classList = { add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
                       toggle: (c, on) => { if (on) s.add(c); else s.delete(c); } };
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
  // `[data-x]` → elke voorkomst in de markup, mét de echte waarde in dataset.
  querySelectorAll(sel) {
    const m = /^\[data-([a-z-]+)\]$/.exec(String(sel));
    if (!m) return [];
    if (this._q.has(sel)) return this._q.get(sel);
    const attr = "data-" + m[1];
    const re = new RegExp(attr + '(?:="([^"]*)")?', "g");
    const uit = [];
    let hit;
    while ((hit = re.exec(this._html))) {
      const b = new El("button");
      b.dataset[_camel(m[1])] = hit[1] === undefined ? "" : hit[1];
      uit.push(b);
    }
    this._q.set(sel, uit);
    return uit;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const document = { createElement: t => new El(t) };

// ── echte gedeelde primitieven ──────────────────────────────────────────────
const PRIMS = [
  sliceLine("const esc = "), sliceLine("const _NL_MND = "),
  sliceFrom("function nlDatum("), sliceFrom("function nlDatumTijd("),
  sliceFrom("function leegState("), sliceFrom("function initialen("),
].join("\n");

// Waarnemingen per scenario.
let posts, meldingen, route, geopend, ververst, badge;
function verse() { posts = []; meldingen = []; route = "#feedback"; geopend = []; ververst = []; badge = null; }

function bouw(inboxRespons, takeRespons, koppelRespons) {
  const api = async (url, opt) => {
    posts.push({ url, method: (opt && opt.method) || "GET" });
    if (url.includes("/take")) return takeRespons;
    if (url.startsWith("/api/intake/inbox")) return inboxRespons;
    return { ok: true };
  };
  const jpost = async (url, body) => { posts.push({ url, body }); return koppelRespons; };
  const env = {
    $: () => box, api, jpost, document,
    skeleton: () => {}, foutState: () => { ververst.push("fout"); },
    setBadge: n => { badge = n; },
    ic: () => "", melding: (t, e) => meldingen.push({ t, e }),
    // De echte route-schrijvers, verkleind tot wat deze test bewijst: de HASH.
    openWorkspace: uk => { geopend.push(["workspace", uk]); route = "#workspace/" + encodeURIComponent(uk); },
    openAthleteModule: (v, uk) => { geopend.push([v, uk]); route = "#" + v + "/" + encodeURIComponent(uk); },
    vervalDossierLijst: () => { ververst.push("atleten"); },
    laadOrphanIntakes: () => { ververst.push("orphans"); },
    confirm: () => true,
  };
  const namen = Object.keys(env);
  const body = PRIMS + "\n" + sliceFrom("async function koppelIntake(") + "\n"
    + sliceFrom("async function laadInbox(") + "\nreturn { laadInbox, koppelIntake };";
  return new Function(...namen, body)(...namen.map(k => env[k]));
}

let box;
const INZENDING = {
  id: "20260901115300-abc123", naam: "Dominique Slooff", email: "d@x.nl",
  doel: "Halve marathon", ingezonden: "2026-09-01T11:53",
  rijen: [{ vraag: "Doel", antwoord: "Halve marathon" }, { vraag: "Volume/wk", antwoord: "40 km" }],
};
const MATCH = { user_key: "uk-dom", naam: "Dominique Slooff", groep: "Dinsdaggroep" };

console.log("== Intake: van aanmelding naar atleet, schema en centrale context ==\n");

// ══ I1 — nieuwe aanmelding, geen bestaande atleet ════════════════════════════
{
  verse(); box = new El("section");
  const mod = bouw({ inbox: [{ ...INZENDING, suggestie: null }] },
                   { ok: true, naam: "Dominique Slooff", key: "nieuw:dominique_slooff" }, null);
  await mod.laadInbox();
  ok(box.children.length === 1, "I1z de inzending wordt gerenderd", box.children.length);
  const html = (box.children[0] || box).innerHTML;
  ok(/Overnemen als intake/.test(html), "I1a één neutrale overname-actie", html.slice(0, 120));
  ok(!/koppelen aan/i.test(html), "I1b geen koppel-actie zonder match");
  ok(!/Bestaat al als atleet/.test(html), "I1c geen atleet-claim zonder match");
  ok(badge === 1, "I1d badge telt de wachtende inzendingen", badge);

  await box.children[0].querySelectorAll("[data-take]")[0].vuur("click");
  ok(posts.filter(p => p.url.includes("/take")).length === 1, "I1e precies één overname-POST");
  ok(!posts.some(p => p.url.includes("/koppel")), "I1f geen koppel-write");
  // De overgenomen intake staat vanaf nu bij de losse intakes — die lijst moet mee
  // verversen, anders is hij tot een volledige herlaad onzichtbaar.
  ok(ververst.includes("orphans"), "I1g de losse-intakelijst wordt mee-ververst", ververst.join(","));
  ok(ververst.includes("atleten"), "I1h de atletenlijst vervalt");
  ok(meldingen.some(m => /losse intakes/.test(m.t) && !m.e), "I1i de melding zegt waar hij nu staat",
     JSON.stringify(meldingen));
}

// ══ I2 — de aanmelder bestaat AL als atleet ══════════════════════════════════
{
  verse(); box = new El("section");
  const mod = bouw({ inbox: [{ ...INZENDING, suggestie: MATCH }] },
                   { ok: true, naam: "Dominique Slooff", key: "nieuw:dominique_slooff" },
                   { ok: true, naam: "Dominique Slooff" });
  await mod.laadInbox();
  const kaart = box.children[0], html = kaart.innerHTML;
  ok(/Bestaat al als atleet/.test(html), "I2a de coach ziet dat de atleet al bestaat");
  ok(/Dinsdaggroep/.test(html), "I2b met de groep erbij");
  ok(/bevestig zelf/.test(html), "I2c als kandidaat, niet als vastgestelde identiteit");
  const knoppen = kaart.querySelectorAll("[data-take]");
  ok(knoppen.length === 2, "I2d twee overname-routes (met en zonder koppelen)", knoppen.length);
  ok(knoppen[0].dataset.take === "uk-dom", "I2e de primaire actie draagt de canonieke user_key",
     knoppen[0].dataset.take);
  ok(knoppen[1].dataset.take === "", "I2f 'alleen overnemen' koppelt niets", knoppen[1].dataset.take);

  await knoppen[0].vuur("click");
  const koppel = posts.find(p => p.url.includes("/koppel"));
  ok(!!koppel, "I2g er wordt gekoppeld");
  // De sleutel komt uit het antwoord van de server, niet uit een tweede afleiding
  // in de client: die zou stil uiteen kunnen lopen met wat er is weggeschreven.
  ok(koppel && koppel.body.nieuw_key === "nieuw:dominique_slooff",
     "I2h met de sleutel die de server teruggaf", koppel && koppel.body.nieuw_key);
  ok(koppel && koppel.body.user_key === "uk-dom", "I2i naar het canonieke account");
  ok(route === "#schema/uk-dom", "I2j daarna de atleetroute MÉT id", route);
  ok(geopend.some(([v, k]) => v === "schema" && k === "uk-dom"), "I2k via de gedeelde route-entry");
}

// ══ I3 — atleetcontext bekijken vóór de overname ═════════════════════════════
{
  verse(); box = new El("section");
  const mod = bouw({ inbox: [{ ...INZENDING, suggestie: MATCH }] }, { ok: true }, { ok: true });
  await mod.laadInbox();
  const kaart = box.children[0];
  const ws = kaart.querySelectorAll("[data-ws]")[0];
  ok(!!ws, "I3a bij een bestaande atleet kun je die atleet openen", kaart.innerHTML.slice(0, 140));
  if (ws) await ws.vuur("click");
  // Een route mét id overleeft een refresh; een sessiegebonden selectie niet.
  ok(route === "#workspace/uk-dom", "I3b de route draagt de athlete-id", route);
  ok(!posts.some(p => p.url.includes("/take") || p.url.includes("/koppel")),
     "I3c kijken schrijft niets");
}

// ══ I4 — geen match → geen geleende context ══════════════════════════════════
{
  verse(); box = new El("section");
  route = "#workspace/uk-iemand-anders";                  // eerder geopende atleet
  const mod = bouw({ inbox: [{ ...INZENDING, suggestie: null }] },
                   { ok: true, naam: "Dominique Slooff", key: "nieuw:dominique_slooff" }, null);
  await mod.laadInbox();
  const kaart = box.children[0];
  ok(kaart.querySelectorAll("[data-ws]").length === 0, "I4a geen 'bekijk atleet' zonder match");
  await kaart.querySelectorAll("[data-take]")[0].vuur("click");
  ok(!posts.some(p => p.url.includes("/koppel")), "I4b en zeker geen koppel-write");
  ok(geopend.length === 0, "I4c geen navigatie naar een willekeurige atleet",
     JSON.stringify(geopend));
  ok(route === "#workspace/uk-iemand-anders", "I4d de vorige atleet wordt niet overgenomen", route);
}

// ══ I5 — overname geslaagd, koppelen mislukt ═════════════════════════════════
{
  verse(); box = new El("section");
  const mod = bouw({ inbox: [{ ...INZENDING, suggestie: MATCH }] },
                   { ok: true, naam: "Dominique Slooff", key: "nieuw:dominique_slooff" },
                   { ok: false, err: "Opslaan mislukt." });
  await mod.laadInbox();
  await box.children[0].querySelectorAll("[data-take]")[0].vuur("click");
  ok(meldingen.some(m => m.e && /Opslaan mislukt/.test(m.t)), "I5a de echte fout wordt getoond");
  ok(meldingen.some(m => /overgenomen/i.test(m.t) && /losse intakes/.test(m.t)),
     "I5b én dat de intake WEL is overgenomen", JSON.stringify(meldingen));
  ok(geopend.length === 0, "I5c geen navigatie naar een niet-gekoppelde atleet");
  ok(ververst.includes("orphans"), "I5d de losse intake wordt zichtbaar gemaakt");
}

// ══ I6 — de FS-match is opt-in ═══════════════════════════════════════════════
{
  verse(); box = new El("section");
  const mod = bouw({ inbox: [] }, { ok: true }, { ok: true });
  await mod.laadInbox();
  const call = posts.find(p => p.url.startsWith("/api/intake/inbox"));
  ok(call && /match=1/.test(call.url), "I6a Intake vraagt de FinalSurge-match op", call && call.url);
  // Home leest dezelfde lijst als goedkoop, store-only praktijksignaal: daar hoort
  // geen roster-read in. Bewijs uit de bron, niet uit deze harnas.
  const home = SRC.slice(SRC.indexOf("Secundaire praktijk-signalen"));
  const homeCall = home.slice(home.indexOf('api("/api/intake/inbox'), home.indexOf('api("/api/intake/inbox') + 60);
  ok(!/match/.test(homeCall), "I6b Home vraagt hem bewust niet op", homeCall);
}

// ══ I7 — de bestaande render blijft intact ═══════════════════════════════════
{
  verse(); box = new El("section");
  const mod = bouw({ inbox: [{ ...INZENDING, suggestie: null }] }, { ok: true }, { ok: true });
  await mod.laadInbox();
  const html = box.children[0].innerHTML;
  ok(/Halve marathon/.test(html) && /40 km/.test(html), "I7a de antwoorden staan er");
  ok(/Bekijk antwoorden/.test(html), "I7b uitklapper");
  ok(/1 sep/.test(html), "I7c inzenddatum in de Nederlandse notatie", html.match(/ingezonden[^<]*/));
  ok(/d@x\.nl/.test(html), "I7d e-mail");
  ok(/data-del/.test(html), "I7e verwijderen kan nog");

  verse(); box = new El("section");
  const leeg = bouw({ inbox: [] }, { ok: true }, { ok: true });
  await leeg.laadInbox();
  ok(/Nog geen nieuwe inzendingen/.test(box.innerHTML), "I7f lege stand", box.innerHTML.slice(0, 80));
  ok(badge === 0, "I7g badge op nul");
}

if (failures.length) { console.log("FAIL\n - " + failures.join("\n - ")); process.exit(1); }
console.log("alle Intake-flow tests groen");
