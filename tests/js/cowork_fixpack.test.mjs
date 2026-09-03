// Executable tests for Cowork Fix Pack v1 logic — B4 (Dossier date cell) + B7 (filter count).
// Slices the REAL dcShort / fbUpdateInfo VERBATIM from pwa/static/app.js and drives them.
//
//   node tests/js/cowork_fixpack.test.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const SRC = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "pwa", "static", "app.js"), "utf8");
function sliceFrom(header) {
  const i = SRC.indexOf(header);
  if (i < 0) throw new Error("not found: " + header);
  const b = SRC.indexOf("{", i);
  let d = 0;
  for (let j = b; j < SRC.length; j++) { if (SRC[j] === "{") d++; else if (SRC[j] === "}") { d--; if (!d) return SRC.slice(i, j + 1); } }
  throw new Error("unbalanced");
}
const sliceLine = (p) => { const i = SRC.indexOf(p); return SRC.slice(i, SRC.indexOf("\n", i)); };

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra ? "  [" + extra + "]" : "")); };

// ── B4: dcShort — date cell never falls back to descriptive text ─────────────
{
  const dcShort = new Function(sliceLine("const _DC_MND = ") + "\n" + sliceFrom("function dcShort(") + "\nreturn dcShort;")();
  ok(dcShort("2026-11-01") === "1 nov", "B4: ISO date → short date", dcShort("2026-11-01"));
  ok(dcShort("Marathon Rotterdam 2026") === "—", "B4: free wedstrijd text → '—' (not the text)", dcShort("Marathon Rotterdam 2026"));
  ok(dcShort("") === "—", "B4: empty → '—'", dcShort(""));
  ok(dcShort(null) === "—", "B4: null → '—'");
}

// ── B7: fbUpdateInfo — filtered visible vs total queue truth ─────────────────
{
  let infoEl = { textContent: "" };
  const $ = () => infoEl;
  const FB = { items: [], gepost: 0 };
  const fbUpdateInfo = new Function("$", "FB", sliceFrom("function fbUpdateInfo(") + "\nreturn fbUpdateInfo;")($, FB);
  // 30 in queue, 5 today posted, no filter (visible === total) → no redundant 'zichtbaar'
  FB.items = Array.from({ length: 30 }, (_, i) => ({ id: i })); FB.gepost = 5;
  fbUpdateInfo(30);
  ok(infoEl.textContent === "30 in de wachtrij · 5 vandaag verstuurd", "B7: unfiltered → total + posted, no noise", infoEl.textContent);
  // filter reduces to 8 visible of 30 → 'X zichtbaar · Y in de wachtrij · Z verstuurd'
  fbUpdateInfo(8);
  ok(/8 zichtbaar · 30 in de wachtrij · 5 vandaag verstuurd/.test(infoEl.textContent),
     "B7: filtered → visible vs total communicated", infoEl.textContent);
  // no hardcoded '/ 30' denominator in the header count (old: `${FB.items.length}<i> / 30</i>`)
  ok(!/<i>\s*\/\s*30<\/i>/.test(SRC), "B7: header count drops the hardcoded '/ 30' denominator");
  ok(/#fb-count.*textContent = String\(FB\.items\.length\)/s.test(
       SRC.slice(SRC.indexOf("function renderTabs"), SRC.indexOf("function renderTabs") + 900)),
     "B7: header count = total queue truth (FB.items.length)");
  // empty inbox
  FB.items = []; fbUpdateInfo();
  ok(/inbox leeg/.test(infoEl.textContent), "B7: empty inbox message", infoEl.textContent);
}

console.log("== Cowork Fix Pack v1 — B4 date-cell + B7 filter-count (executable) ==");
if (failures.length) { console.error("FAIL (" + failures.length + "):\n - " + failures.join("\n - ")); process.exit(1); }
else console.log("PASS: dcShort date-cell sanitised (B4); fbUpdateInfo visible-vs-total contract + no '/30' (B7).");
