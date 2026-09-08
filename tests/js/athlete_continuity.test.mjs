// Executable athlete-context continuity test (Cowork Fix Pack v1, B1 + UX/IA Target B).
//
// Slices the REAL activeAthleteKey() + _shownAthleteKey() + openModuleFromNav() (+ the
// _ATHLETE_VIEWS / _ATHLETE_CTX_VIEWS sets) VERBATIM from pwa/static/app.js and drives them
// against a mock location.hash + controllable module-state (huidigeView/wsSel/dcSel) with spies
// for openWorkspace / openAthleteModule / toonView.
//
//   node tests/js/athlete_continuity.test.mjs
//
// Proves: Workspace ↔ Dossier carry the same selected athlete via the sidebar — including the
// B1 divergence repro where a module shows a remembered athlete under a BARE hash — while generic
// Feedback stays queue-first (no athlete routing), and the `nieuw:` identity-guard holds.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SRC = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "pwa", "static", "app.js"), "utf8");
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

// Prepend test-controlled module-state (the real file declares these later; here we own them).
const STATE = 'let huidigeView = "", wsSel = "", dcSel = "", sbState = null, dossierSel = null, FB = { sel: null };';
const REAL = [
  STATE,
  sliceLine("const _ATHLETE_VIEWS = "),
  sliceLine("const _ATHLETE_CTX_VIEWS = "),
  sliceFrom("function activeAthleteKey("),
  sliceFrom("function _shownAthleteKey("),
  sliceFrom("function openModuleFromNav("),
].join("\n\n");

let calls, hash;
const openWorkspace = (k) => calls.push(["openWorkspace", k]);
const openAthleteModule = (v, k) => calls.push(["openAthleteModule", v, k]);
const toonView = (v) => calls.push(["toonView", v]);
const locationShim = { get hash() { return hash; } };

const app = new Function("openWorkspace", "openAthleteModule", "toonView", "location",
  REAL + "\nreturn { activeAthleteKey, _shownAthleteKey, openModuleFromNav, _set: (o) => { if ('huidigeView' in o) huidigeView = o.huidigeView; if ('wsSel' in o) wsSel = o.wsSel; if ('dcSel' in o) dcSel = o.dcSel; if ('dossierSel' in o) dossierSel = o.dossierSel; if ('sbState' in o) sbState = o.sbState; if ('fbSel' in o) FB.sel = o.fbSel; } };"
)(openWorkspace, openAthleteModule, toonView, locationShim);

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };
function scene(h, state) { calls = []; hash = h; app._set(state || {}); }

// 1. Route-carried: Dossier/<Karin> → sidebar Workspace opens Karin
scene("#dossier/karin", { huidigeView: "dossier", dcSel: "karin" });
ok(app.activeAthleteKey() === "karin", "1: dossier route yields active athlete", app.activeAthleteKey());
app.openModuleFromNav("workspace");
ok(JSON.stringify(calls) === JSON.stringify([["openWorkspace", "karin"]]),
   "1: nav to Workspace opens the same athlete", JSON.stringify(calls));

// 2. B1 divergence repro: Dossier shows dcSel=Karin under a BARE hash (#dossier, no ident).
//    Sidebar Workspace must still open KARIN (the shown athlete), not a remembered wsSel=Esther.
scene("#dossier", { huidigeView: "dossier", dcSel: "karin", wsSel: "esther" });
ok(app.activeAthleteKey() === "", "2: bare #dossier hash has no route athlete", app.activeAthleteKey());
app.openModuleFromNav("workspace");
ok(JSON.stringify(calls) === JSON.stringify([["openWorkspace", "karin"]]),
   "2: sidebar Workspace carries the SHOWN athlete (karin), not remembered wsSel", JSON.stringify(calls));

// 3. Reverse divergence: Workspace shows wsSel=Esther under a bare hash → sidebar Dossier opens Esther
scene("#workspace", { huidigeView: "workspace", wsSel: "esther", dcSel: "karin" });
app.openModuleFromNav("dossier");
ok(JSON.stringify(calls) === JSON.stringify([["openAthleteModule", "dossier", "esther"]]),
   "3: sidebar Dossier carries the shown Workspace athlete (esther)", JSON.stringify(calls));

// 4. Generic Feedback stays queue-first (no athlete routing), even with an active athlete
scene("#workspace/douwe", { huidigeView: "workspace", wsSel: "douwe" });
app.openModuleFromNav("feedback");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "feedback"]]),
   "4: generic Feedback nav stays queue-first (no auto-open athlete)", JSON.stringify(calls));

// 5. No athlete anywhere (Home) → plain module entry
scene("#home", { huidigeView: "home" });
app.openModuleFromNav("dossier");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "dossier"]]),
   "5: no active/shown athlete → plain module entry", JSON.stringify(calls));

// 6. `nieuw:` identity-guard: never an app-wide athlete context
scene("#atleten/nieuw:jan", { huidigeView: "atleten", dossierSel: null });
ok(app.activeAthleteKey() === "", "6: 'nieuw:' route is not an active athlete context", app.activeAthleteKey());
app.openModuleFromNav("dossier");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "dossier"]]),
   "6: 'nieuw:' never carried cross-module", JSON.stringify(calls));

console.log("== Athlete-context continuity (executable, incl. B1 divergence repro) ==");

// ── Feedback → atleetgerichte modules (atleetcontext-coherentie) ─────────────
// Feedback blijft een GLOBALE route (`#feedback`, geen ident) maar heeft wél een geopende
// case. Die atleet leefde alleen in runtime state, waardoor de zijbalk vanuit Feedback een
// KALE doelroute schreef: op het scherm klopte het (de doelview toont zijn onthouden
// atleet), maar een refresh las de route en was de atleet kwijt.
const CASE = (k) => ({ it: { athlete_key: k } });

// 7. Feedback met een geopende case → elke atleetroute krijgt het id mee.
for (const [view, verwacht] of [
  ["workspace", ["openWorkspace", "douwe"]],
  ["dossier", ["openAthleteModule", "dossier", "douwe"]],
  ["schema", ["openAthleteModule", "schema", "douwe"]],
  ["atleten", ["openAthleteModule", "atleten", "douwe"]],
]) {
  scene("#feedback", { huidigeView: "feedback", fbSel: CASE("douwe"), wsSel: "", dcSel: "" });
  app.openModuleFromNav(view);
  ok(JSON.stringify(calls) === JSON.stringify([verwacht]),
     `7: Feedback → ${view} draagt de atleet mee`, JSON.stringify(calls));
}

// 8. De terugval leest de geopende case.
scene("#feedback", { huidigeView: "feedback", fbSel: CASE("douwe") });
ok(app._shownAthleteKey("feedback") === "douwe", "8: _shownAthleteKey('feedback') = de case-atleet",
   app._shownAthleteKey("feedback"));

// 9. Geen case open (queue-overzicht) → gewone module-entry, geen verzonnen atleet.
scene("#feedback", { huidigeView: "feedback", fbSel: null, wsSel: "", dcSel: "" });
ok(app._shownAthleteKey("feedback") === "", "9: geen case = geen context");
app.openModuleFromNav("workspace");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "workspace"]]),
   "9: zonder case gewone entry", JSON.stringify(calls));

// 10. Case zonder gekoppelde atleet (athlete_key null) → geen context.
scene("#feedback", { huidigeView: "feedback", fbSel: { it: { athlete_key: null } }, wsSel: "", dcSel: "" });
ok(app._shownAthleteKey("feedback") === "", "10: ongekoppelde case draagt geen atleet");
app.openModuleFromNav("dossier");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "dossier"]]),
   "10: ongekoppelde case → gewone entry", JSON.stringify(calls));

// 11. Identity-guard blijft: een `nieuw:`-key mag nooit app-breed context worden.
scene("#feedback", { huidigeView: "feedback", fbSel: CASE("nieuw:jan"), wsSel: "", dcSel: "" });
app.openModuleFromNav("workspace");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "workspace"]]),
   "11: 'nieuw:' uit een case wordt niet meegedragen", JSON.stringify(calls));

// 12. Feedback blijft zelf een globale route: navigeren NAAR Feedback opent geen atleet.
scene("#workspace/douwe", { huidigeView: "workspace", wsSel: "douwe" });
app.openModuleFromNav("feedback");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "feedback"]]),
   "12: Feedback zelf blijft queue-first", JSON.stringify(calls));

if (failures.length) {
  console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - "));
  process.exit(1);
} else {
  console.log("PASS: Workspace ↔ Dossier carry the selected/shown athlete (route or bare-hash); generic Feedback queue-first; nieuw:-guard holds; Feedback carries its open case to the athlete routes (12 scenarios).");
}
