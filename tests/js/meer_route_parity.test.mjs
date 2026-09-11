// Mobile route-parity: Meer → Dossier / Schema dragen de atleet mee (11 sep 2026).
//
//   node tests/js/meer_route_parity.test.mjs
//
// Oorzaak (bewezen tegen de echte code): 'Meer' is een eigen view met een KALE route
// (`#meer`). Onderbalk → Meer zette de hash op `#meer`; een Meer-tegel las daarna
// `activeAthleteKey()` = "" en `_shownAthleteKey("meer")` = "" en schreef een kale
// `#dossier` / `#schema`. Op het scherm stond de atleet er nog (runtime), een refresh las
// de route en was hem kwijt. De desktop-zijbalk springt direct en had die tussenstap niet.
//
// Snijdt de ECHTE routinglaag verbatim uit app.js — activeAthleteKey, _shownAthleteKey,
// openModuleFromNav, openAthleteModule, pushRoute, applyRoute — en stubt alleen de
// module-openers, zodat ook 'refresh' (applyRoute op de geschreven hash) echt draait.
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
const sliceLine = p => { const i = SRC.indexOf(p); if (i < 0) throw new Error("not found: " + p); return SRC.slice(i, SRC.indexOf("\n", i)); };

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };

// De tegels die in de ECHTE Meer-view staan (niet een lijst die deze test zelf verzint).
const meerSectie = IDX.slice(IDX.indexOf('data-view="meer"'), IDX.indexOf("</section>", IDX.indexOf('data-view="meer"')));
const TEGELS = [...meerSectie.matchAll(/data-open-view="([a-z-]+)"/g)].map(m => m[1]);
ok(TEGELS.includes("dossier") && TEGELS.includes("schema"), "markup: Meer bevat Dossier en Schema", TEGELS.join(","));

const VIEWS = ["home", "feedback", "workspace", "atleten", "dossier", "schema", "races", "intake",
  "strippen", "meer", "teampuls", "schema-verloop", ...TEGELS];

// Eén 'app-instantie' = verse modulestaat + één hash; `start(hash)` is dus ook een refresh.
function start(beginHash) {
  const st = { hash: beginHash, calls: [] };
  const log = (...a) => st.calls.push(a);
  const REAL = [
    'let huidigeView = "", wsSel = "", dcSel = "", sbState = null, dossierSel = null, FB = { sel: null };',
    'let schemaOpenPending = "", schemaOpenMode = "", dcOpenPending = "", wsOpenPending = "";',
    sliceLine("const _ATHLETE_VIEWS = "),
    sliceLine("const _ATHLETE_CTX_VIEWS = "),
    sliceLine("let _routing = false;"),
    sliceFrom("function pushRoute("),
    sliceFrom("function applyRoute("),
    sliceFrom("function activeAthleteKey("),
    sliceFrom("function openAthleteModule("),
    sliceLine("let _meerKey = "),
    sliceFrom("function _shownAthleteKey("),
    sliceFrom("function openModuleFromNav("),
    // Stub-toonView doet wat de echte doet voor routing: view zetten + route schrijven.
    "function toonView(v) { huidigeView = v; log('toonView', v); pushRoute(v); }",
    "return { openModuleFromNav, applyRoute, view: () => huidigeView,"
    + " set: o => { if ('wsSel' in o) wsSel = o.wsSel; if ('dcSel' in o) dcSel = o.dcSel;"
    + " if ('fbSel' in o) FB.sel = o.fbSel; } };",
  ].join("\n");
  const location = { get hash() { return st.hash; } };
  const history = { pushState: (_s, _t, h) => { st.hash = h; } };
  const document = { querySelector: sel => (VIEWS.some(v => sel === `.view[data-view="${v}"]`) ? {} : null) };
  const stubs = {
    openWorkspace: k => { log("openWorkspace", k); history.pushState(null, "", "#workspace/" + k); },
    openDossier: k => log("openDossier", k),
    openSchemaAthlete: k => log("openSchemaAthlete", k),
    openDossierCockpit: k => log("openDossierCockpit", k),
    sbToonLijst: () => log("sbToonLijst"), dcToonLijst: () => log("dcToonLijst"),
    wsLeegRoute: () => log("wsLeegRoute"), rcZetScope: s => log("rcZetScope", s),
    openRaces: s => { log("openRaces", s); history.pushState(null, "", "#races"); },
    sbDraftSave: () => {},
  };
  const names = Object.keys(stubs);
  const app = new Function("location", "history", "document", "log", ...names, REAL)(
    location, history, document, log, ...names.map(n => stubs[n]));
  app.applyRoute();                          // app-start leest de route, precies als de echte
  st.calls = [];
  return Object.assign(app, { st });
}
const opent = (app, fn, k) => app.st.calls.some(c => c[0] === fn && c[1] === k);

// ══ 1. Actieve atleet → Meer → Dossier / Schema met id ══════════════════════
for (const doel of ["dossier", "schema"]) {
  const app = start("#workspace/karin");
  app.set({ wsSel: "karin" });
  app.openModuleFromNav("meer");            // onderbalk
  ok(app.st.hash === "#meer" && app.view() === "meer", `1 ${doel}: Meer zelf blijft een kale route`, app.st.hash);
  app.openModuleFromNav(doel);              // Meer-tegel
  ok(app.st.hash === `#${doel}/karin`, `1 ${doel}: Meer → ${doel} schrijft #${doel}/<id>`, app.st.hash);
  ok(opent(app, doel === "dossier" ? "openDossierCockpit" : "openSchemaAthlete", "karin"),
     `1 ${doel}: en opent die atleet`, JSON.stringify(app.st.calls));
  // ── 3. refresh: een verse app op precies die hash houdt de atleet ──
  const na = start(app.st.hash);
  na.applyRoute();
  ok(opent(na, doel === "dossier" ? "openDossierCockpit" : "openSchemaAthlete", "karin")
     && na.view() === doel, `3 ${doel}: refresh behoudt de atleet`, JSON.stringify(na.st.calls));
}

// ── 2. Ook vanuit de andere contextbronnen van de zijbalk ──────────────────
{
  // Dossier toont karin onder een kale hash (B1-terugval)
  const app = start("#dossier");
  app.set({ dcSel: "karin" });
  app.openModuleFromNav("meer"); app.openModuleFromNav("schema");
  ok(app.st.hash === "#schema/karin", "2: getoonde atleet (kale hash) gaat mee door Meer", app.st.hash);
}
{
  // Feedback met een geopende case
  const app = start("#feedback");
  app.set({ fbSel: { it: { athlete_key: "douwe" } } });
  app.openModuleFromNav("meer"); app.openModuleFromNav("dossier");
  ok(app.st.hash === "#dossier/douwe", "2: Feedback-case gaat mee door Meer", app.st.hash);
}

// ══ 4. Geen actieve atleet → kale route, gewone atleetkeuze ═════════════════
for (const [doel, lijst] of [["dossier", "dcToonLijst"], ["schema", "sbToonLijst"]]) {
  const app = start("#home");
  app.openModuleFromNav("meer"); app.openModuleFromNav(doel);
  ok(app.st.hash === `#${doel}` && opent(app, "toonView", doel), `4 ${doel}: zonder atleet een kale route`, app.st.hash);
  const na = start(app.st.hash); na.applyRoute();
  ok(opent(na, lijst), `4 ${doel}: refresh toont de gewone keuzelijst`, JSON.stringify(na.st.calls));
}
{
  // Context vervalt als Meer opnieuw vanaf een globale pagina wordt geopend.
  const app = start("#workspace/karin");
  app.set({ wsSel: "karin" });
  app.openModuleFromNav("meer"); app.openModuleFromNav("races");
  app.openModuleFromNav("home"); app.openModuleFromNav("meer"); app.openModuleFromNav("dossier");
  ok(app.st.hash === "#dossier", "4: Meer vanaf Home draagt geen oude atleet mee", app.st.hash);
}
{
  // Identity-guard: een pre-link intake (`nieuw:`) gaat niet door Meer heen.
  const app = start("#atleten/nieuw:jan");
  app.openModuleFromNav("meer"); app.openModuleFromNav("schema");
  ok(app.st.hash === "#schema", "4: 'nieuw:' wordt nooit via Meer meegenomen", app.st.hash);
}

// ══ 5. Andere Meer-tegels: ongewijzigd, ook mét actieve atleet ══════════════
const ATLEETVIEWS = new Set(["workspace", "atleten", "dossier", "schema"]);
for (const tegel of TEGELS.filter(t => !ATLEETVIEWS.has(t))) {
  const app = start("#workspace/karin");
  app.set({ wsSel: "karin" });
  app.openModuleFromNav("meer");
  app.st.calls = [];
  app.openModuleFromNav(tegel);
  const verwacht = tegel === "races" ? [["openRaces", "alle"]] : [["toonView", tegel]];
  ok(JSON.stringify(app.st.calls.filter(c => c[0] !== "toonView" || c[1] === tegel).slice(0, 1)) === JSON.stringify(verwacht)
     && !app.st.hash.includes("karin"), `5: Meer → ${tegel} blijft een globale ingang`, JSON.stringify(app.st.calls) + " " + app.st.hash);
}

// ══ 6. Desktop-zijbalk: direct vanaf de atleetpagina, zoals het al werkte ═══
for (const [doel, verwacht] of [["dossier", "#dossier/karin"], ["schema", "#schema/karin"], ["atleten", "#atleten/karin"]]) {
  const app = start("#workspace/karin");
  app.set({ wsSel: "karin" });
  app.openModuleFromNav(doel);
  ok(app.st.hash === verwacht, `6: zijbalk ${doel} blijft athlete-aware`, app.st.hash);
}
{
  const app = start("#dossier/karin");
  app.set({ dcSel: "karin" });
  app.openModuleFromNav("workspace");
  ok(app.st.hash === "#workspace/karin", "6: zijbalk Workspace blijft athlete-aware", app.st.hash);
}

if (failures.length) {
  console.error(`\n✗ ${failures.length} fout(en):`);
  failures.forEach(f => console.error("  - " + f));
  process.exit(1);
}
console.log(`✓ meer_route_parity: Meer → Dossier/Schema dragen de atleet mee, refresh houdt hem (${TEGELS.length} tegels gecontroleerd)`);
