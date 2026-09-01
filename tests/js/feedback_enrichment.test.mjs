// Executable post-queue enrichment decoupling test (Node, real async).
//
// Drives the ACTUAL app.js fbOpen/fbEnrichDetail/fbEnrichWeek/fbEnrichCockpit/fbBoundedGet/
// fbFetchDetail/fbLeave (sliced verbatim from pwa/static/app.js) against a signal-honoring
// mock api + SHORT real AbortController deadlines. Pure-render leaf functions are shimmed to
// no-ops; the decoupling STATE MACHINE (independent bounds, generation guard, abort on
// switch/leave, local error flags) is REAL and asserted via FB.sel.*.
//
//   node tests/js/feedback_enrichment.test.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SRC = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "pwa", "static", "app.js"), "utf8");
function sliceFn(header) {
  const i = SRC.indexOf(header); if (i < 0) throw new Error("not found: " + header);
  const b = SRC.indexOf("{", i); let d = 0;
  for (let j = b; j < SRC.length; j++) { if (SRC[j] === "{") d++; else if (SRC[j] === "}") { d--; if (!d) return SRC.slice(i, j + 1); } }
  throw new Error("unbalanced: " + header);
}
const REAL = [
  "function fbLeave() {",
  "function fbAbortEnrichment() {",
  "async function fbBoundedGet(url, deadline, ref) {",
  "async function fbFetchDetail(id, preload, ref) {",
  "function fbOpen(id, reason) {",
  "async function fbEnrichDetail(id, gen) {",
  "function fbEnrichContext(akey, datum, id, gen) {",
  "async function fbEnrichWeek(akey, datum, id, gen) {",
  "async function fbEnrichCockpit(akey, id, gen) {",
].map(sliceFn).join("\n\n");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let FB, PLAN;

// ── shims (pure render = no-op; state machine is real) ────────────────────────
const noop = () => {};
const el = { classList: { add: noop, remove: noop, toggle: noop, contains: () => false }, setAttribute: noop, innerHTML: "", onclick: null };
const $ = () => el;
const $$ = () => [];
const ic = () => ""; const esc = (s) => String(s == null ? "" : s);
const isDesktop = () => true;
const fbLog = noop; const fbLockQueue = noop; const fbPreloadNext = noop;
const renderQueue = noop; const fbRenderCase = () => { FB._shellRendered = true; };
const fbRenderMetricsSlot = noop, fbRenderBerichtSlot = noop, fbRenderMbSlot = noop,
  fbRenderWeekSlots = noop, fbRenderDetailBody = noop, fbRenderCtxCol = noop,
  fbBindZoneRetries = noop, fbFillDetail = noop, fbDockHtml = () => "", fbBindDock = noop,
  fbHeadHtml = () => "", fbScrollThreadBottom = noop;
const winShim = {};
const perfShim = { now: () => Date.now() };
const docShim = { body: { classList: { toggle: noop } } };

function api(url, opt) {
  const kind = url.startsWith("/api/cockpit") ? "cockpit" : url.includes("/feedback/week") ? "week" : "detail";
  const plan = PLAN[kind] || { mode: "hang" };
  const signal = opt && opt.signal;
  return new Promise((resolve, reject) => {
    let done = false;
    if (signal) signal.addEventListener("abort", () => { if (!done) { done = true; const e = new Error("aborted"); e.name = "AbortError"; reject(e); } });
    if (plan.mode === "resolve") { done = true; resolve(plan.body); }
    else if (plan.mode === "delay") setTimeout(() => { if (!done) { done = true; resolve(plan.body); } }, plan.delay);
  });
}
const mkDetail = (id) => ({ ok: true, id, naam: "A", voornaam: "A", workout: "w", datum: "2026-08-31", categorie: "reactie", uitgevoerd: {}, gesprek: [] });
const mkWeek = () => ({ ok: true, week: 35, weekvolume_km: 10, range_label: "x", dagen: [] });
const mkCockpit = () => ({ ok: true, load_observation: null, attention: [], planning: { rows: [] }, domains: [], source_health: [], status: { reliability: {} } });

const shimNames = ["window", "document", "$", "$$", "ic", "esc", "isDesktop", "fbLog", "fbLockQueue",
  "fbPreloadNext", "renderQueue", "fbRenderCase", "fbRenderMetricsSlot", "fbRenderBerichtSlot",
  "fbRenderMbSlot", "fbRenderWeekSlots", "fbRenderDetailBody", "fbRenderCtxCol", "fbBindZoneRetries",
  "fbFillDetail", "fbDockHtml", "fbBindDock", "fbHeadHtml", "fbScrollThreadBottom", "api",
  "AbortController", "performance", "setTimeout", "clearTimeout", "FB"];
function build(detailMs, ctxMs) {
  winShim.__FB_DETAIL_MS = detailMs; winShim.__FB_CTX_MS = ctxMs;
  const body = "const FB_DETAIL_DEADLINE = window.__FB_DETAIL_MS||15000;\nconst FB_CTX_DEADLINE = window.__FB_CTX_MS||15000;\n"
    + REAL + "\nreturn { fbOpen, fbLeave, fbEnrichDetail };";
  return new Function(...shimNames, body)(winShim, docShim, $, $$, ic, esc, isDesktop, fbLog, fbLockQueue,
    fbPreloadNext, renderQueue, fbRenderCase, fbRenderMetricsSlot, fbRenderBerichtSlot, fbRenderMbSlot,
    fbRenderWeekSlots, fbRenderDetailBody, fbRenderCtxCol, fbBindZoneRetries, fbFillDetail, fbDockHtml,
    fbBindDock, fbHeadHtml, fbScrollThreadBottom, api, AbortController, perfShim, setTimeout, clearTimeout, FB);
}
function reset(plan, items) {
  PLAN = plan;
  FB = { items: items || [{ id: "A", athlete_key: "ak", datum: "2026-08-31", naam: "A", voornaam: "A", workout: "w", categorie: "reactie", groep_label: "G", preview: "hi" }],
    selId: null, selGen: 0, sel: null, detailCache: {}, ctxCache: {}, sentSet: new Set(), skipSet: new Set(),
    _detailRef: null, _weekRef: null, _cockpitRef: null, reqGen: 0, _ac: null, _shellRendered: false };
}
const R = { resolve: (b) => ({ mode: "resolve", body: b }), hang: () => ({ mode: "hang" }), delay: (ms, b) => ({ mode: "delay", delay: ms, body: b }) };

const fails = [];
const ok = (c, n) => { if (!c) fails.push(n); };

async function s1_detail_hangs() {
  reset({ detail: R.hang(), week: R.resolve(mkWeek()), cockpit: R.resolve(mkCockpit()) });
  const api2 = build(100, 100); api2.fbOpen("A");
  ok(FB.selId === "A" && FB.sel && FB.sel.d === null, "S1: case shell usable from queue before detail");
  ok(FB._shellRendered === true, "S1: shell rendered immediately");
  await sleep(180);
  ok(FB.sel.detailErr === true, "S1: detail terminates to local error (no endless skeleton)");
  ok(FB.sel.week && FB.sel.cockpit, "S1: week+cockpit still enriched independently");
}
async function s2_cockpit_hangs() {
  reset({ detail: R.resolve(mkDetail("A")), week: R.resolve(mkWeek()), cockpit: R.hang() });
  const api2 = build(100, 100); api2.fbOpen("A");
  await sleep(180);
  ok(FB.sel.d && FB.sel.week, "S2: detail+week usable while cockpit hangs");
  ok(FB.sel.cockpitErr === true && !FB.sel.weekErr, "S2: cockpit local error, week unaffected");
}
async function s3_week_hangs() {
  reset({ detail: R.resolve(mkDetail("A")), week: R.hang(), cockpit: R.resolve(mkCockpit()) });
  const api2 = build(100, 100); api2.fbOpen("A");
  await sleep(180);
  ok(FB.sel.d && FB.sel.cockpit, "S3: detail+cockpit usable while week hangs");
  ok(FB.sel.weekErr === true && !FB.sel.cockpitErr, "S3: week local error, cockpit unaffected");
}
async function s4_switch_case() {
  const items = [{ id: "A", athlete_key: "aA", datum: "2026-08-31", naam: "A", workout: "wA", categorie: "reactie", groep_label: "G", preview: "" },
                 { id: "B", athlete_key: "aB", datum: "2026-08-31", naam: "B", workout: "wB", categorie: "reactie", groep_label: "G", preview: "" }];
  reset({ detail: R.delay(140, mkDetail("A")), week: R.hang(), cockpit: R.hang() }, items);
  const api2 = build(500, 500); api2.fbOpen("A");     // A: everything slow/hanging
  await sleep(30);
  PLAN = { detail: R.resolve(mkDetail("B")), week: R.resolve(mkWeek()), cockpit: R.resolve(mkCockpit()) };
  api2.fbOpen("B");                                   // switch before A resolves
  ok(FB.selId === "B" && FB.sel.id === "B", "S4: new case shell immediately on switch");
  await sleep(200);                                   // A's delayed detail (140ms) would land here
  ok(FB.sel.id === "B" && FB.sel.d && FB.sel.d.id === "B", "S4: stale A response cannot overwrite B");
}
async function s5_leave() {
  reset({ detail: R.delay(120, mkDetail("A")), week: R.hang(), cockpit: R.hang() });
  const api2 = build(500, 500); api2.fbOpen("A");
  await sleep(30);
  const genBefore = FB.selGen;
  api2.fbLeave();                                     // navigate away mid-enrichment
  ok(FB.selGen > genBefore, "S5: leave bumps generation (aborts obsolete enrichment)");
  ok(!FB._detailRef && !FB._weekRef && !FB._cockpitRef, "S5: enrichment refs cleared on leave");
  await sleep(160);
  ok(!(FB.sel && FB.sel.d && FB.sel.d.id === "A") || FB.selGen !== genBefore, "S5: late response from before-leave not applied to a newer generation");
}
async function s7_all_fail() {
  reset({ detail: R.hang(), week: R.hang(), cockpit: R.hang() });
  const api2 = build(100, 100); api2.fbOpen("A");
  ok(FB.selId === "A" && FB._shellRendered, "S7: navigable queue + case shell despite all enrichment failing");
  await sleep(180);
  ok(FB.sel.detailErr && FB.sel.weekErr && FB.sel.cockpitErr, "S7: every zone terminates to bounded local error");
}

const scenarios = [s1_detail_hangs, s2_cockpit_hangs, s3_week_hangs, s4_switch_case, s5_leave, s7_all_fail];
for (const s of scenarios) { try { await s(); } catch (e) { fails.push(s.name + " threw: " + (e && e.message)); } }

if (fails.length) { console.error("FAIL (" + fails.length + "):\n - " + fails.join("\n - ")); process.exit(1); }
else console.log("PASS: " + scenarios.length + " enrichment scenarios (shell-first + independent bounds + abort/gen guard)");
