// Cross-Page Consolidation Round 1 — EXECUTEERBARE tests.
// Snijdt de ECHTE functies verbatim uit pwa/static/app.js en draait ze:
//   A3  nlDatum / nlAantal
//   A4b dcBuildEvents-fallback (klacht mag nooit 'geen open klacht' opleveren)
//   B2  homeZetSegment + homeVulMonitoring + homeMonBelasting/homeMonSchema
//   B3  briefingGet-memo + briefKaartHtml
import { readFileSync } from "node:fs";

const SRC = readFileSync(new URL("../../pwa/static/app.js", import.meta.url), "utf8");
let fails = 0;
const ok = (c, m, got) => { if (!c) { fails++; console.error("FAIL:", m, got !== undefined ? `\n  got: ${JSON.stringify(got)}` : ""); } };

function sliceFrom(sig) {
  const i = SRC.indexOf(sig);
  if (i < 0) throw new Error("niet gevonden: " + sig);
  const j = SRC.indexOf("{", i);
  let d = 0;
  for (let k = j; k < SRC.length; k++) {
    if (SRC[k] === "{") d++;
    else if (SRC[k] === "}" && --d === 0) return SRC.slice(i, k + 1);
  }
  throw new Error("ongebalanceerd: " + sig);
}
const sliceLine = (pre) => {
  const i = SRC.indexOf(pre);
  return SRC.slice(i, SRC.indexOf("\n", i));
};

console.log("== Consolidation R1: copy-primitieven, Dossier-coherentie, Vandaag-segmenten ==\n");

// ══ A3 — nlDatum / nlAantal ═════════════════════════════════════════════════
{
  const m = new Function(sliceLine("const _NL_MND = ") + "\n" + sliceFrom("function nlDatum(") +
    "\n" + sliceFrom("function nlAantal(") + "\nreturn { nlDatum, nlAantal };")();

  ok(m.nlDatum("2026-09-03") === "3 sep", "A3: ISO → '3 sep'", m.nlDatum("2026-09-03"));
  ok(m.nlDatum("2026-01-01") === "1 jan", "A3: januari", m.nlDatum("2026-01-01"));
  ok(m.nlDatum("2026-12-31") === "31 dec", "A3: december", m.nlDatum("2026-12-31"));
  ok(m.nlDatum("2026-09-03T10:00:00") === "3 sep", "A3: ISO met tijd", m.nlDatum("2026-09-03T10:00:00"));
  ok(m.nlDatum("") === "", "A3: leeg blijft leeg", m.nlDatum(""));
  ok(m.nlDatum(null) === "", "A3: null blijft leeg", m.nlDatum(null));
  ok(m.nlDatum("Marathon Rotterdam") === "Marathon Rotterdam", "A3: vrije tekst onaangetast");
  // Het punt van de fix: nooit meer de ambigue MM-DD-vorm.
  ok(!/^\d{2}-\d{2}$/.test(m.nlDatum("2026-09-03")), "A3: geen ambigue MM-DD meer");
  // ... en nooit meer een rauwe ISO op een gewone coachkaart.
  ok(!/^\d{4}-/.test(m.nlDatum("2026-09-03")), "A3: geen rauwe ISO meer");

  ok(m.nlAantal(1, "training", "trainingen") === "1 training", "A3: enkelvoud", m.nlAantal(1, "training", "trainingen"));
  ok(m.nlAantal(0, "training", "trainingen") === "0 trainingen", "A3: nul = meervoud");
  ok(m.nlAantal(2, "training", "trainingen") === "2 trainingen", "A3: meervoud");
  ok(m.nlAantal(1, "atleet", "atleten") === "1 atleet", "A3: onregelmatig meervoud");
  ok(m.nlAantal(1, "week", "weken") === "1 week", "A3: week/weken");
  ok(m.nlAantal("1", "training", "trainingen") === "1 training", "A3: string-1 telt als enkelvoud");
}

// ══ A4b — dcBuildEvents: geen valse 'Geen open klacht of signaal' ═══════════
{
  const REAL = [
    sliceLine("const _DC_MND = "), sliceFrom("function dcShort("),
    sliceFrom("const _DC_TRUTH = {"), sliceLine("const _DC_OVERALL = "),
    sliceFrom("const _DC_ATTN_IC = {"),
    sliceFrom("function dcProv("), sliceFrom("function dcPrettyLabel("), sliceFrom("function dcProvText("),
    sliceFrom("function dcChangeMeta("), sliceFrom("function dcFutureNodes("),
    sliceFrom("function dcFutureMetric("), sliceFrom("function dcBuildEvents("),
  ].join("\n\n");
  const { dcBuildEvents } = new Function(REAL + "\nreturn { dcBuildEvents };")();

  const base = { chg: [], plan: { rows: [] }, lo: null, rel: { level: "green" },
                 relTxt: "bronnen vers", canonPct: t => t, olderTl: [], nowSub: "" };
  const klacht = {
    kind: "complaint", id: "cp-scheen", title: "Klacht: scheen — actief",
    why: "scheen doet zeer bij aanzetten · 2026-09-03", strength: "LOW",
    prov: { truth_type: "ATHLETE_REPORTED", source: "fs.comment", observed_at: "2026-09-03", status: "ACTIVE" },
  };

  // 1) Klacht is het ENIGE aandachtspunt → de nu-kolom mag hem niet ontkennen.
  {
    const ev = dcBuildEvents({ ...base, attn: [klacht], st: { overall: "ATTENTION" } });
    const now = ev.filter(e => e.cls === "now");
    ok(now.length === 1, "A4b: precies één nu-anker", now.map(n => n.title));
    ok(now[0].title !== "Geen open klacht of signaal",
       "A4b: geen valse 'Geen open klacht of signaal' naast een actieve klacht", now[0].title);
    ok(now[0].title === klacht.title, "A4b: nu-anker hergebruikt de canonieke klachttitel", now[0].title);
    ok(now[0].tone === "is-attention", "A4b: toon volgt de klacht, niet 'kalm'", now[0].tone);
    ok(now[0].ev === "cp-scheen", "A4b: bestaande deep-link blijft gedragen", now[0].ev);
    // De klacht blijft ÓÓK gedateerd in het verleden staan (bestaand contract).
    ok(ev.some(e => e.cls === "past" && e.title === klacht.title),
       "A4b: klacht blijft gedateerd in de verleden-kolom");
  }

  // 2) Écht niets open → de kalme fallback blijft precies zoals hij was.
  {
    const ev = dcBuildEvents({ ...base, attn: [], st: { overall: "GOOD" } });
    const now = ev.filter(e => e.cls === "now");
    ok(now.length === 1 && now[0].title === "Geen open klacht of signaal",
       "A4b: lege attention houdt de bestaande kalme tekst", now[0] && now[0].title);
    ok(now[0].tone === "is-success", "A4b: GOOD blijft groen", now[0].tone);
  }

  // 3) Te weinig data wint van de klachtvariant (nooit een oordeel suggereren).
  {
    const ev = dcBuildEvents({ ...base, attn: [klacht], st: { overall: "INSUFFICIENT_DATA" } });
    const now = ev.filter(e => e.cls === "now");
    ok(now[0].title === "Te weinig data voor een oordeel",
       "A4b: INSUFFICIENT_DATA blijft leidend", now[0].title);
  }

  // 4) Een niet-klacht-signaal vulde de nu-kolom al → gedrag ongewijzigd.
  {
    const zone = { kind: "zone_review", id: "z1", title: "Zones mogelijk niet passend", why: "zone-review kandidaat", prov: null };
    const ev = dcBuildEvents({ ...base, attn: [klacht, zone], st: { overall: "ATTENTION" } });
    const now = ev.filter(e => e.cls === "now");
    ok(now.length === 1 && now[0].title === zone.title,
       "A4b: bestaand nu-signaal blijft het anker", now.map(n => n.title));
    ok(!ev.some(e => e.title === "Geen open klacht of signaal"), "A4b: geen kalme kaart erbij");
  }
}

// ══ B2 — Vandaag-segmenten + Monitoring ═════════════════════════════════════
{
  let els = {}, apiCalls = [], apiRouter = null, hapticN = 0;
  const mkEl = () => ({
    _html: "", hidden: false, dataset: {}, isConnected: true,
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); },
    _kids: [], appendChild(c) { this._kids.push(c); this._html += (c && c.outerHTML) || "<card>"; },
    addEventListener() {}, setAttribute(k, v) { this.dataset["a_" + k] = v; },
    classList: { _on: false, add() { this._on = true; }, remove() { this._on = false; },
                 toggle(_c, v) { this._on = !!v; }, contains() { return this._on; } },
    querySelector() { return null; }, querySelectorAll() { return []; }, textContent: "",
  });
  const $ = (s) => (els[s] ||= mkEl());
  let segButtons = [];
  const $$ = () => segButtons;
  const esc = (s) => String(s == null ? "" : s);
  const ic = (n) => `<i:${n}>`;
  const nlNum = (x) => String(x).replace(".", ",");
  const haptic = () => { hapticN++; };
  const api = async (u) => { apiCalls.push(u); return apiRouter ? apiRouter(u) : null; };
  const skeleton = (b) => { if (b) b.innerHTML = "<skel>"; };
  // Kaartbouwers worden apart getest (Teampuls/Schema-verloop); hier alleen dat ze
  // ECHT worden aangeroepen — één kaartimplementatie, geen tweede renderer.
  let pulsCalls = 0, svCalls = 0;
  const pulsItem = (it) => { pulsCalls++; return { outerHTML: `<puls:${it.user_key}>` }; };
  const svItem = (it) => { svCalls++; return { outerHTML: `<sv:${it.user_key}:${it.status}>` }; };

  const REAL = [
    sliceLine("const _NL_MND = "), sliceFrom("function nlDatum("), sliceFrom("function nlAantal("),
    sliceLine("let homeSeg = "), sliceLine("let homeMonGeladen = "),
    sliceFrom("function homeZetSegment("), sliceFrom("async function homeVulMonitoring("),
    sliceFrom("function homeMonBelasting("), sliceFrom("function homeMonSchema("),
  ].join("\n\n");
  const build = () => new Function("$", "$$", "esc", "ic", "nlNum", "haptic", "api", "skeleton",
    "pulsItem", "svItem",
    REAL + "\nreturn { homeZetSegment, homeVulMonitoring, homeMonBelasting, homeMonSchema," +
    " _seg: () => homeSeg, _geladen: () => homeMonGeladen };"
  )($, $$, esc, ic, nlNum, haptic, api, skeleton, pulsItem, svItem);

  const reset = () => {
    els = {}; apiCalls = []; apiRouter = null; pulsCalls = 0; svCalls = 0;
    segButtons = [{ dataset: { seg: "actie" }, classList: { _on: true, toggle(_c, v) { this._on = !!v; } }, setAttribute() {} },
                  { dataset: { seg: "monitoring" }, classList: { _on: false, toggle(_c, v) { this._on = !!v; } }, setAttribute() {} }];
  };

  // 1) Actie is de default en haalt NIETS op (page-open blijft goedkoop).
  {
    reset(); const app = build();
    ok(app._seg() === "actie", "B2: Actie is het default-segment", app._seg());
    ok(app._geladen() === false, "B2: monitoring nog niet geladen bij page-open");
    ok(apiCalls.length === 0, "B2: geen enkele request zonder segmentwissel", apiCalls);
  }

  // 2) Wisselen naar Monitoring: lazy, precies twee bestaande endpoints, geen force.
  {
    reset(); const app = build();
    apiRouter = (u) => u.startsWith("/api/teampuls")
      ? { fs: true, vers: true, datum: "2026-09-06", hoog: 1, items: [{ user_key: "u1", ernst: "hoog" }] }
      : { fs: true, items: [{ user_key: "u2", status: "bijna" }, { user_key: "u3", status: "loopt" }] };
    app.homeZetSegment("monitoring");
    await new Promise(r => setTimeout(r, 0));
    ok(app._seg() === "monitoring", "B2: segment gewisseld");
    ok(els["#home-actie"].hidden === true, "B2: Actie-paneel verborgen");
    ok(els["#home-mon"].hidden === false, "B2: Monitoring-paneel zichtbaar");
    ok(apiCalls.includes("/api/teampuls/signalen"), "B2/T20: bestaand teampuls-endpoint", apiCalls);
    ok(apiCalls.includes("/api/schema-verloop"), "B2/T21: bestaand schema-verloop-endpoint", apiCalls);
    ok(!apiCalls.some(u => u.includes("force")), "B2: nooit een recompute forceren", apiCalls);
    ok(apiCalls.length === 2, "B2: precies twee requests", apiCalls);
    ok(pulsCalls === 1, "B2: hergebruikt de ECHTE Teampuls-kaart", pulsCalls);
    ok(svCalls === 1, "B2: alleen de schema's die aandacht vragen ('bijna'), niet 'loopt'", svCalls);
  }

  // 3) Tweede keer wisselen doet geen tweede fetch.
  {
    reset(); const app = build();
    apiRouter = () => ({ fs: true, items: [] });
    app.homeZetSegment("monitoring"); await new Promise(r => setTimeout(r, 0));
    const n = apiCalls.length;
    app.homeZetSegment("actie"); app.homeZetSegment("monitoring");
    await new Promise(r => setTimeout(r, 0));
    ok(apiCalls.length === n, "B2: heen-en-weer wisselen refetcht niet", apiCalls.length);
    ok(els["#home-actie"].hidden === false || app._seg() === "monitoring", "B2: panelen consistent");
  }

  // 4) Eerlijke lege/kapotte staten — nooit een valse geruststelling.
  {
    reset(); const app = build();
    app.homeMonBelasting(null);
    ok(els["#hmon-bel"].innerHTML.includes("Geen verbinding"), "B2: netwerkfout is geen 'alles goed'");
    reset(); const app2 = build();
    app2.homeMonBelasting({ fs: true, pending: true });
    ok(els["#hmon-bel-info"].textContent.includes("voor het eerst berekend"),
       "B2: pending is geen lege stand", els["#hmon-bel-info"].textContent);
    ok(els["#hmon-bel"].innerHTML === "", "B2: pending toont geen 'binnen de marge'");
    reset(); const app3 = build();
    app3.homeMonBelasting({ fs: true, vers: true, items: [], hoog: 0 });
    ok(els["#hmon-bel"].innerHTML.includes("binnen de marge"),
       "B2: écht leeg mag wél geruststellen", els["#hmon-bel"].innerHTML);
  }

  // 5) Stale stand wordt gelabeld met de gedeelde datumformatter (geen rauwe ISO).
  {
    reset(); const app = build();
    app.homeMonBelasting({ fs: true, vers: false, datum: "2026-09-05", hoog: 0, items: [{ user_key: "u1" }] });
    const html = els["#hmon-bel-info"].innerHTML;
    ok(html.includes("stand 5 sep"), "B2/A3: stand-datum leesbaar", html);
    ok(!html.includes("2026-09-05"), "B2/A3: geen rauwe ISO in de kop", html);
  }

  // 6) Enkelvoud in de schema-teller.
  {
    reset(); const app = build();
    app.homeMonSchema({ fs: true, items: [{ user_key: "u1", status: "verlopen" }, { user_key: "u2", status: "loopt" }] });
    ok(els["#hmon-sv-info"].textContent.startsWith("1 atleet "),
       "B2/A3: '1 atleet', niet '1 atleten'", els["#hmon-sv-info"].textContent);
  }
}

// ══ B3 — briefing: één ophaalpad, één render ════════════════════════════════
{
  let apiCalls = [];
  const esc = (s) => String(s == null ? "" : s);
  const ic = (n) => `<i:${n}>`;
  const api = async (u) => { apiCalls.push(u); return {
    fs: true, gemaakt: "2026-09-02", tekst: "**Kop**\n- punt een",
    stats: { n_trainingen: 210, km_totaal: 1840, n_actief: 48, n_atleten: 68 },
    populatie_label: "gecoachte atleten actief", populatie_uitleg: "definitie…" }; };

  const REAL = [
    sliceLine("const _BR_DAGEN = "), sliceLine("const _BR_MND = "),
    sliceFrom("function briefGemaaktLabel("), sliceFrom("function briefHtml("),
    sliceLine("let _briefMemo = "), sliceFrom("async function briefingGet("),
    sliceFrom("function briefKaartHtml("),
  ].join("\n\n");
  const m = new Function("esc", "ic", "api",
    REAL + "\nreturn { briefingGet, briefKaartHtml };")(esc, ic, api);

  const a = await m.briefingGet(false);
  const b = await m.briefingGet(false);
  ok(apiCalls.length === 1, "B3/T28: tweede lezer haalt niet opnieuw op (memo)", apiCalls);
  ok(a === b, "B3: beide oppervlakken krijgen exact dezelfde payload");
  await m.briefingGet(true);
  ok(apiCalls.length === 2 && apiCalls[1].includes("force=true"),
     "B3: alleen een expliciete 'Vernieuw' forceert", apiCalls);

  const html = m.briefKaartHtml(a);
  ok(html.includes("48/68 gecoachte atleten actief"), "B3/T26: populatie-semantiek bewaard", html.slice(0, 200));
  ok(html.includes("gedeeld met beide coaches"), "B3: herkomst bewaard");
  ok(html.includes("210 trainingen") && html.includes("1840 km"), "B3/T27: stats bewaard");
  ok(/Gemaakt \w+ 2 sep/.test(html), "B3/T27: dateringsmarkering bewaard", html.slice(0, 160));
  ok(html.includes("<b>Kop</b>") || html.includes("<h4>") || html.includes("<li>"),
     "B3: briefingtekst wordt nog steeds gerenderd", html);
  ok(html.includes("data-brief-refresh"), "B3: vernieuw-actie aanwezig");

  ok(m.briefKaartHtml(null).includes("niet beschikbaar"), "B3: geen verbinding is geen lege kaart");
  ok(m.briefKaartHtml({ fs: true, err: "AI-sleutel ontbreekt" }).includes("AI-sleutel ontbreekt"),
     "B3: serverfout blijft leesbaar");
}

if (fails) { console.error(`\n${fails} check(s) FAILED`); process.exit(1); }
console.log("\nPASS: nlDatum/nlAantal, Dossier nu-anker (A4b), Vandaag-segmenten lazy + endpoint-hergebruik, briefing-memo.");
