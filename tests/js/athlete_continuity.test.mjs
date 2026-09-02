// Executable athlete-context continuity test (Cross-Module UX/IA v1, Target B).
//
// Slices the REAL activeAthleteKey() + openModuleFromNav() (+ the _ATHLETE_VIEWS /
// _ATHLETE_CTX_VIEWS sets) VERBATIM from pwa/static/app.js and drives them against a mock
// location.hash with spies for openWorkspace / openAthleteModule / toonView.
//
//   node tests/js/athlete_continuity.test.mjs
//
// Proves: Workspace ↔ Dossier carry the same selected athlete via the sidebar, while generic
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

const REAL = [
  sliceLine("const _ATHLETE_VIEWS = "),
  sliceLine("const _ATHLETE_CTX_VIEWS = "),
  sliceFrom("function activeAthleteKey("),
  sliceFrom("function openModuleFromNav("),
].join("\n\n");

let calls, hash;
const openWorkspace = (k) => calls.push(["openWorkspace", k]);
const openAthleteModule = (v, k) => calls.push(["openAthleteModule", v, k]);
const toonView = (v) => calls.push(["toonView", v]);
const locationShim = { get hash() { return hash; } };

const build = () => new Function("openWorkspace", "openAthleteModule", "toonView", "location",
  REAL + "\nreturn { activeAthleteKey, openModuleFromNav };"
)(openWorkspace, openAthleteModule, toonView, locationShim);

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };
const app = build();

function at(h) { calls = []; hash = h; }

// 1. Workspace → Dossier carries the athlete
at("#workspace/douwe");
ok(app.activeAthleteKey() === "douwe", "1: workspace route yields active athlete", app.activeAthleteKey());
app.openModuleFromNav("dossier");
ok(JSON.stringify(calls) === JSON.stringify([["openAthleteModule", "dossier", "douwe"]]),
   "1: nav to Dossier opens the same athlete", JSON.stringify(calls));

// 2. Dossier → Workspace carries the athlete (own entry)
at("#dossier/douwe");
app.openModuleFromNav("workspace");
ok(JSON.stringify(calls) === JSON.stringify([["openWorkspace", "douwe"]]),
   "2: nav to Workspace opens the same athlete via openWorkspace", JSON.stringify(calls));

// 3. Generic Feedback stays queue-first (no athlete routing), even with an active athlete
at("#workspace/douwe");
app.openModuleFromNav("feedback");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "feedback"]]),
   "3: generic Feedback nav stays queue-first (no auto-open athlete)", JSON.stringify(calls));

// 4. Global view with no athlete context → plain module entry
at("#home");
app.openModuleFromNav("dossier");
ok(JSON.stringify(calls) === JSON.stringify([["toonView", "dossier"]]),
   "4: no active athlete → plain module entry", JSON.stringify(calls));

// 5. `nieuw:` identity-guard: never an app-wide athlete context
at("#atleten/nieuw:jan");
ok(app.activeAthleteKey() === "", "5: 'nieuw:' route is not an active athlete context", app.activeAthleteKey());

console.log("== Athlete-context continuity (executable) ==");
if (failures.length) {
  console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - "));
  process.exit(1);
} else {
  console.log("PASS: Workspace ↔ Dossier carry the selected athlete; generic Feedback stays queue-first; nieuw:-guard holds (5 checks).");
}
