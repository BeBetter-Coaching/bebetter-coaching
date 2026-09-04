// Executable REAL Workspace renderer/runtime test (Node, real functions — NO renderer stub).
//
// Slices the REAL production wsRender/wsLoadDeep/wsShow (+ pure helpers, Design-System
// primitives, generation guard) VERBATIM from pwa/static/app.js and drives them against a
// minimal DOM/api shim. Only DOM/api/icon primitives are mocked — the render logic is real.
//
//   node tests/js/workspace_render.test.mjs
//
// Proves, on the current code:
//   A. the real Workspace renderer executes without throwing and writes the Now/Next grid;
//   B. the shell renders WITHOUT any /api/cockpit (deep) fetch — shell independent of deep;
//   C. the generation guard adopts vm.generation and stamps the banner;
//   D. route/open lifecycle (wsShow) renders the shell first, THEN lazy-loads the deep context;
//   E. a failing deep load never breaks the already-rendered shell;
//   F. layout/dedup contract (UX/IA v1): one load truth, one open-feedback summary, no flame,
//      no internal bottom module nav, all primary panels present exactly once, "laatste 7 dagen".
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
  sliceFrom("const _DS_TONE = {"), sliceLine("const _DS_RANK = "),
  sliceFrom("function dsTone("), sliceFrom("function dsWorstTone("), sliceFrom("function dsChip("),
  sliceFrom("function dsFresh("), sliceFrom("function dsKv("), sliceFrom("function dsStream("),
  sliceLine("const _bbGen = "), sliceFrom("function _genDominates("), sliceFrom("function noteGeneration("),
  sliceFrom("function bbGenSync("), sliceFrom("function genBanner("),
  sliceFrom("const _DC_KIND_IC = {"),
  sliceLine("let wsSel = "),
  sliceFrom("function nlNum("), sliceFrom("function wsWeekStrip("), sliceFrom("function wsLoadInstrument("),
  sliceFrom("function wsLine("), sliceFrom("function wsSkel("),
  sliceFrom("function wsRender("), sliceFrom("async function wsLoadDeep("),
  sliceFrom("function wsSwitchVul("), sliceFrom("async function laadWorkspace("), sliceFrom("async function wsShow("),
].join("\n\n");

// ── DOM/api shim ─────────────────────────────────────────────────────────────
let els, apiCalls, apiRouter, scrollCalls;
function mkEl() {
  return {
    _html: "", hidden: false, dataset: {},
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); },
    addEventListener() {}, removeEventListener() {}, focus() {}, scrollTo() { scrollCalls++; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    textContent: "",
  };
}
const $ = (sel) => (els[sel] ||= mkEl());
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const ic = (n) => `<i:${n}>`;
const initialen = (naam) => String(naam || "").slice(0, 2).toUpperCase();
const openAthleteModule = () => {};
const wsMarkeerGezien = () => {};
const melding = () => {};
const toonView = () => {};
const pushRoute = () => {};
const bindRefresh = () => {};
const geladen = {};
let huidigeView = "workspace";
const documentShim = { querySelectorAll() { return []; }, createElement() { return mkEl(); } };
const windowShim = { innerWidth: 1440, addEventListener() {} };
const locationShim = { hash: "" };
const historyShim = { pushState() {} };
async function api(url) { apiCalls.push(url); return apiRouter ? apiRouter(url) : null; }

const shimNames = ["$", "esc", "ic", "initialen", "openAthleteModule", "wsMarkeerGezien", "melding",
  "toonView", "pushRoute", "bindRefresh", "geladen", "huidigeView",
  "document", "window", "location", "history", "api", "jpost"];
const build = () => new Function(...shimNames,
  REAL + "\nreturn { wsRender, wsLoadDeep, wsShow, laadWorkspace, noteGeneration, genBanner, _peekGen: () => _bbGen };"
)($, esc, ic, initialen, openAthleteModule, wsMarkeerGezien, melding,
  toonView, pushRoute, bindRefresh, geladen, huidigeView, documentShim, windowShim, locationShim,
  historyShim, api, async () => ({ ok: true }));

const reset = () => { els = {}; apiCalls = []; apiRouter = null; scrollCalls = 0; };

const wsPayload = (over = {}) => ({
  ok: true, key: "u1", naam: "Lisa Jansen", voornaam: "Lisa",
  generation: { generation_id: "gen-A", generation_at: "2026-09-01T10:00:00", generated_at: "2026-09-01T10:00:05",
    source_versions: { belasting: "2026-09-01", home: "2026-09-01T09:00", feedback: "2026-09-01T08:00" },
    freshness: { belasting: "fresh", home: "fresh", feedback: "fresh" } },
  attention: [{ soort: "belasting", tier: "actie", kort: "Verhoogd belastingssignaal", pct: 42 }],
  belasting: { actief: true, ernst: "hoog", pct: 42, km_recent: 48, km_basis_week: 34,
    signalen: ["Volume sterk omhoog"], reden: "Volume sterk omhoog",
    runs: [{ datum: "2026-08-26", km: 8 }, { datum: "2026-08-28", km: 12 }, { datum: "2026-08-30", km: 14 }],
    datum: "2026-09-01" },
  schema: { tier: "aandacht", kort: "Schema loopt af", days_left: 5, einddatum: "2026-09-06" },
  feedback: { status: "fresh", open: 2 },
  deep: { cockpit: "/api/cockpit?key=u1" },
  ...over,
});

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };
const run = (fn) => { try { fn(); } catch (e) { failures.push(fn.name + " threw: " + e.constructor.name + ": " + e.message); } };
const runAsync = async (fn) => { try { await fn(); } catch (e) { failures.push(fn.name + " threw: " + e.constructor.name + ": " + e.message); } };
const count = (h, re) => (h.match(re) || []).length;

function A_render_no_throw() {
  reset();
  const app = build();
  const wrap = mkEl();
  app.wsRender(wrap, wsPayload());
  const h = wrap.innerHTML;
  ok(/ws-grid/.test(h), "A: ws-grid written");
  ok(/ws-attn-panel/.test(h) && /ws-load-panel/.test(h), "A: attention + load panels rendered");
  ok(/\+42%/.test(h), "A: load pct rendered");
  ok(/ws-next-btn/.test(h), "A: next-action button rendered");
}

function B_shell_independent_of_deep() {
  reset();
  const app = build();
  const wrap = mkEl();
  app.wsRender(wrap, wsPayload());
  ok(apiCalls.length === 0, "B: wsRender issues no fetch (shell independent of deep)", apiCalls.join(","));
  ok(/ws-deep-slot/.test(wrap.innerHTML), "B: deep slots present as lazy placeholders");
}

function C_generation_guard() {
  reset();
  const app = build();
  const wrap = mkEl();
  app.wsRender(wrap, wsPayload());
  ok(app._peekGen().id === "gen-A", "C: noteGeneration adopted generation_id", app._peekGen().id);
  ok(/gen-banner/.test(wrap.innerHTML) && /data-gen="gen-A"/.test(wrap.innerHTML), "C: generation banner stamped");
}

async function D_lifecycle_shell_then_deep() {
  reset();
  const app = build();
  const order = [];
  apiRouter = (url) => {
    order.push(url);
    if (url.startsWith("/api/atleten")) return { atleten: [{ id: "u1", naam: "Lisa Jansen", groep: "High Performer" }], groep_volgorde: [] };
    if (url.startsWith("/api/workspace/")) return wsPayload();
    if (url.startsWith("/api/cockpit")) return { ok: true, planning: { rows: [{ label: "Hoofddoel", value: "10 km" }] }, attention: [], load_observation: null };
    return null;
  };
  await app.wsShow("u1");
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
  const wrap = $("#ws-detail");
  ok(/ws-grid/.test(wrap.innerHTML), "D: shell grid rendered after lifecycle", wrap.innerHTML.slice(0, 40));
  const wIdx = order.findIndex(u => u.startsWith("/api/workspace/"));
  const cIdx = order.findIndex(u => u.startsWith("/api/cockpit"));
  ok(wIdx >= 0 && cIdx >= 0 && wIdx < cIdx, "D: workspace shell fetched before cockpit deep", order.join(" | "));
}

async function E_deep_failure_safe() {
  reset();
  const app = build();
  const wrap = mkEl();
  app.wsRender(wrap, wsPayload());
  apiRouter = () => { throw new Error("cockpit down"); };
  let threw = null;
  try { await app.wsLoadDeep(wrap, "u1"); } catch (e) { threw = e; }
  ok(threw === null, "E: wsLoadDeep swallows a failing deep read (no throw)", threw && threw.message);
  ok(wrap.innerHTML.length > 0, "E: shell markup still present after deep failure");
}

// ── F. Layout / dedup contract (UX/IA v1) ────────────────────────────────────
function F_layout_dedup_contract() {
  reset();
  const app = build();
  const wrap = mkEl();
  app.wsRender(wrap, wsPayload());
  const h = wrap.innerHTML;
  // one authoritative load section
  ok(count(h, /ws-load-panel/g) === 1, "F: exactly one load panel", String(count(h, /ws-load-panel/g)));
  ok(count(h, /laatste 7 dagen/g) >= 1, "F: load labelled 'laatste 7 dagen'", String(count(h, /laatste 7 dagen/g)));
  ok(!/deze week/i.test(h), "F: no misleading 'deze week' label");
  // one open-feedback summary (single 'open reactie' representation)
  ok(count(h, /open reactie/g) === 1, "F: exactly one open-feedback summary", String(count(h, /open reactie/g)));
  // no dominant flame / decorative scene / internal bottom module nav
  ok(!/ws-core|ws-scene|ws-web\b|ws-orbits|ws-geo|ws-dock/.test(h), "F: no flame/orbit/scene/dock decoration");
  ok(!/>Teampuls<|>Profiel</.test(h), "F: no redundant internal module nav (Teampuls/Profiel)");
  // all primary panels present exactly once
  ["ws-attn-panel", "ws-load-panel", "ws-plan-panel", "ws-next-panel", "ws-fb-panel", "ws-src-panel"]
    .forEach(p => ok(count(h, new RegExp(p, "g")) === 1, `F: ${p} present once`, String(count(h, new RegExp(p, "g")))));
  // grid areas used (robust layout, not absolute)
  ok(/grid-area:attn/.test(h) && /grid-area:load/.test(h), "F: cards placed via grid areas");
}

console.log("== REAL Workspace renderer/runtime + layout contract (executable, no renderer stub) ==");
[A_render_no_throw, B_shell_independent_of_deep, C_generation_guard].forEach(run);
await runAsync(D_lifecycle_shell_then_deep);
await runAsync(E_deep_failure_safe);
run(F_layout_dedup_contract);

console.log("");
if (failures.length) {
  console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - "));
  process.exit(1);
} else {
  console.log("PASS: real wsRender/wsLoadDeep/wsShow execute; shell independent of deep; generation guard + lifecycle + layout/dedup contract correct (6 scenarios).");
}
