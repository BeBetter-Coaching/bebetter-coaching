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

const sliceLine = (p) => { const i = SRC.indexOf(p); if (i < 0) throw new Error("not found: " + p); return SRC.slice(i, SRC.indexOf("\n", i)); };
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
  get outerHTML() { return this._outer || ""; }
  set outerHTML(v) { this._outer = String(v); }
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
const _NL_MND = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"];
const nlDatum = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || "")); return m ? `${+m[3]} ${_NL_MND[+m[2]-1]}` : String(iso || ""); };
const nlAantal = (n, e, mv) => `${n} ${Number(n) === 1 ? e : mv}`;
const athleteNav = (v, k) => `<div class="anav" data-anav="${v}:${k}"></div>`;
const documentShim = { querySelector: () => byId._chip || null, createElement: t => new El(t) };

// ── Gedeelde slices ──────────────────────────────────────────────────────────
const HELPERS = [
  sliceFrom("const _DS_TONE = {"), sliceLine("const _DS_RANK = "),
  sliceFrom("function dsTone("), sliceFrom("function dsWorstTone("), sliceFrom("function dsChip("),
  sliceFrom("function wsActieLead("),
  sliceFrom("function wsSchemaVerloopt("),
  sliceFrom("function wsActieBtn("),
  sliceFrom("function wsLine("),
  sliceFrom("function wsVulLoadContext("),
  sliceFrom("const _WS_CTX_KIND = {"), sliceFrom("function wsUniekeSignalen("),
  sliceFrom("function wsTweedeActie("),
  sliceFrom("function wsContextSignalen("),
  sliceFrom("function wsDeepContext("),
  sliceFrom("function wsMagRustig("),
  sliceFrom("function wsZetBadge("),
  sliceFrom("function wsSignalenHtml("),
  sliceFrom("function wsNextHtml("),
  sliceFrom("function prioSessiesHtml("),
].join("\n\n");

const app = new Function("$", "$$", "esc", "ic", "nlNum", "nlDatum", "nlAantal", "athleteNav", "document",
  HELPERS + "\nreturn { wsActieLead, wsSchemaVerloopt, wsActieBtn, wsVulLoadContext," +
  " wsContextSignalen, wsDeepContext, wsMagRustig, wsZetBadge, wsSignalenHtml, wsNextHtml," +
  " wsUniekeSignalen, wsTweedeActie," +
  " prioSessiesHtml };"
)($, $$, esc, ic, nlNum, nlDatum, nlAantal, athleteNav, documentShim);

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
  ok(/geen actief belastingssignaal/i.test(slot.innerHTML),
     "T1.5 eerlijk gelabeld: bekend, alleen geen actief signaal", slot.innerHTML.slice(-140));
  ok(/laatste 4 weken/i.test(slot.innerHTML),
     "T1.5b eigen venster benoemd (4 weken, niet de rolling-7 uit de kop)");
  ok(!/onbekend|niet beschikbaar|verouderd/i.test(slot.innerHTML),
     "T1.5c leest niet als ontbrekende of stale data");

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
  const nextHtml = sliceFrom("function wsNextHtml(");
  ok(/Te weinig om op te oordelen/.test(nextHtml), "T2.3 expliciete insufficient-data-tekst");
  // 'alles bij' mag ALLEEN in de rustig-tak staan
  const i = nextHtml.indexOf("Geen directe actie — alles bij.");
  ok(i > -1 && nextHtml.lastIndexOf('staat === "rustig"', i) > -1,
     "T2.4 'alles bij' zit uitsluitend achter de rustig-stand");
  ok(app.wsNextHtml(null, "u1", {}, null, "is-calm", "is-calm", "rustig").includes("alles bij"),
     "T2.4b rustig-stand geeft de bestaande alles-bij-tekst");
  ok(app.wsNextHtml(null, "u1", {}, null, "is-calm", "is-calm", "onbekend").includes("Te weinig om op te oordelen"),
     "T2.4c onbekend-stand geeft NOOIT alles-bij");

  // Opwaarderen mag alleen als een autoritatieve bron dat draagt.
  ok(app.wsMagRustig({ load_context: { known: true }, status: { insufficient: false } }) === true,
     "T2.5 rustig mag bij bekende load zonder insufficient");
  ok(app.wsMagRustig({ load_context: { known: true }, status: { insufficient: true } }) === false,
     "T2.6 AthleteState 'insufficient' blijft onbekend");
  ok(app.wsMagRustig({ load_context: { known: false }, status: {} }) === false,
     "T2.7 onbekende load geeft nooit groen licht");
}

// ══ T3/T4 — actuele Dossier-context in de Workspace ══════════════════════════
{
  const sigBox = new El("div"), nxtBox = new El("div"), badge = new El("span");
  byId = { "ws-signals": sigBox, "ws-next-body": nxtBox, "ws-badge": badge };
  const box = sigBox;                                   // context = signaalregels (één eenheid)
  app.wsDeepContext({ _ws: { attn: [], key: "u1", bel: {}, sc: null, tone: "is-calm", belTone: "is-calm", staat: "onbekend" } }, {
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

  const leegSig = new El("div");
  byId = { "ws-signals": leegSig, "ws-next-body": new El("div"), "ws-badge": new El("span") };
  app.wsDeepContext({ _ws: { attn: [], key: "u1", bel: {}, sc: null, tone: "is-calm", belTone: "is-calm", staat: "onbekend" } },
                    { attention: [] });
  ok(!/ws-signals/.test(leegSig.innerHTML), "T3.4 geen context → geen signaalregels");
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
  const sig = app.wsContextSignalen({ attention: [{ kind: "complaint", id: "ev-42", title: "Klacht: scheen — actief", why: "x" }] });
  ok(sig[0].ev === "cp-ev-42", "T8.1 klacht → cp-<evidence id> (cockpit-id-schema)", sig[0].ev);
  const sig2 = app.wsContextSignalen({ attention: [], load_context: { interruption: { tekst: "3 weken", evidence_id: "ev-7" } } });
  ok(sig2[0].ev === "ch-ev-7", "T8.2 onderbreking → ch-<evidence id>", sig2[0].ev);

  const btn = app.wsActieBtn(sig[0], "u1", {}, null, "is-attention", "is-calm");
  ok(btn.includes('openDossierEvent(') && btn.includes('data-ev="cp-ev-42"'),
     "T8.3 de knop draagt het exacte event mee", btn.slice(0, 120));
  const zonder = app.wsActieBtn({ soort: "klacht", kort: "Klacht" }, "u1", {}, null, "is-attention", "is-calm");
  ok(zonder.includes('data-ev=""'), "T8.4 geen match → bestaand gedrag (cockpit kiest zijn default)");

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
  const nxt = sliceFrom("function wsNextHtml(");
  ok(nxt.includes("wsActieLead(topAttn, bel)") && nxt.includes("wsActieBtn(topAttn"),
     "T9.6 lead én knop lezen exact hetzelfde topAttn");
}


// ══ RONDE 2 — context forceert aandacht en bepaalt de actie ══════════════════
function _slots() {
  const sig = new El("div"), nxt = new El("div"), badge = new El("span");
  byId = { "ws-signals": sig, "ws-next-body": nxt, "ws-badge": badge };
  return { sig, nxt, badge };
}
const _shell = (over = {}) => ({ _ws: {
  attn: [], key: "u1", bel: {}, sc: null, tone: "is-calm", belTone: "is-calm", staat: "onbekend",
  ...over } });

// R1 — Nathalie: geen load, wél actieve klacht + onderbreking → nooit RUSTIG.
{
  const s1 = _slots();
  const wrap = _shell();
  app.wsDeepContext(wrap, {
    status: { insufficient: false },
    load_context: { known: false, no_recent_running: true,
                    interruption: { tekst: "laatste 10 weken (bijna) niet getraind", status: "ACTIVE", wanneer: "2026-08-30" } },
    attention: [{ kind: "complaint", id: "ev-1", title: "Klacht: knie — actief", why: "knie zeurt · 02-09" }],
  });
  ok(/aandacht/.test(s1.badge.outerHTML), "R1.1 badge wordt aandacht, nooit rustig", s1.badge.outerHTML);
  ok(!/rustig/.test(s1.badge.outerHTML), "R1.2 geen RUSTIG bij actieve klacht/onderbreking");
  ok(!/alles bij/.test(s1.nxt.innerHTML), "R1.3 geen all-clear-copy", s1.nxt.innerHTML.slice(0, 80));
  ok(/Klacht: knie/.test(s1.nxt.innerHTML), "R1.4 primaire actie gaat over de klacht", s1.nxt.innerHTML.slice(0, 120));
  ok(/openDossierEvent/.test(s1.nxt.innerHTML), "R1.5 bruikbare route naar de context (CTA blijft aan)");
  ok(/Klacht: knie/.test(s1.sig.innerHTML) && /Trainingsonderbreking/.test(s1.sig.innerHTML),
     "R1.6 beide contextsignalen staan in Aandacht nu");
  ok(/<small>/.test(s1.sig.innerHTML), "R1.7 met leesbaar detail onder het label (één eenheid)");
}

// R2 — Douwe: shell heeft een belasting-signaal (aandacht); de concrete klacht wint.
{
  const s2 = _slots();
  const wrap = _shell({ attn: [{ soort: "belasting", tier: "aandacht", kort: "Belasting let op · -13% t.o.v. referentie" }],
                        bel: { actief: true, ernst: "let_op" }, staat: "aandacht", tone: "is-attention" });
  app.wsDeepContext(wrap, {
    status: { insufficient: false }, load_context: { known: true },
    attention: [{ kind: "complaint", id: "ev-9", title: "Klacht: scheen — actief",
                  why: "ontsteking (scheen) · 23-08" }],
  });
  ok(/Klacht: scheen/.test(s2.nxt.innerHTML), "R2.1 primaire actie volgt de klacht", s2.nxt.innerHTML.slice(0, 120));
  const primair = s2.nxt.innerHTML.split('<div class="ws-next-2"')[0];
  ok(!/Belasting gezien/.test(primair), "R2.2 geen 'Belasting gezien' als PRIMAIRE actie terwijl de klacht primair is", primair.slice(0, 100));
  ok(/data-ev="cp-ev-9"/.test(s2.nxt.innerHTML), "R2.3 opent de CONCRETE klacht in het dossier");
  const rows = s2.sig.innerHTML;
  ok(rows.indexOf("Klacht: scheen") < rows.indexOf("Belasting let op"),
     "R2.4 klacht boven het belasting-signaal, dat secundair blijft staan");
  ok(/ontsteking \(scheen\)/.test(s2.sig.innerHTML), "R2.5 de concrete bekende klachtinhoud is zichtbaar");
}

// R3 — een ACTIE-tier belastingsignaal blijft primair; de klacht wordt secundair.
{
  const s3 = _slots();
  const wrap = _shell({ attn: [{ soort: "belasting", tier: "actie", kort: "Belasting hoog · +60% t.o.v. referentie" }],
                        bel: { actief: true, ernst: "hoog" }, staat: "aandacht", tone: "is-critical", belTone: "is-critical" });
  app.wsDeepContext(wrap, {
    status: {}, load_context: { known: true },
    attention: [{ kind: "complaint", id: "ev-3", title: "Klacht: kuit — actief", why: "kuit · 01-09" }],
  });
  ok(/Belasting gezien/.test(s3.nxt.innerHTML), "R3.1 zwaarste signaal blijft primair", s3.nxt.innerHTML.slice(0, 120));
  ok(/Klacht: kuit/.test(s3.sig.innerHTML), "R3.2 klacht blijft wél zichtbaar als secundair signaal");
}

// R4 — Sophie: context mag NIET wegvallen zodra er al signalen zijn (precedentie-bug).
{
  const render = sliceFrom("function wsRender(");
  ok(/const attnBody = `<div id="ws-signals">/.test(render),
     "R4.1 signaal-slot staat altijd in de kaart");
  ok(!/id="ws-ctx"/.test(render),
     "R4.2 geen apart contextslot meer — dat dupliceerde elk signaal");
  const s4 = _slots();
  const wrap = _shell({ attn: [{ soort: "belasting", tier: "aandacht", kort: "Belasting let op" }], staat: "aandacht" });
  app.wsDeepContext(wrap, {
    status: {}, load_context: { known: true,
      interruption: { tekst: "3 weken minder/geen training", status: "RECENT", wanneer: "2026-08-30" } },
    attention: [],
  });
  ok(/Trainingsonderbreking: 3 weken/.test(s4.sig.innerHTML),
     "R4.3 bekende onderbreking verschijnt óók bij een atleet mét signalen", s4.sig.innerHTML.slice(0, 100));
  ok(/Trainingsonderbreking/.test(s4.sig.innerHTML), "R4.4 en telt mee als aandachtssignaal");
}

// R5 — zonder context blijft de bestaande stand ongemoeid (geen valse aandacht).
{
  const s5 = _slots();
  const wrap = _shell({ staat: "onbekend" });
  app.wsDeepContext(wrap, { status: {}, load_context: { known: false }, attention: [] });
  ok(!/Trainingsonderbreking|Klacht:/.test(s5.sig.innerHTML), "R5.1 geen context → geen contextregels");
  ok(/onbekend/.test(s5.badge.outerHTML), "R5.2 onbekend blijft onbekend", s5.badge.outerHTML);
  ok(/Te weinig om op te oordelen/.test(s5.nxt.innerHTML), "R5.3 en nooit een all-clear");

  const s6 = _slots();
  app.wsDeepContext(_shell({ staat: "onbekend" }),
                    { status: { insufficient: false }, load_context: { known: true }, attention: [] });
  ok(/rustig/.test(s6.badge.outerHTML), "R5.4 bekende load zonder signalen mag wél rustig worden", s6.badge.outerHTML);
}

if (failures.length) { console.error("FAIL\n - " + failures.join("\n - ")); process.exit(1); }
console.log("workspace_cleanup: all checks passed");
