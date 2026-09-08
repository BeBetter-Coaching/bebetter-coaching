// Vier gerichte herstellen — EXECUTEERBARE tests.
//
//   node tests/js/cockpit_context_fixes.test.mjs
//
// Snijdt de ECHTE functies verbatim uit pwa/static/app.js en draait ze:
//   H  renderFeedbackStrip — een ONBEKENDE stand mag nooit als 'afgerond' lezen.
//   C  _shownAthleteKey    — de zijbalk houdt de zichtbaar geopende atleet vast.
//   D  svModus/svActieLabel — schema-verloop kiest Verlengen waar dat de actie is.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = readFileSync(join(ROOT, "pwa", "static", "app.js"), "utf8");

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

const failures = [];
const ok = (c, n, extra) => { if (!c) failures.push(n + (extra !== undefined ? "  [" + extra + "]" : "")); };

class El {
  constructor() { this._html = ""; this._cls = new Set(); this.onclick = null; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v == null ? "" : v); }
  get textContent() { return this._html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim(); }
  get classList() {
    const s = this._cls;
    return { add: c => s.add(c), remove: c => s.delete(c), contains: c => s.has(c),
             toggle: (c, on) => { if (on) s.add(c); else s.delete(c); } };
  }
}

console.log("== Cockpit/context-herstellen: onbekend≠afgerond, athlete-context, verlengen ==\n");

// ══ H — de feedbacktegel bij een NIET-berekende stand ════════════════════════
{
  const strip = new El();
  const mod = new Function("$", "ic", "openModuleFromNav", "homeFbDelta",
    sliceFrom("function renderFeedbackStrip(") + "\nreturn { renderFeedbackStrip };"
  )(() => strip, () => "", () => {}, { wachten: 0, gepost: 0 });

  // 1. Payload die de tegel HELEMAAL niet draagt (koud proces / onvolledige sweep).
  mod.renderFeedbackStrip(undefined, true);
  ok(/bijwerken/i.test(strip.textContent), "H1 ontbrekende tegel = 'bijwerken…'", strip.textContent);
  ok(!/Alles beoordeeld/.test(strip.textContent), "H2 en claimt NIET 'alles beoordeeld'");
  ok(!/100%/.test(strip.textContent), "H3 en toont geen 100%");
  ok(!strip.classList.contains("done"), "H4 en krijgt geen 'done'-opmaak");

  // 2. Leeg object (pending-payload zonder feedback-blok) → zelfde eerlijke uitkomst.
  mod.renderFeedbackStrip({}, true);
  ok(/bijwerken/i.test(strip.textContent), "H5 leeg feedbackblok = onbekend", strip.textContent);

  // 3. Expliciet onbekend (stale open-set) blijft werken zoals voorheen.
  mod.renderFeedbackStrip({ stale: true, wachten: null }, true);
  ok(/bijwerken/i.test(strip.textContent), "H6 stale+geen telling = onbekend");

  // 4. Een ECHTE stand met nul wachtenden MAG wél 'afgerond' zeggen (geen overcorrectie).
  mod.renderFeedbackStrip({ wachten: 0, gepost: 12, pct: 100 }, true);
  ok(/Alles beoordeeld/.test(strip.textContent), "H7 echte nul = 'Alles beoordeeld'", strip.textContent);
  ok(strip.classList.contains("done"), "H8 en krijgt wel 'done'-opmaak");

  // 5. Echte stand met wachtenden.
  mod.renderFeedbackStrip({ wachten: 5, gepost: 3, pct: 38 }, true);
  ok(/5 wachten op feedback/.test(strip.textContent), "H9 telling wordt gewoon getoond", strip.textContent);
  ok(!strip.classList.contains("done"), "H10 en is niet 'done'");

  // 6. Nul wachtenden maar gepost onbekend: telling bestaat → geen 'bijwerken'.
  mod.renderFeedbackStrip({ wachten: 0, gepost: 0, pct: 100 }, true);
  ok(!/bijwerken/i.test(strip.textContent), "H11 een bestaande telling van 0 is geen onbekend");
}

// ══ C — athlete-context via de zijbalk ══════════════════════════════════════
{
  const maak = ({ wsSel = "", dcSel = "", sbState = null, dossierSel = null }) =>
    new Function("wsSel", "dcSel", "sbState", "dossierSel",
      sliceFrom("function _shownAthleteKey(") + "\nreturn _shownAthleteKey;"
    )(wsSel, dcSel, sbState, dossierSel);

  // De regressie: `dossierSel` IS de atleet-id (string), geen object.
  ok(maak({ dossierSel: "K1" })("atleten") === "K1",
     "C1 Atleten onthoudt de zichtbaar geopende atleet", maak({ dossierSel: "K1" })("atleten"));
  ok(maak({ dossierSel: null })("atleten") === "", "C2 geen selectie = geen context");
  ok(maak({ dossierSel: "" })("atleten") === "", "C3 lege selectie = geen context");
  // Een object mag geen id opleveren (dat was juist de foute aanname).
  ok(maak({ dossierSel: { key: "K9" } })("atleten") === "",
     "C4 een object is geen atleet-id", maak({ dossierSel: { key: "K9" } })("atleten"));

  // De andere views blijven werken zoals ze waren.
  ok(maak({ wsSel: "K2" })("workspace") === "K2", "C5 Workspace ongewijzigd");
  ok(maak({ dcSel: "K3" })("dossier") === "K3", "C6 Dossier ongewijzigd");
  ok(maak({ sbState: { key: "K4" } })("schema") === "K4", "C7 Schema ongewijzigd (object mét key)");
  ok(maak({})("home") === "", "C8 een globale view draagt geen context");
}

// ══ D — schema-verloop kiest de passende schema-actie ═══════════════════════
{
  const mod = new Function(
    sliceFrom("function svModus(") + "\n" + sliceFrom("function svActieLabel(") +
    "\nreturn { svModus, svActieLabel };")();

  for (const st of ["verlopen", "bijna", "loopt"]) {
    ok(mod.svModus({ status: st }) === "verlengen",
       `D1 '${st}' heeft een bestaand blok → verlengen`, mod.svModus({ status: st }));
    ok(mod.svActieLabel({ status: st }) === "Schema verlengen", `D2 '${st}' benoemt dat ook`);
  }
  ok(mod.svModus({ status: "geen" }) === "nieuw", "D3 'geen schema' → nieuw");
  ok(mod.svActieLabel({ status: "geen" }) === "Schema opzetten", "D4 en benoemt dat ook");
  // Onbekende status: een bestaand blok aannemen is veiliger dan er naast bouwen.
  ok(mod.svModus({ status: "" }) === "verlengen", "D5 onbekende status valt naar verlengen");
}

if (failures.length) {
  console.error("cockpit_context_fixes: " + failures.length + " CHECK(S) FAILED\n");
  failures.forEach(f => console.error("  ✗ " + f));
  process.exit(1);
}
console.log("cockpit_context_fixes: all checks passed");
