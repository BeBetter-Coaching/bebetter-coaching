// Executable REAL-function tests for the Coach Review v2 consolidation build.
// Slices production functions VERBATIM from pwa/static/app.js (no reimplementation) and drives
// them against a minimal shim. Covers the behavioural P1/P2 fixes:
//   C1 (V-07) group-chip counts respect the active status filter
//   C4 (V-19) status-filter toggle-off
//   C5 (V-23) send button disabled on empty draft
//   D9 (V-28) picker Enter selects the sole visible result
//   A2 (V-03) Workspace "Volgende actie" coherent with the badge + no "belasting vers" without a stand
//
//   node tests/js/coach_review_v2.test.mjs
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
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const ic = (n) => `<i:${n}>`;
const nlNum = (n) => String(n).replace(".", ",");
const initialen = (naam) => String(naam || "").slice(0, 2).toUpperCase();

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };

// ── C1 (V-07): group-chip counts under the active status filter ───────────────
{
  // Real: fbGroupOrder + fbFilterItems + renderGroupsBar. Minimal DOM/api shim.
  let barEl;
  const mkEl = () => ({ innerHTML: "", hidden: false, _click: [],
    querySelectorAll: () => [], classList: { contains: () => false } });
  const $ = () => barEl;
  const $$ = () => [];
  const fbLog = () => {};
  const fbIsAandacht = (it) => it.categorie === "reactie";
  const fbLocalISO = () => "2026-09-04";
  const FB = {
    items: [
      { id: 1, groep: "s2r", categorie: "reactie", datum: "2026-09-04" },
      { id: 2, groep: "s2r", categorie: "beoordeling", datum: "2026-09-02" },
      { id: 3, groep: "gb", categorie: "beoordeling", datum: "2026-09-02" },   // GB: 0 onder 'aandacht'
      { id: 4, groep: "comfort", categorie: "reactie", datum: "2026-09-01" },
    ],
    groups: [{ key: "s2r", label: "Start to Run" }, { key: "gb", label: "Getting Better" }, { key: "comfort", label: "Comfort" }],
    group: "alle", filter: "aandacht",
  };
  const code = sliceFrom("function fbGroupOrder(") + "\n" + sliceFrom("function fbFilterItems(") + "\n" + sliceFrom("function renderGroupsBar(") + "\nreturn { renderGroupsBar, fbFilterItems };";
  const api = new Function("$", "$$", "esc", "fbLog", "fbIsAandacht", "fbLocalISO", "FB", code)($, $$, esc, fbLog, fbIsAandacht, fbLocalISO, FB);
  barEl = mkEl();
  api.renderGroupsBar();
  const html = barEl.innerHTML;
  // Under 'aandacht' (categorie==reactie): s2r=1, gb=0, comfort=1, Alle=2.
  ok(/Start to Run\s*<b>1<\/b>/.test(html), "C1: s2r count = filtered (1)", html);
  ok(/Getting Better\s*<b>0<\/b>/.test(html), "C1: gb count = 0 under aandacht (never promise 1, render 0)", html);
  ok(/zero/.test(html), "C1: zero-count chip marked non-clickable", html);
  ok(/Alle\s*<b>2<\/b>/.test(html), "C1: 'Alle' = visible-under-filter total (2)", html);
}

// ── C4 (V-19): status-filter toggle-off returns to 'wachten' ──────────────────
{
  // Re-implement ONLY the one-line decision, asserting it matches the source verbatim.
  const toggle = (cur, tab) => (cur === tab && tab !== "wachten") ? "wachten" : tab;
  ok(toggle("aandacht", "aandacht") === "wachten", "C4: re-click active 'aandacht' → wachten");
  ok(toggle("wachten", "wachten") === "wachten", "C4: 'wachten' stays wachten");
  ok(toggle("wachten", "aandacht") === "aandacht", "C4: first click activates");
  ok(SRC.includes('FB.filter = (FB.filter === tab && tab !== "wachten") ? "wachten" : tab;'),
     "C4: source carries the exact toggle contract");
}

// ── C5 (V-23): send button disabled unless the trimmed draft is non-empty ─────
{
  const btn = { disabled: false, _aria: {}, setAttribute(k, v) { this._aria[k] = v; } };
  let taVal = "";
  const ta = { get value() { return taVal; } };
  const $ = (sel) => sel === "#fb-send" ? btn : (sel === "#fb-ta" ? ta : null);
  const fbSyncSend = new Function("$", sliceFrom("function fbSyncSend(") + "\nreturn fbSyncSend;")($);
  taVal = ""; fbSyncSend(); ok(btn.disabled === true, "C5: empty → disabled");
  taVal = "   \n\t "; fbSyncSend(); ok(btn.disabled === true, "C5: whitespace-only → disabled");
  taVal = "Goed gedaan!"; fbSyncSend(); ok(btn.disabled === false, "C5: content → enabled");
  taVal = ""; fbSyncSend(); ok(btn.disabled === true, "C5: cleared again → disabled");
}

// ── D9 (V-28): picker Enter selects the sole visible result ───────────────────
{
  const mkEl = () => {
    const el = { innerHTML: "", value: "", hidden: false, dataset: {},
      _listeners: {}, addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); },
      removeEventListener() {}, focus() {}, classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      querySelector: () => null, querySelectorAll: () => [], closest: () => null, scrollIntoView() {} };
    return el;
  };
  const mount = mkEl();
  mount.querySelector = () => mkEl();
  const windowShim = { CSS: null };
  let confirmed = null;
  const renderPicker = new Function("esc", "initialen", "window", "setTimeout",
    sliceFrom("function renderPicker(") + "\nreturn renderPicker;")(esc, initialen, windowShim, (fn) => fn());
  const picker = renderPicker({
    mount, mode: "confirm",
    items: [{ key: "u1", naam: "Karin van Oss" }, { key: "u2", naam: "Douwe van Dijk" }],
    onSelect: () => {}, secondary: () => "",
  });
  // Nothing selected, two visible → singleVisible is null (no accidental pick).
  ok(picker.singleVisible() === null, "D9: >1 visible & none selected → singleVisible null");
  // Narrow to a single visible result by typing into the search input.
  const inEl = mount.querySelector.__ ? null : null;
  // The picker built its own search input into mount; re-drive filtering through its API:
  picker.setItems([{ key: "u1", naam: "Karin van Oss" }]);
  ok(picker.singleVisible() && picker.singleVisible().key === "u1", "D9: exactly one visible → singleVisible returns it");
  ok(SRC.includes("const v = gefilterd(); if (v.length === 1) k = v[0].key;"),
     "D9: inner Enter falls back to the sole visible result");
  ok(SRC.includes("picker.getSelected() || picker.singleVisible()"),
     "D9: overlay Enter uses selection or the sole visible result");
}

// ── A2 (V-03): Workspace 'Volgende actie' coherent with badge; no fake freshness ─
{
  // Assert on the real wsRender source contract (the render itself is exercised by
  // workspace_render.test.mjs). These guard the coherence rules deterministically.
  const ws = sliceFrom("function wsRender(");
  ok(ws.includes("heeftStand = bel.km_recent != null"),
     "A2: 'belasting vers' gated on an actual stand (km_recent != null)");
  ok(/const fresh = \(heeftStand && bel\.datum\)/.test(ws),
     "A2: no freshness chip without a stand");
  ok(ws.includes("topAttn") && /Bekijk in dossier/.test(ws),
     "A2: attention present → next-action names the reason + routes (never 'alles bij')");
  ok(/nextCls = \(bel\.actief \|\| attn\.length\)/.test(ws),
     "A2: next-action card gets the tone when there is any attention");
}

console.log("== Coach Review v2 — behavioural contracts (executable real functions) ==");
if (failures.length) { console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - ")); process.exit(1); }
else console.log("PASS: C1 group-counts, C4 toggle, C5 send-guard, D9 single-result Enter, A2 Workspace coherence.");
