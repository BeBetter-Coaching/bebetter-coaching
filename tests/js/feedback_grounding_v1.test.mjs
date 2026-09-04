// Executable REAL-function tests for Feedback Grounding & Masterbrein Correctness v1 (P0 UI).
// Slices production functions VERBATIM from pwa/static/app.js. Covers:
//   P0 raw machine value — a boolean never reaches coach text (afwijking.report / attention why)
//   P0 context readiness — LOADING is 'Context laden…', never 'Geen bijzondere signalen'
//   P0 generate gating — #fb-gen disabled while context pending, enabled on terminal state
//
//   node tests/js/feedback_grounding_v1.test.mjs
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
const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };
const mkEl = () => ({ innerHTML: "", disabled: false, dataset: {}, _aria: {},
  setAttribute(k, v) { this._aria[k] = v; }, removeAttribute() {} });

// ── P0: raw machine value never reaches coach-facing Masterbrein text ──────────
{
  const fbMasterbreinBullets = new Function("esc", "ic",
    sliceFrom("function fbMasterbreinBullets(") + "\nreturn fbMasterbreinBullets;")(esc, ic);
  // attention.why is a boolean (the audit's leak shape); afwijking.report is the true boolean flag.
  const cockpit = { load_observation: null, attention: [{ kind: "complaint", title: "Knieklacht terug", why: true }] };
  const d = { afwijking: { relevance: "clear", report: true, pct: 15.2 } };
  const html = fbMasterbreinBullets(d, cockpit);
  ok(!/\btrue\b/i.test(html), "P0: no literal 'true' in Masterbrein", html);
  ok(/Knieklacht terug/.test(html), "P0: attention title still shown");
  ok(!/Knieklacht terug\s*—/.test(html), "P0: boolean 'why' suppressed (no ' — true')", html);
  ok(/Afstand \+15% t\.o\.v\. gepland/.test(html), "P0: deviation rendered as human text from pct (not the boolean flag)", html);
  // genuinely empty → honest empty state
  ok(/Geen bijzondere signalen/.test(fbMasterbreinBullets({ afwijking: {} }, { attention: [], load_observation: null })),
     "known-empty → 'Geen bijzondere signalen'");
}

// ── P0: readiness — LOADING vs KNOWN_EMPTY vs ERROR, and Generate gating ───────
{
  const REAL = sliceFrom("function fbMasterbreinBullets(") + "\n"
    + sliceFrom("function fbRenderMbSlot(") + "\n"
    + sliceFrom("function fbSyncGen(") + "\nreturn { fbRenderMbSlot, fbSyncGen };";
  const mb = mkEl(), gen = mkEl();
  const els = { "#fb-mb": mb, "#fb-gen": gen };
  const $ = (sel) => els[sel] || null;
  const FB = { sel: { cockpit: null, cockpitErr: false, d: {} } };
  const melding = () => {};
  const app = new Function("$", "esc", "ic", "FB", "melding", REAL)($, esc, ic, FB, melding);

  // LOADING (cockpit null, no error)
  FB.sel.cockpit = null; FB.sel.cockpitErr = false;
  app.fbRenderMbSlot();
  ok(/Context laden…/.test(mb.innerHTML), "LOADING → 'Context laden…' in Masterbrein", mb.innerHTML);
  ok(!/Geen bijzondere signalen/.test(mb.innerHTML), "LOADING is NOT 'Geen bijzondere signalen'");
  ok(gen.disabled === true, "LOADING → Generate disabled");
  ok(/Context laden…/.test(gen.innerHTML), "LOADING → Generate shows 'Context laden…'");

  // KNOWN_EMPTY (cockpit loaded, no signals)
  FB.sel.cockpit = { attention: [], load_observation: null }; FB.sel.cockpitErr = false;
  app.fbRenderMbSlot();
  ok(/Geen bijzondere signalen/.test(mb.innerHTML), "KNOWN_EMPTY → 'Geen bijzondere signalen'");
  ok(gen.disabled === false, "READY → Generate enabled");
  ok(/Genereer/.test(gen.innerHTML), "READY → Generate label restored");

  // ERROR (terminal) → enabled, honest message
  FB.sel.cockpit = null; FB.sel.cockpitErr = true;
  app.fbRenderMbSlot();
  ok(/niet beschikbaar/.test(mb.innerHTML), "ERROR → honest unavailable message");
  ok(gen.disabled === false, "ERROR is terminal → Generate enabled");

  // Busy in-flight state is not overwritten by a sync
  gen.dataset.busy = "1"; gen.disabled = true; gen.innerHTML = "AI schrijft…";
  app.fbSyncGen();
  ok(gen.innerHTML === "AI schrijft…", "in-flight (busy) state preserved by fbSyncGen");
}

// ── Source contract: fbGen guards + gating wired ──────────────────────────────
{
  ok(SRC.includes("if (FB.sel && !FB.sel.cockpit && !FB.sel.cockpitErr) { melding("),
     "fbGen refuses to generate while context is loading (also blocks the keyboard shortcut)");
  ok(/function fbSyncGen\(/.test(SRC), "fbSyncGen exists");
  ok(SRC.includes("fbSyncGen();"), "fbSyncGen is called (from fbRenderMbSlot)");
  // P1: 'zone uitgevoerd' expliciet gelabeld als het GEMIDDELDE over de hele training
  ok(SRC.includes("gem. hele training"), "executed zone labelled as whole-session average (not 'in target')");
  // no-akey → terminale staat (geen eeuwige 'Context laden…' die generatie blokkeert)
  ok(SRC.includes("if (!akey) {") && SRC.includes("FB.sel.cockpitErr = true"),
     "no linked athlete → context marked terminal so Generate is not blocked forever");
}

console.log("== Feedback Grounding v1 — P0 UI (raw value, readiness, generate gating) ==");
if (failures.length) { console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - ")); process.exit(1); }
else console.log("PASS: no raw boolean in MB; LOADING≠empty; Generate gated on terminal context.");
