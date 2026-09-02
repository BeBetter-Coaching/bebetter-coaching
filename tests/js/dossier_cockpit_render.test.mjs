// Executable REAL Dossier/cockpit renderer/runtime test (Node, real functions — NO renderer stub).
//
// Gate 0 safety net for Canonical Athlete Read Layer v1. Slices the REAL production dcRender +
// dcScene (desktop 3-zone) + dcStack (narrow) + every pure helper they call, plus the real
// dcWaarom ("Waarom?") lifecycle, VERBATIM from pwa/static/app.js and drives them against a
// minimal DOM/api shim. Only DOM/api/icon primitives are mocked — the render logic is real.
//
//   node tests/js/dossier_cockpit_render.test.mjs
//
// Proves, on the CURRENT production code (e8f1bde):
//   A. the real desktop cockpit renderer (dcScene) executes without throwing;
//   B. the real narrow cockpit renderer (dcStack) executes without throwing;
//   C. a degraded/source-gap + INSUFFICIENT_DATA view-model renders (source-health honesty,
//      never a silent "niets bekend");
//   D. the real "Waarom?" lifecycle executes (fetch → provenance box inserted).
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
    else if (SRC[j] === "}") { d--; if (d === 0) {
      let k = j + 1;
      while (k < SRC.length && SRC[k] !== ";" && SRC[k] !== "\n") k++;
      return SRC.slice(i, (SRC[k] === ";" ? k + 1 : j + 1));
    } }
  }
  throw new Error("unbalanced: " + header);
}
const sliceLine = (p) => { const i = SRC.indexOf(p); if (i < 0) throw new Error("not found: " + p); return SRC.slice(i, SRC.indexOf("\n", i)); };

const REAL = [
  // Design System v1 primitives
  sliceFrom("const _DS_TONE = {"), sliceLine("const _DS_RANK = "),
  sliceFrom("function dsTone("), sliceFrom("function dsWorstTone("), sliceFrom("function dsChip("),
  sliceFrom("function dsFresh("), sliceFrom("function dsSpark("), sliceFrom("function dsRing("),
  sliceFrom("function dsMetric("), sliceFrom("function dsAttnCard("), sliceFrom("function dsPanel("),
  sliceFrom("function dsKv("), sliceFrom("function dsStream("), sliceFrom("function dsAction("),
  sliceFrom("function dsEmpty("), sliceFrom("function dsSkeletonBlock("),
  // Dossier consts
  sliceFrom("const _DC_OVERALL = {"), sliceFrom("const _DC_TRUTH = {"), sliceFrom("const _DC_KIND_IC = {"),
  sliceFrom("const _DC_TONE_HEX = {"), sliceLine("const dcHex = "), sliceLine("const DC_MEM = "),
  sliceLine("const _DC_MND = "), sliceFrom("const _DC_ATTN_IC = {"), sliceFrom("const _DC_DOM_IC = {"),
  sliceLine("let dcEvents = "), sliceLine("let _dcResizeBound = "),
  // Dossier helpers + renderers (real)
  sliceFrom("function dcProv("), sliceFrom("function dcPrettyLabel("), sliceFrom("function dcProvText("),
  sliceFrom("function dcShort("), sliceFrom("function dcChangeMeta("), sliceFrom("function dcPastNodes("),
  sliceFrom("function dcFutureNodes("), sliceFrom("function dcRender("), sliceFrom("function dcBindResize("),
  sliceFrom("function dcWireDesktop("), sliceFrom("function dcBuildEvents("), sliceFrom("function dcFutureMetric("),
  sliceFrom("function dcScene("), sliceFrom("function dcTlItem("), sliceFrom("function dcRelCard("),
  sliceFrom("function dcScaleDots("), sliceFrom("function dcMemPanel("), sliceFrom("function dcDrawConnectors("),
  sliceFrom("function dcSelectEvent("), sliceFrom("function dcOpenDomain("), sliceFrom("function dcRow("),
  sliceFrom("function dcHeader("), sliceFrom("function dcDiag("), sliceFrom("function dcToday("),
  sliceFrom("function dcStack("), sliceFrom("async function dcWaarom("),
].join("\n\n");

// ── DOM/api shim ─────────────────────────────────────────────────────────────
let apiCalls, apiRouter, innerW;
function mkEl() {
  const el = {
    _html: "", hidden: false, dataset: {}, className: "", textContent: "", _open: false,
    _children: [], nextElementSibling: null,
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); },
    addEventListener() {}, removeEventListener() {}, focus() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 40, right: 100, bottom: 40 }; },
    insertAdjacentElement(pos, node) { el.nextElementSibling = node; return node; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  };
  return el;
}
const $ = (sel) => mkEl();
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const ic = (n) => `<i:${n}>`;
const initialen = (naam) => String(naam || "").slice(0, 2).toUpperCase();
const openAthleteModule = () => {};
const athleteNav = () => `<nav class="anav"></nav>`;   // shared nav component (not the cockpit renderer)
const wsOrbits = () => "";                              // shared decorative background (not the cockpit renderer)
const documentShim = { createElement: () => mkEl(), querySelectorAll: () => [], querySelector: () => null };
const requestAnimationFrame = () => {};
const consoleShim = { debug() {}, log() {}, error() {}, warn() {} };
async function api(url) { apiCalls.push(url); return apiRouter ? apiRouter(url) : null; }
const windowShim = { get innerWidth() { return innerW; }, addEventListener() {} };

const shimNames = ["$", "esc", "ic", "initialen", "openAthleteModule", "athleteNav", "wsOrbits",
  "document", "window", "requestAnimationFrame", "console", "api", "setTimeout", "clearTimeout"];
const build = () => new Function(...shimNames,
  REAL + "\nreturn { dcRender, dcScene, dcStack, dcWaarom };"
)($, esc, ic, initialen, openAthleteModule, athleteNav, wsOrbits, documentShim, windowShim,
  requestAnimationFrame, consoleShim, api, setTimeout, clearTimeout);

const reset = (w) => { apiCalls = []; apiRouter = null; innerW = w || 1440; };

// A rich, healthy cockpit view-model (shape from dossier_cockpit.cockpit()).
const vmHealthy = (over = {}) => ({
  ok: true, key: "u1", naam: "Lisa Jansen", groep: "High Performer",
  status: { overall: "ATTENTION", insufficient: false, reliability: { level: "green", core_gap: false } },
  attention: [{ kind: "complaint", title: "Knieklacht terug", why: "Athlete meldde pijn na de lange duurloop" }],
  attention_domains: ["gezondheid"],
  load_observation: { ernst: "hoog", signalen: "Volume +38%", home_action: true, afgehandeld: false, delta_pct: 38 },
  changes: [{ title: "Klacht opnieuw in beeld", effective_at: "2026-08-28", transition: { to: "RECENT" }, provenance_refs: ["ev1"] }],
  planning: { rows: [{ label: "Hoofddoel", value: "Marathon" }, { label: "Wedstrijddatum", value: "2026-11-01" }, { label: "Schema-status", value: "Actief" }] },
  domains: [{ key: "coach", onbekend: false, regels: [{ value: "Let op de knie de komende week" }] }],
  timeline: { events: [], capture_mode: "off", empty_reason: "capture_off" },
  source_health: [{ source: "intake", available: true }, { source: "fs.training_log", available: true }],
  build_diagnostic: [],
  ...over,
});

// A degraded / insufficient-data view-model with a source gap (must still render honestly).
const vmDegraded = () => vmHealthy({
  status: { overall: "INSUFFICIENT_DATA", insufficient: true, reliability: { level: "unknown", core_gap: true } },
  attention: [{ kind: "source_gap", title: "FinalSurge-bron uitgevallen", why: "trainingslog tijdelijk niet beschikbaar" }],
  load_observation: null,
  changes: [],
  planning: { rows: [] },
  domains: [],
  source_health: [{ source: "fs.training_log", available: false, error: "timeout" }],
  build_diagnostic: ["load_stage: partial"],
});

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };
const run = (fn) => { try { fn(); } catch (e) { failures.push(fn.name + " threw: " + e.constructor.name + ": " + e.message); } };
const runAsync = async (fn) => { try { await fn(); } catch (e) { failures.push(fn.name + " threw: " + e.constructor.name + ": " + e.message); } };

// ── A. Real desktop renderer (dcScene via dcRender, innerWidth ≥ 1280) ────────
function A_desktop_render() {
  reset(1440);
  const app = build();
  const wrap = mkEl();
  app.dcRender(wrap, vmHealthy());
  ok(wrap.innerHTML.length > 0, "A: desktop cockpit wrote markup");
  ok(/dc-/.test(wrap.innerHTML), "A: dc- cockpit markup present");
  ok(/Lisa Jansen/.test(wrap.innerHTML), "A: athlete identity rendered");
}

// ── B. Real narrow renderer (dcStack via dcRender, innerWidth < 1280) ─────────
function B_narrow_render() {
  reset(800);
  const app = build();
  const wrap = mkEl();
  app.dcRender(wrap, vmHealthy());
  ok(wrap.innerHTML.length > 0, "B: narrow cockpit wrote markup");
  ok(/dc-/.test(wrap.innerHTML), "B: dc- cockpit markup present (narrow)");
}

// ── C. Degraded / source-gap view-model renders honestly (no silent empty) ───
function C_degraded_render() {
  reset(1440);
  const app = build();
  const wrap = mkEl();
  app.dcRender(wrap, vmDegraded());
  ok(wrap.innerHTML.length > 0, "C: degraded cockpit still rendered markup (not blank)");
  ok(/uitgevallen|onzeker|verouderd|onvolledig/i.test(wrap.innerHTML),
     "C: source-health/degraded state surfaced in the render");
  // narrow branch too
  reset(800);
  const app2 = build();
  const wrap2 = mkEl();
  app2.dcRender(wrap2, vmDegraded());
  ok(wrap2.innerHTML.length > 0, "C: degraded narrow cockpit rendered");
}

// ── D. Real "Waarom?" lifecycle executes (fetch carries gen → provenance box) ─
async function D_waarom_lifecycle() {
  reset(1440);
  const app = build();
  // dcRender stamps dcVMgen from the view-model — drive it so the Waarom call carries the gen.
  app.dcRender(mkEl(), vmHealthy({ state_generation_id: "gen-Z9" }));
  apiRouter = (url) => {
    return { ok: true, generation_changed: false,
      explain: { truth_type: "ATHLETE_REPORTED", strength: "HIGH", observed_at: "2026-08-28",
      sources: ["intake"], provenance: [{ key: "klacht.knie", source: "intake", observed_at: "2026-08-28", truth_type: "ATHLETE_REPORTED" }] } };
  };
  const btn = mkEl();
  btn.dataset.id = "ev1"; btn.dataset.key = "u1"; btn._open = false; btn.textContent = "Waarom?";
  await app.dcWaarom(btn);
  const explainUrl = apiCalls.find(u => /\/api\/cockpit\/explain/.test(u)) || "";
  ok(explainUrl !== "", "D: explain fetch issued", apiCalls.join(","));
  ok(/gen=gen-Z9/.test(explainUrl), "D: explain request carries the shown state_generation_id", explainUrl);
  ok(btn.nextElementSibling && /klein|dc-why-chain/.test(btn.nextElementSibling.innerHTML || ""),
     "D: provenance box inserted after the button", btn.nextElementSibling && btn.nextElementSibling.innerHTML.slice(0, 40));
}

// ── E. "Waarom?" generation_changed → no fabricated explanation, refreshed note ─
async function E_waarom_generation_changed() {
  reset(1440);
  const app = build();
  app.dcRender(mkEl(), vmHealthy({ state_generation_id: "gen-OLD" }));
  apiRouter = () => ({ ok: true, generation_changed: true, explain: null,
    note: "De context is intussen ververst" });
  const btn = mkEl();
  btn.dataset.id = "ev1"; btn.dataset.key = "u1"; btn._open = false; btn.textContent = "Waarom?";
  await app.dcWaarom(btn);
  const html = (btn.nextElementSibling && btn.nextElementSibling.innerHTML) || "";
  ok(/ververst/i.test(html), "E: refreshed-context message shown (no fabricated explanation)", html.slice(0, 60));
  ok(!/dc-why-chain/.test(html), "E: no provenance chain rendered on generation mismatch");
}

console.log("== REAL Dossier cockpit renderer/runtime contract (executable, no renderer stub) ==");
[A_desktop_render, B_narrow_render, C_degraded_render].forEach(run);
await runAsync(D_waarom_lifecycle);
await runAsync(E_waarom_generation_changed);

console.log("");
if (failures.length) {
  console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - "));
  process.exit(1);
} else {
  console.log("PASS: real dcRender/dcScene/dcStack + dcWaarom execute; desktop + narrow + degraded render; Waarom lifecycle + generation-coherence correct (5 scenarios).");
}
