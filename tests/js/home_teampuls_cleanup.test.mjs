// Executable regressietests voor de Home/Teampuls correctness & UX cleanup.
//
//   node tests/js/home_teampuls_cleanup.test.mjs
//
// Slicet de ECHTE functies VERBATIM uit pwa/static/app.js en draait ze tegen een minimale
// DOM/history-shim. Bewijst:
//   T1  toast-stack        — meldingen stapelen in één container, geen twee op dezelfde plek,
//                            de state-melding dooft vanzelf en vangt geen pointer.
//   T2  back-navigatie     — Home → Workspace laat precies ÉÉN history-entry achter, en een
//                            bare `#workspace` route valt netjes terug (geen crash, geen
//                            achtergebleven atleet).
//   T3  deep-link          — `#workspace/<uuid>` blijft werken.
//   T4  races-filter       — de Home-chip opent `#races/7d`, de zijbalk blijft ongefilterd,
//                            en het gefilterde laadpad gebruikt hetzelfde 7-daagse venster.
//   T6  primair signaal    — de ingeklapte regel en de uitgeklapte kaartkop lezen ÉÉN keuze.
//   T8  briefing-leeftijd  — een briefing van eerder deze week leest niet als 'van vandaag'.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = readFileSync(join(ROOT, "pwa", "static", "app.js"), "utf8");
const CSS = readFileSync(join(ROOT, "pwa", "static", "styles.css"), "utf8");
const HTML = readFileSync(join(ROOT, "pwa", "static", "index.html"), "utf8");

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
const sliceLine = (p) => { const i = SRC.indexOf(p); if (i < 0) throw new Error("not found: " + p); return SRC.slice(i, SRC.indexOf("\n", i)); };

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };

// ── Minimale DOM-shim ────────────────────────────────────────────────────────
class El {
  constructor(tag) {
    this.tag = tag || "div"; this.dataset = {}; this.children = []; this.parent = null;
    this.textContent = ""; this.attrs = {};
    this._cls = new Set();
    const s = this._cls;
    this.classList = {
      add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
      toggle: (c, on) => { if (on) s.add(c); else s.delete(c); },
    };
  }
  get className() { return [...this._cls].join(" "); }
  set className(v) { this._cls.clear(); String(v || "").split(/\s+/).filter(Boolean).forEach(c => this._cls.add(c)); }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  closest(sel) { let n = this.parent; while (n) { if (sel === ".view" && n._cls.has("view")) return n; n = n.parent; } return null; }
}
let byId = {}, markers = [], created = [];
const document = {
  createElement: t => { const e = new El(t); created.push(e); return e; },
  querySelectorAll: sel => (sel.startsWith(".gen-mark") ? markers.slice() : []),
  body: new El("body"),
};
// `$` in app.js is document.querySelector: hier zoeken we op id in de bekende slots én
// in alles wat de code zelf heeft aangemaakt (zoals de toast).
const $ = sel => {
  const k = String(sel).replace(/^#/, "");
  return byId[k] || created.find(e => e.id === k) || null;
};
const $$ = () => [];

// Fake timers (auto-dismiss deterministisch bewijzen)
let timers = [], tid = 0;
const setTimeout_ = (fn, ms) => { timers.push({ id: ++tid, fn, ms }); return tid; };
const clearTimeout_ = id => { timers = timers.filter(t => t.id !== id); };
const runTimers = () => { const t = timers; timers = []; t.forEach(x => x.fn()); };

const esc = s => String(s == null ? "" : s);

// ── T1 · toast-stack ─────────────────────────────────────────────────────────
{
  const stack = new El("div"); byId.toaststack = stack;
  const REAL = [
    "const _bbGen = { id: '', at: '', sv: {} };",
    sliceFrom("function _genDominates("),
    sliceFrom("function noteGeneration("),
    sliceFrom("function _genZichtbaar("),
    sliceFrom("function bbGenSync("),
    sliceFrom("function genToast("),
    sliceFrom("function genToastWeg("),
    sliceFrom("function genBanner("),
    sliceFrom("function toastHost("),
    sliceLine("const _GEN_TOAST_MS = "),
    "let _genToastT = 0;",
  ].join("\n\n");
  const app = new Function("document", "$", "esc", "setTimeout", "clearTimeout",
    REAL + "\nreturn { bbGenSync, genToast, genBanner, _bbGen, toastHost };"
  )(document, $, esc, setTimeout_, clearTimeout_);

  // Twee views tonen elk een (oudere) generatie → twee markers, één melding.
  const mkView = (on, gen, at) => {
    const v = new El("section"); v.className = "view" + (on ? " on" : "");
    const m = new El("div"); m.className = "gen-mark"; m.dataset.gen = gen; m.dataset.at = at;
    v.appendChild(m); markers.push(m); return v;
  };
  markers = [];
  const zichtbaar = mkView(true, "genA", "09:12");
  const verborgen = mkView(false, "genA", "09:12");
  app._bbGen.id = "genB";                                   // nieuwere generatie bekend
  app.bbGenSync();

  const toasts = stack.children;
  ok(toasts.length === 1, "T1.1 één melding in de stack (geen stapel op dezelfde plek)", toasts.length);
  ok(toasts[0].classList.contains("on"), "T1.2 melding staat aan bij een oudere generatie");
  ok(toasts[0].textContent.includes("nieuwe state beschikbaar"),
     "T1.3 dezelfde betekenis als voorheen", toasts[0].textContent);
  ok(toasts[0].parent === stack, "T1.4 melding hangt in de gedeelde stack, niet los in de body");

  // Een tweede sync maakt géén tweede toast-element (geen stapeling op één coordinaat).
  app.bbGenSync();
  ok(stack.children.length === 1, "T1.5 herhaalde sync stapelt geen duplicaten", stack.children.length);

  // Auto-dismiss: na de timer is de melding weg.
  runTimers();
  ok(!stack.children[0].classList.contains("on"), "T1.6 melding dooft vanzelf (auto-dismiss)");

  // Alleen ZICHTBARE views tellen: verberg de actieve view → geen melding meer.
  zichtbaar.classList.remove("on");
  app.bbGenSync();
  ok(!stack.children[0].classList.contains("on"), "T1.7 verborgen view triggert geen melding");
  void verborgen;

  // CSS-contract: één container aan de veilige rand, verticale tussenruimte, geen
  // per-melding fixed coordinaat meer, en de container blokkeert scrollen niet.
  ok(/#toaststack\{[^}]*position:fixed/.test(CSS), "T1.8 stack is de enige fixed container");
  ok(/#toaststack\{[^}]*display:flex/.test(CSS) && /#toaststack\{[^}]*flex-direction:column/.test(CSS),
     "T1.9 stack is een verticale kolom");
  ok(/#toaststack\{[^}]*gap:10px/.test(CSS), "T1.10 vaste tussenruimte tussen meldingen");
  ok(/#toaststack\{[^}]*pointer-events:none/.test(CSS), "T1.11 container vangt geen pointer (scroll blijft werken)");
  ok(/#toaststack\{[^}]*env\(safe-area-inset-bottom\)/.test(CSS), "T1.12 safe-area op mobiel");
  ok(/#toaststack > \*\{[^}]*position:static/.test(CSS), "T1.13 meldingen zelf zijn niet meer los gepositioneerd");
  ok(/\.gen-toast\{[^}]*pointer-events:none/.test(CSS), "T1.14 niet-interactieve melding blokkeert niets");
  ok(!/#msg\{bottom:/.test(CSS) && !/#offline\{bottom:/.test(CSS),
     "T1.15 geen losse bottom-coordinaten per melding meer");
  ok(HTML.indexOf('id="toaststack"') > -1 && HTML.indexOf('id="msg"') > HTML.indexOf('id="toaststack"'),
     "T1.16 offline/melding staan IN de stack");
}

// ── T2/T3 · back-navigatie en deep-link ──────────────────────────────────────
{
  let hist = ["#home"], hash = "#home", huidige = "home", calls = [];
  const history = { pushState: (a, b, h) => { hist.push(h); hash = h; } };
  const locationShim = { get hash() { return hash; } };
  const back = () => { hist.pop(); hash = hist[hist.length - 1]; };

  const REAL = [
    "let _routing = false;",
    sliceFrom("function pushRoute("),
    sliceFrom("function applyRoute("),
    sliceFrom("function openWorkspace("),
    sliceFrom("function wsLeegRoute("),
  ].join("\n\n");
  // `toonView` wordt gespiegeld op het ENE punt dat er hier toe doet: de afsluitende
  // pushRoute(view). Precies die regel zette vroeger de extra bare `#workspace`-entry.
  const toonView = v => { huidige = v; calls.push(["toonView", v]); app.pushRoute(v); };
  const spy = n => (...a) => calls.push([n, ...a]);
  const documentShim = { querySelector: sel => (/data-view="(home|workspace|races|atleten|schema|dossier)"/.test(sel) ? {} : null) };

  const app = new Function(
    "history", "location", "toonView", "document", "wsShow", "wsLeegScherm", "openDossier",
    "openSchemaAthlete", "openDossierCockpit", "rcZetScope", "encodeURIComponent",
    REAL + `
    let huidigeView = "", wsSel = "", wsOpenPending = "", schemaOpenPending = "", dcOpenPending = "";
    function sbToonLijst() {} function dcToonLijst() {}
    return { pushRoute, applyRoute, openWorkspace, wsLeegRoute,
             setView: v => { huidigeView = v; }, wsSel: () => wsSel };`
  )(history, locationShim, v => { toonView(v); app.setView(v); }, documentShim,
    spy("wsShow"), spy("wsLeegScherm"), spy("openDossier"), spy("openSchemaAthlete"),
    spy("openDossierCockpit"), spy("rcZetScope"), encodeURIComponent);

  // Home → Workspace: exact ÉÉN nieuwe history-entry, en die draagt de atleet.
  app.setView("home"); calls = [];
  app.openWorkspace("u-123");
  ok(hist.length === 2, "T2.1 één klik = één history-entry (geen bare #workspace ertussen)", JSON.stringify(hist));
  ok(hash === "#workspace/u-123", "T2.2 de zichtbare URL draagt de atleet", hash);
  ok(!hist.includes("#workspace"), "T2.3 geen tussenroute zonder atleet-id", JSON.stringify(hist));

  // Browser Back → terug naar Home, coherent.
  back();
  calls = [];
  app.applyRoute();
  ok(hash === "#home", "T2.4 back landt op Home", hash);
  ok(calls.some(c => c[0] === "toonView" && c[1] === "home"), "T2.5 Home wordt getoond", JSON.stringify(calls));
  ok(hist.length === 1, "T2.6 applyRoute schrijft geen extra entry tijdens back", JSON.stringify(hist));

  // Bare `#workspace` (oude bug: ReferenceError → vorige atleet bleef staan).
  hist = ["#workspace"]; hash = "#workspace"; calls = []; app.setView("home");
  let crash = null;
  try { app.applyRoute(); } catch (e) { crash = e; }
  ok(!crash, "T2.7 bare #workspace crasht niet meer", crash && crash.message);
  ok(calls.some(c => c[0] === "wsLeegScherm"), "T2.8 bare #workspace toont de kies-scène (geen achtergebleven atleet)",
     JSON.stringify(calls));
  ok(app.wsSel() === "", "T2.9 de vorige atleet is losgelaten", app.wsSel());

  // T3 — directe deep-link blijft werken.
  hist = ["#workspace/abc-uuid"]; hash = "#workspace/abc-uuid"; calls = []; app.setView("home");
  app.applyRoute();
  ok(calls.some(c => c[0] === "wsShow" && c[1] === "abc-uuid"), "T3.1 #workspace/<uuid> opent die atleet",
     JSON.stringify(calls));
  ok(hash === "#workspace/abc-uuid" && hist.length === 1, "T3.2 refresh op die URL blijft coherent", hash);

  // T4a — races-scope reist mee in de route.
  hist = ["#races/7d"]; hash = "#races/7d"; calls = [];
  app.applyRoute();
  ok(calls.some(c => c[0] === "rcZetScope" && c[1] === "7d"), "T4.1 #races/7d activeert het 7-dagenfilter",
     JSON.stringify(calls));
  hist = ["#races"]; hash = "#races"; calls = [];
  app.applyRoute();
  ok(calls.some(c => c[0] === "rcZetScope" && c[1] === "alle"), "T4.2 bare #races blijft ongefilterd",
     JSON.stringify(calls));
}

// ── T4 · races-filter: chip-belofte == bestemming ───────────────────────────
{
  let hash = "", scopes = [];
  const history = { pushState: (a, b, h) => { hash = h; } };
  const app = new Function("history", "location", "rcZetScope",
    sliceFrom("function openRaces(") + "\nreturn { openRaces };"
  )(history, { get hash() { return hash; } }, s => scopes.push(s));

  app.openRaces("7d");
  ok(hash === "#races/7d", "T4.3 de Home-chip opent de gefilterde route", hash);
  ok(scopes[scopes.length - 1] === "7d", "T4.4 en zet het filter daadwerkelijk aan");
  app.openRaces("alle");
  ok(hash === "#races", "T4.5 zijbalk-ingang blijft de gewone, ongefilterde Races-pagina", hash);

  // Het gefilterde laadpad gebruikt hetzelfde venster + filter als de chip-telling.
  let gevraagd = "";
  const box = new El("div"), info = new El("div");
  byId = { "rc-lijst": box, "rc-info": info };
  // `nlAantal`/`leegState`/`foutState` zijn gedeelde presentatie-primitieven; slice de
  // ECHTE implementaties mee zodat het laadpad draait zoals in productie.
  const RACE_DEPS = ["$", "$$", "api", "skeleton", "ic", "raceItem", "rcScope", "RC_CHIP_DAGEN"];
  const RACE_REAL = [sliceFrom("function nlAantal("), sliceFrom("function leegState("),
                     sliceLine("let _foutSeq = "), sliceFrom("function foutState("),
                     sliceFrom("async function laadRaces(")].join("\n\n");
  const laad = new Function(...RACE_DEPS, RACE_REAL + "\nreturn laadRaces;"
  )($, $$, u => { gevraagd = u; return Promise.resolve({ fs: true, items: [{ wens_gegeven: false }] }); },
    () => {}, () => "", () => new El("div"), "7d", 7);
  await laad();
  ok(gevraagd === "/api/races?dagen=7&zonder_wens=true",
     "T4.6 gefilterd laadpad = 7 dagen + zonder wens (zelfde logica als de chip-telling)", gevraagd);
  ok(info.textContent.includes("zonder wens") && info.textContent.includes("7 dagen"),
     "T4.7 de bestemming benoemt exact wat de chip belooft", info.textContent);

  const laad2 = new Function(...RACE_DEPS, RACE_REAL + "\nreturn laadRaces;"
  )($, $$, u => { gevraagd = u; return Promise.resolve({ fs: true, items: [] }); },
    () => {}, () => "", () => new El("div"), "alle", 7);
  await laad2();
  ok(gevraagd === "/api/races", "T4.8 ongefilterd pad blijft het bestaande verzoek", gevraagd);
}

// ── T6 · ingeklapte preview toont hetzelfde primaire signaal ────────────────
{
  const app = new Function(
    [sliceFrom("function prioHoofdSignaal("), sliceFrom("function prioPrimairTekst(")].join("\n\n") +
    "\nreturn { prioHoofdSignaal, prioPrimairTekst };")();

  // De echte auditcase: belasting is de reden dat deze atleet in de lijst staat, maar de
  // eerste onderliggende bronzin is een notitie-signaal.
  const it = {
    reden: "Belasting let op · -13% t.o.v. referentie",
    n_signalen: 2,
    signalen: [
      { soort: "belasting", tier: "aandacht", reden: "Belasting let op · -13% t.o.v. referentie",
        detail: { primair: "Belasting let op · -13% t.o.v. referentie", pct: -13,
                  signalen: ["Noemt in notities: gevoelig"] } },
      { soort: "schema", tier: "aandacht", reden: "schema loopt af over 3 dagen", detail: {} },
    ],
  };
  const hoofd = app.prioHoofdSignaal(it);
  const ingeklapt = app.prioPrimairTekst(hoofd);
  ok(hoofd.soort === "belasting", "T6.1 het primaire signaal is de reden voor prioritering", hoofd.soort);
  ok(ingeklapt === "Belasting let op · -13% t.o.v. referentie",
     "T6.2 de ingeklapte regel toont de hoofdreden, niet de notitie-bronzin", ingeklapt);
  ok(!ingeklapt.includes("Noemt in notities"), "T6.3 secundair signaal vervangt de hoofdreden niet", ingeklapt);

  // Ingeklapt == uitgeklapt: één keuze, twee weergaven.
  const item = sliceFrom("function prioItem(");
  const detail = sliceFrom("function prioDetailHtml(");
  ok(item.includes("prioPrimairTekst(prioHoofdSignaal(it))"), "T6.4 ingeklapte regel leest de gedeelde keuze");
  ok(detail.includes("const hoofd = prioHoofdSignaal(it)") && detail.includes("prioPrimairTekst(hoofd)"),
     "T6.5 uitgeklapte kop leest exact dezelfde keuze");
  ok(!detail.includes('hoofd.tier === "actie" ? "hoog" : "let op"'),
     "T6.6 geen tweede, eigen kopformulering meer in de kaart");

  // Fallback voor een oudere snapshot zonder `primair` levert dezelfde zin.
  const oud = { soort: "belasting", tier: "aandacht", detail: { pct: -13 } };
  ok(app.prioPrimairTekst(oud) === "Belasting let op · -13% t.o.v. referentie",
     "T6.7 oudere snapshot valt terug op dezelfde formulering", app.prioPrimairTekst(oud));
  // Niet-belasting blijft ongewijzigd.
  ok(app.prioPrimairTekst({ soort: "compliance", reden: "3 van 5 trainingen gemist" }) === "3 van 5 trainingen gemist",
     "T6.8 andere soorten houden hun eigen reden");
}

// ── T8 · leeftijd van de weekbriefing ────────────────────────────────────────
{
  const app = new Function(
    [sliceLine("const _BR_DAGEN = "), sliceLine("const _BR_MND = "), sliceFrom("function briefGemaaktLabel(")].join("\n") +
    "\nreturn briefGemaaktLabel;")();
  ok(app("2026-09-05", "2026-09-05") === "Gemaakt vandaag (zaterdag 5 sep)", "T8.1 van vandaag", app("2026-09-05", "2026-09-05"));
  ok(app("2026-09-04", "2026-09-05") === "Gemaakt gisteren (vrijdag 4 sep)", "T8.2 gisteren", app("2026-09-04", "2026-09-05"));
  const oud = app("2026-09-02", "2026-09-05");
  ok(oud === "Gemaakt woensdag 2 sep · 3 dagen oud", "T8.3 woensdag-briefing leest op zaterdag niet als vandaag", oud);
  ok(app("") === "Gemaakt", "T8.4 lege datum blijft veilig", app(""));
}

if (failures.length) { console.error("FAIL\n - " + failures.join("\n - ")); process.exit(1); }
console.log("home_teampuls_cleanup: all checks passed");
