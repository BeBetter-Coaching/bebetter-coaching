// Weekendbeheer — Jip, Remco en Tim. Alle data komt uit /api/weekend/beheer*, die de
// server alleen aan een beheersessie geeft. Deze pagina verbergt niets om te beveiligen.
//
// Drie weergaven: Dashboard (wat moet ik weten en doen), Inschrijvingen (per persoon) en
// Instellingen (open/dicht, deadlines, kosten). Alle cijfers rekent de SERVER uit
// (weekend_core.dashboard); deze pagina tekent ze alleen.
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const getToken = () => { try { return localStorage.getItem("bb_token") || ""; } catch { return ""; } };
const setToken = t => { try { t ? localStorage.setItem("bb_token", t) : localStorage.removeItem("bb_token"); } catch {} };
const escAttr = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Kleuren: gevalideerd met de dataviz-validator op het donkere kaartoppervlak.
// Betaalstatus = ORDINAAL (één tint, oplopend naar 'betaald'); betaalkeuze = CATEGORISCH.
const KLEUR = {
  status: { open: "#2A6F7C", aanbetaling: "#3AA5B0", betaald: "#5EE6EB", terugbetaald: "#61789E" },
  keuze: { aanbetaling: "#22A7B2", volledig: "#8E7BEF", onbekend: "#61789E" },
  lijn: "#5EE6EB",
};
const KEUZE_KORT = { aanbetaling: "Twee termijnen", volledig: "In één keer" };
const NA_ONTVANGST = { aanbetaling: "aanbetaling", volledig: "betaald", rest: "betaald" };

// "249" · "249,50" · "€ 1.249,50" · "249.5" → centen. Leeg → null. Onleesbaar → NaN.
function parseEuroCent(invoer) {
  let s = String(invoer ?? "").replace(/€|\s/g, "");
  if (s === "") return null;
  if (!/^\d[\d.,]*$/.test(s)) return NaN;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return NaN;
  const [heel, dec = ""] = s.split(".");
  return Number(heel) * 100 + Number((dec + "00").slice(0, 2));
}
function centNaarInvoer(cent) {
  if (cent === null || cent === undefined) return "";
  return (cent / 100).toFixed(2).replace(".", ",").replace(/,00$/, "");
}
function euro(cent) {
  if (cent === null || cent === undefined) return "niet vastgesteld";
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" }).format(cent / 100);
}
// Grote getallen op het dashboard: hele euro's zonder ",00".
function euroKort(cent) {
  if (cent === null || cent === undefined) return "–";
  const heel = cent % 100 === 0;
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", minimumFractionDigits: heel ? 0 : 2, maximumFractionDigits: 2 }).format(cent / 100);
}
function tijdstip(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d)) return "";
  return new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Amsterdam" }).format(d);
}
function datumKort(isoDatum) {
  const d = new Date(isoDatum + "T12:00:00");
  return isNaN(d) ? isoDatum : new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short" }).format(d);
}
function pct(n, totaal) { return totaal ? Math.round((n / totaal) * 100) : 0; }
function meervoud(n, een, meer) { return `${n} ${n === 1 ? een : meer}`; }
// Nette bovengrens voor een as met hele getallen.
function niceMax(n) {
  const m = Math.max(1, n);
  const stap = m <= 5 ? 1 : m <= 20 ? 5 : m <= 50 ? 10 : 25;
  return Math.ceil(m / stap) * stap;
}

async function api(pad, opt = {}) {
  const headers = Object.assign({}, opt.headers || {});
  const t = getToken(); if (t) headers.Authorization = "Bearer " + t;
  const r = await fetch(pad, { ...opt, headers, cache: "no-store" });
  if (r.status === 401 || r.status === 403) { toonLogin(r.status === 403 ? "Dit account heeft geen toegang tot weekendbeheer." : ""); throw new Error("auth"); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(d.err || "Er ging iets mis."); e.status = r.status; throw e; }
  return d;
}
const post = (pad, body, method = "POST") => api(pad, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let toastTimer = null;
function toast(tekst, isFout = false) {
  const el = $("#wb-toast");
  el.textContent = tekst; el.hidden = !tekst; el.classList.toggle("is-critical", isFout);
  clearTimeout(toastTimer);
  if (tekst && !isFout) toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}
const fout = err => { if (err.message !== "auth") toast(err.message, true); };

function bevestig(titel, tekst, ja = "Bevestigen") {
  const dlg = $("#wb-dialog");
  $("#wb-dialog-titel").textContent = titel;
  $("#wb-dialog-tekst").textContent = tekst;
  $("#wb-dialog-ja").textContent = ja;
  return new Promise(res => {
    dlg.addEventListener("close", () => res(dlg.returnValue === "ja"), { once: true });
    dlg.returnValue = ""; dlg.showModal();
  });
}

// ── Inloggen ────────────────────────────────────────────────────────────────
let loginWie = null;
function toonLogin(melding = "") {
  $("#wb-app").hidden = true; $("#wb-login").hidden = false;
  $("#wb-who").hidden = false; $("#wb-pw").hidden = true; loginWie = null;
  $("#wb-login-err").textContent = melding; $("#wb-login-err").hidden = !melding;
}
$$(".wb-who").forEach(b => b.addEventListener("click", () => {
  loginWie = b.dataset.wie;
  $("#wb-who").hidden = true; $("#wb-pw").hidden = false; $("#wb-login-err").hidden = true;
  $("#wb-as").textContent = `Inloggen als ${loginWie}`;
  $("#wb-pass").value = ""; setTimeout(() => $("#wb-pass").focus(), 40);
}));
$("#wb-login-back").addEventListener("click", () => toonLogin());
$("#wb-login-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (!loginWie) return;
  const btn = $("#wb-login-btn"); btn.disabled = true; btn.textContent = "Bezig…";
  try {
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wie: loginWie, password: $("#wb-pass").value }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) { setToken(d.token); await start(); }
    else { $("#wb-login-err").textContent = d.err || "Inloggen mislukt."; $("#wb-login-err").hidden = false; }
  } catch { $("#wb-login-err").textContent = "Geen verbinding."; $("#wb-login-err").hidden = false; }
  btn.disabled = false; btn.textContent = "Inloggen";
});
$("#wb-uitloggen").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST", headers: getToken() ? { Authorization: "Bearer " + getToken() } : {} }).catch(() => {});
  setToken(""); toonLogin();
});

// ── Staat + navigatie ───────────────────────────────────────────────────────
let data = null;
let rol = "";
let metTest = (() => { try { return localStorage.getItem("wb_met_test") === "1"; } catch { return false; } })();
let lijstFilter = "alle";
let zoek = "";
const TABS = ["dashboard", "inschrijvingen", "instellingen"];

function huidigeTab() {
  const h = location.hash.replace("#", "");
  return TABS.includes(h) ? h : "dashboard";
}
function toonTab() {
  const tab = huidigeTab();
  TABS.forEach(t => { $(`#wb-v-${t}`).hidden = t !== tab; });
  $$(".wb-tabs a").forEach(a => a.setAttribute("aria-current", a.dataset.tab === tab ? "page" : "false"));
  if (tab === "dashboard" && data) tekenTijdlijn();     // breedte is pas bekend als de view zichtbaar is
}
window.addEventListener("hashchange", toonTab);

// ── Grafiek-bouwstenen (SVG/HTML, geen bibliotheek) ─────────────────────────
// Donut: part-to-whole met ≤ 4 segmenten, 2px oppervlakte-gat tussen segmenten.
function donutSvg(segmenten, totaal, midden) {
  const R = 52, SW = 16, C = 2 * Math.PI * R, GAT = 2;
  const zichtbaar = segmenten.filter(s => s.waarde > 0);
  let offset = 0;
  const bogen = zichtbaar.map(s => {
    const len = (s.waarde / totaal) * C;
    const dash = zichtbaar.length > 1 ? Math.max(len - GAT, 0.5) : C;
    const tip = `${s.label}: ${s.waarde} (${pct(s.waarde, totaal)}%)`;
    const boog = (extra, sw) => `<circle cx="70" cy="70" r="${R}" fill="none" stroke-width="${sw}" ${extra}
      stroke-dasharray="${dash.toFixed(2)} ${(C - dash).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}"/>`;
    // Zichtbare boog + een bredere, onzichtbare boog als hover/focus-doel.
    const el = boog(`class="wb-seg" stroke="${s.kleur}"`, SW)
      + boog(`class="wb-seg-hit" stroke="transparent" data-tip="${escAttr(tip)}" tabindex="0" aria-label="${escAttr(tip)}"`, 30);
    offset += len;
    return el;
  }).join("");
  const spoor = `<circle cx="70" cy="70" r="${R}" fill="none" stroke="var(--wb-track)" stroke-width="${SW}"/>`;
  return `<svg class="wb-donut" viewBox="0 0 140 140" width="140" height="140" role="group" aria-label="${escAttr(midden.aria)}">
    <g transform="rotate(-90 70 70)">${totaal ? bogen : spoor}</g>
    <text x="70" y="70" text-anchor="middle" class="wb-donut-val">${escAttr(midden.waarde)}</text>
    <text x="70" y="88" text-anchor="middle" class="wb-donut-lbl">${escAttr(midden.label)}</text></svg>`;
}
// Legenda = tegelijk de tabelweergave: label, aantal, percentage.
function legenda(segmenten, totaal) {
  return `<ul class="wb-leg">${segmenten.map(s => `<li${s.waarde ? "" : ' class="is-nul"'}>
    <span class="wb-sw" style="background:${s.kleur}"></span><span class="wb-leg-l">${escAttr(s.label)}</span>
    <span class="wb-leg-n">${s.waarde}</span><span class="wb-leg-p">${pct(s.waarde, totaal)}%</span></li>`).join("")}</ul>`;
}
// Gesplitste balk voor twee delen (een taart met twee punten leest slechter).
function splitBalk(segmenten, totaal) {
  if (!totaal) return `<div class="wb-split is-leeg" aria-hidden="true"><span></span></div>`;
  return `<div class="wb-split">${segmenten.filter(s => s.waarde > 0).map(s => {
    const tip = `${s.label}: ${s.waarde} (${pct(s.waarde, totaal)}%)`;
    return `<span class="wb-split-seg" style="flex:${s.waarde} 1 0;--kleur:${s.kleur}" tabindex="0" data-tip="${escAttr(tip)}" aria-label="${escAttr(tip)}"></span>`;
  }).join("")}</div>`;
}

// ── Dashboard ───────────────────────────────────────────────────────────────
const dash = () => (metTest ? data.dashboard.met_test : data.dashboard.echt);

function dagenTekst(d) {
  if (!d.ingesteld) return "";
  if (d.verlopen) return "verlopen";
  if (d.dagen <= 1) return "vandaag of morgen";
  return `nog ${d.dagen} dagen`;
}

function tekenDashboard() {
  const D = dash();
  const chip = $("#wb-d-open");
  chip.textContent = data.open ? "Inschrijving open" : "Inschrijving gesloten";
  chip.className = "wb-chip " + (data.open ? "is-success" : "is-stale");

  const hint = $("#wb-d-hint");
  const alleenTests = !metTest && D.aantal.actief === 0 && data.dashboard.met_test.aantal.actief > 0;
  hint.hidden = !alleenTests;
  hint.textContent = alleenTests ? "Nog geen echte inschrijvingen. Zet ‘Testinschrijvingen meenemen’ aan om het dashboard met je tests te bekijken." : "";

  // Deadlines: wanneer moet wat binnen zijn, en hoeveel staat er nog open.
  $("#wb-d-deadlines").innerHTML = D.deadlines.map(d => {
    const toon = !d.ingesteld ? "is-unknown" : d.te_laat ? "is-critical" : (d.dagen <= 7 && d.open) ? "is-attention" : "is-calm";
    const status = !d.ingesteld
      ? `<a href="#instellingen">Deadline instellen</a>`
      : `${escAttr(d.tekst)} · ${escAttr(dagenTekst(d))}`;
    const open = d.ingesteld ? `<span class="wb-dl-open">${d.te_laat ? `<svg class="wk-ic"><use href="#ic-alert"/></svg> ${meervoud(d.te_laat, "te laat", "te laat")} · ` : ""}${meervoud(d.open, "open", "open")}</span>` : "";
    return `<div class="wb-dl ${toon}"><span class="wb-dl-lbl">${escAttr(d.label)}</span><span class="wb-dl-wanneer">${status}</span>${open}</div>`;
  }).join("");

  // KPI-rij.
  const g = D.geld, versturen = D.acties.versturen.length, wachten = D.acties.wachten.length;
  const teLaat = [...D.acties.versturen, ...D.acties.wachten].filter(a => a.te_laat).length;
  const tegel = (lbl, waarde, sub, toon = "") => `<div class="wb-kpi ${toon}"><span class="wb-kpi-lbl">${lbl}</span>
    <span class="wb-kpi-val">${waarde}</span><span class="wb-kpi-sub">${sub}</span></div>`;
  $("#wb-d-kpis").innerHTML =
    tegel("Deelnemers", D.aantal.actief, D.aantal.geannuleerd ? meervoud(D.aantal.geannuleerd, "geannuleerd", "geannuleerd") : (metTest && D.aantal.test ? `waarvan ${D.aantal.test} test` : "actieve inschrijvingen"))
    + tegel("Ontvangen", euroKort(g.ontvangen_cent), `van ${euroKort(g.toegezegd_cent)} toegezegd`)
    + tegel("Nog te ontvangen", euroKort(g.open_cent), g.te_laat_cent ? `<svg class="wk-ic"><use href="#ic-alert"/></svg> ${euroKort(g.te_laat_cent)} is te laat` : "niets te laat", g.te_laat_cent ? "is-critical" : "")
    + tegel("Actie nodig", versturen, `${meervoud(versturen, "verzoek", "verzoeken")} te sturen · ${wachten} wachten`, teLaat ? "is-attention" : "");

  // Geld: meter ontvangen van toegezegd.
  const p = pct(g.ontvangen_cent, g.toegezegd_cent);
  $("#wb-c-geld").innerHTML = g.toegezegd_cent
    ? `<p class="wb-geld-kop"><b>${p}%</b> binnen</p>
       <div class="wb-meter" role="img" aria-label="${escAttr(`${euro(g.ontvangen_cent)} ontvangen van ${euro(g.toegezegd_cent)}`)}"><span style="width:${p}%"></span></div>
       <ul class="wb-leg">
         <li><span class="wb-sw" style="background:${KLEUR.status.betaald}"></span><span class="wb-leg-l">Ontvangen</span><span class="wb-leg-n">${escAttr(euroKort(g.ontvangen_cent))}</span></li>
         <li><span class="wb-sw is-track"></span><span class="wb-leg-l">Nog te ontvangen</span><span class="wb-leg-n">${escAttr(euroKort(g.open_cent))}</span></li>
         <li><span class="wb-sw is-leeg"></span><span class="wb-leg-l">Toegezegd totaal</span><span class="wb-leg-n">${escAttr(euroKort(g.toegezegd_cent))}</span></li>
       </ul>`
    : `<p class="wb-leeg-klein">Nog geen toegezegde bedragen.</p>`;

  // Betaalstatus: donut (ordinaal: niet betaald → aanbetaling → volledig).
  const L = data.labels.betaalstatus;
  const st = ["open", "aanbetaling", "betaald", "terugbetaald"]
    .filter(k => k !== "terugbetaald" || D.betaalstatus.terugbetaald)
    .map(k => ({ label: L[k], waarde: D.betaalstatus[k], kleur: KLEUR.status[k] }));
  const volledig = D.betaalstatus.betaald;
  $("#wb-c-status").innerHTML = `<div class="wb-donut-wrap">${donutSvg(st, D.aantal.actief,
      { waarde: `${volledig}/${D.aantal.actief}`, label: "volledig", aria: `Betaalstatus van ${D.aantal.actief} deelnemers` })}
    ${legenda(st, D.aantal.actief)}</div>`;

  // Betaalkeuze: gesplitste balk + legenda.
  const ks = ["aanbetaling", "volledig", "onbekend"]
    .filter(k => k !== "onbekend" || D.betaalkeuze.onbekend)
    .map(k => ({ label: k === "onbekend" ? "Niet gekozen" : KEUZE_KORT[k], waarde: D.betaalkeuze[k], kleur: KLEUR.keuze[k] }));
  $("#wb-c-keuze").innerHTML = `${splitBalk(ks, D.aantal.actief)}${legenda(ks, D.aantal.actief)}
    <p class="wb-chart-noot">Twee termijnen: € aanbetaling nu, rest later. In één keer: alles direct.</p>`
    .replace("€ aanbetaling nu", "aanbetaling nu");

  // Actielijsten.
  $("#wb-a-versturen-n").textContent = versturen ? `(${versturen})` : "";
  $("#wb-a-wachten-n").textContent = wachten ? `(${wachten})` : "";
  $("#wb-a-versturen").innerHTML = versturen ? D.acties.versturen.map(a => actieItem(a, "versturen")).join("")
    : `<p class="wb-leeg-klein"><svg class="wk-ic"><use href="#ic-check"/></svg> Niemand wacht op een betaalverzoek.</p>`;
  $("#wb-a-wachten").innerHTML = wachten ? D.acties.wachten.map(a => actieItem(a, "wachten")).join("")
    : `<p class="wb-leeg-klein">Geen openstaande verzoeken.</p>`;

  tekenTijdlijn();
}

function keuzeTag(keuze) {
  if (!KEUZE_KORT[keuze]) return `<span class="wb-keuze"><span class="wb-sw" style="background:${KLEUR.keuze.onbekend}"></span>Betaalkeuze onbekend</span>`;
  return `<span class="wb-keuze"><span class="wb-sw" style="background:${KLEUR.keuze[keuze]}"></span>${KEUZE_KORT[keuze]}</span>`;
}

function actieItem(a, soort) {
  const laat = a.te_laat ? `<span class="wb-tag is-critical"><svg class="wk-ic"><use href="#ic-alert"/></svg> Te laat</span>` : "";
  const test = a.test ? `<span class="wb-tag is-attention">Test</span>` : "";
  const wat = `${escAttr(a.label)} <b>${escAttr(euro(a.bedrag_cent))}</b>${a.deadline_tekst ? ` · vóór ${escAttr(a.deadline_tekst)}` : ""}`;
  const verzoek = a.verzoek ? `<p class="wb-a-meta">Verzoek verstuurd door ${escAttr(a.verzoek.door)} · ${escAttr(tijdstip(a.verzoek.op))}</p>` : "";
  const wa = a.wa_link ? `<a class="wk-btn small" href="${escAttr(a.wa_link)}" target="_blank" rel="noopener"><svg class="wk-ic"><use href="#ic-message"/></svg> WhatsApp</a>` : "";
  const ids = `data-id="${escAttr(a.id)}" data-fase="${escAttr(a.fase)}" data-verwacht="${escAttr(a.betaalstatus)}" data-naam="${escAttr(a.naam)}"`;
  const knoppen = soort === "versturen"
    ? `${wa}<button class="wk-btn small primary-soft" type="button" data-verzoek="1" ${ids}><svg class="wk-ic"><use href="#ic-check"/></svg> Verzoek verstuurd</button>
       <button class="wk-btn small wb-ghost" type="button" data-ontvangen ${ids}>Al betaald</button>`
    : `<button class="wk-btn small primary-soft" type="button" data-ontvangen ${ids}><svg class="wk-ic"><use href="#ic-check"/></svg> Betaling ontvangen</button>
       ${wa}<button class="wk-btn small wb-ghost" type="button" data-verzoek="0" ${ids}>Niet verstuurd</button>`;
  return `<article class="wb-a${a.te_laat ? " is-laat" : ""}">
    <div class="wb-a-kop"><h4>${escAttr(a.naam)}</h4>${test}${laat}</div>
    <p class="wb-a-wat">${wat}</p>
    <p class="wb-a-meta">${keuzeTag(a.betaalkeuze)}</p>${verzoek}
    <div class="wb-a-acts">${knoppen}</div>
  </article>`;
}

// Instroom: cumulatief aantal inschrijvingen, één lijn met crosshair-tooltip.
function tekenTijdlijn() {
  const el = $("#wb-c-tijd");
  if (!el || huidigeTab() !== "dashboard") return;
  const punten = dash().tijdlijn;
  if (punten.length < 2) {
    el.innerHTML = `<p class="wb-leeg-klein">${punten.length
      ? `${meervoud(punten[0].cumulatief, "inschrijving", "inschrijvingen")} op ${escAttr(datumKort(punten[0].datum))}. De lijn verschijnt zodra er op een tweede dag inschrijvingen bij komen.`
      : "Nog geen inschrijvingen."}</p>`;
    return;
  }
  const W = Math.max(el.clientWidth, 280), H = 190, P = { l: 34, r: 40, t: 16, b: 28 };
  const t0 = Date.parse(punten[0].datum), t1 = Date.parse(punten[punten.length - 1].datum);
  const ymax = niceMax(punten[punten.length - 1].cumulatief);
  const x = t => P.l + ((t - t0) / (t1 - t0)) * (W - P.l - P.r);
  const y = v => H - P.b - (v / ymax) * (H - P.t - P.b);
  const xy = punten.map(p => [x(Date.parse(p.datum)), y(p.cumulatief)]);
  const lijn = xy.map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)},${b.toFixed(1)}`).join("");
  const vlak = `${lijn}L${xy[xy.length - 1][0].toFixed(1)},${y(0)}L${xy[0][0].toFixed(1)},${y(0)}Z`;
  const ticks = [0, ymax / 2, ymax].filter(v => Number.isInteger(v));
  const [ex, ey] = xy[xy.length - 1];
  el.innerHTML = `<svg class="wb-lijn" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${escAttr(`Inschrijvingen van ${datumKort(punten[0].datum)} tot ${datumKort(punten[punten.length - 1].datum)}: nu ${punten[punten.length - 1].cumulatief}`)}">
    ${ticks.map(v => `<line class="wb-grid" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="wb-as" x="${P.l - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("")}
    <text class="wb-as" x="${P.l}" y="${H - 8}">${escAttr(datumKort(punten[0].datum))}</text>
    <text class="wb-as" x="${W - P.r}" y="${H - 8}" text-anchor="end">${escAttr(datumKort(punten[punten.length - 1].datum))}</text>
    <path d="${vlak}" fill="${KLEUR.lijn}" opacity=".1"/>
    <path d="${lijn}" fill="none" stroke="${KLEUR.lijn}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${ex}" cy="${ey}" r="4" fill="${KLEUR.lijn}" stroke="var(--wb-surface)" stroke-width="2"/>
    <text class="wb-eind" x="${ex + 8}" y="${ey + 4}">${punten[punten.length - 1].cumulatief}</text>
    <line class="wb-kruis" id="wb-kruis" x1="0" x2="0" y1="${P.t}" y2="${H - P.b}" visibility="hidden"/>
    <rect class="wb-hit" x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${H - P.t - P.b}" fill="transparent"/>
  </svg>`;
  const svg = el.querySelector("svg"), kruis = el.querySelector("#wb-kruis");
  svg.querySelector(".wb-hit").addEventListener("pointermove", ev => {
    const rect = svg.getBoundingClientRect(), px = ev.clientX - rect.left;
    let i = 0;
    xy.forEach(([a], j) => { if (Math.abs(a - px) < Math.abs(xy[i][0] - px)) i = j; });
    kruis.setAttribute("x1", xy[i][0]); kruis.setAttribute("x2", xy[i][0]); kruis.setAttribute("visibility", "visible");
    const p = punten[i];
    toonTip(`${meervoud(p.cumulatief, "inschrijving", "inschrijvingen")} totaal`, `${datumKort(p.datum)} · +${p.aantal} die dag`, ev.clientX, ev.clientY);
  });
  svg.querySelector(".wb-hit").addEventListener("pointerleave", () => { kruis.setAttribute("visibility", "hidden"); verbergTip(); });
}

// ── Tooltip (hover én toetsenbordfocus; waarden staan ook in de legenda) ─────
function toonTip(waarde, label, px, py) {
  const tip = $("#wb-tip");
  tip.replaceChildren();
  const b = document.createElement("strong"); b.textContent = waarde;
  const s = document.createElement("span"); s.textContent = label;
  tip.append(b, s);
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(Math.max(8, px - r.width / 2), innerWidth - r.width - 8)}px`;
  tip.style.top = `${Math.max(8, py - r.height - 14)}px`;
}
function verbergTip() { $("#wb-tip").hidden = true; }
function tipVan(el) {
  const [label, waarde] = el.dataset.tip.split(": ");
  return { waarde: waarde || el.dataset.tip, label: waarde ? label : "" };
}
document.addEventListener("pointermove", e => {
  const el = e.target.closest?.("[data-tip]");
  if (!el) return;
  const t = tipVan(el); toonTip(t.waarde, t.label, e.clientX, e.clientY);
});
document.addEventListener("pointerout", e => { if (e.target.closest?.("[data-tip]")) verbergTip(); });
document.addEventListener("focusin", e => {
  const el = e.target.closest?.("[data-tip]");
  if (!el) return;
  const r = el.getBoundingClientRect(), t = tipVan(el);
  toonTip(t.waarde, t.label, r.left + r.width / 2, r.top);
});
document.addEventListener("focusout", e => { if (e.target.closest?.("[data-tip]")) verbergTip(); });
let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => data && tekenTijdlijn(), 120); });

// ── Inschrijvingen ──────────────────────────────────────────────────────────
function optie(labels, huidig) {
  return Object.entries(labels).map(([k, l]) => `<option value="${escAttr(k)}"${k === huidig ? " selected" : ""}>${escAttr(l)}</option>`).join("");
}
function historieRegel(h, L) {
  if (h.veld === "betaalverzoek") {
    const fase = (L.betaalfase || {})[h.naar || h.van] || h.naar || h.van;
    return `${escAttr(tijdstip(h.op))} · ${escAttr(h.door)}: betaalverzoek ${escAttr(fase.toLowerCase())} ${h.naar ? "verstuurd" : "teruggezet naar niet verstuurd"}`;
  }
  return `${escAttr(tijdstip(h.op))} · ${escAttr(h.door)}: ${escAttr((L[h.veld] || {})[h.van] || h.van)} → ${escAttr((L[h.veld] || {})[h.naar] || h.naar)}`;
}

function tekenLijst() {
  const L = data.labels, versie = data.instellingen.voorwaarden_versie || 0;
  const q = zoek.trim().toLowerCase();
  const rijen = data.inschrijvingen.filter(r => {
    if (!metTest && r.test) return false;
    if (lijstFilter === "actie" && !r.actie) return false;
    if (lijstFilter === "laat" && !(r.actie && r.actie.te_laat)) return false;
    if (lijstFilter === "geannuleerd" && r.inschrijfstatus !== "geannuleerd") return false;
    if (lijstFilter !== "geannuleerd" && lijstFilter !== "alle" && r.inschrijfstatus === "geannuleerd") return false;
    return !q || [r.naam, r.email, r.telefoon].some(v => String(v || "").toLowerCase().includes(q));
  });
  const echtActief = data.inschrijvingen.filter(r => !r.test && r.inschrijfstatus !== "geannuleerd").length;
  $("#wb-tab-n").textContent = echtActief ? `(${echtActief})` : "";
  if (!rijen.length) {
    $("#wb-rijen").innerHTML = `<p class="wb-leeg">${data.inschrijvingen.length ? "Niets gevonden met dit filter." : "Nog geen inschrijvingen."}</p>`;
    return;
  }
  $("#wb-rijen").innerHTML = rijen.map(r => {
    const a = r.akkoord || {}, act = r.actie;
    const tags = [
      r.test ? `<span class="wb-tag is-attention">Test${r.test_door ? " · " + escAttr(r.test_door) : ""}</span>` : "",
      r.mogelijk_dubbel ? `<span class="wb-tag is-attention">Mogelijk dubbel</span>` : "",
      act && act.te_laat ? `<span class="wb-tag is-critical"><svg class="wk-ic"><use href="#ic-alert"/></svg> Te laat</span>` : "",
    ].join("");
    const volgende = act
      ? `<p class="wb-volgende"><span class="wb-lbl-klein">Volgende stap</span> ${escAttr(act.label)} <b>${escAttr(euro(act.bedrag_cent))}</b>${act.deadline_tekst ? ` · vóór ${escAttr(act.deadline_tekst)}` : ""}${act.verzoek ? ` · verzoek verstuurd` : ` · verzoek nog sturen`}</p>`
      : `<p class="wb-volgende is-klaar"><svg class="wk-ic"><use href="#ic-check"/></svg> ${r.inschrijfstatus === "geannuleerd" ? "Geannuleerd" : r.betaalstatus === "betaald" ? "Volledig betaald" : escAttr(L.betaalstatus[r.betaalstatus] || "")}</p>`;
    const hist = (r.historie || []).slice().reverse().map(h => `<li>${historieRegel(h, L)}</li>`).join("");
    return `<article class="wb-rij${r.test ? " is-test" : ""}${r.inschrijfstatus === "geannuleerd" ? " is-geannuleerd" : ""}">
      <div class="wb-rij-kop"><h3>${escAttr(r.naam)}</h3>${tags}</div>
      <p class="wb-rij-keuze">${keuzeTag(r.betaalkeuze)}</p>
      <div class="wb-contact"><span>${escAttr(r.email)}</span><span>${escAttr(r.telefoon)}</span></div>
      ${volgende}
      <dl class="wb-akkoord">
        <dt>Ingeschreven</dt><dd>${escAttr(tijdstip(r.ingeschreven_op))}</dd>
        <dt>Akkoord prijs</dt><dd>${escAttr(euro(a.deelnemersprijs_cent))} · aanbetaling ${escAttr(euro(a.aanbetaling_cent))}</dd>
        <dt>Voorwaarden</dt><dd>versie ${escAttr(a.voorwaarden_versie)}${a.voorwaarden_versie !== versie ? " (niet de huidige)" : ""}</dd>
      </dl>
      <div class="wb-statussen">
        <label class="wk-field">Inschrijfstatus
          <select data-id="${escAttr(r.id)}" data-veld="inschrijfstatus" data-verwacht="${escAttr(r.inschrijfstatus)}">${optie(L.inschrijfstatus, r.inschrijfstatus)}</select></label>
        <label class="wk-field">Betaalstatus
          <select data-id="${escAttr(r.id)}" data-veld="betaalstatus" data-verwacht="${escAttr(r.betaalstatus)}">${optie(L.betaalstatus, r.betaalstatus)}</select></label>
      </div>
      <div class="wb-rij-voet">
        ${hist ? `<details class="wb-historie"><summary>Wijzigingen (${r.historie.length})</summary><ul>${hist}</ul></details>` : `<span class="wb-historie">Nog geen wijzigingen</span>`}
        ${r.test ? `<button class="wk-btn small wb-ghost wb-weg" type="button" data-weg="${escAttr(r.id)}"><svg class="wk-ic"><use href="#ic-trash"/></svg> Test verwijderen</button>` : ""}
      </div>
    </article>`;
  }).join("");
}

// ── Instellingen ────────────────────────────────────────────────────────────
function tekenInstellingen(forceer = false) {
  const open = data.open, mist = data.ontbreekt || [], inst = data.instellingen;
  const chip = $("#wb-open-chip");
  chip.textContent = open ? "Open" : "Gesloten";
  chip.className = "wb-chip " + (open ? "is-success" : "is-stale");
  $("#wb-open-uitleg").textContent = open
    ? "Iedereen met de link kan zich nu definitief inschrijven."
    : `Bezoekers zien: “${data.gesloten_tekst}”.`;
  $("#wb-ontbreekt").hidden = open || !mist.length;
  $("#wb-ontbreekt").textContent = mist.length ? `Openen kan pas als dit is ingevuld: ${mist.join(", ")}.` : "";
  const btn = $("#wb-open-btn");
  btn.textContent = open ? "Inschrijving sluiten" : "Inschrijving openen";
  btn.classList.toggle("primary", !open && !mist.length);
  btn.disabled = !open && mist.length > 0;

  const f = $("#wb-kosten");
  if (forceer || !f.dataset.bewerkt) {
    f.prijs.value = centNaarInvoer(inst.deelnemersprijs_cent);
    f.aanbetaling.value = centNaarInvoer(inst.aanbetaling_cent);
    f.betaaltermijn.value = inst.betaaltermijn || "";
    f.voorwaarden.value = inst.voorwaarden || "";
    f.dataset.versie = inst.voorwaarden_versie || 0;
    delete f.dataset.bewerkt;
  }
  const v = inst.voorwaarden_versie || 0;
  $("#wb-versie").textContent = v
    ? `Huidige versie ${v} · vastgesteld door ${inst.vastgesteld_door || "onbekend"} op ${tijdstip(inst.vastgesteld_op)}.`
    : "Nog niets vastgesteld.";

  const dl = $("#wb-deadlines");
  if (forceer || !dl.dataset.bewerkt) {
    dl.eerste.value = inst.deadline_eerste || "";
    dl.rest.value = inst.deadline_rest || "";
    delete dl.dataset.bewerkt;
  }
}

function render(forceer = false) {
  $("#wb-login").hidden = true; $("#wb-app").hidden = false;
  $("#wb-wie").textContent = data.wie ? `Ingelogd als ${data.wie}` : "";
  $("#wb-naar-app").hidden = rol !== "coach";
  $$(".wb-met-test").forEach(c => { c.checked = metTest; });
  toonTab();
  tekenDashboard(); tekenLijst(); tekenInstellingen(forceer);
}

async function laad(forceer = false) {
  data = await api("/api/weekend/beheer");
  render(forceer);
}
function metNieuweData(d, forceer = false) { data = { ...d, wie: data.wie }; render(forceer); }

// ── Acties ──────────────────────────────────────────────────────────────────
$$(".wb-met-test").forEach(c => c.addEventListener("change", () => {
  metTest = c.checked;
  try { localStorage.setItem("wb_met_test", metTest ? "1" : "0"); } catch {}
  render();
}));
$$(".wb-ververs").forEach(b => b.addEventListener("click", () => laad().then(() => toast("Bijgewerkt.")).catch(fout)));
$("#wb-zoek").addEventListener("input", e => { zoek = e.target.value; tekenLijst(); });
$("#wb-lijst-filter").addEventListener("click", e => {
  const b = e.target.closest("button[data-f]");
  if (!b) return;
  lijstFilter = b.dataset.f;
  $$("#wb-lijst-filter button").forEach(x => x.classList.toggle("on", x === b));
  tekenLijst();
});

// Dashboard-acties: verzoek verstuurd / terugzetten / betaling ontvangen.
$("#wb-v-dashboard").addEventListener("click", async e => {
  const b = e.target.closest("button[data-verzoek], button[data-ontvangen]");
  if (!b) return;
  const { id, fase, verwacht, naam } = b.dataset;
  b.disabled = true;
  try {
    if ("verzoek" in b.dataset) {
      const verstuurd = b.dataset.verzoek === "1";
      metNieuweData(await post(`/api/weekend/beheer/inschrijvingen/${encodeURIComponent(id)}/verzoek`, { fase, verstuurd }));
      toast(verstuurd ? `Betaalverzoek aan ${naam} gemarkeerd als verstuurd.` : `${naam} staat weer bij ‘nog sturen’.`);
    } else {
      const naar = NA_ONTVANGST[fase];
      metNieuweData(await post(`/api/weekend/beheer/inschrijvingen/${encodeURIComponent(id)}/betaalstatus`, { waarde: naar, verwacht }));
      toast(naar === "aanbetaling" ? `Aanbetaling van ${naam} ontvangen. De restbetaling staat nu klaar.` : `${naam} heeft volledig betaald.`);
    }
  } catch (err) { b.disabled = false; fout(err); }
});

$("#wb-kosten").addEventListener("input", () => { $("#wb-kosten").dataset.bewerkt = "1"; });
$("#wb-kosten").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  const prijs = parseEuroCent(f.prijs.value), aanbetaling = parseEuroCent(f.aanbetaling.value);
  if (Number.isNaN(prijs)) return toast("De deelnemersprijs is geen geldig bedrag (bijv. 249 of 249,50).", true);
  if (Number.isNaN(aanbetaling)) return toast("De aanbetaling is geen geldig bedrag (bijv. 50 of 49,50).", true);
  const ok = await bevestig("Kosten en voorwaarden opslaan?",
    "Dit wordt een nieuwe voorwaardenversie. Bestaande inschrijvingen houden de versie waarmee ze akkoord gingen.", "Opslaan");
  if (!ok) return;
  const btn = $("#wb-kosten-btn"); btn.disabled = true;
  try {
    const d = await post("/api/weekend/beheer/instellingen", {
      deelnemersprijs_cent: prijs, aanbetaling_cent: aanbetaling,
      betaaltermijn: f.betaaltermijn.value, voorwaarden: f.voorwaarden.value,
      verwacht_versie: Number(f.dataset.versie || 0),
    });
    metNieuweData(d, true);
    toast(`Opgeslagen · versie ${d.instellingen.voorwaarden_versie}.`);
  } catch (err) { fout(err); }
  btn.disabled = false;
});

$("#wb-deadlines").addEventListener("input", () => { $("#wb-deadlines").dataset.bewerkt = "1"; });
$("#wb-deadlines").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  try {
    metNieuweData(await post("/api/weekend/beheer/deadlines", { deadline_eerste: f.eerste.value, deadline_rest: f.rest.value }), true);
    toast("Deadlines opgeslagen.");
  } catch (err) { fout(err); }
});

$("#wb-open-btn").addEventListener("click", async () => {
  const open = !data.open;
  const ok = await bevestig(open ? "Inschrijving openen?" : "Inschrijving sluiten?",
    open ? `Vanaf nu kan iedereen met de link zich definitief inschrijven met voorwaardenversie ${data.instellingen.voorwaarden_versie}.`
      : "Bezoekers zien weer dat de inschrijving binnenkort opent. Bestaande inschrijvingen blijven staan.",
    open ? "Openen" : "Sluiten");
  if (!ok) return;
  try { metNieuweData(await post("/api/weekend/beheer/inschrijving-open", { open })); toast(open ? "Inschrijving is open." : "Inschrijving is gesloten."); }
  catch (err) { fout(err); }
});

$("#wb-rijen").addEventListener("change", async e => {
  const sel = e.target.closest("select[data-veld]");
  if (!sel) return;
  const { id, veld, verwacht } = sel.dataset;
  sel.disabled = true;
  try {
    metNieuweData(await post(`/api/weekend/beheer/inschrijvingen/${encodeURIComponent(id)}/${veld}`, { waarde: sel.value, verwacht }));
    toast(`${veld === "betaalstatus" ? "Betaalstatus" : "Inschrijfstatus"} bijgewerkt.`);
  } catch (err) { sel.value = verwacht; sel.disabled = false; fout(err); }
});

$("#wb-rijen").addEventListener("click", async e => {
  const b = e.target.closest("[data-weg]");
  if (!b) return;
  const ok = await bevestig("Testinschrijving verwijderen?", "Alleen testinschrijvingen kunnen weg. Dit is niet terug te draaien.", "Verwijderen");
  if (!ok) return;
  try { metNieuweData(await api(`/api/weekend/beheer/inschrijvingen/${encodeURIComponent(b.dataset.weg)}`, { method: "DELETE" })); toast("Testinschrijving verwijderd."); }
  catch (err) { fout(err); }
});

async function start() {
  try {
    const me = await fetch("/api/me", { headers: getToken() ? { Authorization: "Bearer " + getToken() } : {}, cache: "no-store" }).then(r => r.json());
    if (!me.ingelogd) return toonLogin();
    rol = me.rol || "";
    await laad(true);
  } catch (err) {
    if (err.message !== "auth") { toonLogin("Weekendbeheer kon niet worden geladen."); }
  }
}
start();
