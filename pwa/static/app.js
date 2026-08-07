// BeBetter PWA — native app-schil. Vanilla JS, geen build.
// Onderbalk-navigatie + dashboard-home + skeletons. Vier modules op één schil:
// dashboard, atleten, intake en strippenkaart — allemaal op dezelfde data als
// Streamlit. Toont wat Streamlit niet kan: direct reageren zonder herladen,
// swipe-om-af-te-boeken, installeren als app en werken zonder netwerk (queue).

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
// Sessie als token in localStorage (robuust in geïnstalleerde iOS-PWA's, waar
// cookies onbetrouwbaar zijn) → meegestuurd als Authorization-header.
const getToken = () => { try { return localStorage.getItem("bb_token") || ""; } catch { return ""; } };
const setToken = t => { try { t ? localStorage.setItem("bb_token", t) : localStorage.removeItem("bb_token"); } catch {} };
function authHeaders(base) {
  const h = Object.assign({}, base || {});
  const t = getToken(); if (t) h["Authorization"] = "Bearer " + t;
  return h;
}
const api = (u, opt = {}) => fetch(u, { ...opt, headers: authHeaders(opt.headers) }).then(r => {
  if (r.status === 401) { toonLogin(); throw new Error("auth"); }   // sessie verlopen → inlogscherm
  return r.json();
});
const jpost = (u, body, method = "POST") => api(u, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const haptic = ms => navigator.vibrate?.(ms);
const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const ic = n => `<svg class="ic"><use href="#ic-${n}"/></svg>`;

// ── Inlog (kies Jip/Remco → wachtwoord of biometrie; blijvende sessie-cookie) ─
let loginWie = null;        // gekozen coach op het inlogscherm
let ingelogdeCoach = "";    // wie is er ingelogd (voor toeschrijven van acties)

function toonLogin() {
  const el = $("#login"); if (!el) return;
  el.hidden = false;
  $("#login-who").hidden = false; $("#login-pw").hidden = true; loginWie = null;   // begin bij de keuze
}
$$(".who-btn").forEach(b => b.addEventListener("click", () => kiesCoach(b.dataset.wie)));
$("#login-back")?.addEventListener("click", () => {
  $("#login-who").hidden = false; $("#login-pw").hidden = true; loginWie = null; $("#login-err").hidden = true;
});
async function kiesCoach(wie) {
  loginWie = wie;
  $("#login-who").hidden = true; $("#login-pw").hidden = false;
  $("#login-as").textContent = `Inloggen als ${wie}`;
  $("#login-err").hidden = true;
  const pass = $("#login-pass"); pass.value = ""; setTimeout(() => pass.focus(), 60);
  const fb = $("#login-faceid"); fb.hidden = true;      // biometrie-knop alleen als deze coach een passkey heeft
  if (waSupport()) {
    try {
      const a = await fetch(`/api/webauthn/available?wie=${encodeURIComponent(wie)}`).then(r => r.json());
      if (a.aan) fb.hidden = false;
    } catch {}
  }
}
$("#login-form")?.addEventListener("submit", async e => {
  e.preventDefault();
  if (!loginWie) return;
  const err = $("#login-err"); err.hidden = true;
  const btn = $("#login-btn"); btn.disabled = true; btn.textContent = "Bezig…";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wie: loginWie, password: $("#login-pass").value }),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) { setToken(d.token); location.reload(); return; }   // token bewaard → herlaad ingelogd
    err.textContent = d.err || "Inloggen mislukt."; err.hidden = false;
  } catch { err.textContent = "Geen verbinding."; err.hidden = false; }
  btn.disabled = false; btn.textContent = "Inloggen";
});
// ── Face ID / passkeys (WebAuthn) — additief; wachtwoord blijft de fallback ──
const waSupport = () => !!(window.PublicKeyCredential && navigator.credentials);
function b64urlToBuf(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/"); s += "=".repeat((4 - s.length % 4) % 4);
  const bin = atob(s), buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}
function bufToB64url(buf) {
  let bin = ""; for (const b of new Uint8Array(buf)) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function prepCreate(o) {
  o.challenge = b64urlToBuf(o.challenge); o.user.id = b64urlToBuf(o.user.id);
  (o.excludeCredentials || []).forEach(c => c.id = b64urlToBuf(c.id));
  return o;
}
function prepGet(o) {
  o.challenge = b64urlToBuf(o.challenge);
  (o.allowCredentials || []).forEach(c => c.id = b64urlToBuf(c.id));
  return o;
}
function credToJSON(c) {
  const r = c.response, out = { id: c.id, rawId: bufToB64url(c.rawId), type: c.type, clientExtensionResults: {} };
  if (r.attestationObject) {
    out.response = { clientDataJSON: bufToB64url(r.clientDataJSON), attestationObject: bufToB64url(r.attestationObject) };
    if (r.getTransports) out.response.transports = r.getTransports();
  } else {
    out.response = { clientDataJSON: bufToB64url(r.clientDataJSON), authenticatorData: bufToB64url(r.authenticatorData),
      signature: bufToB64url(r.signature), userHandle: r.userHandle ? bufToB64url(r.userHandle) : null };
  }
  return out;
}
async function faceIDregister() {
  if (!waSupport()) return melding("Dit apparaat ondersteunt geen Face ID/passkeys.", true);
  try {
    const opts = await fetch("/api/webauthn/register/options", { method: "POST", headers: authHeaders() }).then(r => r.json());
    if (opts.err) return melding(opts.err, true);
    const cred = await navigator.credentials.create({ publicKey: prepCreate(opts) });
    const r = await fetch("/api/webauthn/register/verify", { method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(credToJSON(cred)) }).then(r => r.json());
    melding(r && r.ok ? "Face ID ingeschakeld op dit apparaat." : (r?.err || "Inschakelen mislukt."), !(r && r.ok));
  } catch { melding("Face ID inschakelen afgebroken.", true); }
}
async function faceIDunlock() {
  if (!waSupport() || !loginWie) return;
  try {
    const opts = await fetch(`/api/webauthn/auth/options?wie=${encodeURIComponent(loginWie)}`, { method: "POST" }).then(r => r.json());
    if (opts.err) return melding(opts.err, true);
    const cred = await navigator.credentials.get({ publicKey: prepGet(opts) });
    const r = await fetch("/api/webauthn/auth/verify", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(credToJSON(cred)) }).then(r => r.json());
    if (r && r.ok) { setToken(r.token); location.reload(); } else melding(r?.err || "Ontgrendelen mislukt.", true);
  } catch { /* gebruiker annuleerde de Face ID-prompt */ }
}
$("#login-faceid")?.addEventListener("click", faceIDunlock);
$("#faceid-enable")?.addEventListener("click", faceIDregister);
if (waSupport()) $("#faceid-enable")?.removeAttribute("hidden");   // 'inschakelen' in Meer

// Bij opstarten: niet ingelogd → toon scherm; heeft dit account een passkey +
// steunt de browser het, toon dan de Face ID-ontgrendelknop.
$("#uitloggen")?.addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST", headers: authHeaders() }).catch(() => {});
  setToken("");
  location.reload();
});
(async () => {
  try {
    const me = await fetch("/api/me", { headers: authHeaders() }).then(r => r.json());
    if (!me.ingelogd) { toonLogin(); return; }
    ingelogdeCoach = me.wie || "";
    const w = $("#wie-ingelogd");
    if (w) w.textContent = ingelogdeCoach ? `Ingelogd als ${ingelogdeCoach}.` : "Ingelogd.";
  } catch {}
})();

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
  const g = groetInfo();
  // 1) De shell verschijnt DIRECT — geen await op trage data. Hero + skeletons.
  //    Atleten/groepen + status/feedback/prioriteit komen uit de cockpit-snapshot
  //    (near-instant); de secundaire praktijk-kaarten uit de lokale store.
  box.innerHTML = `
    <div class="hero hero-photo">
      <button class="hero-gear" data-open-view="meer" aria-label="Meer">${ic("settings")}</button>
      <div class="hero-content">
        <p class="hero-greet">${g.groet}</p>
        <p class="hero-date">${g.datum}</p>
        <h2 class="hero-tag">Zij lopen.<br><span>Jij stuurt.</span></h2>
        <div class="hero-ids">
          <span><b id="hero-atleten" data-count="0">—</b> atleten</span><i>·</i>
          <span><b id="hero-groepen" data-count="0">—</b> groepen</span>
        </div>
        <div class="hero-status" id="hero-status"><span class="hs-skel"></span><span class="hs-skel"></span></div>
      </div>
      <span class="hero-portrait" id="hero-foto"></span>
    </div>

    <button class="fb-strip skel-strip" id="home-fb" data-open-view="feedback" aria-label="Feedback bekijken">
      <div class="skel skel-line w40" style="margin:2px 0"></div>
      <div class="skel skel-line w60" style="margin:10px 0 2px"></div>
    </button>

    <div class="sec-head"><p class="sec-label">Prioriteit vandaag</p><span class="sec-note" id="prio-note"></span></div>
    <div id="home-prio">
      ${[0, 0, 0].map(() => `<div class="prio-skel"><span class="skel prio-skel-av"></span><span class="prio-skel-body"><span class="skel skel-line w40"></span><span class="skel skel-line w60"></span></span></div>`).join("")}
    </div>

    <div id="home-info"></div>
    <div id="home-ook"></div>

    <p class="sec-label">Snel toevoegen</p>
    <div class="quick-actions">
      <button class="qa" data-open-view="intake">${ic("user-plus")}<span>Nieuwe intake</span></button>
      <button class="qa" data-open-view="schema">${ic("brain")}<span>Schema bouwen</span></button>
      <button class="qa" data-open-view="strippen">${ic("ticket")}<span>Strippenkaart</span></button>
    </div>`;
  box.dataset.done = "1";
  $$("[data-open-view]", box).forEach(b => b.addEventListener("click", () => toonView(b.dataset.openView)));
  laadHeroFoto();

  // 2) Cockpit-snapshot (direct) → hero-telling/status, feedback, prioriteit.
  //    Verouderd? Dan op de achtergrond verversen (stale-while-revalidate).
  api("/api/home/stats").then(s => {
    // Eerste-ooit (pending): laat de skeletons staan en bouw op de achtergrond op.
    if (s && s.pending) { cockpitVersen(s); return; }
    vulCockpit(s); cockpitVersen(s);
  }).catch(() => {
    const p = $("#home-prio"); if (p) p.innerHTML = '<p class="muted klein">Kon de dagstatus niet laden.</p>';
    const fb = $("#home-fb"); if (fb) fb.remove();
  });

  // 3) Secundaire praktijk-signalen (lokale store, direct) — badge + "ook nog".
  Promise.all([
    api("/api/intake/inbox").catch(() => ({ inbox: [] })),
    api("/api/kaarten").catch(() => ({ kaarten: [] })),
  ]).then(([inbox, kaarten]) => {
    const nNieuw = (inbox.inbox || []).length;
    setBadge(nNieuw);
    const kn = kaarten.kaarten || [];
    const vol = kn.filter(k => k.rest <= 0);
    const bijna = kn.filter(k => k.rest > 0 && k.rest <= 1);
    const items = [];
    if (nNieuw) items.push(kaartItem("mail", `${nNieuw} nieuwe intake${nNieuw === 1 ? "" : "s"}`,
      "Bekijk en neem over als atleet", "intake", true));
    vol.forEach(k => items.push(kaartItem("ticket", `Strippenkaart vol — ${esc(k.naam)}`,
      "Kaart is op, tijd voor een nieuwe", "strippen", true)));
    bijna.forEach(k => items.push(kaartItem("ticket", `${esc(k.naam)} — nog 1 training`,
      "Strippenkaart bijna vol", "strippen", false)));
    const ook = $("#home-ook");
    if (ook) {
      ook.innerHTML = items.length ? `<p class="sec-label">Ook nog</p>${items.join("")}` : "";
      $$("[data-open-view]", ook).forEach(b => b.addEventListener("click", () => toonView(b.dataset.openView)));
    }
    bronStatus(kaarten.cloud);
  });
}

// Coach-foto met nette fallback: bij een laadfout NOOIT een broken-image-icoon,
// maar een subtiel gradientvlak met het BeBetter-logo.
function laadHeroFoto() {
  const holder = $("#hero-foto"); if (!holder) return;
  const img = new Image();
  img.className = "hero-portrait-img";
  img.alt = "Jip & Remco";
  img.onload = () => { holder.replaceWith(img); };
  img.onerror = () => { holder.classList.add("foto-fallback"); holder.innerHTML = `<img src="/static/logo.png" alt="BeBetter" class="foto-fallback-logo">`; };
  img.src = "/static/team.jpeg";
}

// Is de snapshot verouderd? Nieuwe dag → altijd; anders ouder dan 15 min.
function cockpitStale(s) {
  if (!s || !s.berekend) return true;
  const today = new Date().toISOString().slice(0, 10);
  if (s.datum && s.datum !== today) return true;
  const t = Date.parse(s.berekend);
  return isNaN(t) || (Date.now() - t) > 15 * 60 * 1000;
}

// Ververst de cockpit op de achtergrond als de snapshot verouderd is.
function cockpitVersen(s) {
  if (!s || !s.fs) return;
  // Ververs als er nog niets is (pending) óf de gedeelde snapshot verouderd is.
  if (!s.pending && !(s.cached && cockpitStale(s))) return;
  const note = $("#prio-note"); const was = note ? note.textContent : "";
  if (note) note.dataset.busy = "1";
  markVersen(true);
  api("/api/home/stats?refresh=1").then(fresh => {
    markVersen(false);
    if (fresh && fresh.pending) return;      // nog niet klaar (andere instance) → skeletons blijven
    vulCockpit(fresh);
  }).catch(() => { markVersen(false); if (note) note.textContent = was; });
}
function markVersen(on) {
  const n = $("#prio-note"); if (!n) return;
  if (on) n.innerHTML = `<span class="versen">bijwerken…</span>`;
}

// Vult hero-status + feedbackbalk + prioriteitlijst + info-strip met echte cockpit-data
function vulCockpit(s) {
  if (!s || !s.fs) {
    const p = $("#home-prio"); if (p) p.innerHTML = '<p class="muted klein">FinalSurge niet gekoppeld.</p>';
    const fb = $("#home-fb"); if (fb) fb.remove();
    return;
  }
  const team = s.team || {}, fbs = s.feedback || {}, info = s.info || {};

  // ── Hero: atleten/groepen-telling (uit de cockpit, geen aparte trage call) ──
  const hAt = $("#hero-atleten"), hGr = $("#hero-groepen");
  if (hAt && s.atleten != null && +hAt.dataset.count !== s.atleten) { hAt.dataset.count = s.atleten; countUp(hAt); }
  if (hGr && s.groepen != null && +hGr.dataset.count !== s.groepen) { hGr.dataset.count = s.groepen; countUp(hGr); }

  // ── Hero: team-status (afgeleid uit echte signalen — DISTINCT atleten per tier) ──
  const hs = $("#hero-status");
  if (hs) {
    const chips = [];
    if (team.actie) chips.push(`<span class="hs actie"><i></i>${team.actie} actie</span>`);
    if (team.aandacht) chips.push(`<span class="hs aandacht"><i></i>${team.aandacht} aandacht</span>`);
    if (team.rustig) chips.push(`<span class="hs rustig"><i></i>${team.rustig} rustig</span>`);
    hs.innerHTML = chips.join("") || `<span class="hs rustig"><i></i>iedereen bij</span>`;
  }

  // ── Feedback: dagelijkse kern als voortgangsbalk ──
  const fb = $("#home-fb");
  if (fb) {
    const w = fbs.wachten || 0, pct = fbs.pct != null ? fbs.pct : 100;
    fb.classList.remove("skel-strip");
    fb.classList.toggle("done", w === 0);
    fb.innerHTML = `
      <div class="fb-strip-top">
        <span class="fb-strip-ic">${ic(w ? "message" : "check")}</span>
        <span class="fb-strip-t">${w ? `<b>${w}</b> wachten op feedback` : "Alles beoordeeld"}</span>
        <span class="fb-strip-pct">${pct}%</span>
      </div>
      <div class="mt-bar"><i style="width:${pct}%"></i></div>
      <span class="fb-strip-sub">${fbs.gepost || 0} vandaag gepost · ${pct}% afgerond</span>`;
  }

  // ── Prioriteit vandaag: individuele atleten (wie → waarom → actie) ──
  const prio = s.prioriteit || [];
  const box = $("#home-prio"), note = $("#prio-note");
  if (note) note.textContent = prio.length ? `${team.actie || 0} actie · ${team.aandacht || 0} aandacht` : "";
  if (box) {
    if (!prio.length) {
      box.innerHTML = `<div class="leeg small">${ic("check")}<p>Niks urgents nu — mooie dag om te coachen.</p></div>`;
    } else {
      box.innerHTML = prio.map(prioRow).join("");
      const rest = (s.prioriteit_totaal || prio.length) - prio.length;
      if (rest > 0) box.innerHTML += `<button class="prio-meer" data-open-view="teampuls">Nog ${rest} in Teampuls ${ic("chevron")}</button>`;
      $$("[data-open-view]", box).forEach(b => b.addEventListener("click", () => toonView(b.dataset.openView)));
      $$(".prio-row", box).forEach(r => r.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toonView(r.dataset.openView); }
      }));
    }
  }

  // ── Info-strip (voortgang/rustig, cyaan — geen alarm) ──
  const inf = $("#home-info");
  if (inf) {
    const chips = [];
    if (info.races) chips.push(`<button class="info-chip" data-open-view="races">${ic("flag")} ${info.races} race${info.races === 1 ? "" : "s"} komende 7 dgn</button>`);
    chips.push(`<span class="info-chip ok">${ic("check")} ${info.gepost || 0} vandaag gepost</span>`);
    inf.innerHTML = `<div class="info-strip">${chips.join("")}</div>`;
    $$("[data-open-view]", inf).forEach(b => b.addEventListener("click", () => toonView(b.dataset.openView)));
  }
}

// BeBetter-signatuurcomponent: één atleet-prioriteitrij (statusstip · naam · reden · actie)
function prioRow(it) {
  return `<article class="prio-row ${it.tier}" data-open-view="${it.view}" role="button" tabindex="0">
    <span class="prio-dot ${it.tier}"></span>
    <span class="avatar">${initialen(it.naam)}</span>
    <span class="prio-body">
      <span class="prio-naam">${esc(it.naam)}</span>
      <span class="prio-reden">${esc(it.reden)}</span>
    </span>
    <span class="prio-actie">${esc(it.actie)} ${ic("chevron")}</span>
  </article>`;
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
let dossierSel = null;   // geselecteerde atleet-id (voor master-detail op laptop)
let fsActief = false;    // is de FinalSurge-koppeling actief (volledige roster)?

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
  skeleton(box, 6);
  let data;
  try { data = await api("/api/atleten"); }
  catch { box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  dossierCache = data.atleten || [];
  fsActief = !!data.fs;
  tekenDossierLijst($("#d-zoek").value || "");
}

function tekenDossierLijst(filter) {
  const box = $("#d-lijst");
  box.hidden = false;
  if (isDesktop()) { if (!dossierSel) toonDetailLeeg(); }   // detail blijft staan naast de lijst
  else { $(".md-list").hidden = false; $("#d-detail").hidden = true; }  // telefoon: terug naar de lijst
  const f = (filter || "").trim().toLowerCase();
  const rijen = dossierCache.filter(a => !f || (a.naam || "").toLowerCase().includes(f));
  if (!rijen.length) {
    box.innerHTML = `<div class="leeg">${ic("users")}<p>${dossierCache.length
      ? "Geen atleet gevonden." : (fsActief ? "Geen atleten." : "Nog geen atleten.<br>Koppel FinalSurge (FS_TOKEN) voor de volledige lijst.")}</p></div>`;
    return;
  }
  box.innerHTML = "";
  rijen.forEach(a => {
    const el = document.createElement("button");
    el.className = "listcard";
    el.dataset.key = a.id;
    if (a.id === dossierSel) el.classList.add("sel");
    const meta = [
      a.n_notities ? a.n_notities + " notitie(s)" : "",
      a.n_documenten ? a.n_documenten + " document(en)" : "",
    ].filter(Boolean).join(" · ");
    el.innerHTML = `
      <span class="avatar">${initialen(a.naam)}</span>
      <span class="lc-body">
        <span class="lc-title">${esc(a.naam)}${a.heeft_intake ? ' <span class="tag">intake</span>' : ""}</span>
        <span class="lc-sub">${a.groep ? esc(a.groep) : "—"}</span>
        ${meta ? `<span class="lc-meta">${meta}</span>` : ""}
      </span>${ic("chevron")}`;
    el.addEventListener("click", () => openDossier(a.id));
    box.appendChild(el);
  });
}
function initialen(naam) {
  const p = (naam || "?").trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase() || "?";
}

$("#d-zoek").addEventListener("input", e => tekenDossierLijst(e.target.value));
$("#a-refresh").addEventListener("click", () => { geladen.atleten = true; laadDossierLijst(); });

async function openDossier(ident) {
  dossierSel = ident;
  const wrap = $("#d-detail");
  if (isDesktop()) { markSel(ident); }      // laptop: lijst blijft, rij licht op
  else { $(".md-list").hidden = true; $("#scroller").scrollTo({ top: 0 }); }  // telefoon: meteen 'in' de klant
  wrap.hidden = false;
  wrap.innerHTML = '<p class="muted center">Laden…</p>';
  const d = await api(`/api/atleten/${encodeURIComponent(ident)}`).catch(() => null);
  if (!d || !d.naam) { wrap.innerHTML = '<p class="muted center">Kon atleet niet laden.</p>'; return; }
  tekenAtleet(d);
}

function tekenAtleet(d) {
  const wrap = $("#d-detail");
  const storeKey = d.store_key;
  const wk = (d.training && d.training.week) ? d.training.week.deze_week : 0;
  const recent = (d.training && d.training.recent) || [];
  const recentHtml = recent.length
    ? recent.map(t => `<div class="tr-row"><span class="tr-d">${esc((t.datum || "").slice(5))}</span>
        <span class="tr-t">${esc(t.type || "Training")}</span>
        ${t.duur_min ? `<span class="tr-m">${t.duur_min} min</span>` : ""}</div>`).join("")
    : '<p class="muted klein">Geen trainingen in de laatste 2 weken.</p>';

  const dos = d.dossier;
  const velden = dos ? (dos.velden.map(v =>
    `<p class="veld"><b>${esc(v.label)}:</b> ${esc(v.waarde)}</p>`).join("")) : "";
  const notities = (dos && dos.notities.length) ? dos.notities.map((n, i) => `
    <div class="note">
      <div class="note-h"><span>${esc(n.coach || "?")} · ${esc(n.datum || "")}</span>
        <button class="btn danger-ghost mini" data-del-note="${i}" aria-label="Verwijderen">${ic("trash")}</button></div>
      <p>${esc(n.tekst || "")}</p>
    </div>`).join("") : '<p class="muted klein">Nog geen notities.</p>';
  const docs = (dos && dos.documenten.length) ? dos.documenten.map(x => `
    <div class="doc"><span class="doc-d">${esc(x.datum || "")}</span>
      <span>${esc(x.type || "")}${x.onderwerp ? " — " + esc(x.onderwerp) : ""}</span></div>`).join("")
    : '<p class="muted klein">Nog geen documenten.</p>';
  const prof = dos ? dos.profiel : { tekst: "", bijgewerkt: "" };
  const nDocs = dos ? dos.documenten.length : 0;

  wrap.innerHTML = `
    <button class="btn ghost back" id="d-terug">${ic("back")} Alle atleten</button>
    <div class="d-head"><span class="avatar big">${initialen(d.naam)}</span>
      <div><h2 class="d-naam">${esc(d.naam)}</h2>
        ${d.groep ? `<p class="muted klein" style="margin:3px 0 0">${esc(d.groep)}</p>` : ""}</div></div>

    <section class="panel open-static">
      <h3 class="panel-h">${ic("activity")} Training <span class="muted klein">(uit FinalSurge)</span></h3>
      <div class="train-top">
        <div class="train-ring"><span class="train-n">${wk}</span><span class="train-lbl">deze week</span></div>
        <div class="train-recent">${recentHtml}</div>
      </div>
    </section>

    ${velden ? `<section class="panel open-static">
      <h3 class="panel-h">${ic("file")} Intake &amp; doel</h3>${velden}
    </section>` : ""}

    <section class="panel open-static">
      <h3 class="panel-h">${ic("note")} Coach-notities <span class="muted klein">(gedeeld Jip &amp; Remco)</span></h3>
      <div class="row">
        <input id="nt-tekst" placeholder="Nieuwe notitie…">
        <div class="seg" id="nt-coach" data-value="${ingelogdeCoach === "Remco" ? "Remco" : "Jip"}">
          <button data-v="Jip" class="${ingelogdeCoach !== "Remco" ? "on" : ""}">Jip</button><button data-v="Remco" class="${ingelogdeCoach === "Remco" ? "on" : ""}">Remco</button>
        </div>
        <button class="btn primary" id="nt-add" aria-label="Toevoegen">${ic("plus")}</button>
      </div>
      <div id="nt-lijst">${notities}</div>
    </section>

    <section class="panel">
      <button class="acc-toggle" data-target="d-docs">${ic("file")} Documenten (${nDocs})</button>
      <div id="d-docs" class="collapse">${docs}</div>
    </section>

    <section class="panel">
      <button class="acc-toggle" data-target="d-prof">${ic("brain")} Coach-geheugen</button>
      <div id="d-prof" class="collapse">
        <p class="hint">Wat de AI over deze atleet weet. Groeit mee bij feedback in Streamlit; jouw aanpassing is leidend.${prof.bijgewerkt ? " Laatst bijgewerkt: " + esc(prof.bijgewerkt) + "." : ""}</p>
        <textarea id="pf-tekst" rows="5" placeholder="Nog leeg.">${esc(prof.tekst || "")}</textarea>
        <button class="btn primary" id="pf-save">Geheugen opslaan</button>
      </div>
    </section>`;

  bindAccordions(wrap);
  $("#scroller").scrollTo({ top: 0 });
  $("#d-terug").addEventListener("click", () => tekenDossierLijst($("#d-zoek").value));

  $("#nt-add").addEventListener("click", async () => {
    const tekst = $("#nt-tekst").value.trim();
    if (!tekst) return melding("Typ eerst een notitie.", true);
    const r = await jpost(`/api/dossier/${encodeURIComponent(storeKey)}/note`,
      { coach: $("#nt-coach").dataset.value, tekst }).catch(() => null);
    if (!r || !r.ok) return melding(r?.err || "Opslaan mislukt.", true);
    openDossier(d.id); vervalDossierLijst();
  });
  $("#nt-lijst").querySelectorAll("[data-del-note]").forEach(btn =>
    btn.addEventListener("click", async () => {
      const r = await api(`/api/dossier/${encodeURIComponent(storeKey)}/note/${+btn.dataset.delNote}`, { method: "DELETE" }).catch(() => null);
      if (!r || !r.ok) return melding(r?.err || "Verwijderen mislukt.", true);
      openDossier(d.id); vervalDossierLijst();
    }));
  $("#pf-save").addEventListener("click", async () => {
    const r = await jpost(`/api/dossier/${encodeURIComponent(storeKey)}/profiel`, { tekst: $("#pf-tekst").value }).catch(() => null);
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

// ════════════════════════════════════════════════════════════════════════════
// DOCUMENTEN — template-PDF's (AI-intro's zodra de sleutel gezet is)
// ════════════════════════════════════════════════════════════════════════════
let docsTpls = [], docsAthletes = [];

async function laadDocs() {
  const info = $("#docs-ai"), keuze = $("#docs-keuze");
  $("#docs-form").hidden = true; keuze.hidden = false;
  skeleton(keuze, 4);
  const [r, a] = await Promise.all([
    api("/api/docs/templates").catch(() => null),
    api("/api/dossier/athletes").catch(() => ({ athletes: [] })),
  ]);
  if (!r) { keuze.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  docsTpls = r.templates || [];
  docsAthletes = a.athletes || [];
  info.textContent = r.ai
    ? "De AI schrijft de persoonlijke intro’s in de huisstijl. Kies een document en een atleet."
    : "AI-sleutel nog niet ingesteld: je krijgt de vaste inhoud (de persoonlijke intro’s blijven leeg). Zodra de sleutel op Render staat, vullen die zich vanzelf.";
  keuze.innerHTML = "";
  docsTpls.forEach(t => {
    const el = document.createElement("button");
    el.className = "listcard";
    el.innerHTML = `<span class="lc-ic">${ic("file")}</span>
      <span class="lc-body"><span class="lc-title">${esc(t.label)}</span>
        <span class="lc-sub">${esc(t.omschrijving)}</span></span>${ic("chevron")}`;
    el.addEventListener("click", () => docForm(t));
    keuze.appendChild(el);
  });
}

function docForm(t) {
  $("#docs-keuze").hidden = true;
  const wrap = $("#docs-form"); wrap.hidden = false;
  const opts = ['<option value="">— Algemeen (geen naam) —</option>']
    .concat(docsAthletes.map(a => `<option value="${esc(a.key)}">${esc(a.naam)}</option>`)).join("");
  const velden = (t.velden || []).map(docVeld).join("");
  wrap.innerHTML = `
    <button class="btn ghost back" id="docs-terug">${ic("back")} Alle documenten</button>
    <div class="d-head"><span class="lc-ic">${ic("file")}</span><h2 class="d-naam">${esc(t.label)}</h2></div>
    <section class="panel open-static">
      <label class="lbl">Voor welke atleet?</label>
      <select id="docs-atleet">${opts}</select>
      ${velden}
      <button class="btn primary" id="docs-gen" style="margin-top:14px">${ic("download")} Genereer PDF</button>
      <p class="hint" id="docs-status"></p>
    </section>`;
  $("#docs-terug").addEventListener("click", laadDocs);
  $("#docs-gen").addEventListener("click", () => genereerDoc(t));
  $("#scroller").scrollTo({ top: 0 });
}

function docVeld(v) {
  const id = "df-" + v.veld;
  if (v.type === "keuze") {
    const opts = (v.opties || []).map(o => `<option value="${esc(o)}">${o === "" ? "—" : esc(o)}</option>`).join("");
    return `<label class="lbl">${esc(v.vraag)}</label><select id="${id}" data-veld="${esc(v.veld)}">${opts}</select>`;
  }
  const type = v.type === "getal" ? "number" : "text";
  return `<label class="lbl">${esc(v.vraag)}</label><input id="${id}" data-veld="${esc(v.veld)}" type="${type}">`;
}

async function genereerDoc(t) {
  const user_key = $("#docs-atleet").value || null;
  const naam = user_key ? (docsAthletes.find(a => a.key === user_key)?.naam || "") : "";
  const voornaam = naam ? naam.trim().split(/\s+/)[0] : "";
  const answers = {};
  if (voornaam) answers.voornaam = voornaam;
  $$("#docs-form [data-veld]").forEach(el => { if (el.value) answers[el.dataset.veld] = el.value; });
  const status = $("#docs-status");
  status.textContent = "Genereren…";
  try {
    const res = await fetch("/api/docs/generate", {
      method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ slug: t.slug, user_key, answers }),
    });
    if (!res.ok) { status.textContent = "Mislukt: " + (await res.text()); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${t.label}${voornaam ? " - " + voornaam : ""}.pdf`;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    status.textContent = "Klaar — PDF gedownload." + (voornaam ? " Gelogd in het dossier." : "");
    haptic(15);
    if (voornaam) vervalDossierLijst();      // dossier toont het nieuwe document na verversen
  } catch {
    status.textContent = "Geen verbinding — probeer opnieuw.";
  }
}

// ════════════════════════════════════════════════════════════════════════════
// FEEDBACK — AI-concept op de trainingen van atleten (FinalSurge + Anthropic)
// ════════════════════════════════════════════════════════════════════════════
async function laadFeedback() {
  const box = $("#fb-lijst"), info = $("#fb-info");
  info.textContent = "Trainingen ophalen uit FinalSurge…";
  skeleton(box, 4);
  const r = await api("/api/feedback").catch(() => null);
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  if (!r.fs) { info.textContent = "FinalSurge nog niet gekoppeld."; box.innerHTML = ""; return; }
  const items = r.items || [];
  info.textContent = items.length
    ? `${items.length} training${items.length === 1 ? "" : "en"} met aandacht. Genereer een concept en pas het naar wens aan.`
    : "";
  if (!items.length) { box.innerHTML = `<div class="leeg">${ic("check")}<p>Niks te beoordelen — netjes bijgewerkt.</p></div>`; return; }
  box.innerHTML = "";
  items.forEach(it => box.appendChild(fbItem(it)));
}

function fbItem(it) {
  const el = document.createElement("article");
  el.className = "rij-kaart";
  const gesprek = it.gesprek || [];
  const bubbels = gesprek.length
    ? gesprek.map(m => `<div class="fb-bub ${m.coach ? "coach" : "atl"}"><span class="fb-wie">${m.coach ? "Jij" : esc(m.wie || it.voornaam)}</span>${esc(m.tekst)}</div>`).join("")
    : '<p class="muted klein">Geen bericht van de atleet — reageer op de uitvoering.</p>';
  el.innerHTML = `
    <div class="d-head"><span class="avatar">${initialen(it.naam)}</span>
      <div><h3>${esc(it.naam)}</h3>
        <p class="muted klein">${esc(it.datum)} · ${esc(it.workout)}</p></div></div>
    <div class="fb-thread">${bubbels}</div>
    <textarea class="fb-tekst" rows="5" placeholder="Schrijf zelf een reactie, of genereer met AI…"></textarea>
    <div class="fb-acts">
      <button class="btn" data-gen>${ic("brain")} Genereer met AI</button>
      <button class="btn primary" data-post>${ic("message")} Plaats</button>
    </div>
    <div class="fb-acts">
      <button class="btn ghost small" data-copy>${ic("copy")} Kopieer</button>
      <button class="btn ghost small" data-skip>Overslaan</button>
    </div>
    <p class="hint" data-poststatus></p>`;

  const tekstEl = el.querySelector(".fb-tekst");
  const status = el.querySelector("[data-poststatus]");

  el.querySelector("[data-gen]").addEventListener("click", async e => {
    const btn = e.currentTarget; btn.disabled = true; btn.textContent = "AI schrijft…";
    const r = await jpost("/api/feedback/generate", { id: it.id }).catch(() => null);
    btn.disabled = false; btn.innerHTML = `${ic("brain")} Genereer met AI`;
    if (!r || !r.ok) return melding(r?.err || "Genereren mislukt.", true);
    tekstEl.value = r.tekst || "";
  });
  el.querySelector("[data-post]").addEventListener("click", async () => {
    const tekst = tekstEl.value.trim();
    if (!tekst) return melding("Schrijf of genereer eerst een reactie.", true);
    if (!confirm(`Deze reactie in FinalSurge plaatsen bij ${it.voornaam}? ${it.voornaam} ziet dit.`)) return;
    const btn = el.querySelector("[data-post]"); btn.disabled = true; btn.textContent = "Plaatsen…";
    const r = await jpost("/api/feedback/post", { id: it.id, tekst }).catch(() => null);
    btn.disabled = false; btn.innerHTML = `${ic("message")} Plaats`;
    if (!r || !r.ok) return melding(r?.err || "Posten mislukt.", true);
    status.textContent = "Geplaatst in FinalSurge ✓"; el.style.opacity = ".55"; haptic(15);
  });
  el.querySelector("[data-copy]").addEventListener("click", () => {
    navigator.clipboard?.writeText(tekstEl.value).then(() => melding("Gekopieerd."));
  });
  el.querySelector("[data-skip]").addEventListener("click", async () => {
    if (!confirm(`Training van ${it.voornaam} overslaan? Komt terug als ${it.voornaam} weer reageert.`)) return;
    const r = await jpost("/api/feedback/skip", { id: it.id }).catch(() => null);
    if (!r || !r.ok) return melding(r?.err || "Overslaan mislukt.", true);
    el.remove(); haptic(10);
  });
  return el;
}
$("#fb-refresh").addEventListener("click", () => { geladen.feedback = true; laadFeedback(); });

// ════════════════════════════════════════════════════════════════════════════
// SCHEMA BOUWEN — opgeslagen intake → AI-plan → CSV-download voor FinalSurge
// ════════════════════════════════════════════════════════════════════════════
let schemaAtleten = [];
async function laadSchema() {
  const box = $("#sb-lijst"), info = $("#sb-info");
  $("#sb-werk").hidden = true; box.hidden = false;
  skeleton(box, 4);
  const r = await api("/api/schema/atleten").catch(() => null);
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  schemaAtleten = r.atleten || [];
  info.textContent = r.ai
    ? "Kies een atleet met een opgeslagen intake. De AI maakt het plan; jij controleert en downloadt de CSV voor FinalSurge."
    : "AI-sleutel nog niet ingesteld.";
  if (!schemaAtleten.length) {
    box.innerHTML = `<div class="leeg">${ic("brain")}<p>Nog geen atleten met een opgeslagen bouwer-intake.<br>Vul de intake in de bouwer (Streamlit), dan verschijnen ze hier.</p></div>`;
    return;
  }
  box.innerHTML = "";
  schemaAtleten.forEach(a => {
    const el = document.createElement("button");
    el.className = "listcard";
    el.innerHTML = `<span class="avatar">${initialen(a.naam)}</span>
      <span class="lc-body"><span class="lc-title">${esc(a.naam)}</span>
        <span class="lc-sub">${a.doel ? esc(a.doel) : "geen doel"}</span>
        <span class="lc-meta">${a.weken ? a.weken + " weken" : ""}${a.trainingsdagen ? " · " + esc(a.trainingsdagen) : ""}</span>
      </span>${ic("chevron")}`;
    el.addEventListener("click", () => schemaWerk(a));
    box.appendChild(el);
  });
}

function schemaWerk(a) {
  $("#sb-lijst").hidden = true;
  const wrap = $("#sb-werk"); wrap.hidden = false;
  wrap.innerHTML = `
    <button class="btn ghost back" id="sb-terug">${ic("back")} Alle atleten</button>
    <div class="d-head"><span class="avatar big">${initialen(a.naam)}</span>
      <div><h2 class="d-naam">${esc(a.naam)}</h2>
        <p class="muted klein">${a.doel ? esc(a.doel) : ""}${a.weken ? " · " + a.weken + " weken" : ""}</p></div></div>
    <section class="panel open-static">
      <button class="btn primary" id="sb-plan">${ic("brain")} Genereer plan</button>
      <p class="hint" id="sb-status">Het plan maken duurt ~30-60s (AI).</p>
      <div id="sb-planbox" hidden>
        <label class="lbl">Plan — pas het gerust aan vóór de CSV</label>
        <textarea id="sb-plantekst" rows="12"></textarea>
        <button class="btn primary" id="sb-csv" style="margin-top:10px">${ic("check")} Genereer CSV</button>
        <div id="sb-na" hidden>
          <button class="btn" id="sb-download">${ic("download")} Download CSV</button>
          <button class="btn primary" id="sb-push">${ic("refresh")} Zet in FinalSurge</button>
        </div>
        <p class="hint" id="sb-csvstatus"></p>
      </div>
    </section>`;
  $("#sb-terug").addEventListener("click", laadSchema);
  $("#scroller").scrollTo({ top: 0 });
  $("#sb-plan").addEventListener("click", async () => {
    const btn = $("#sb-plan"); btn.disabled = true; btn.textContent = "AI bouwt het plan…";
    const r = await jpost("/api/schema/plan", { key: a.key }).catch(() => null);
    btn.disabled = false; btn.innerHTML = `${ic("refresh")} Opnieuw`;
    if (!r || !r.ok) return melding(r?.err || "Plan mislukt.", true);
    $("#sb-planbox").hidden = false;
    $("#sb-plantekst").value = r.plan || "";
  });
  let csvTekst = "", rijenN = 0;
  $("#sb-csv").addEventListener("click", async () => {
    const st = $("#sb-csvstatus"); st.textContent = "CSV genereren…";
    const r = await jpost("/api/schema/csv", { key: a.key, plan: $("#sb-plantekst").value }).catch(() => null);
    if (!r || !r.ok) { st.textContent = ""; return melding(r?.err || "CSV mislukt.", true); }
    csvTekst = r.csv || ""; rijenN = (r.rijen || []).length;
    $("#sb-na").hidden = false;
    st.textContent = `CSV klaar — ${rijenN} trainingen. Download 'm, of zet ze direct op de FinalSurge-kalender.`;
    haptic(15);
  });
  $("#sb-download").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([csvTekst], { type: "text/csv" }));
    const dl = document.createElement("a");
    dl.href = url; dl.download = `Schema - ${a.naam}.csv`;
    document.body.appendChild(dl); dl.click(); dl.remove(); URL.revokeObjectURL(url);
  });
  $("#sb-push").addEventListener("click", async () => {
    if (!confirm(`${rijenN} trainingen op de FinalSurge-kalender van ${a.naam} zetten? Bestaande trainingen blijven staan (worden niet gewist).`)) return;
    const btn = $("#sb-push"); btn.disabled = true; btn.textContent = "Bezig met pushen…";
    const st = $("#sb-csvstatus"); st.textContent = "Trainingen in FinalSurge zetten… (kan even duren)";
    const r = await jpost("/api/schema/push", { key: a.key, csv: csvTekst }).catch(() => null);
    btn.disabled = false; btn.innerHTML = `${ic("refresh")} Zet in FinalSurge`;
    if (!r || !r.ok) { st.textContent = ""; return melding(r?.err || "Pushen mislukt.", true); }
    const fout = (r.fouten || []).length;
    st.textContent = `${r.ok_aantal} van ${r.totaal} trainingen in FinalSurge gezet${fout ? `, ${fout} met een fout` : ""}. ✓`;
    haptic(20);
  });
}
$("#sb-refresh").addEventListener("click", () => { geladen.schema = true; laadSchema(); });

// ════════════════════════════════════════════════════════════════════════════
// RACES — aankomende races + race-wens plaatsen (WRITE via post_comment)
// ════════════════════════════════════════════════════════════════════════════
async function laadRaces() {
  const box = $("#rc-lijst"), info = $("#rc-info");
  info.textContent = "Races ophalen uit FinalSurge…";
  skeleton(box, 4);
  const r = await api("/api/races").catch(() => null);
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  if (!r.fs) { info.textContent = "FinalSurge nog niet gekoppeld."; box.innerHTML = ""; return; }
  const items = r.items || [];
  const open = items.filter(i => !i.wens_gegeven).length;
  info.textContent = items.length
    ? `${items.length} aankomende race${items.length === 1 ? "" : "s"}${open ? ` · ${open} zonder wens` : " · alle wensen gegeven"}.`
    : "";
  if (!items.length) { box.innerHTML = `<div class="leeg">${ic("check")}<p>Geen races in de komende weken.</p></div>`; return; }
  box.innerHTML = "";
  items.forEach(it => box.appendChild(raceItem(it)));
}

function raceItem(it) {
  const el = document.createElement("article");
  el.className = "rij-kaart";
  const badge = it.wens_gegeven
    ? '<span class="mrow-tag" style="background:var(--ok-bg,#123);color:var(--ok,#5db98b)">wens gegeven</span>'
    : '<span class="mrow-tag soon-tag">nog geen wens</span>';
  el.innerHTML = `
    <div class="d-head"><span class="avatar">${initialen(it.naam)}</span>
      <div><h3>${esc(it.naam)}</h3>
        <p class="muted klein">${esc(it.datum)} · ${esc(it.race)}${it.type ? " · " + esc(it.type) : ""}</p></div>
      <span style="margin-left:auto">${badge}</span></div>
    ${it.wens ? `<div class="fb-thread"><div class="fb-bub coach"><span class="fb-wie">Jij</span>${esc(it.wens)}</div></div>` : ""}
    <textarea class="fb-tekst" rows="4" placeholder="Race-wens / strategie voor ${esc(it.voornaam)}…">${esc(it.wens || "")}</textarea>
    <div class="fb-acts">
      <button class="btn primary" data-post>${ic("message")} Plaats wens</button>
    </div>
    <p class="hint" data-poststatus></p>`;
  const tekstEl = el.querySelector(".fb-tekst");
  const status = el.querySelector("[data-poststatus]");
  el.querySelector("[data-post]").addEventListener("click", async () => {
    const tekst = tekstEl.value.trim();
    if (!tekst) return melding("Schrijf eerst een race-wens.", true);
    if (!confirm(`Deze race-wens bij ${it.voornaam} plaatsen? ${it.voornaam} ziet dit in FinalSurge.`)) return;
    const btn = el.querySelector("[data-post]"); btn.disabled = true; btn.textContent = "Plaatsen…";
    const r = await jpost("/api/races/wens", { id: it.id, tekst }).catch(() => null);
    btn.disabled = false; btn.innerHTML = `${ic("message")} Plaats wens`;
    if (!r || !r.ok) return melding(r?.err || "Posten mislukt.", true);
    status.textContent = "Wens geplaatst in FinalSurge ✓"; haptic(15);
  });
  return el;
}
$("#rc-refresh").addEventListener("click", () => { geladen.races = true; laadRaces(); });

// ════════════════════════════════════════════════════════════════════════════
// SCHEMA-VERLOOP — wie loopt bijna zonder schema (puur lezend)
// ════════════════════════════════════════════════════════════════════════════
const SV_LABEL = { verlopen: "verlopen", bijna: "loopt bijna af", loopt: "loopt nog", geen: "geen schema" };
async function laadSchemaVerloop() {
  const box = $("#sv-lijst"), info = $("#sv-info");
  info.textContent = "Schema's ophalen uit FinalSurge…";
  skeleton(box, 5);
  const r = await api("/api/schema-verloop").catch(() => null);
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  if (!r.fs) { info.textContent = "FinalSurge nog niet gekoppeld."; box.innerHTML = ""; return; }
  const items = r.items || [];
  const aandacht = items.filter(i => i.status === "verlopen" || i.status === "bijna" || i.status === "geen").length;
  info.textContent = items.length
    ? `${items.length} atleten · ${aandacht} met aandacht (verlopen, bijna klaar of geen schema).`
    : "";
  if (!items.length) { box.innerHTML = `<div class="leeg">${ic("check")}<p>Geen schema-data.</p></div>`; return; }
  box.innerHTML = "";
  items.forEach(it => box.appendChild(svItem(it)));
}

function svItem(it) {
  const el = document.createElement("article");
  el.className = "rij-kaart sv-rij";
  const kleur = { verlopen: "#e0645a", bijna: "#e0a23a", loopt: "#5db98b", geen: "#8a8f98" }[it.status] || "#8a8f98";
  const dagtxt = it.dagen === null ? "—"
    : it.dagen < 0 ? `${-it.dagen}d verlopen`
    : it.dagen === 0 ? "vandaag klaar"
    : `nog ${it.dagen}d`;
  el.innerHTML = `
    <div class="d-head"><span class="avatar">${initialen(it.naam)}</span>
      <div><h3>${esc(it.naam)}</h3>
        <p class="muted klein">${esc(it.groep || "")}${it.laatste ? " · laatste " + esc(it.laatste) : ""}</p></div>
      <span style="margin-left:auto;text-align:right">
        <b style="color:${kleur}">${dagtxt}</b>
        <span class="muted klein" style="display:block">${SV_LABEL[it.status] || ""}</span></span></div>
    ${it.verborgen ? `<p class="muted klein">${it.verborgen} training(en) nog verborgen voor de atleet${it.zichtbaar_tot ? " · zichtbaar t/m " + esc(it.zichtbaar_tot) : ""}</p>` : ""}`;
  return el;
}
$("#sv-refresh").addEventListener("click", () => { geladen["schema-verloop"] = true; laadSchemaVerloop(); });

// ════════════════════════════════════════════════════════════════════════════
// TEAMPULS — belasting-signalen (gezien/dossier) + AI-weekbriefing
// ════════════════════════════════════════════════════════════════════════════
async function laadTeampuls(force = false) {
  const box = $("#tp-signalen"), info = $("#tp-info");
  info.textContent = force ? "Belasting-signalen herberekenen (alle atleten)…" : "Belasting-signalen laden…";
  skeleton(box, 3);
  const brief = $("#tp-briefing"); brief.innerHTML = `<div class="skel-card"><div class="skel skel-line w60"></div></div>`;
  const r = await api(`/api/teampuls/signalen${force ? "?force=true" : ""}`).catch(() => null);
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  if (!r.fs) { info.textContent = "FinalSurge nog niet gekoppeld."; box.innerHTML = ""; return; }
  const items = r.items || [];
  info.innerHTML = `Signalen uit volume, gevoel, RPE en notities — geen diagnose, wel een seintje. `
    + (items.length ? `<b>${r.hoog || 0}</b> hoog · <b>${items.length}</b> in beeld · ${esc(r.datum || "")}` : `alles binnen de marge · ${esc(r.datum || "")}`);
  box.innerHTML = "";
  if (!items.length) { box.innerHTML = `<div class="leeg">${ic("check")}<p>Geen belasting-signalen — iedereen binnen de marge.</p></div>`; }
  else items.forEach(it => box.appendChild(pulsItem(it)));
  laadBriefing();
}

function pulsItem(it) {
  const el = document.createElement("article");
  el.className = "rij-kaart puls-kaart " + (it.ernst === "hoog" ? "ernst-hoog" : "ernst-let");
  const m = it.metrics || {};
  const runs = (m.runs || []).map(r => `<li>${esc(r.datum)}: ${r.km} km${r.naam ? " · " + esc(r.naam) : ""}</li>`).join("");
  const sig = (it.signalen || []).map(s => `<li>${esc(s)}</li>`).join("");
  el.innerHTML = `
    <div class="d-head">
      <span class="puls-dot ${it.ernst === "hoog" ? "hoog" : "let"}"></span>
      <div><h3>${esc(it.naam)}</h3><p class="muted klein">${esc(it.groep || "")}</p></div>
      <span class="puls-tag ${it.ernst === "hoog" ? "hoog" : "let"}">${it.ernst === "hoog" ? "hoog" : "let op"}</span>
    </div>
    <ul class="puls-sig">${sig}</ul>
    ${it.duiding ? `<p class="puls-duiding">${ic("message")} ${esc(it.duiding)}</p>` : ""}
    <details class="puls-ond"><summary>Onderbouwing (welke trainingen zijn geteld)</summary>
      <ul class="puls-runs">${runs || "<li class='muted'>Geen losse runs geregistreerd.</li>"}</ul>
      <p class="muted klein">Recente week ${m.km_recent ?? "?"} km · basis ${m.km_basis ?? "?"} km/wk · gevoel ${m.gevoel_recent ?? "—"} vs ${m.gevoel_basis ?? "—"} · RPE ${m.rpe_recent ?? "—"} vs ${m.rpe_basis ?? "—"}.</p>
    </details>
    <div class="fb-acts">
      <button class="btn ghost small" data-gezien>${ic("check")} Gezien (7 dagen)</button>
      <button class="btn ghost small" data-dossier>Dossier →</button>
    </div>`;
  el.querySelector("[data-gezien]").addEventListener("click", async () => {
    const r = await jpost("/api/teampuls/gezien", { user_key: it.user_key, ernst: it.ernst }).catch(() => null);
    if (!r || !r.ok) return melding("Kon niet dempen.", true);
    el.style.opacity = ".4"; setTimeout(() => el.remove(), 250); haptic(10);
  });
  el.querySelector("[data-dossier]").addEventListener("click", () => toonView("atleten"));
  return el;
}

async function laadBriefing(force = false) {
  const brief = $("#tp-briefing");
  brief.innerHTML = `<div class="skel-card"><div class="skel skel-line w60"></div><div class="skel skel-line w80"></div></div>`;
  const r = await api(`/api/teampuls/briefing${force ? "?force=true" : ""}`).catch(() => null);
  if (!r || !r.fs) { brief.innerHTML = `<p class="muted klein">Weekbriefing niet beschikbaar.</p>`; return; }
  if (r.err) { brief.innerHTML = `<p class="muted klein">${esc(r.err)}</p>`; return; }
  const s = r.stats || {};
  brief.innerHTML = `
    <article class="brief-kaart">
      <p class="muted klein">Gemaakt ${esc(r.gemaakt || "")} · gedeeld met beide coaches · ${s.n_trainingen ?? "?"} trainingen · ±${s.km_totaal ?? "?"} km · ${s.n_actief ?? "?"}/${s.n_atleten ?? "?"} actief</p>
      <div class="brief-tekst">${briefHtml(r.tekst || "")}</div>
      <button class="btn ghost small" id="tp-brief-refresh">${ic("refresh")} Vernieuw briefing</button>
    </article>`;
  $("#tp-brief-refresh")?.addEventListener("click", () => laadBriefing(true));
}
// Lichte markdown → HTML voor de briefing (kop/bullet/vet)
function briefHtml(t) {
  const lines = esc(t).split("\n"); let out = "", inUl = false;
  for (let ln of lines) {
    ln = ln.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    if (/^\s*[-•]\s+/.test(ln)) { if (!inUl) { out += "<ul>"; inUl = true; } out += `<li>${ln.replace(/^\s*[-•]\s+/, "")}</li>`; continue; }
    if (inUl) { out += "</ul>"; inUl = false; }
    if (/^#{1,4}\s/.test(ln)) out += `<h4>${ln.replace(/^#{1,4}\s/, "")}</h4>`;
    else if (ln.trim()) out += `<p>${ln}</p>`;
  }
  if (inUl) out += "</ul>";
  return out;
}
$("#tp-refresh").addEventListener("click", () => laadTeampuls(true));

// ════════════════════════════════════════════════════════════════════════════
// ADMINISTRATIE — financiële cockpit (pincode-gate, puur lezend)
// ════════════════════════════════════════════════════════════════════════════
const eur = v => "€" + (Math.round(v || 0)).toLocaleString("nl-NL");
let adminPin = "";
async function laadAdmin() {
  const st = await api("/api/admin/status").catch(() => null);
  const hint = $("#ad-lockhint");
  if (st && st.vergrendeld) {
    $("#ad-gate").hidden = false; $("#ad-body").hidden = true;
    hint.innerHTML = `<span style="color:var(--warn,#e0a23a)">Geen ADMIN_PIN ingesteld op de server — deze module is vergrendeld.</span>`;
    $("#ad-pin").disabled = true; $("#ad-unlock").disabled = true;
    return;
  }
}
$("#ad-unlock")?.addEventListener("click", ontgrendelAdmin);
$("#ad-pin")?.addEventListener("keydown", e => { if (e.key === "Enter") ontgrendelAdmin(); });

async function ontgrendelAdmin() {
  const pin = $("#ad-pin").value.trim();
  if (!pin) return;
  const btn = $("#ad-unlock"); btn.disabled = true; btn.textContent = "Openen…";
  const r = await jpost("/api/admin/overzicht", { pin }).catch(() => null);
  btn.disabled = false; btn.innerHTML = `${ic("check")} Openen`;
  if (!r || !r.ok) { $("#ad-lockhint").innerHTML = `<span style="color:var(--danger,#e0645a)">Onjuiste pincode.</span>`; haptic(20); return; }
  adminPin = pin;
  $("#ad-gate").hidden = true; $("#ad-body").hidden = false; $("#ad-refresh").hidden = false;
  tekenAdmin(r);
}
$("#ad-refresh")?.addEventListener("click", async () => {
  if (!adminPin) return;
  const r = await jpost("/api/admin/overzicht", { pin: adminPin }).catch(() => null);
  if (r && r.ok) tekenAdmin(r);
});

function ring(pct, kleur, label, sub) {
  const R = 52, C = 2 * Math.PI * R, off = C * (1 - Math.min(pct, 100) / 100);
  return `<div class="ad-ring">
    <svg viewBox="0 0 120 120"><circle class="ring-bg" cx="60" cy="60" r="${R}"/>
      <circle class="ring-arc" cx="60" cy="60" r="${R}" stroke="${kleur}"
        stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/></svg>
    <div class="ad-ring-mid"><b>${label}</b><span>${sub}</span></div></div>`;
}

function tekenAdmin(d) {
  const body = $("#ad-body");
  const k = d.kor || {}, b = d.btw || {}, t = d.tellen || {};
  const modusBtw = d.modus === "btw";
  const korKleur = k.pct >= 90 ? "#e0645a" : k.pct >= 75 ? "#e0a23a" : "#5db98b";
  const maxCat = Math.max(1, ...(d.categorie || []).map(c => c.bedrag));
  const catBars = (d.categorie || []).map(c =>
    `<div class="ad-bar"><span class="ad-bar-l">${esc(c.naam)}</span>
      <span class="ad-bar-track"><i style="width:${Math.max(4, c.bedrag / maxCat * 100)}%;background:${c.kleur}"></i></span>
      <span class="ad-bar-v">${eur(c.bedrag)}</span></div>`).join("")
    || `<p class="muted klein">${d.rompslomp ? "Nog geen gefactureerde omzet dit jaar." : "Rompslomp niet gekoppeld — facturen ontbreken."}</p>`;
  const maxPak = Math.max(1, ...(d.pakketten || []).map(p => p.bedrag));
  const pakBars = (d.pakketten || []).map(p =>
    `<div class="ad-bar"><span class="ad-bar-l">${esc(p.naam)}</span>
      <span class="ad-bar-track"><i style="width:${Math.max(4, p.bedrag / maxPak * 100)}%;background:#5EE6EB"></i></span>
      <span class="ad-bar-v">${eur(p.bedrag)}</span></div>`).join("")
    || `<p class="muted klein">Geen pakketverdeling.</p>`;
  const nf = d.niet_gefactureerd || [];

  body.innerHTML = `
    <div class="ad-hero">
      ${ring(k.pct || 0, korKleur, eur(k.huidig), "van " + eur(k.grens))}
      <div class="ad-hero-txt">
        <p class="ad-badge ${modusBtw ? "btw" : "kor"}">${modusBtw ? "BTW-modus" : "KOR-modus"} · ${d.jaar}</p>
        <h2>${eur(k.huidig)}<span class="muted"> / ${eur(k.grens)} KOR</span></h2>
        <p class="muted klein">${k.gepasseerd ? "⚠️ KOR-grens gepasseerd" :
          (k.datum_grens ? `Bij dit tempo grens rond ${esc(k.datum_grens)}` : "Ruim binnen de grens")}${k.per_week ? ` · ~${eur(k.per_week)}/wk` : ""}</p>
      </div>
    </div>

    <div class="ad-grid">
      <div class="ad-metric"><span>Verwachte jaaromzet</span><b>${eur(d.jaaromzet)}</b><i class="muted klein">actieve klanten × 13 periodes</i></div>
      <div class="ad-metric"><span>Actieve klanten</span><b>${t.actief || 0}</b><i class="muted klein">${t.on_hold || 0} on hold · ${t.gratis || 0} gratis</i></div>
      ${modusBtw ? `<div class="ad-metric"><span>Btw dit jaar</span><b>${eur(b.btw_totaal)}</b><i class="muted klein">${esc(b.kwartaal || "")} · ${eur(b.btw_kwartaal)} · ${esc(b.aangifte_label || "")}</i></div>`
        : `<div class="ad-metric"><span>Nog tot KOR-grens</span><b>${eur(k.resterend)}</b><i class="muted klein">${k.per_week ? "~" + eur(k.per_week) + "/wk" : ""}</i></div>`}
    </div>

    <p class="sec-label">Gefactureerde omzet per categorie ${d.jaar}</p>
    <div class="ad-bars">${catBars}</div>

    <p class="sec-label">Verwachte jaaromzet per pakket</p>
    <div class="ad-bars">${pakBars}</div>

    <p class="sec-label">Nog niet gefactureerd dit jaar${nf.length ? ` · ${nf.length}` : ""}</p>
    ${nf.length ? `<div class="ad-chips">${nf.map(n => `<span class="ad-chip">${esc(n)}</span>`).join("")}</div>`
      : `<div class="leeg small">${ic("check")}<p>${d.rompslomp ? "Iedereen gefactureerd (voor zover te matchen)." : "Rompslomp niet gekoppeld — geen factuurcontrole."}</p></div>`}
    ${d.fx_err ? `<p class="muted klein" style="margin-top:10px">${esc(d.fx_err)}</p>` : ""}`;
  requestAnimationFrame(() => body.querySelectorAll(".ring-arc").forEach(a => a.style.strokeDashoffset = a.getAttribute("stroke-dashoffset")));
}

// ── Start ──────────────────────────────────────────────────────────────────
laders.strippen = laad;
laders.atleten = laadDossierLijst;
laders.intake = laadIntake;
laders.documenten = laadDocs;
laders.feedback = laadFeedback;
laders.schema = laadSchema;
laders.races = laadRaces;
laders["schema-verloop"] = laadSchemaVerloop;
laders.teampuls = laadTeampuls;
laders.admin = laadAdmin;
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
toonOffline();
if (navigator.onLine) flush();
renderHome();
