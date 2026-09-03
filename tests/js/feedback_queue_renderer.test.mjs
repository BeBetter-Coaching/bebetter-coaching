// Executable REAL-renderer test (Node, real functions — NO renderQueue stub).
//
// Per BEBETTER-FEEDBACK-P0-EXACT-FBLOCALISO-RENDERER-FIX.md. The startup/route-entry harnesses
// stub renderQueue (noop / simple shim), so they cannot observe a crash INSIDE the real renderer.
// This test slices the REAL FB state object AND the real renderQueue/renderTabs/fbFilterItems/
// renderGroupsBar/fbRowHtml/fbShortTime/fbLocalISO (+ pure date helpers) verbatim from
// pwa/static/app.js and drives them against a minimal DOM shim. Only DOM/icon primitives are mocked.
//
//   node tests/js/feedback_queue_renderer.test.mjs
//
// PROVEN PRE-FIX CRASH (822bec9): the redesign introduced three zero-argument fbLocalISO() calls
// (fbFilterItems ~2738, renderTabs ~2746, fbShortTime ~2805). fbLocalISO(dd) does dd.getFullYear()
// with no default → TypeError "Cannot read properties of undefined (reading 'getFullYear')".
// renderQueue() runs renderGroupsBar() first (group counts appear), then renderTabs() throws before
// any rows are written → #fb-queue keeps its skeleton. This test FAILS on 822bec9 (scenario A throws)
// and PASSES once the three calls pass an explicit Date and the group-filter intersection is restored.
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
const sliceLine = (p) => { const i = SRC.indexOf(p); return SRC.slice(i, SRC.indexOf("\n", i)); };

const REAL = [
  sliceFrom("const FB = {"),                 // the ACTUAL production FB state (incl. its initializers)
  sliceLine("const FB_CAT = {"),
  sliceLine("const _FB_TABS = "),
  sliceFrom("function fbGroupOrder("),
  sliceFrom("function renderGroupsBar("),
  sliceFrom("function fbLocalISO("),
  sliceFrom("function fbDateLabel("),
  sliceFrom("function fbIsoWeek("),
  "function fbIsAandacht(it) { return it.categorie === \"reactie\"; }",
  sliceFrom("function fbFilterItems("),
  sliceFrom("function renderTabs("),
  sliceFrom("function renderQueue("),
  sliceFrom("function fbRowHtml("),
  sliceFrom("function fbShortTime("),
].join("\n\n");

// Guard: the invalid pre-fix pattern must be gone once fixed (belt-and-suspenders on the slice).
const ZERO_ARG_CALLS = (SRC.match(/fbLocalISO\(\)/g) || []).length;

// ── DOM shim (only mocked primitives) ────────────────────────────────────────
let els, boundRows, openCalls;
function mkEl() {
  return {
    _html: "", hidden: false, onclick: null,
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); },
    addEventListener() {}, focus() {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } }, dataset: {},
  };
}
const $ = (sel) => (els[sel] ||= mkEl());
function $$(sel, root) {
  if (sel === ".fbq-row" && root) {
    const ids = [...String(root._html).matchAll(/data-id="([^"]+)"/g)].map(m => m[1]);
    boundRows = ids.slice();
    return ids.map(id => { const e = mkEl(); e.dataset.id = id; return e; });
  }
  if (sel === ".fbg-pill" || sel === ".fbq-tab") return [];
  return [];
}
const ic = (n) => `<i:${n}>`;
const initialen = (naam) => String(naam || "").slice(0, 2).toUpperCase();
const fbLog = () => {};
const fbOpen = (id, reason) => { openCalls.push([id, reason]); };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const fbUpdateInfo = () => {};   // status-line leaf (#fb-info) — not under test here
const shimNames = ["$", "$$", "ic", "initialen", "fbLog", "fbOpen", "esc", "fbUpdateInfo"];
const build = () => new Function(...shimNames,
  REAL + "\nreturn { FB, renderQueue, renderTabs, fbFilterItems, renderGroupsBar, fbRowHtml, fbShortTime, fbLocalISO };"
)($, $$, ic, initialen, fbLog, fbOpen, esc, fbUpdateInfo);
const reset = () => { els = {}; boundRows = []; openCalls = []; };

// today's LOCAL iso (matches fbLocalISO semantics) so 'vandaag'-scenarios are date-robust.
const _now = new Date();
const todayISO = `${_now.getFullYear()}-${String(_now.getMonth() + 1).padStart(2, "0")}-${String(_now.getDate()).padStart(2, "0")}`;

const rowsInQueue = () => [...String($("#fb-queue").innerHTML).matchAll(/data-id="([^"]+)"/g)].map(m => m[1]);
const groupsRendered = () => String(($("#fb-groups") || {}).innerHTML || "").includes("fbg-pill");

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };
const run = (fn) => { try { fn(); } catch (e) { failures.push(fn.name + " threw: " + e.constructor.name + ": " + e.message); } };

// ── A. Real queue render: items + skeleton preset → rows appear, skeleton gone ─
function A_real_render() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "w1", naam: "Lisa", voornaam: "Lisa", workout: "Duurloop", datum: "2026-08-28", categorie: "reactie", groep: "comfort", groep_label: "Comfort", athlete_ts: "" },
    { id: "w2", naam: "Sam", voornaam: "Sam", workout: "Interval", datum: "2026-08-28", categorie: "gevoel", groep: "tempo", groep_label: "Tempo", athlete_ts: "" },
    { id: "w3", naam: "Tom", voornaam: "Tom", workout: "Rustloop", datum: "2026-08-27", categorie: "uitgevoerd", groep: "comfort", groep_label: "Comfort", athlete_ts: "" },
  ];
  app.FB.groups = [{ key: "comfort", label: "Comfort" }, { key: "tempo", label: "Tempo" }];
  app.FB.filter = "wachten"; app.FB.group = "alle";
  $("#fb-queue").innerHTML = "SKELETON";
  let threw = null;
  try { app.renderQueue(); } catch (e) { threw = e; }
  if (threw) {
    // PRE-FIX diagnostic: prove the exact crash + that counts rendered but rows did not.
    console.log("  · PRE-FIX crash observed: " + threw.constructor.name + ": " + threw.message);
    console.log("  · group counts rendered before exception? " + groupsRendered());
    console.log("  · #fb-queue after: " + (/SKELETON/.test($("#fb-queue").innerHTML) ? "STILL SKELETON (rows not written)" : "rows"));
    ok(false, "A: renderQueue() threw", threw.message);
    // Assert the crash shape matches the proven root cause (useful signal in pre-fix runs).
    ok(/Cannot read properties of undefined/.test(threw.message) && /getFullYear/.test(threw.message),
       "A: (pre-fix) exception is the proven fbLocalISO getFullYear crash");
    return;
  }
  ok(!/SKELETON/.test($("#fb-queue").innerHTML), "A: skeleton replaced");
  ok(/fbq-row/.test($("#fb-queue").innerHTML), "A: real .fbq-row markup written");
  ok(rowsInQueue().length === 3, "A: all three rows rendered", rowsInQueue().join(","));
}

// ── B. Wachten: open items render, server order unchanged (no client sort) ────
function B_wachten_order() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "a", naam: "A", voornaam: "A", workout: "x", datum: "2026-08-28", categorie: "reactie", groep: "comfort", athlete_ts: "" },
    { id: "b", naam: "B", voornaam: "B", workout: "x", datum: "2026-08-28", categorie: "gevoel", groep: "comfort", athlete_ts: "" },
    { id: "c", naam: "C", voornaam: "C", workout: "x", datum: "2026-08-27", categorie: "uitgevoerd", groep: "comfort", athlete_ts: "" },
  ];
  app.FB.filter = "wachten"; app.FB.group = "alle";
  app.renderQueue();
  ok(JSON.stringify(rowsInQueue()) === JSON.stringify(["a", "b", "c"]),
     "B: server order preserved (no client resort)", rowsInQueue().join(","));
}

// ── C. Group intersection: select a group → only that group renders ──────────
function C_group_intersection() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "a", naam: "A", voornaam: "A", workout: "x", datum: "2026-08-28", categorie: "reactie", groep: "comfort", athlete_ts: "" },
    { id: "b", naam: "B", voornaam: "B", workout: "x", datum: "2026-08-28", categorie: "gevoel", groep: "tempo", athlete_ts: "" },
    { id: "c", naam: "C", voornaam: "C", workout: "x", datum: "2026-08-27", categorie: "uitgevoerd", groep: "comfort", athlete_ts: "" },
  ];
  app.FB.groups = [{ key: "comfort", label: "Comfort" }, { key: "tempo", label: "Tempo" }];
  app.FB.filter = "wachten"; app.FB.group = "tempo";
  app.renderQueue();
  ok(JSON.stringify(rowsInQueue()) === JSON.stringify(["b"]),
     "C: only selected group 'tempo' renders", rowsInQueue().join(","));
}

// ── D. Today + group both apply ──────────────────────────────────────────────
function D_today_group() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "t1", naam: "T1", voornaam: "T1", workout: "x", datum: todayISO, categorie: "gevoel", groep: "tempo", athlete_ts: "08:00" },
    { id: "t2", naam: "T2", voornaam: "T2", workout: "x", datum: todayISO, categorie: "gevoel", groep: "comfort", athlete_ts: "08:00" },
    { id: "y1", naam: "Y1", voornaam: "Y1", workout: "x", datum: "2026-08-27", categorie: "gevoel", groep: "tempo", athlete_ts: "" },
  ];
  app.FB.groups = [{ key: "comfort", label: "Comfort" }, { key: "tempo", label: "Tempo" }];
  app.FB.filter = "vandaag"; app.FB.group = "tempo";
  app.renderQueue();
  ok(JSON.stringify(rowsInQueue()) === JSON.stringify(["t1"]),
     "D: today ∩ group=tempo → only t1", rowsInQueue().join(","));
}

// ── E. Attention + group both apply ──────────────────────────────────────────
function E_attention_group() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "r1", naam: "R1", voornaam: "R1", workout: "x", datum: "2026-08-28", categorie: "reactie", groep: "tempo", athlete_ts: "" },
    { id: "r2", naam: "R2", voornaam: "R2", workout: "x", datum: "2026-08-28", categorie: "reactie", groep: "comfort", athlete_ts: "" },
    { id: "g1", naam: "G1", voornaam: "G1", workout: "x", datum: "2026-08-28", categorie: "gevoel", groep: "tempo", athlete_ts: "" },
  ];
  app.FB.groups = [{ key: "comfort", label: "Comfort" }, { key: "tempo", label: "Tempo" }];
  app.FB.filter = "aandacht"; app.FB.group = "tempo";
  app.renderQueue();
  ok(JSON.stringify(rowsInQueue()) === JSON.stringify(["r1"]),
     "E: attention(reactie) ∩ group=tempo → only r1", rowsInQueue().join(","));
}

// ── F. Invalid current group → falls back to 'alle', no crash ────────────────
function F_invalid_group_fallback() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "a", naam: "A", voornaam: "A", workout: "x", datum: "2026-08-28", categorie: "reactie", groep: "comfort", athlete_ts: "" },
    { id: "b", naam: "B", voornaam: "B", workout: "x", datum: "2026-08-28", categorie: "gevoel", groep: "comfort", athlete_ts: "" },
  ];
  app.FB.groups = [{ key: "comfort", label: "Comfort" }];
  app.FB.filter = "wachten"; app.FB.group = "tempo";   // 'tempo' not present in the open queue
  app.renderQueue();
  ok(app.FB.group === "alle", "F: stale group resets to 'alle'", app.FB.group);
  ok(rowsInQueue().length === 2, "F: all items render after fallback", rowsInQueue().join(","));
}

// ── G. fbShortTime: no zero-argument date crash (today + non-today) ──────────
function G_fbshorttime() {
  reset();
  const app = build();
  let e1 = null, e2 = null;
  try { app.fbShortTime({ datum: todayISO, athlete_ts: "07:45" }); } catch (e) { e1 = e; }
  try { app.fbShortTime({ datum: "2026-08-27", athlete_ts: "" }); } catch (e) { e2 = e; }
  ok(e1 === null, "G: fbShortTime(today) does not throw", e1 && e1.message);
  ok(e2 === null, "G: fbShortTime(past) does not throw", e2 && e2.message);
}

// ── H. Route-entry-ish contract in the renderer: no auto-open, rows bind fbOpen ─
function H_no_autoopen_binds() {
  reset();
  const app = build();
  app.FB.items = [
    { id: "a", naam: "A", voornaam: "A", workout: "x", datum: "2026-08-28", categorie: "reactie", groep: "comfort", athlete_ts: "" },
    { id: "b", naam: "B", voornaam: "B", workout: "x", datum: "2026-08-28", categorie: "gevoel", groep: "comfort", athlete_ts: "" },
  ];
  app.FB.filter = "wachten"; app.FB.group = "alle";
  app.renderQueue();
  ok(openCalls.length === 0, "H: rendering opens no case (no auto-open)", JSON.stringify(openCalls));
  ok(boundRows.length === 2, "H: a click handler bound per row", boundRows.join(","));
  ok(/role="option"/.test($("#fb-queue").innerHTML), "H: rows carry role=option (fbRowHtml ran)");
}

console.log("== REAL renderer contract (executable, no renderQueue stub) ==");
console.log("zero-argument fbLocalISO() call-sites in app.js: " + ZERO_ARG_CALLS);
ok(ZERO_ARG_CALLS === 0, "guard: zero-argument fbLocalISO() call-sites must be 0", "found " + ZERO_ARG_CALLS);

[A_real_render, B_wachten_order, C_group_intersection, D_today_group,
 E_attention_group, F_invalid_group_fallback, G_fbshorttime, H_no_autoopen_binds].forEach(run);

console.log("");
if (failures.length) {
  console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - "));
  process.exit(1);
} else {
  console.log("PASS: real renderQueue() renders rows without throwing; group intersection + triage filters + fbShortTime all correct (8 scenarios).");
}
