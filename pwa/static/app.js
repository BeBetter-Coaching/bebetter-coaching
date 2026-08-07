// BeBetter PWA — native app-schil. Vanilla JS, geen build.
// Onderbalk-navigatie + dashboard-home + skeletons. Vier modules op één schil:
// dashboard, atleten, intake en strippenkaart — allemaal op dezelfde data als
// Streamlit. Toont wat Streamlit niet kan: direct reageren zonder herladen,
// swipe-om-af-te-boeken, installeren als app en werken zonder netwerk (queue).

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = (u, opt) => fetch(u, opt).then(r => r.json());
const jpost = (u, body, method = "POST") => api(u, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const haptic = ms => navigator.vibrate?.(ms);
const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const ic = n => `<svg class="ic"><use href="#ic-${n}"/></svg>`;

// ── Onderbalk-navigatie ──────────────────────────────────────────────────────
const laders = {};   // view -> laadfunctie (eenmalig lui laden per module)
const geladen = {};
let huidigeView = "home";

function toonView(view) {
  huidigeView = view;
  $$(".view").forEach(v => {
    const on = v.dataset.view === view;
    v.classList.toggle("on", on);
    if (on) { v.classList.remove("slidein"); void v.offsetWidth; v.classList.add("slidein"); }
  });
  $$(".nav-item").forEach(n => n.classList.toggle("on", n.dataset.openView === view));
  $("#scroller").scrollTo({ top: 0 });
  haptic(6);
  if (view === "home") renderHome();
  if (laders[view] && !geladen[view]) { geladen[view] = true; laders[view](); }
}
$$("[data-open-view]").forEach(b => b.addEventListener("click", () => toonView(b.dataset.openView)));

// Begroeting + datum voor de home-hero (zelfde toon als de Streamlit-home)
function groetInfo() {
  const dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"];
  const maanden = ["januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december"];
  const nu = new Date(), u = nu.getHours();
  const groet = u < 12 ? "Goedemorgen" : (u < 18 ? "Goedemiddag" : "Goedenavond");
  return { groet: `${groet}, Coach`,
    datum: `${dagen[(nu.getDay() + 6) % 7]} ${nu.getDate()} ${maanden[nu.getMonth()]}` };
}
// Laptop/desktop? Bepaalt of Atleten master-detail toont (lijst + dossier naast elkaar)
const isDesktop = () => matchMedia("(min-width:900px)").matches;

// "Binnenkort"-modules op de Meer-pagina: laat zien dat de héle app hier komt
[["file", "Feedback"], ["file", "Schema-verloop"], ["file", "Schema bouwen"],
 ["file", "Documenten"], ["alert", "Teampuls"], ["ticket", "Races"], ["settings", "Administratie"]]
  .forEach(([icn, t]) => {
    const el = document.createElement("div");
    el.className = "mrow soon-row";
    el.innerHTML = `<span class="mrow-ic">${ic(icn)}</span>
      <span class="mrow-body"><span class="mrow-title">${t}</span></span>
      <span class="mrow-tag soon-tag">binnenkort</span>`;
    $("#soon").appendChild(el);
  });

// ── Uitklappers + segmenten ────────────────────────────────────────────────
function bindAccordions(root = document) {
  root.querySelectorAll(".acc-toggle").forEach(btn => {
    if (btn._bound) return; btn._bound = true;
    btn.addEventListener("click", () => $("#" + btn.dataset.target).classList.toggle("open"));
  });
  root.querySelectorAll(".seg").forEach(seg => {
    if (seg._bound) return; seg._bound = true;
    seg.addEventListener("click", e => {
      const b = e.target.closest("button[data-v]"); if (!b) return;
      seg.dataset.value = b.dataset.v;
      seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    });
  });
}
bindAccordions();

function melding(txt, isErr = false) {
  const m = $("#msg");
  m.textContent = txt; m.classList.toggle("err", isErr); m.hidden = !txt;
  if (txt) setTimeout(() => { m.hidden = true; }, 4000);
}

// Cijfers laten "optellen" bij het laden — high-end apps voelen levend
function countUp(el) {
  const doel = +el.dataset.count || 0;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches || doel <= 0) { el.textContent = doel; return; }
  const dur = 650, t0 = performance.now();
  (function step(t) {
    const p = Math.min(1, (t - t0) / dur);
    el.textContent = Math.round(doel * (1 - Math.pow(1 - p, 3)));   // ease-out
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}

// Skeleton-blokken tonen terwijl er geladen wordt (i.p.v. kale "Laden…")
function skeleton(box, rijen = 3) {
  box.innerHTML = Array.from({ length: rijen },
    () => '<div class="skel-card"><div class="skel skel-line w60"></div><div class="skel skel-line w40"></div></div>').join("");
}

// ════════════════════════════════════════════════════════════════════════════
// HOME — dashboard: glanceable overzicht van wat er speelt
// ════════════════════════════════════════════════════════════════════════════
async function renderHome() {
  const box = $("#home-body");
  if (!box.dataset.done) box.innerHTML = `
    <div class="skel" style="height:150px;border-radius:18px;margin:10px 0 6px"></div>
    <div class="skel-card" style="margin-top:12px"><div class="skel skel-line w60"></div></div>`;

  const [inbox, ath, kaarten] = await Promise.all([
    api("/api/intake/inbox").catch(() => ({ inbox: [] })),
    api("/api/dossier/athletes").catch(() => ({ athletes: [] })),
    api("/api/kaarten").catch(() => ({ kaarten: [] })),
  ]);
  const nNieuw = (inbox.inbox || []).length;
  const nAtl = (ath.athletes || []).length;
  const kn = kaarten.kaarten || [];
  const vol = kn.filter(k => k.rest <= 0);
  const bijna = kn.filter(k => k.rest > 0 && k.rest <= 1);
  box.dataset.done = "1";
  setBadge(nNieuw);

  const items = [];
  if (nNieuw) items.push(kaartItem("mail", `${nNieuw} nieuwe intake${nNieuw === 1 ? "" : "s"}`,
    "Bekijk en neem over als atleet", "intake", true));
  vol.forEach(k => items.push(kaartItem("ticket", `Strippenkaart vol — ${esc(k.naam)}`,
    "Kaart is op, tijd voor een nieuwe", "strippen", true)));
  bijna.forEach(k => items.push(kaartItem("ticket", `${esc(k.naam)} — nog 1 training`,
    "Strippenkaart bijna vol", "strippen", false)));

  const g = groetInfo();
  const nBijna = vol.length + bijna.length;
  box.innerHTML = `
    <div class="hero">
      <div class="hero-top">
        <div><p class="hero-greet">${g.groet}</p><p class="hero-date">${g.datum}</p></div>
        <button class="hero-gear" data-open-view="meer" aria-label="Meer">${ic("settings")}</button>
      </div>
      <div class="hero-stats">
        <button class="hstat teal" data-open-view="intake"><b data-count="${nNieuw}">0</b><span>nieuwe intake${nNieuw === 1 ? "" : "s"}</span></button>
        <button class="hstat" data-open-view="atleten"><b data-count="${nAtl}">0</b><span>${nAtl === 1 ? "atleet" : "atleten"}</span></button>
        <button class="hstat amber" data-open-view="strippen"><b data-count="${nBijna}">0</b><span>kaart${nBijna === 1 ? "" : "en"} bijna vol</span></button>
      </div>
    </div>

    <p class="sec-label">Vandaag</p>
    ${items.length ? items.join("") :
      `<div class="leeg">${ic("check")}<p>Niks dat nu je aandacht vraagt.<br>Mooie dag om te coachen.</p></div>`}

    <p class="sec-label">Snel naar</p>
    <div class="quick">
      <button class="qtile" data-open-view="intake">${ic("user-plus")}<span>Nieuwe intake</span></button>
      <button class="qtile" data-open-view="strippen">${ic("ticket")}<span>Strippenkaart</span></button>
    </div>`;

  $$("[data-open-view]", box).forEach(b => b.addEventListener("click", () => toonView(b.dataset.openView)));
  $$("[data-count]", box).forEach(countUp);
  bronStatus(kaarten.cloud);
}

function kaartItem(icn, titel, sub, view, alert) {
  return `<button class="listcard" data-open-view="${view}">
    <span class="lc-ic ${alert ? "warn" : ""}">${ic(icn)}</span>
    <span class="lc-body"><span class="lc-title">${titel}</span><span class="lc-sub">${sub}</span></span>
    ${ic("chevron")}</button>`;
}

function setBadge(n) {
  $$(".nav-badge").forEach(b => {           // onderbalk + zijbalk allebei
    if (n > 0) { b.textContent = n; b.hidden = false; } else b.hidden = true;
  });
}
function bronStatus(cloud) {
  const el = $("#bron");
  if (!el) return;
  el.textContent = cloud
    ? "Verbonden met de gedeelde opslag (GitHub) — zelfde data als Streamlit."
    : "Lokale opslag (zelfde bestand als Streamlit lokaal).";
}

// ── Offline-queue: acties die offline gebeuren, verstuurd zodra je online bent ─
const QKEY = "bb_queue";
const getQ = () => JSON.parse(localStorage.getItem(QKEY) || "[]");
const setQ = q => localStorage.setItem(QKEY, JSON.stringify(q));
function enqueue(item) { const q = getQ(); q.push(item); setQ(q); toonOffline(); }

async function flush() {
  let q = getQ();
  if (!q.length) return;
  const rest = [];
  for (const it of q) {
    try { const r = await api(it.url, { method: "POST" }); if (!r.ok) rest.push(it); }
    catch { rest.push(it); }
  }
  setQ(rest); toonOffline();
  if (rest.length < q.length) { melding("Openstaande afboekingen verstuurd."); laad(); }
}

function toonOffline() {
  const off = !navigator.onLine, q = getQ().length;
  const el = $("#offline");
  if (!off && !q) { el.hidden = true; return; }
  el.hidden = false;
  el.textContent = off
    ? `Offline — je ziet de laatste stand. ${q ? q + " afboeking(en) wachten; ze gaan mee zodra je online bent." : "Wijzigingen worden verzonden zodra je weer online bent."}`
    : `Verbinding terug — ${q} afboeking(en) worden verstuurd…`;
}
window.addEventListener("online", () => { toonOffline(); flush(); });
window.addEventListener("offline", toonOffline);

// ── App installeren ────────────────────────────────────────────────────────
let deferred = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferred = e; $("#install").hidden = false; });
window.addEventListener("appinstalled", () => { $("#install").hidden = true; melding("Geïnstalleerd."); });

$("#install").addEventListener("click", async () => {
  if (deferred) {
    deferred.prompt();
    const keuze = await deferred.userChoice;
    deferred = null;
    if (keuze.outcome === "accepted") $("#install").hidden = true;
    return;
  }
  const ua = navigator.userAgent;
  const isSafari = /safari/i.test(ua) && !/chrome|crios|edg|android/i.test(ua);
  const isIOS = /iphone|ipad|ipod/i.test(ua);
  if (isIOS) melding("iPhone/iPad: tik op de deelknop → ‘Zet op beginscherm’.");
  else if (isSafari) melding("Safari op Mac: menubalk ‘Archief’ → ‘Voeg toe aan Dock’.");
  else melding("Klik op het installeer-icoon in de adresbalk, of het menu → ‘App installeren’.");
});
if (!matchMedia("(display-mode: standalone)").matches) $("#install").hidden = false;

// ════════════════════════════════════════════════════════════════════════════
// STRIPPENKAART
// ════════════════════════════════════════════════════════════════════════════
async function laad() {
  const lijst = $("#lijst");
  if (!lijst.children.length) skeleton(lijst, 3);
  let data;
  try { data = await api("/api/kaarten"); }
  catch { lijst.innerHTML = '<p class="muted center">Offline — laatste bekende stand.</p>'; return; }
  bronStatus(data.cloud);
  lijst.innerHTML = "";
  if (!data.kaarten.length) {
    lijst.innerHTML = '<div class="leeg">' + ic("ticket") + '<p>Nog geen strippenkaarten.<br>Voeg er hierboven een toe.</p></div>';
    return;
  }
  data.kaarten.forEach(k => lijst.appendChild(kaartEl(k)));
}

// Signatuur-ring: omtrek van r=31 → vullen op basis van gebruikt/totaal (echte data)
const RING_C = 2 * Math.PI * 31;   // ≈ 194.8
function setRing(el, gebruikt, totaal) {
  const rest = Math.max(0, totaal - gebruikt);
  const frac = totaal ? Math.min(1, gebruikt / totaal) : 0;
  const arc = $(".ring-arc", el);
  arc.style.strokeDasharray = RING_C;
  if (!arc.style.strokeDashoffset) arc.style.strokeDashoffset = RING_C;   // leeg starten → loopt vol
  requestAnimationFrame(() => { arc.style.strokeDashoffset = RING_C * (1 - frac); });
  $(".ring-rest", el).textContent = rest;
  $(".ring-tot", el).textContent = "van " + totaal;
  const st = $(".k-status", el);
  if (rest <= 0) { st.className = "k-status op"; st.innerHTML = `${ic("alert")} vol`; }
  else if (rest <= 1) { st.className = "k-status warn"; st.innerHTML = `${ic("alert")} bijna vol`; }
  else { st.className = "k-status ok"; st.innerHTML = `${ic("check")} op schema`; }
}

function kaartEl(k) {
  const el = $("#kaart-tpl").content.firstElementChild.cloneNode(true);
  el.dataset.naam = k.naam; el.dataset.totaal = k.totaal; el.dataset.gebruikt = k.gebruikt;
  $(".k-naam", el).textContent = k.naam;
  $(".k-tel", el).textContent = k.telefoon || "geen nummer";
  el.classList.toggle("bijna", k.rest > 0 && k.rest <= 1);
  el.classList.toggle("op", k.rest <= 0);
  setRing(el, k.gebruikt, k.totaal);
  $(".k-laatst", el).textContent = k.laatst ? "Laatst afgeboekt: " + k.laatst : "";

  const afBtn = $(".k-af", el);
  afBtn.disabled = k.rest <= 0;
  afBtn.addEventListener("click", () => afboek(k.naam, el));
  const tBtn = $(".k-terug", el);
  tBtn.disabled = k.gebruikt <= 0;
  tBtn.addEventListener("click", () => actie(`/api/kaarten/${encodeURIComponent(k.naam)}/terug`, "POST"));
  $(".k-del", el).addEventListener("click", () => {
    if (confirm(`Strippenkaart van ${k.naam} verwijderen?`))
      actie(`/api/kaarten/${encodeURIComponent(k.naam)}`, "DELETE");
  });
  addSwipe(el);
  return el;
}

async function actie(url, method) {
  const r = await api(url, { method }).catch(() => null);
  if (!r) return melding("Geen verbinding.", true);
  if (!r.ok) return melding(r.err || "Er ging iets mis.", true);
  laad();
}

function optimistischAf(el) {
  const tot = +el.dataset.totaal, geb = +el.dataset.gebruikt + 1;
  el.dataset.gebruikt = geb;
  const rest = Math.max(0, tot - geb);
  el.classList.toggle("bijna", rest > 0 && rest <= 1);
  el.classList.toggle("op", rest <= 0);
  setRing(el, geb, tot);                       // ring loopt vol + status + getal
  const restEl = $(".ring-rest", el);
  restEl.classList.remove("bump"); void restEl.offsetWidth; restEl.classList.add("bump");
  const fg = $(".swipe-fg", el);
  fg.classList.remove("flash"); void fg.offsetWidth; fg.classList.add("flash");
  $(".k-af", el).disabled = rest <= 0;
  return rest;
}

async function afboek(naam, el) {
  if (+el.dataset.totaal - +el.dataset.gebruikt <= 0) return;
  haptic(15);
  optimistischAf(el);
  const url = `/api/kaarten/${encodeURIComponent(naam)}/afboeken`;
  if (!navigator.onLine) {
    enqueue({ url });
    $(".k-laatst", el).textContent = "Zojuist afgeboekt · ⏳ wordt verzonden zodra je online bent";
    return;
  }
  const r = await api(url, { method: "POST" }).catch(() => null);
  if (!r) { enqueue({ url }); $(".k-laatst", el).textContent = "Zojuist afgeboekt · ⏳ wordt nog verzonden"; return; }
  if (!r.ok) { melding(r.err || "Afboeken mislukt.", true); return laad(); }
  await laad();
  const kaart = [...document.querySelectorAll(".kaart")].find(c => c.dataset.naam === naam);
  if (kaart) toonWA(kaart, r.info);
}

function toonWA(kaart, info) {
  const wa = $(".wa", kaart);
  const link = $(".wa-btn", wa);
  if (info.wa_link) { link.href = info.wa_link; link.style.display = ""; $(".wa-msg", wa).textContent = info.bericht; }
  else { link.style.display = "none"; $(".wa-msg", wa).textContent = info.bericht + "  (geen telefoonnummer — vul het bij de kaart in)"; }
  wa.classList.remove("hidden");
  kaart.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function addSwipe(el) {
  const fg = $(".swipe-fg", el);
  let x0 = 0, dx = 0, drag = false;
  fg.addEventListener("pointerdown", e => {
    if (e.target.closest("button,a")) return;
    drag = true; x0 = e.clientX; dx = 0;
    fg.style.transition = "none"; fg.setPointerCapture(e.pointerId);
  });
  fg.addEventListener("pointermove", e => {
    if (!drag) return;
    dx = Math.min(0, e.clientX - x0);
    fg.style.transform = `translateX(${Math.max(dx, -150)}px)`;
  });
  const eind = () => {
    if (!drag) return;
    drag = false; fg.style.transition = ""; fg.style.transform = "";
    const rest = +el.dataset.totaal - +el.dataset.gebruikt;
    if (dx < -90 && rest > 0) afboek(el.dataset.naam, el);
  };
  fg.addEventListener("pointerup", eind);
  fg.addEventListener("pointercancel", eind);
}

$("#n-add").addEventListener("click", async () => {
  const naam = $("#n-naam").value.trim(), telefoon = $("#n-tel").value.trim();
  const aantal = +$("#n-aantal").dataset.value;
  if (!naam) return melding("Vul een naam in.", true);
  const r = await jpost("/api/kaarten", { naam, aantal, telefoon }).catch(() => null);
  if (!r) return melding("Geen verbinding.", true);
  if (!r.ok) return melding(r.err, true);
  $("#n-naam").value = ""; $("#n-tel").value = "";
  melding(`${naam} toegevoegd.`); laad();
});

let bulkText = "";
$("#b-vcf").addEventListener("change", async e => {
  const f = e.target.files[0];
  if (f) { bulkText = await f.text(); melding(`${f.name} gekozen — klik op Controleer.`); }
});
$("#b-check").addEventListener("click", async () => {
  const text = ($("#b-text").value + "\n" + bulkText).trim();
  if (!text) return melding("Plak namen of kies een .vcf-bestand.", true);
  const pv = await jpost("/api/import/preview", { text });
  toonPreview(pv);
});

function toonPreview(pv) {
  const box = $("#b-preview");
  if (!pv.nieuw.length && !pv.bestaat.length) { box.innerHTML = '<p class="muted">Niks gevonden om te importeren.</p>'; return; }
  const rows = (pv.nieuw.length ? pv.nieuw : pv.bestaat)
    .map(r => `<tr><td>${esc(r.naam)}</td><td>${esc(r.telefoon || "—")}</td></tr>`).join("");
  const waarschuwing = pv.zonder_nr.length
    ? `<p class="hint">⚠️ ${pv.zonder_nr.length} zonder bruikbaar nummer (kaart wordt wel aangemaakt, nummer later invullen).</p>` : "";
  box.innerHTML = `
    <p><b>${pv.nieuw.length}</b> nieuw · <b>${pv.bestaat.length}</b> bestaan al.</p>
    ${waarschuwing}
    <table class="pv-tbl">${rows}</table>
    <div class="row">
      <button class="btn primary" id="b-do" ${pv.nieuw.length ? "" : "disabled"}>${pv.nieuw.length} toevoegen</button>
      <button class="btn ghost" id="b-cancel">Annuleer</button>
    </div>`;
  $("#b-do")?.addEventListener("click", async () => {
    const aantal = +$("#b-aantal").dataset.value;
    const r = await jpost("/api/import", { rows: pv.nieuw.concat(pv.bestaat), aantal });
    if (!r.ok) return melding(r.err, true);
    box.innerHTML = ""; $("#b-text").value = ""; bulkText = "";
    melding(`${r.toegevoegd} toegevoegd${r.aangevuld ? `, ${r.aangevuld} nummer aangevuld` : ""}.`);
    laad();
  });
  $("#b-cancel")?.addEventListener("click", () => { box.innerHTML = ""; });
}

// ════════════════════════════════════════════════════════════════════════════
// ATLETEN — store-only 360° per atleet (intake, notities, documenten, geheugen)
// ════════════════════════════════════════════════════════════════════════════
let dossierCache = [];
let dossierSel = null;   // geselecteerde atleet-key (voor master-detail op laptop)

// Placeholder in het rechterpaneel zolang er nog niks gekozen is (alleen laptop)
function toonDetailLeeg() {
  const w = $("#d-detail"); w.hidden = false;
  w.innerHTML = `<div class="leeg md-leeg">${ic("users")}<p>Kies links een atleet om het dossier te openen.</p></div>`;
}
// Gekozen rij oplichten zonder de lijst opnieuw te tekenen
function markSel(key) {
  $$("#d-lijst .listcard").forEach(el => el.classList.toggle("sel", el.dataset.key === key));
}

async function laadDossierLijst() {
  const box = $("#d-lijst");
  skeleton(box, 4);
  let data;
  try { data = await api("/api/dossier/athletes"); }
  catch { box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  dossierCache = data.athletes || [];
  tekenDossierLijst("");
}

function tekenDossierLijst(filter) {
  const box = $("#d-lijst");
  box.hidden = false;
  if (isDesktop()) { if (!dossierSel) toonDetailLeeg(); }   // detail blijft staan naast de lijst
  else { $("#d-detail").hidden = true; }                    // telefoon: één scherm tegelijk
  const f = filter.trim().toLowerCase();
  const rijen = dossierCache.filter(a => !f || (a.naam || "").toLowerCase().includes(f));
  if (!rijen.length) {
    box.innerHTML = `<div class="leeg">${ic("users")}<p>${dossierCache.length
      ? "Geen atleet gevonden." : "Nog geen atleten met een intake.<br>Neem er een over via Intake."}</p></div>`;
    return;
  }
  box.innerHTML = "";
  rijen.forEach(a => {
    const el = document.createElement("button");
    el.className = "listcard";
    el.dataset.key = a.key;
    if (a.key === dossierSel) el.classList.add("sel");
    el.innerHTML = `
      <span class="avatar">${initialen(a.naam)}</span>
      <span class="lc-body">
        <span class="lc-title">${esc(a.naam)}${a.nieuw ? ' <span class="tag">nieuw</span>' : ""}</span>
        <span class="lc-sub">${a.doel ? esc(a.doel) : "geen doel ingevuld"}</span>
        <span class="lc-meta">${a.n_notities ? a.n_notities + " notitie(s)" : ""}${a.n_notities && a.n_documenten ? " · " : ""}${a.n_documenten ? a.n_documenten + " document(en)" : ""}</span>
      </span>${ic("chevron")}`;
    el.addEventListener("click", () => openDossier(a.key));
    box.appendChild(el);
  });
}
function initialen(naam) {
  const p = (naam || "?").trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase() || "?";
}

$("#d-zoek").addEventListener("input", e => tekenDossierLijst(e.target.value));
$("#a-refresh").addEventListener("click", () => { geladen.atleten = true; laadDossierLijst(); });

async function openDossier(key) {
  dossierSel = key;
  const wrap = $("#d-detail");
  if (isDesktop()) markSel(key);            // laptop: lijst blijft, rij licht op
  else $("#d-lijst").hidden = true;         // telefoon: lijst wijkt voor het dossier
  wrap.hidden = false;
  wrap.innerHTML = '<p class="muted center">Laden…</p>';
  const r = await api(`/api/dossier/${encodeURIComponent(key)}`).catch(() => null);
  if (!r || !r.ok) { wrap.innerHTML = '<p class="muted center">Kon dossier niet laden.</p>'; return; }
  tekenDossier(r.dossier);
}

function tekenDossier(d) {
  const velden = d.velden.map(v =>
    `<p class="veld"><b>${esc(v.label)}:</b> ${esc(v.waarde)}</p>`).join("")
    || '<p class="muted klein">Intake aanwezig, nog geen velden ingevuld.</p>';

  const notities = d.notities.map((n, i) => `
    <div class="note">
      <div class="note-h"><span>${esc(n.coach || "?")} · ${esc(n.datum || "")}</span>
        <button class="btn danger-ghost mini" data-del-note="${i}" aria-label="Verwijderen">${ic("trash")}</button></div>
      <p>${esc(n.tekst || "")}</p>
    </div>`).join("") || '<p class="muted klein">Nog geen notities.</p>';

  const docs = d.documenten.map(x => `
    <div class="doc"><span class="doc-d">${esc(x.datum || "")}</span>
      <span>${esc(x.type || "")}${x.onderwerp ? " — " + esc(x.onderwerp) : ""}</span></div>`).join("")
    || '<p class="muted klein">Nog geen documenten.</p>';

  const p = d.profiel;
  const wrap = $("#d-detail");
  wrap.innerHTML = `
    <button class="btn ghost back" id="d-terug">${ic("back")} Alle atleten</button>
    <div class="d-head"><span class="avatar big">${initialen(d.naam)}</span>
      <h2 class="d-naam">${esc(d.naam)}${d.nieuw ? ' <span class="tag">nieuw</span>' : ""}</h2></div>

    <section class="panel open-static">
      <h3 class="panel-h">${ic("file")} Intake &amp; doel</h3>${velden}
    </section>

    <section class="panel open-static">
      <h3 class="panel-h">${ic("note")} Coach-notities <span class="muted klein">(gedeeld Jip &amp; Remco)</span></h3>
      <div class="row">
        <input id="nt-tekst" placeholder="Nieuwe notitie…">
        <div class="seg" id="nt-coach" data-value="Jip">
          <button data-v="Jip" class="on">Jip</button><button data-v="Remco">Remco</button>
        </div>
        <button class="btn primary" id="nt-add" aria-label="Toevoegen">${ic("plus")}</button>
      </div>
      <div id="nt-lijst">${notities}</div>
    </section>

    <section class="panel">
      <button class="acc-toggle" data-target="d-docs">${ic("file")} Documenten (${d.documenten.length})</button>
      <div id="d-docs" class="collapse">${docs}</div>
    </section>

    <section class="panel">
      <button class="acc-toggle" data-target="d-prof">${ic("brain")} Coach-geheugen</button>
      <div id="d-prof" class="collapse">
        <p class="hint">Wat de AI over deze atleet weet. Groeit mee bij feedback in Streamlit; jouw aanpassing is leidend.${p.bijgewerkt ? " Laatst bijgewerkt: " + esc(p.bijgewerkt) + "." : ""}</p>
        <textarea id="pf-tekst" rows="5" placeholder="Nog leeg.">${esc(p.tekst || "")}</textarea>
        <button class="btn primary" id="pf-save">Geheugen opslaan</button>
      </div>
    </section>`;

  bindAccordions(wrap);
  $("#scroller").scrollTo({ top: 0 });
  $("#d-terug").addEventListener("click", () => tekenDossierLijst($("#d-zoek").value));

  $("#nt-add").addEventListener("click", async () => {
    const tekst = $("#nt-tekst").value.trim();
    if (!tekst) return melding("Typ eerst een notitie.", true);
    const r = await jpost(`/api/dossier/${encodeURIComponent(d.key)}/note`,
      { coach: $("#nt-coach").dataset.value, tekst }).catch(() => null);
    if (!r || !r.ok) return melding(r?.err || "Opslaan mislukt.", true);
    openDossier(d.key); vervalDossierLijst();
  });
  $("#nt-lijst").querySelectorAll("[data-del-note]").forEach(btn =>
    btn.addEventListener("click", async () => {
      const r = await api(`/api/dossier/${encodeURIComponent(d.key)}/note/${+btn.dataset.delNote}`, { method: "DELETE" }).catch(() => null);
      if (!r || !r.ok) return melding(r?.err || "Verwijderen mislukt.", true);
      openDossier(d.key); vervalDossierLijst();
    }));
  $("#pf-save").addEventListener("click", async () => {
    const r = await jpost(`/api/dossier/${encodeURIComponent(d.key)}/profiel`, { tekst: $("#pf-tekst").value }).catch(() => null);
    if (!r || !r.ok) return melding(r?.err || "Opslaan mislukt.", true);
    melding("Geheugen opgeslagen.");
  });
}

function vervalDossierLijst() { geladen.atleten = false; laders.atleten = laadDossierLijst; }

// ════════════════════════════════════════════════════════════════════════════
// INTAKE — deelbare link + inbox met binnengekomen klant-inzendingen
// ════════════════════════════════════════════════════════════════════════════
async function laadIntakeLink() {
  const box = $("#i-link");
  const r = await api("/api/intake/link").catch(() => null);
  if (!r) { box.innerHTML = '<p class="muted">Geen verbinding.</p>'; return; }
  const url = r.token ? `${location.origin}/intake?token=${r.token}` : "";
  box.innerHTML = url
    ? `<div class="linkbox"><code id="i-url">${esc(url)}</code>
         <button class="btn small" id="i-copy">${ic("copy")} Kopieer</button></div>
       <button class="btn ghost small" id="i-new">Nieuwe link (oude vervalt)</button>`
    : `<p class="muted">Nog geen link.</p><button class="btn primary" id="i-new">Genereer intakelink</button>`;
  $("#i-copy")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(url).then(() => melding("Link gekopieerd.")); });
  $("#i-new")?.addEventListener("click", async () => {
    if (r.token && !confirm("Nieuwe link maken? De oude link werkt daarna niet meer.")) return;
    await api("/api/intake/link", { method: "POST" }); laadIntakeLink();
  });
}

async function laadInbox() {
  const box = $("#i-inbox");
  skeleton(box, 2);
  const r = await api("/api/intake/inbox").catch(() => null);
  if (!r) { box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  const inbox = r.inbox || [];
  setBadge(inbox.length);
  if (!inbox.length) { box.innerHTML = `<div class="leeg">${ic("mail")}<p>Nog geen nieuwe inzendingen.</p></div>`; return; }
  box.innerHTML = "";
  inbox.forEach(sub => {
    const rijen = sub.rijen.map(x => `<tr><td>${esc(x.vraag)}</td><td>${esc(x.antwoord)}</td></tr>`).join("");
    const el = document.createElement("article");
    el.className = "rij-kaart";
    el.innerHTML = `
      <div class="d-head"><span class="avatar">${initialen(sub.naam)}</span>
        <div><h3>${esc(sub.naam)}</h3>
          <p class="muted klein">ingezonden ${esc(sub.ingezonden)}${sub.email ? " · " + esc(sub.email) : ""}</p></div></div>
      <button class="acc-toggle sub" data-open>Bekijk antwoorden</button>
      <div class="collapse"><table class="pv-tbl">${rijen}</table></div>
      <div class="row">
        <button class="btn primary" data-take>${ic("check")} Overnemen als intake</button>
        <button class="btn danger-ghost" data-del aria-label="Verwijderen">${ic("trash")}</button>
      </div>`;
    el.querySelector("[data-open]").addEventListener("click", e => e.target.nextElementSibling.classList.toggle("open"));
    el.querySelector("[data-take]").addEventListener("click", async () => {
      const r2 = await api(`/api/intake/inbox/${encodeURIComponent(sub.id)}/take`, { method: "POST" }).catch(() => null);
      if (!r2 || !r2.ok) return melding(r2?.err || "Overnemen mislukt.", true);
      melding(`'${r2.naam}' overgenomen — staat nu bij Atleten.`);
      vervalDossierLijst(); laadInbox();
    });
    el.querySelector("[data-del]").addEventListener("click", async () => {
      if (!confirm(`Inzending van ${sub.naam} verwijderen?`)) return;
      const r2 = await api(`/api/intake/inbox/${encodeURIComponent(sub.id)}`, { method: "DELETE" }).catch(() => null);
      if (!r2 || !r2.ok) return melding(r2?.err || "Verwijderen mislukt.", true);
      laadInbox();
    });
    box.appendChild(el);
  });
}

$("#i-refresh").addEventListener("click", laadInbox);
function laadIntake() { laadIntakeLink(); laadInbox(); }

// ── Start ──────────────────────────────────────────────────────────────────
laders.strippen = laad;
laders.atleten = laadDossierLijst;
laders.intake = laadIntake;
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
toonOffline();
if (navigator.onLine) flush();
renderHome();
