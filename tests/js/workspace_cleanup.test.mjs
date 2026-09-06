// Executable regressietests voor de Athlete Workspace targeted cleanup.
//
//   node tests/js/workspace_cleanup.test.mjs
//
// Slicet de ECHTE functies VERBATIM uit pwa/static/app.js en draait ze tegen een minimale
// DOM-shim. Bewijst:
//   T1  bekende belasting uit de canonieke AthleteState eindigt NIET als UNKNOWN
//   T2  echte UNKNOWN wordt nooit 'RUSTIG / alles bij'
//   T3  actuele Dossier-onderbreking verschijnt in de Workspace-context
//   T4  het klachtsignaal draagt lichaamsdeel + status + bron/datum
//   T5  het trainingsblok onderscheidt gedaan / half / gemist / gepland
//   T6  'Schema openen' landt niet in een blanco 'Nieuw'
//   T7  een aflopend schema routeert naar de bestaande Verlengen-flow
//   T8  de dossier-deeplink draagt het EXACTE event-id
//   T9  primair signaal en primaire actie horen bij elkaar
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

// ── Minimale DOM-shim ────────────────────────────────────────────────────────
class El {
  constructor(tag) {
    this.tag = tag || "div"; this.dataset = {}; this.children = []; this.parent = null;
    this._html = ""; this.textContent = ""; this.className = ""; this.id = "";
    const self = this;
    this.classList = {
      add: c => { self.className = (self.className + " " + c).trim(); },
      remove: c => { self.className = self.className.split(/\s+/).filter(x => x && x !== c).join(" "); },
      contains: c => self.className.split(/\s+/).includes(c),
      toggle: () => {},
    };
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  get isConnected() { return true; }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  scrollIntoView() { this._scrolled = true; }
}
let byId = {};
const $ = sel => byId[String(sel).replace(/^#/, "")] || null;
const $$ = () => [];
const esc = s => String(s == null ? "" : s);
const ic = n => `<i:${n}>`;
const nlNum = x => String(x).replace(".", ",");
const documentShim = { querySelector: () => byId._chip || null, createElement: t => new El(t) };

// ── Gedeelde slices ──────────────────────────────────────────────────────────
const HELPERS = [
  sliceFrom("function wsActieLead("),
  sliceFrom("function wsSchemaVerloopt("),
  sliceFrom("function wsActieBtn("),
  sliceFrom("function wsLine("),
  sliceFrom("function wsVulLoadContext("),
  sliceFrom("function wsVulContext("),
  sliceFrom("function wsHefOnbekendOp("),
  sliceFrom("function wsKoppelEvent("),
  sliceFrom("function prioSessiesHtml("),
].join("\n\n");

const app = new Function("$", "$$", "esc", "ic", "nlNum", "document",
  HELPERS + "\nreturn { wsActieLead, wsSchemaVerloopt, wsActieBtn, wsVulLoadContext, wsVulContext," +
  " wsHefOnbekendOp, wsKoppelEvent, prioSessiesHtml };"
)($, $$, esc, ic, nlNum, documentShim);

// ══ T1 — bekende belasting mag niet als UNKNOWN eindigen ═════════════════════
{
  byId = { "ws-load-ctx": new El("div"), "ws-next-unknown": new El("p"), _chip: null };
  const slot = byId["ws-load-ctx"];
  slot.innerHTML = `<p class="ws-calm">Geen belastingstand bekend.</p>`;
  app.wsVulLoadContext({
    status: { insufficient: false },
    load_context: { known: true, km_per_week: 33.4, runs_per_week: 4.0, trend: "opbouwend", stale: false },
  });
  ok(!slot.innerHTML.includes("Geen belastingstand bekend"),
     "T1.1 UNKNOWN-zin verdwijnt zodra de canonieke state de belasting kent", slot.innerHTML.slice(0, 60));
  ok(slot.innerHTML.includes("33,4") && slot.innerHTML.includes("km/week"),
     "T1.2 km/week uit het dossier wordt getoond", slot.innerHTML.slice(0, 120));
  ok(slot.innerHTML.includes("4") && slot.innerHTML.includes("p/w"), "T1.3 runs/week wordt getoond");
  ok(slot.innerHTML.includes("opbouwend"), "T1.4 belastingstrend wordt getoond");
  ok(/geen actueel belastingssignaal/i.test(slot.innerHTML),
     "T1.5 eerlijk gelabeld: dossierbelasting, geen rolling-7 signaal");

  // ECHT onbekend → de exacte LOCK-zin blijft staan.
  byId = { "ws-load-ctx": new El("div") };
  byId["ws-load-ctx"].innerHTML = `<p class="ws-calm">Geen belastingstand bekend.</p>`;
  app.wsVulLoadContext({ load_context: { known: false } });
  ok(byId["ws-load-ctx"].innerHTML.includes("Geen belastingstand bekend."),
     "T1.6 echt onbekend → exacte LOCK-zin blijft");
}

// ══ T2 — UNKNOWN wordt nooit RUSTIG / alles bij ══════════════════════════════
{
  const render = sliceFrom("function wsRender(");
  ok(render.includes('const wsStaat = attn.length ? "aandacht" : (belStand ? "rustig" : "onbekend")'),
     "T2.1 drie expliciete standen (geen impliciete rust)");
  ok(render.includes('dsChip("onbekend", "is-unknown")'), "T2.2 eigen onbekend-badge");
  ok(/Te weinig om op te oordelen/.test(render), "T2.3 expliciete insufficient-data-tekst");
  // 'alles bij' mag ALLEEN in de rustig-tak staan
  const i = render.indexOf("Geen directe actie — alles bij.");
  ok(i > -1 && render.lastIndexOf('wsStaat === "rustig"', i) > -1,
     "T2.4 'alles bij' zit uitsluitend achter de rustig-stand");

  // Opwaarderen mag alleen als een autoritatieve bron dat draagt.
  const lead = new El("p"); lead.outerHTML = "";
  byId = { "ws-next-unknown": lead, _chip: null };
  app.wsHefOnbekendOp({ status: { insufficient: true } });
  ok(byId["ws-next-unknown"] === lead, "T2.5 AthleteState 'insufficient' blijft onbekend");
  const hef = sliceFrom("function wsHefOnbekendOp(");
  ok(hef.includes("if (st.insufficient) return"), "T2.6 harde guard op insufficient");
  ok(sliceFrom("function wsVulLoadContext(").includes("wsHefOnbekendOp(r)"),
     "T2.7 opwaardering hangt aan BEKENDE load, niet aan afwezigheid");
}

// ══ T3/T4 — actuele Dossier-context in de Workspace ══════════════════════════
{
  const box = new El("div"); byId = { "ws-ctx": box };
  app.wsVulContext({
    load_context: { interruption: { tekst: "circa 3 weken minder/geen training", status: "ACTIVE", wanneer: "2026-08-30" } },
    attention: [
      { kind: "complaint", id: "ev-9", title: "Klacht: scheen — actief", why: "last van mijn scheen na de lange duurloop · 31-08" },
      { kind: "source_gap", id: "srcgap.training_log", title: "Bron ontbreekt" },
    ],
  });
  ok(/Trainingsonderbreking/.test(box.innerHTML), "T3.1 lopende onderbreking wordt zichtbaar");
  ok(box.innerHTML.includes("circa 3 weken"), "T3.2 met de concrete inhoud");
  ok(box.innerHTML.includes("2026-08-30"), "T3.3 met datum/bron");
  ok(box.innerHTML.includes("scheen"), "T4.1 klacht noemt het lichaamsdeel");
  ok(/actief/.test(box.innerHTML), "T4.2 klacht noemt de status");
  ok(box.innerHTML.includes("31-08"), "T4.3 klacht draagt de bron-datum");
  ok(!/Bron ontbreekt/.test(box.innerHTML), "T4.4 alleen relevante context, geen dossier-dump");

  const leeg = new El("div"); byId = { "ws-ctx": leeg };
  app.wsVulContext({ attention: [] });
  ok(leeg.innerHTML === "", "T3.4 geen context → geen lege kaart-ruimte");
}

// ══ T5 — trainingsblok onderscheidt de vier statussen ════════════════════════
{
  const html = app.prioSessiesHtml([
    { datum: "2026-09-01", type: "Duurloop", status: "gedaan", km_planned: 12, km_actual: 12 },
    { datum: "2026-09-02", type: "Interval", status: "half", km_planned: 10, km_actual: 4 },
    { datum: "2026-09-03", type: "Herstel", status: "gemist", km_planned: 8, km_actual: 0 },
    { datum: "2026-09-08", type: "Lange duurloop", status: "gepland", km_planned: 18, km_actual: 0 },
  ]);
  for (const st of ["gedaan", "half", "gemist", "gepland"]) {
    ok(html.includes(`pd-s-st ${st}`), `T5.1 status '${st}' heeft een eigen pill`, st);
  }
  ok(html.includes(">gepland<"), "T5.2 'gepland' krijgt een eigen label (geen 'gemist')");
  const css = readFileSync(join(ROOT, "pwa", "static", "styles.css"), "utf8");
  ok(/\.pd-s-st\.gepland\{/.test(css), "T5.3 'gepland' is visueel onderscheiden");
  ok(sliceFrom("async function wsTrainingen(").includes("/trainingen?vooruit=7"),
     "T5.4 Workspace vraagt recent + komend in één bestaand endpoint");
  ok(sliceFrom("async function wsTrainingen(").includes("prioSessiesHtml(rows)"),
     "T5.5 zelfde rij-renderer als Home (geen tweede trainings-engine)");
}

// ══ T6/T7 — schema-acties landen op de juiste bestemming ═════════════════════
{
  const render = sliceFrom("function wsRender(");
  ok(!/openAthleteModule\('schema','\$\{esc\(key\)\}'\)/.test(render),
     "T6.1 geen kale schema-open meer (die landde in een blanco 'Nieuw')");
  ok(render.includes(`openSchemaMode('${"${esc(key)}"}','verlengen')`),
     "T6.2 de primaire schema-CTA opent het huidige blok / verlengen");
  ok(render.includes(`openSchemaMode('${"${esc(key)}"}','nieuw')`),
     "T6.3 een nieuw schema bouwen blijft bereikbaar, apart gelabeld");
  ok(/Huidig schema &amp; verlengen|Schema verlengen/.test(render), "T6.4 eerlijk gelabeld");

  ok(app.wsSchemaVerloopt({ days_left: 0 }) === true, "T7.1 vandaag aflopend = verlengen");
  ok(app.wsSchemaVerloopt({ days_left: 5 }) === true, "T7.2 binnen 7 dagen = verlengen");
  ok(app.wsSchemaVerloopt({ days_left: -3 }) === true, "T7.3 al verlopen = verlengen");
  ok(app.wsSchemaVerloopt({ days_left: null }) === false, "T7.4 onbekend ≠ verlengen");
  ok(app.wsSchemaVerloopt(null) === false, "T7.5 geen signaal ≠ verlengen");

  const btn = app.wsActieBtn({ soort: "schema", kort: "schema loopt af over 0 dagen" },
                             "u1", {}, { days_left: 0 }, "is-critical", "is-calm");
  ok(btn.includes("openSchemaMode('u1','verlengen')"), "T7.6 aflopend schema → bestaande Verlengen-flow", btn);
  ok(/Schema verlengen/.test(btn), "T7.7 knoplabel zegt wat er gebeurt");
}

// ══ T8 — dossier-deeplink draagt het exacte event ════════════════════════════
{
  const mk = () => { const b = new El("button"); byId = { "ws-next-btn": b }; return b; };
  let b = mk();
  app.wsKoppelEvent({ attention: [{ kind: "complaint", id: "ev-42" }] });
  ok(b.dataset.ev === "cp-ev-42", "T8.1 klacht → cp-<evidence id> (cockpit-id-schema)", b.dataset.ev);

  b = mk();
  app.wsKoppelEvent({ attention: [], load_context: { interruption: { evidence_id: "ev-7" } } });
  ok(b.dataset.ev === "ch-ev-7", "T8.2 onderbreking → ch-<evidence id>", b.dataset.ev);

  b = mk();
  app.wsKoppelEvent({ attention: [], load_observation: { ernst: "hoog" } });
  ok(b.dataset.ev === "now-load", "T8.3 belastingsignaal → now-load", b.dataset.ev);

  b = mk();
  app.wsKoppelEvent({ attention: [], load_context: {} });
  ok(!b.dataset.ev, "T8.4 geen match → bestaand gedrag (cockpit kiest zijn default)");

  const open = sliceFrom("async function openDossierCockpit(");
  ok(open.includes("dcSelectEvent(wrap, _ev)"), "T8.5 het aangevraagde event wordt geselecteerd");
  ok(open.indexOf("dcRender(wrap, r)") < open.indexOf("dcSelectEvent(wrap, _ev)"),
     "T8.6 selectie gebeurt NA render (dcEvents gevuld)");
  ok(sliceFrom("function openDossierEvent(").includes('openAthleteModule("dossier", user_key)'),
     "T8.7 hergebruikt de bestaande dossier-route (geen extra routesegment)");
}

// ══ T9 — primair signaal ⇄ primaire actie ════════════════════════════════════
{
  const cases = [
    [{ soort: "belasting", kort: "Belasting hoog" }, { ernst: "hoog" }, "wsMarkeerGezien(", "Belasting gezien"],
    [{ soort: "schema", kort: "schema nog 5d" }, {}, "openSchemaMode(", "schema"],
    [{ soort: "compliance", kort: "2 van 5 trainingen gemist" }, {}, "wsToonTrainingen()", "gemiste trainingen"],
    [{ soort: "feedback", kort: "2 open reacties" }, {}, "openModuleFromNav('feedback')", "feedback"],
    [{ soort: "klacht", kort: "Klacht: scheen" }, {}, "openDossierEvent(", "dossier"],
  ];
  for (const [sig, bel, call, woord] of cases) {
    const html = app.wsActieBtn(sig, "u1", bel, { days_left: 5 }, "is-attention", "is-calm");
    ok(html.includes(call), `T9.1 ${sig.soort} → ${call}`, html.slice(0, 90));
    ok(new RegExp(woord, "i").test(html), `T9.2 ${sig.soort}: knoptekst benoemt hetzelfde onderwerp`, html);
  }
  // De lead-zin gaat over HETZELFDE signaal als de knop.
  ok(app.wsActieLead({ soort: "klacht", kort: "Klacht: scheen — actief" }, { ernst: "hoog" })
      .includes("Klacht: scheen"),
     "T9.3 lead volgt het primaire signaal, niet de belasting");
  ok(app.wsActieLead({ soort: "belasting" }, { ernst: "hoog" }).includes("verhoogd"),
     "T9.4 belasting-lead blijft ongewijzigd");
  const render = sliceFrom("function wsRender(");
  ok(!/const nextBody = bel\.actief/.test(render),
     "T9.5 de actie wordt niet meer los van het primaire signaal gekozen");
  ok(render.includes("wsActieLead(topAttn, bel)") && render.includes("wsActieBtn(topAttn"),
     "T9.6 lead én knop lezen exact hetzelfde topAttn");
}

if (failures.length) { console.error("FAIL\n - " + failures.join("\n - ")); process.exit(1); }
console.log("workspace_cleanup: all checks passed");
