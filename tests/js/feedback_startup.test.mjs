// Executable startup state-machine test (Node, real async).
//
// Drives the ACTUAL app.js functions fbEnter/fbRefresh/fbQueueGet/fbLeave +
// fbRenderError/fbMarkStale/fbRenderColdWaiting/fbRenderLoading (sliced verbatim from
// pwa/static/app.js) against a signal-honoring mock fetch and SHORT real deadlines.
// This proves the browser waiting-state always terminates and never blanks a visible
// queue — not a source-string check. Leaf renderers (fbApplyQueue/fbOpen/…) are shimmed
// to record observable DOM/state; the state machine + AbortController deadlines are REAL.
//
//   node tests/js/feedback_startup.test.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const _here = dirname(fileURLToPath(import.meta.url));
const APP = join(_here, "..", "..", "pwa", "static", "app.js");
const SRC = readFileSync(APP, "utf8");

function sliceFn(header) {
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

const REAL = [
  "function fbLeave() {",
  "async function fbQueueGet(refresh, gen) {",
  "function fbRenderError(kind) {",
  "function fbMarkStale(kind) {",
  "function fbRenderLoading() {",
  "function fbRenderColdWaiting() {",
  "async function fbEnter() {",
  "async function fbRefresh() {",
].map(sliceFn).join("\n\n");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Test rig ────────────────────────────────────────────────────────────────
let els, FB, PLAN, logs;

function mkEl() {
  return {
    innerHTML: "", textContent: "", hidden: false, onclick: null, style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, focus() {},
  };
}
function $(sel) { return (els[sel] ||= mkEl()); }
const $$ = () => [];
const ic = (n) => `<i:${n}>`;
const esc = (s) => String(s == null ? "" : s);
const isDesktop = () => true;
const skeleton = (el) => { if (el) el.innerHTML = "SKELETON"; };
const fbLog = (ev, d) => logs.push([ev, d]);
const authHeaders = () => ({});
const toonLogin = () => {};
const fbDraftCleanup = () => {};
const fbUpdateInfo = () => {};
const renderFocusEmpty = () => { $("#fb-focus").innerHTML = "EMPTY"; };
const fbFilterWeg = (items) => (items || []).filter((i) => !FB.sentSet.has(i.id) && !FB.skipSet.has(i.id));
const fbNieuwBalk = () => {};
const renderQueue = () => { $("#fb-queue").innerHTML = FB.items.length ? "ROWS:" + FB.items.map((i) => i.id).join(",") : ""; };
const fbApplyQueue = (items) => { FB.items = fbFilterWeg(items); renderQueue(); };
const fbOpen = (id) => { FB.selId = id; $("#fb-focus").innerHTML = "CASE:" + id; };
const perfShim = { now: () => Date.now() };
const winShim = {};

function mkRes(body) {
  return { status: 200, headers: { get: () => null }, json: async () => body };
}
// Signal-honoring mock: 'hang' never resolves (only abort rejects); 'delay' resolves late;
// 'resolve' resolves now. Abort → AbortError (exactly like real fetch).
function mockFetch(url, opt) {
  const key = url.includes("refresh=1") ? "refresh" : "nonrefresh";
  const plan = PLAN[key] || { mode: "hang" };
  const signal = opt && opt.signal;
  return new Promise((resolve, reject) => {
    let done = false;
    if (signal) signal.addEventListener("abort", () => {
      if (!done) { done = true; const e = new Error("aborted"); e.name = "AbortError"; reject(e); }
    });
    if (plan.mode === "resolve") { done = true; resolve(mkRes(plan.body)); }
    else if (plan.mode === "delay") setTimeout(() => { if (!done) { done = true; resolve(mkRes(plan.body)); } }, plan.delay);
    // 'hang': never resolves on its own
  });
}

// Instantiate the REAL functions sharing one scope, closing over the shims.
const fbAbortEnrichment = () => {};                     // post-queue enrichment niet onderdeel van deze startup-test
const shimNames = ["window", "document", "$", "$$", "ic", "esc", "isDesktop", "skeleton",
  "fbLog", "authHeaders", "toonLogin", "fbDraftCleanup", "fbUpdateInfo", "renderFocusEmpty",
  "fbFilterWeg", "fbNieuwBalk", "renderQueue", "fbApplyQueue", "fbOpen", "fbAbortEnrichment", "fetch",
  "AbortController", "performance", "setTimeout", "clearTimeout", "FB"];
function build(hotMs, refreshMs) {
  winShim.__FB_HOT_MS = hotMs; winShim.__FB_REFRESH_MS = refreshMs;
  const body =
    "const FB_HOT_DEADLINE = window.__FB_HOT_MS || 8000;\n" +
    "const FB_REFRESH_DEADLINE = window.__FB_REFRESH_MS || 90000;\n" +
    REAL + "\nreturn { fbEnter, fbRefresh, fbQueueGet, fbLeave };";
  const fn = new Function(...shimNames, body);
  return fn(winShim, {}, $, $$, ic, esc, isDesktop, skeleton, fbLog, authHeaders, toonLogin,
    fbDraftCleanup, fbUpdateInfo, renderFocusEmpty, fbFilterWeg, fbNieuwBalk, renderQueue,
    fbApplyQueue, fbOpen, fbAbortEnrichment, mockFetch, AbortController, perfShim, setTimeout, clearTimeout, FB);
}

function reset(plan) {
  els = {}; logs = []; PLAN = plan;
  FB = {
    items: [], selId: null, pending: null, pendingInitial: false, loaded: false,
    gepost: 0, groups: [], sentSet: new Set(), skipSet: new Set(), reqGen: 0, _ac: null,
  };
}

const failures = [];
function ok(cond, name) { if (!cond) failures.push(name); }

// ── Scenarios ─────────────────────────────────────────────────────────────
async function s1_never_resolves() {
  reset({ nonrefresh: { mode: "hang" }, refresh: { mode: "hang" } });
  const api = build(120, 200);
  await api.fbEnter();                                   // must terminate (deadline), not hang
  const q = els["#fb-queue"].innerHTML;
  ok(/fb-retry|Opnieuw/.test(q), "S1: terminal retry state shown");
  ok(!/SKELETON/.test(q), "S1: not stuck on skeleton");
}
async function s2_warm_then_refresh_hangs() {
  reset({ nonrefresh: { mode: "resolve", body: { fs: true, items: [{ id: "a" }, { id: "b" }] } },
          refresh: { mode: "hang" } });
  const api = build(120, 150);
  await api.fbEnter();
  ok(FB.items.length === 2, "S2: warm queue visible immediately");
  ok(FB.selId === "a", "S2: first server-ordered item opened");
  await sleep(260);                                      // refresh deadline elapses
  ok(FB.items.length === 2, "S2: warm queue stays usable while refresh hangs");
  ok(/opnieuw/i.test(els["#fb-info"].innerHTML || ""), "S2: subtle stale/retry signal");
}
async function s3_cold_pending_then_refresh() {
  reset({ nonrefresh: { mode: "resolve", body: { fs: true, pending: true, items: [] } },
          refresh: { mode: "delay", delay: 100, body: { fs: true, items: [{ id: "x" }, { id: "y" }] } } });
  const api = build(120, 400);
  await api.fbEnter();
  ok(/SKELETON/.test(els["#fb-queue"].innerHTML), "S3: cold pending shows non-blocking waiting shell");
  await sleep(220);                                      // let the background refresh resolve
  ok(FB.items.length === 2, "S3: fresh queue atomically filled");
  ok(FB.selId === "x", "S3: first server-ordered item opened after cold sweep");
}
async function s4_refresh_timeout_no_blank() {
  reset({ nonrefresh: { mode: "resolve", body: { fs: true, items: [{ id: "a" }, { id: "b" }, { id: "c" }] } },
          refresh: { mode: "hang" } });
  const api = build(120, 150);
  await api.fbEnter();
  const before = FB.items.map((i) => i.id).join(",");
  await sleep(260);
  ok(FB.items.map((i) => i.id).join(",") === before, "S4: visible queue not reset by refresh timeout");
  ok(FB.items.length === 3, "S4: items preserved");
}
async function s5_stale_after_leave() {
  reset({ nonrefresh: { mode: "delay", delay: 120, body: { fs: true, items: [{ id: "a" }] } },
          refresh: { mode: "hang" } });
  const api = build(500, 500);                           // deadline long → only navigation ends it
  const p = api.fbEnter();
  await sleep(30);
  api.fbLeave();                                        // navigate away mid-request
  await p;
  await sleep(160);                                     // let the late response arrive
  ok(FB.items.length === 0, "S5: stale response did not overwrite the current view");
  ok(FB.selId === null, "S5: no auto-open from a stale request");
}

const scenarios = [s1_never_resolves, s2_warm_then_refresh_hangs, s3_cold_pending_then_refresh,
  s4_refresh_timeout_no_blank, s5_stale_after_leave];

for (const s of scenarios) {
  try { await s(); } catch (e) { failures.push(s.name + " threw: " + (e && e.message)); }
}

if (failures.length) {
  console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - "));
  process.exit(1);
} else {
  console.log("PASS: " + scenarios.length + " startup scenarios (termination + no-blank + stale-guard)");
}
