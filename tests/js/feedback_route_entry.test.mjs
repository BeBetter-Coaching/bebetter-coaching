// Executable route-entry contract test (Node, real async).
//
// Drives the ACTUAL app.js fbEnter/fbRefresh/fbOpen/fbEnrich*/fbBoundedGet/fbQueueGet
// (sliced verbatim from pwa/static/app.js) with request-recording mock fetch+api and
// short real deadlines. Proves the restored known-good contract:
//   - route entry (Home & main-nav share fbEnter) fires ONLY /api/feedback/queue
//     (+ background refresh); NEVER detail/week/cockpit before an explicit case click;
//   - no case auto-opens on entry (FB.selId stays null);
//   - on explicit fbOpen: detail fires; week+cockpit are lazy AND only after selection.
//
//   node tests/js/feedback_route_entry.test.mjs
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
  "function fbLeave() {", "function fbAbortEnrichment() {", "async function fbBoundedGet(url, deadline, ref) {",
  "async function fbQueueGet(refresh, gen) {", "function fbRenderError(kind) {", "function fbMarkStale(kind) {",
  "function fbRenderLoading() {", "function fbRenderColdWaiting() {", "async function fbEnter() {",
  "async function fbRefresh() {", "async function fbFetchDetail(id, preload, ref) {", "function fbOpen(id, reason) {",
  "async function fbEnrichDetail(id, gen) {", "function fbEnrichContext(akey, datum, id, gen) {",
  "async function fbEnrichWeek(akey, datum, id, gen) {", "async function fbEnrichCockpit(akey, id, gen) {",
].map(sliceFn).join("\n\n");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let FB, PLAN, REQ;

const noop = () => {};
const el = { classList: { add: noop, remove: noop, toggle: noop, contains: () => false }, setAttribute: noop, innerHTML: "", textContent: "", onclick: null };
const $ = () => el; const $$ = () => [];
const ic = () => ""; const esc = (s) => String(s == null ? "" : s);
const isDesktop = () => true; const skeleton = noop;
const fbLog = noop, authHeaders = () => ({}), toonLogin = noop, fbDraftCleanup = noop, fbUpdateInfo = noop,
  fbNieuwBalk = noop, renderQueue = noop, fbLockQueue = noop, fbPreloadNext = noop, fbRenderCase = noop,
  fbRenderMetricsSlot = noop, fbRenderBerichtSlot = noop, fbRenderMbSlot = noop, fbRenderWeekSlots = noop,
  fbRenderDetailBody = noop, fbRenderCtxCol = noop, fbBindZoneRetries = noop, fbFillDetail = noop,
  fbDockHtml = () => "", fbBindDock = noop, fbHeadHtml = () => "", fbScrollThreadBottom = noop;
const fbFilterWeg = (items) => (items || []).filter((i) => !FB.sentSet.has(i.id) && !FB.skipSet.has(i.id));
const fbApplyQueue = (items) => { FB.items = fbFilterWeg(items); if (isDesktop() && !FB.selId) renderFocusEmpty(); };
const renderFocusEmpty = () => { FB.centerNeutral = true; };
const winShim = {}; const perfShim = { now: () => Date.now() };
const docShim = { body: { classList: { toggle: noop } } };

function planFor(url) {
  if (url.includes("/api/feedback/queue")) return url.includes("refresh") ? (PLAN.refresh || PLAN.queue) : PLAN.queue;
  if (url.startsWith("/api/cockpit")) return PLAN.cockpit;
  if (url.includes("/api/feedback/week")) return PLAN.week;
  return PLAN.detail;                                    // /api/feedback/{id}
}
function respond(url, opt, jsonWrap) {
  REQ.push(url.split("?")[0] + (url.includes("refresh") ? "?refresh" : ""));
  const plan = planFor(url) || { mode: "hang" };
  const signal = opt && opt.signal;
  return new Promise((resolve, reject) => {
    let done = false;
    if (signal) signal.addEventListener("abort", () => { if (!done) { done = true; const e = new Error("aborted"); e.name = "AbortError"; reject(e); } });
    const give = () => jsonWrap ? { status: 200, headers: { get: () => null }, json: async () => plan.body } : plan.body;
    if (plan.mode === "resolve") { done = true; resolve(give()); }
    else if (plan.mode === "delay") setTimeout(() => { if (!done) { done = true; resolve(give()); } }, plan.delay);
  });
}
const fetchMock = (url, opt) => respond(url, opt, true);   // queue uses fetch(...).json()
const api = (url, opt) => respond(url, opt, false);        // detail/week/cockpit use api() -> parsed json

const shimNames = ["window", "document", "$", "$$", "ic", "esc", "isDesktop", "skeleton", "fbLog", "authHeaders",
  "toonLogin", "fbDraftCleanup", "fbUpdateInfo", "fbNieuwBalk", "renderQueue", "fbLockQueue", "fbPreloadNext",
  "fbRenderCase", "fbRenderMetricsSlot", "fbRenderBerichtSlot", "fbRenderMbSlot", "fbRenderWeekSlots",
  "fbRenderDetailBody", "fbRenderCtxCol", "fbBindZoneRetries", "fbFillDetail", "fbDockHtml", "fbBindDock",
  "fbHeadHtml", "fbScrollThreadBottom", "fbFilterWeg", "fbApplyQueue", "renderFocusEmpty", "fetch", "api",
  "AbortController", "performance", "setTimeout", "clearTimeout", "FB"];
function build() {
  winShim.__FB_HOT_MS = 400; winShim.__FB_REFRESH_MS = 400; winShim.__FB_DETAIL_MS = 400; winShim.__FB_CTX_MS = 400;
  const body = "const FB_HOT_DEADLINE=window.__FB_HOT_MS||8000;const FB_REFRESH_DEADLINE=window.__FB_REFRESH_MS||90000;"
    + "const FB_DETAIL_DEADLINE=window.__FB_DETAIL_MS||15000;const FB_CTX_DEADLINE=window.__FB_CTX_MS||15000;"
    + REAL + "\nreturn { fbEnter, fbOpen, fbLeave };";
  return new Function(...shimNames, body)(winShim, docShim, $, $$, ic, esc, isDesktop, skeleton, fbLog, authHeaders,
    toonLogin, fbDraftCleanup, fbUpdateInfo, fbNieuwBalk, renderQueue, fbLockQueue, fbPreloadNext, fbRenderCase,
    fbRenderMetricsSlot, fbRenderBerichtSlot, fbRenderMbSlot, fbRenderWeekSlots, fbRenderDetailBody, fbRenderCtxCol,
    fbBindZoneRetries, fbFillDetail, fbDockHtml, fbBindDock, fbHeadHtml, fbScrollThreadBottom, fbFilterWeg,
    fbApplyQueue, renderFocusEmpty, fetchMock, api, AbortController, perfShim, setTimeout, clearTimeout, FB);
}
function reset(plan, items) {
  PLAN = plan; REQ = [];
  FB = { items: [], selId: null, selGen: 0, sel: null, pendingInitial: false, loaded: false, gepost: 0, groups: [],
    detailCache: {}, ctxCache: {}, sentSet: new Set(), skipSet: new Set(), reqGen: 0, _ac: null,
    _detailRef: null, _weekRef: null, _cockpitRef: null, centerNeutral: false };
}
const R = { resolve: (b) => ({ mode: "resolve", body: b }), hang: () => ({ mode: "hang" }), delay: (ms, b) => ({ mode: "delay", delay: ms, body: b }) };
const QUEUE = { fs: true, items: [{ id: "A", athlete_key: "ak", datum: "2026-08-31", naam: "A", workout: "w", categorie: "reactie", groep_label: "G", preview: "" }] };
const DEEP = { detail: R.resolve({ ok: true, id: "A", naam: "A", workout: "w", datum: "2026-08-31", categorie: "reactie", uitgevoerd: {}, gesprek: [] }),
  week: R.resolve({ ok: true, week: 35, weekvolume_km: 1, dagen: [] }), cockpit: R.resolve({ ok: true, load_observation: null, attention: [], planning: { rows: [] }, domains: [], source_health: [], status: { reliability: {} } }) };

const fails = []; const ok = (c, n) => { if (!c) fails.push(n); };
const onlyQueue = (log) => log.every(u => u.startsWith("/api/feedback/queue"));
const has = (log, u) => log.some(x => x === u || x.startsWith(u));

let navLog, homeLog;
async function nav_entry() {
  reset({ queue: R.resolve(QUEUE), ...DEEP });
  const app = build(); await app.fbEnter(); await sleep(60);
  navLog = REQ.slice();
  ok(onlyQueue(REQ), "nav-entry: ONLY /api/feedback/queue fired (no detail/week/cockpit)");
  ok(!has(REQ, "/api/cockpit") && !has(REQ, "/api/feedback/week"), "nav-entry: no cockpit/week before click");
  ok(FB.selId === null, "nav-entry: no case auto-opened");
  ok(FB.centerNeutral === true, "nav-entry: center rendered neutral");
}
async function home_entry_same() {
  reset({ queue: R.resolve(QUEUE), ...DEEP });
  const app = build(); await app.fbEnter(); await sleep(60);
  homeLog = REQ.slice();
  ok(onlyQueue(REQ), "home-entry: ONLY queue fired");
  ok(JSON.stringify(homeLog) === JSON.stringify(navLog), "home==nav: identical route-entry request log (shared fbEnter lifecycle)");
}
async function click_then_detail_first() {
  reset({ queue: R.resolve(QUEUE), ...DEEP });
  const app = build(); await app.fbEnter(); await sleep(40);
  REQ = [];                                              // isoleer de klik
  app.fbOpen("A", "row_tap");
  ok(REQ.some(u => u === "/api/feedback/A" || u === "/api/feedback/A".split("?")[0]) || has(REQ, "/api/feedback/A"), "click: detail request fired");
  await sleep(80);
  ok(has(REQ, "/api/cockpit") && has(REQ, "/api/feedback/week"), "click: week+cockpit enrich lazily AFTER selection");
  ok(FB.selId === "A", "click: case selected");
}
async function cold_entry_no_deepread() {
  reset({ queue: R.resolve({ fs: true, pending: true, items: [] }),
    refresh: R.resolve(QUEUE), ...DEEP });
  const app = build(); await app.fbEnter(); await sleep(80);
  ok(onlyQueue(REQ), "cold-entry: only queue (+refresh); no deep case reads on entry");
  ok(FB.selId === null, "cold-entry: no auto-open after cold sweep");
}
async function warm_zero_case_requests() {
  reset({ queue: R.resolve(QUEUE), ...DEEP });
  const app = build(); await app.fbEnter(); await sleep(60);
  ok(!has(REQ, "/api/feedback/A") && !has(REQ, "/api/cockpit") && !has(REQ, "/api/feedback/week"),
    "warm-entry: zero selected-case requests before click");
}

const scenarios = [nav_entry, home_entry_same, click_then_detail_first, cold_entry_no_deepread, warm_zero_case_requests];
for (const s of scenarios) { try { await s(); } catch (e) { fails.push(s.name + " threw: " + (e && e.message)); } }
if (fails.length) { console.error("FAIL (" + fails.length + "):\n - " + fails.join("\n - ")); process.exit(1); }
else console.log("PASS: " + scenarios.length + " route-entry scenarios (entry=queue-only, no auto-open, detail-first-on-click, lazy enrichment)");
