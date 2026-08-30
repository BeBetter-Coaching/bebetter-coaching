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
const jpost = (u, body, method = "POST", keepalive = false) => api(u, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), keepalive,
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
  // Verlaat Home → bewaar scrollpositie zodat terugkeer die kan herstellen (#14).
  if (huidigeView === "home" && view !== "home") {
    const sc = $("#scroller"); if (sc) homeScroll = sc.scrollTop;
  }
  // Verlaat Feedback → sluit de mobiele focus-overlay (mag niet over andere views blijven).
  if (huidigeView === "feedback" && view !== "feedback") {
    const c = $("#fb-focus-col"); if (c) { c.classList.remove("on"); c.setAttribute("aria-hidden", "true"); c.style.height = ""; c.style.top = ""; }
    document.body.classList.remove("kb-open");
  }
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
  pushRoute(view);
}
$$("[data-open-view]").forEach(b => b.addEventListener("click", () => openModuleFromNav(b.dataset.openView)));

// ── Deep-link routing: view + geselecteerde atleet overleven een refresh (#C) ─
// De PWA had géén URL-state; elke refresh viel terug op Home + de volledige lijst.
// We schrijven nu een lichte hash (#view of #atleten/<id>) en herstellen die bij
// laden en bij terug/vooruit. Expliciete URL wint; onbekende atleet valt netjes
// terug (openDossier toont dan 'kon niet laden'), onbekende view → Home.
let _routing = false;                                   // onderdruk hash-schrijven tijdens toepassen
function pushRoute(view, ident) {
  if (_routing) return;
  const h = "#" + (ident ? `${view}/${encodeURIComponent(ident)}` : view);
  if (location.hash !== h) { try { history.pushState(null, "", h); } catch {} }
}
function applyRoute() {
  const raw = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  const slash = raw.indexOf("/");
  const view = slash === -1 ? raw : raw.slice(0, slash);
  const ident = slash === -1 ? "" : raw.slice(slash + 1);
  _routing = true;
  try {
    if (view && document.querySelector(`.view[data-view="${view}"]`)) toonView(view);
    else toonView("home");
    if (view === "atleten" && ident) openDossier(ident);   // synchrone prefix draait nog binnen de guard
    else if (view === "schema") { if (ident) openSchemaAthlete(ident); else { schemaOpenPending = ""; sbToonLijst(); } }
    else if (view === "dossier") { if (ident) openDossierCockpit(ident); else { dcOpenPending = ""; dcToonLijst(); } }
    else if (view === "workspace") { if (ident) openWorkspace(ident); else { wsOpenPending = ""; wsToonLijst(); } }
  } finally { _routing = false; }
}
window.addEventListener("popstate", applyRoute);

// ── Coach Workflow Cohesion v1 (FINAL) — athlete-first navigatie-shell ────────
// ÉÉN contract, op VIEW-namen (de route is de enige waarheid; geen module-alias-map
// meer, geen tweede navigatielaag, geen store). Kernonderscheid:
//   • active athlete = navigation/workflow-context (leeft ALLEEN in de route-hash);
//   • athlete facts  = server/canonical truth (`user_key`).
// Zodra de route een athlete-view + `user_key` draagt, is DIE atleet de actieve
// context; athlete-aware navigatie (chips én globale sidebar) neemt 'm mee tot de
// coach bewust een andere atleet kiest of naar een globale view gaat.
const _ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"]);   // views die een athlete-context dragen
// De atleet uit de HUIDIGE route (of "" als er geen athlete-context is). Route wint
// altijd van in-memory UI-state — precies daarom lezen we 'm hier uit de hash.
function activeAthleteKey() {
  const raw = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  const i = raw.indexOf("/");
  if (i === -1) return "";
  const view = raw.slice(0, i), ident = raw.slice(i + 1);
  // Identity-guard: `nieuw:` is UITSLUITEND pre-link intake-identity. Zo'n route mag het
  // orphan-detail in Atleten openen (koppel-flow), maar mag NOOIT als app-brede athlete-
  // context fungeren — alleen een echte FinalSurge user_key mag cross-module meegenomen
  // worden. Anders zou de globale sidebar `nieuw:` naar Schema/Dossier/Cockpit dragen,
  // modules die een canonical user_key verwachten. Na koppelen (echte user_key) werkt de
  // athlete-first navigatie gewoon.
  if (ident.startsWith("nieuw:")) return "";
  return (_ATHLETE_VIEWS.has(view) && ident) ? ident : "";
}
// Open een specifieke atleet (canonical `user_key`) in een athlete-view, zonder
// opnieuw te zoeken. Schrijft de route en laat applyRoute via de bestaande consume-
// paden laden. Geen key of globale view → gewone module-entry (picker/lijst).
function openAthleteModule(view, user_key) {
  if (!user_key || !_ATHLETE_VIEWS.has(view)) { toonView(view); return; }
  // Draft-veiligheid (PF-1): verlaat je de schema-workbench, flush dan eerst de
  // coach-draft zodat in-memory edits niet verloren gaan bij het wegnavigeren.
  if (huidigeView === "schema" && view !== "schema" && typeof sbDraftSave === "function" && sbState) {
    try { sbDraftSave(); } catch {}
  }
  const h = "#" + view + "/" + encodeURIComponent(user_key);
  if (location.hash !== h) { try { history.pushState(null, "", h); } catch {} }
  applyRoute();
}
// Globale nav-adapter (sidebar/bottomnav/'meer'/home-kaarten): is de doel-view
// athlete-aware ÉN is er een actieve atleet in de route → open die atleet; anders
// gewone (globale) module-entry. Zo blijft de sidebar athlete-aware zonder verborgen
// contextwissels: globale views (home/races/admin/…) laten de context bewust los.
function openModuleFromNav(view) {
  const key = activeAthleteKey();
  if (key && _ATHLETE_VIEWS.has(view)) openAthleteModule(view, key);
  else toonView(view);
}
// Gedeelde, compacte athlete-context navigatie (chips): de OVERIGE athlete-tools naast
// de naam-kop. Eén component, view-gekeyd (zelfde vocabulaire als de shell), zodat de
// actieve tool niet dubbel verschijnt. `activeView` = huidige route-view.
function athleteNav(activeView, user_key) {
  if (!user_key) return "";
  const opts = [
    { view: "atleten", label: "Dossier" },
    { view: "schema", label: "Schema" },
    { view: "dossier", label: "Cockpit" },
  ];
  const chips = opts.filter(o => o.view !== activeView).map(o =>
    `<button type="button" class="anav-chip" onclick="openAthleteModule('${o.view}','${esc(user_key)}')">${esc(o.label)}</button>`).join("");
  // Workspace is athlete-aware maar bewust NIET in _ATHLETE_VIEWS (Cohesion-contract
  // byte-identiek): een eigen chip die direct openWorkspace(key) aanroept.
  const ws = activeView === "workspace" ? "" :
    `<button type="button" class="anav-chip" onclick="openWorkspace('${esc(user_key)}')">Workspace</button>`;
  const all = ws + chips;
  return all ? `<div class="anav" role="group" aria-label="Ga naar voor deze atleet">${all}</div>` : "";
}

// ══════════════════════════════════════════════════════════════════════════
// Design System v1 — gedeelde UI-primitives (Workspace, Dossier, Home-detail)
// --------------------------------------------------------------------------
// ÉÉN visuele + interactionele taal. Deze functies geven HTML-strings terug en
// zijn PUUR presentatie: ze lezen alleen wat de server al als waarheid levert en
// verzinnen niets. Statussemantiek loopt via `dsTone()` — de enige plek waar een
// betekenis (actie/aandacht/hoog/let_op/stale/…) een kleur krijgt, zodat dezelfde
// betekenis nooit meer per module een andere kleur kan krijgen.
// ══════════════════════════════════════════════════════════════════════════

// DE statusmapping. Server-vocabulaires (tier, ernst, reliability-level,
// freshness) → één set toon-klassen uit design-system.css.
const _DS_TONE = {
  actie: "is-critical", aandacht: "is-attention",
  hoog: "is-critical", let_op: "is-attention",
  critical: "is-critical", attention: "is-attention", calm: "is-calm",
  success: "is-success", resolved: "is-success", ok: "is-calm",
  stale: "is-stale", refreshing: "is-stale",
  unknown: "is-unknown", partial: "is-unknown",
  red: "is-critical", amber: "is-attention", green: "is-calm",
  fresh: "is-calm",
};
function dsTone(v) { return _DS_TONE[String(v == null ? "" : v).toLowerCase()] || "is-calm"; }

// Zwaarste toon uit een set (actie wint van aandacht wint van rustig).
const _DS_RANK = { "is-critical": 3, "is-attention": 2, "is-stale": 1, "is-unknown": 1, "is-success": 0, "is-calm": 0 };
function dsWorstTone(tones) {
  return (tones || []).reduce((a, t) => (_DS_RANK[t] || 0) > (_DS_RANK[a] || 0) ? t : a, "is-calm");
}

function dsChip(text, tone) { return `<span class="ds-chip ${tone || "is-calm"}">${esc(text)}</span>`; }

// Bron/versheid — één component voor Home, Workspace, Dossier en Teampuls.
function dsFresh(state, text) {
  const t = dsTone(state);
  return `<span class="ds-fresh ${t}"><i class="ds-dot"></i>${esc(text)}</span>`;
}

// Sparkline uit ECHTE reeksen (bv. de recente runs uit de belasting-stand).
// Geen library, geen canvas: één inline SVG-pad. Leeg bij < 2 punten — we
// tekenen liever niets dan een verzonnen lijn.
function dsSpark(vals) {
  const v = (vals || []).map(Number).filter(n => isFinite(n));
  if (v.length < 2) return "";
  const w = 100, h = 30, min = Math.min(...v), max = Math.max(...v), span = (max - min) || 1;
  const pts = v.map((n, i) => [(i / (v.length - 1)) * w, h - 3 - ((n - min) / span) * (h - 8)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return `<svg class="ds-metric-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path class="ds-spark-area" d="${d} L ${w} ${h} L 0 ${h} Z"/>
    <path class="ds-spark-line" d="${d}" vector-effect="non-scaling-stroke"/>
    <circle class="ds-spark-dot" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.4"/></svg>`;
}

// Voortgangsring (bv. feedback-afhandeling). Alleen bij een echt percentage.
function dsRing(pct, tone) {
  if (pct == null || !isFinite(Number(pct))) return "";
  const p = Math.max(0, Math.min(100, Math.round(Number(pct)))), r = 30, c = 2 * Math.PI * r;
  return `<figure class="ds-ringwrap ${tone || "is-calm"}"><svg viewBox="0 0 76 76" aria-hidden="true">
    <circle class="ds-ring-track" cx="38" cy="38" r="${r}"/>
    <circle class="ds-ring-val" cx="38" cy="38" r="${r}" stroke-dasharray="${(c * p / 100).toFixed(1)} ${c.toFixed(1)}"/>
    </svg><figcaption>${p}%</figcaption></figure>`;
}

// Metric-tegel: label, groot getal, eenheid, subregel en optionele sparkline.
function dsMetric(m) {
  const tone = m.tone ? ` ds-tone ${m.tone}` : "";
  return `<div class="ds-metric${tone}">
    <span class="ds-metric-l">${esc(m.label)}${m.badge ? `<span class="ds-chip ${m.tone || "is-calm"}">${esc(m.badge)}</span>` : ""}</span>
    <span class="ds-metric-v">${esc(m.value)}${m.unit ? `<span class="ds-metric-u">${esc(m.unit)}</span>` : ""}</span>
    ${m.sub ? `<span class="ds-metric-s">${esc(m.sub)}</span>` : ""}
    ${m.spark || ""}</div>`;
}

// Aandachtkaart — DE manier waarop de app "dit vraagt nu aandacht" toont.
function dsAttnCard(a) {
  const tone = a.tone || "is-attention";
  return `<div class="ds-attn-card ${tone}">
    <span class="ds-attn-ic">${ic(a.icon || "alert")}</span>
    <span class="ds-attn-body">
      <p class="ds-attn-t">${esc(a.title)}</p>
      ${a.why ? `<p class="ds-attn-w">${esc(a.why)}</p>` : ""}
      ${a.meta ? `<p class="ds-attn-meta">${esc(a.meta)}</p>` : ""}
    </span>
    ${a.value ? `<span class="ds-attn-val">${esc(a.value)}</span>` : ""}</div>`;
}

// Paneel met sectiekop — vervangt de losse `*-sec h3`-varianten per module.
function dsPanel(label, body, o) {
  o = o || {};
  const tone = o.tone ? ` ds-tone ${o.tone}` : "";
  return `<section class="ds-panel${tone} ${o.cls || ""}">
    <div class="ds-sechead"><h3 class="ds-label">${esc(label)}</h3>
      ${o.note ? `<span class="ds-sechead-note">${esc(o.note)}</span>` : ""}</div>
    ${body}</section>`;
}

// Leesbare feitenlijst (vervangt de kale label/value-<ul>'s).
function dsKv(rows) {
  const r = (rows || []).filter(x => x && x.label != null);
  if (!r.length) return "";
  return `<dl class="ds-kv">` + r.map(x =>
    `<div><dt>${esc(x.label)}</dt><dd>${esc(x.value == null ? "—" : x.value)}</dd></div>`).join("") + `</dl>`;
}

// Compacte stream/tijdlijn (recent veranderd, historie).
function dsStream(items) {
  const it = (items || []).filter(Boolean);
  if (!it.length) return "";
  return `<ul class="ds-stream">` + it.map(x =>
    `<li class="${x.tone || "is-calm"}">${x.date ? `<span class="ds-stream-d">${esc(x.date)}</span>` : ""}
      <span class="ds-stream-t">${esc(x.text)}</span></li>`).join("") + `</ul>`;
}

// Snelle actie — bestaande routes/authority, alleen een gedeelde presentatie.
function dsAction(a) {
  const tone = a.tone ? ` ds-tone ${a.tone}` : "";
  return `<button type="button" class="ds-action${tone}" onclick="${a.onclick}">
    <span class="ds-action-ic">${ic(a.icon || "chevron")}</span>
    <span class="ds-action-b"><span class="ds-action-t">${esc(a.title)}</span>
      ${a.sub ? `<span class="ds-action-s">${esc(a.sub)}</span>` : ""}</span></button>`;
}

function dsEmpty(text, o) {
  o = o || {};
  return `<p class="ds-empty ${o.tone || ""}">${ic(o.icon || "check")}<span>${esc(text)}</span></p>`;
}
function dsSkeletonBlock(n) {
  return `<div class="ds-panel">${Array.from({ length: n || 3 },
    (_, i) => `<div class="ds-skel ${i % 2 ? "w60" : "w80"}"></div>`).join("")}</div>`;
}

// NB: contextnavigatie tussen athlete-views blijft de BESTAANDE gedeelde
// `athleteNav()` (één definitie, vaste call-contracten). Het design system
// vervangt die niet — het geeft 'm alleen de gedeelde shell-stijl (.anav /
// .anav-chip worden in design-system.css opgewaardeerd). Eén nav-component.

// ── Coach Read Model v2 — generation/freshness-coherentie ────────────────────
// Eén gedeelde read-generation (server-side, inhoud-afgeleid) reist mee in elke
// Home/Teampuls/Workspace-response. De client onthoudt de LAATST ontvangen generatie
// en markeert elke nog-zichtbare view die een OUDERE generatie toont — zo zie je nooit
// meer `46%` naast `64%` als co-actueel, maar netjes "nieuwe state beschikbaar" zonder
// dat de lijst onder je verspringt. Puur presentatie-state; geen truth, geen cache.
const _bbGen = { id: "", at: "", sv: {} };
// Vector/version-dominance over de per-source versie-vector (belasting/home/feedback).
// `max(generation_at)` alleen is GEEN volledige ordening: twee composites kunnen dezelfde
// max delen terwijl één source-versie verschilt. Harde invariant: een generatie vervangt de
// bekende latest ALLEEN als hij op geen enkele source ouder is én op minstens één nieuwer.
// Een response die op één source terugloopt (bv. nieuwere feedback maar oudere belasting)
// wordt nooit stil de latest → geen sluipende load-terugval, geen arrival-order als waarheid.
function _genDominates(nv, cv) {
  const keys = new Set([...Object.keys(nv || {}), ...Object.keys(cv || {})]);
  let newer = false, older = false;
  keys.forEach(k => {
    const a = (nv && nv[k]) || "", b = (cv && cv[k]) || "";
    if (a > b) newer = true; else if (a < b) older = true;
  });
  return newer && !older;                                  // dominance: nieuwer op ≥1, ouder op geen
}
function noteGeneration(gen) {
  const id = gen && gen.generation_id;
  if (!id) return;
  if (id === _bbGen.id) return;                            // zelfde bekende state → no-op
  const nv = gen.source_versions || {};
  if (_bbGen.id && !_genDominates(nv, _bbGen.sv)) return;  // niet-dominant → nooit latest
  _bbGen.id = id; _bbGen.at = gen.generation_at || ""; _bbGen.sv = nv; bbGenSync();
}
function bbGenSync() {
  document.querySelectorAll(".gen-banner[data-gen]").forEach(el => {
    el.classList.toggle("on", el.dataset.gen && el.dataset.gen !== _bbGen.id);
  });
}
function genBanner(gen) {
  const id = (gen && gen.generation_id) || "";
  const at = ((gen && gen.generated_at) || "").slice(11, 16);
  const old = !!(id && _bbGen.id && id !== _bbGen.id);
  return `<div class="gen-banner${old ? " on" : ""}" data-gen="${esc(id)}">Bijgewerkt ${esc(at)} · nieuwe state beschikbaar</div>`;
}
// Stempel een dedicated slot (Home/Teampuls). ADOPTEER eerst de generatie (zodat deze
// verse response de nieuwe 'latest' wordt en oudere views geflipt worden), render dan
// de eigen banner (die dus zelf niet 'oud' is).
function genMount(sel, gen) {
  noteGeneration(gen);
  const el = $(sel);
  if (el) el.innerHTML = gen && gen.generation_id ? genBanner(gen) : "";
}

// ── Gedeelde refresh-feedback (Cohesion live-repair, cluster C) ──────────────
// Eén helper voor ELKE expliciete refresh-knop: directe spinner bij klik, blijft
// draaien tijdens de async refresh, reset bij succes én fout (finally) en blokkeert
// dubbel afvuren zolang de refresh loopt. Puur presentation-state — geen nieuwe truth,
// geen persistente state. Herbruikt de bestaande .iconbtn.spinning-animatie en het
// bewezen patroon van de Feedback-refresh (nu gedeeld i.p.v. per-module gekopieerd).
async function withSpin(btn, fn) {
  if (!btn) return fn && fn();
  if (btn.dataset.busy === "1") return;                    // dubbel afvuren geblokkeerd tijdens run
  btn.dataset.busy = "1"; btn.classList.add("spinning"); btn.disabled = true; btn.setAttribute("aria-busy", "true");
  try { return await fn(); }
  finally { btn.classList.remove("spinning"); btn.disabled = false; btn.dataset.busy = ""; btn.removeAttribute("aria-busy"); }
}
function bindRefresh(id, fn) {
  const btn = document.getElementById(id);
  if (btn) btn.addEventListener("click", () => withSpin(btn, fn));
}

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
  // Al opgebouwd? Behoud de state (open rij, prioriteiten, scrollpositie) i.p.v.
  // een volledige reset + zware herlaad bij elke terugkeer naar Home (#14).
  if (box && box.dataset.done === "1") {
    requestAnimationFrame(() => { const sc = $("#scroller"); if (sc) sc.scrollTo({ top: homeScroll || 0 }); });
    // Terugkeer via in-app navigatie (geen browserrefresh): her-lees de snapshot en render
    // de feedbacktegel DIRECT uit de canonieke fast-read (Class 1: `_apply_feedback_overlay`
    // → open-set). Na een post/skip klopt de tegel zo binnen één read, ZONDER de trage
    // Home-sweep (~20-25s). Is de open-set UNKNOWN (koud proces), dan toont de strip
    // 'bijwerken…' en verwarmen we de queue. cockpitVersen blijft enkel voor prioriteit-
    // staleness (nieuwe dag / TTL) op de achtergrond.
    api("/api/home/stats").then(s => {
      if (!s || !s.fs) return;
      genMount("#home-genbar", s.generation);              // v2: gedeelde generation-coherentie
      renderFeedbackStrip(s.feedback, true);
      if (s.feedback && s.feedback.stale) feedbackQueueWarm();
      cockpitVersen(s);
    }).catch(() => {});
    return;
  }
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
    <div id="home-ook"></div>`;
  box.dataset.done = "1";
  $$("[data-open-view]", box).forEach(b => b.addEventListener("click", () => openModuleFromNav(b.dataset.openView)));
  laadHeroFoto();

  // 2) Cockpit-snapshot (direct) → hero-telling/status, feedback, prioriteit.
  //    Verouderd? Dan op de achtergrond verversen (stale-while-revalidate).
  api("/api/home/stats").then(s => {
    if (s) genMount("#home-genbar", s.generation);         // v2: gedeelde generation-coherentie
    // Eerste-ooit (pending): laat de skeletons staan en bouw op de achtergrond op.
    if (s && s.pending) { cockpitVersen(s); return; }
    vulCockpit(s); cockpitVersen(s);
    if (s && s.feedback && s.feedback.stale) feedbackQueueWarm();   // Class 1: koude open-set → queue verwarmen
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
      $$("[data-open-view]", ook).forEach(b => b.addEventListener("click", () => openModuleFromNav(b.dataset.openView)));
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
// Class 1: een feedback-post/skip forceert HIER geen refresh meer — de tegel wordt canoniek
// uit de open-set gereconcilieerd (`_apply_feedback_overlay`) op de fast-read, dus de trage
// Home-sweep is niet nodig om de teller te corrigeren. Staleness geldt alleen nog de
// prioriteit-signalen (nieuwe dag / TTL), die post/skip niet raken.
function cockpitStale(s) {
  if (!s) return true;
  if (!s.berekend) return true;
  const today = new Date().toISOString().slice(0, 10);
  if (s.datum && s.datum !== today) return true;
  const t = Date.parse(s.berekend);
  return isNaN(t) || (Date.now() - t) > 15 * 60 * 1000;
}

let pendingSnap = null;   // verse snapshot die wacht tot de coach 'm toepast (#12)

// Ververst de cockpit op de achtergrond als de snapshot verouderd is.
function cockpitVersen(s) {
  if (!s || !s.fs) return;
  // Ververs als er nog niets is (pending) óf de gedeelde snapshot verouderd is.
  if (!s.pending && !(s.cached && cockpitStale(s))) return;
  const note = $("#prio-note");
  if (note) note.dataset.busy = "1";
  markVersen(true);
  api("/api/home/stats?refresh=1").then(fresh => {
    markVersen(false);
    if (note) note.dataset.busy = "";
    if (!fresh || fresh.pending) return;     // nog niet klaar → skeletons blijven
    const box = $("#home-prio");
    const heeftLijst = box && box.querySelector(".prio-item, .prio-leeg");
    if (!heeftLijst) { vulCockpit(fresh, true); genMount("#home-genbar", fresh.generation); return; }   // eerste build → direct tonen (autoritatief)
    // Feedbacktegel convergeert altijd naar de canonieke sweep (los van de lijst-diff),
    // zodat een post/skip-invalidatie de telling ook in diff-modus bijwerkt.
    renderFeedbackStrip(fresh.feedback, true);
    // v2: de refresh maakte generatie B, maar de ACTIEVE lijst verspringt bewust niet.
    // Adopteer B als 'latest' (→ de Home-banner flipt naar 'nieuwe state beschikbaar')
    // zonder de banner als actueel te herstempelen — dus geen verborgen mix A/B.
    noteGeneration(fresh.generation);
    cockpitDiffToon(fresh);                            // actieve lijst → NIET verspringen
  }).catch(() => { markVersen(false); if (note) note.dataset.busy = ""; prioTekenStatus(); });
}

// Class 1 (punt 6): "N nieuw" = AUTORITATIEVE set-diff, niet een DOM-diff. We vergelijken
// de verse serverlijst met de laatst TOEGEPASTE autoritatieve set (`lastPrioSig`, uk→signature),
// niet met de toevallige DOM-state — die kan optimistisch geleegd zijn, waardoor een oude
// lijst als "iedereen nieuw" terugkwam. De coach beslist wanneer de nieuwe stand wordt
// toegepast (scroll/open/swipe intact). DOM is rendering, geen truth-store.
let lastPrioSig = null;   // laatst toegepaste autoritatieve prioriteit-set (uk→signature)
function prioSigMap(list) {
  const m = {};
  (list || []).forEach(it => { m[it.user_key] = it.signature || ""; });
  return m;
}
function cockpitDiffToon(fresh) {
  const basis = lastPrioSig || {};
  let nieuw = 0;
  (fresh.prioriteit || []).forEach(it => {
    if (!(it.user_key in basis) || basis[it.user_key] !== (it.signature || "")) nieuw++;
  });
  pendingSnap = fresh;
  if (nieuw > 0) cockpitNieuwBalk(nieuw);
  else cockpitNieuwBalkWeg();               // niks wezenlijks veranderd → geen melding (#13)
  prioTekenStatus();                        // note terug van "bijwerken…" naar de telling
}
function cockpitNieuwBalk(n) {
  const box = $("#home-prio"); if (!box || !box.parentNode) return;
  let bar = $("#prio-nieuw");
  if (!bar) {
    bar = document.createElement("button");
    bar.id = "prio-nieuw"; bar.className = "prio-nieuw"; bar.type = "button";
    bar.addEventListener("click", cockpitToepassen);
    box.parentNode.insertBefore(bar, box);
  }
  bar.innerHTML = `${ic("refresh")} ${n} nieuw${n === 1 ? " aandachtspunt" : "e aandachtspunten"} — tik om te tonen`;
}
function cockpitNieuwBalkWeg() { const b = $("#prio-nieuw"); if (b) b.remove(); }
function cockpitToepassen() {
  if (!pendingSnap) { cockpitNieuwBalkWeg(); return; }
  const sc = $("#scroller"); const y = sc ? sc.scrollTop : 0;
  prioHerstelUk = prioOpenUk;                // heropen de rij die openstond na de rebuild
  const snap = pendingSnap; pendingSnap = null;
  cockpitNieuwBalkWeg();
  vulCockpit(snap, true);                     // toegepaste verse snapshot = autoritatief
  genMount("#home-genbar", snap.generation);  // v2: toegepaste generatie → banner weer actueel
  requestAnimationFrame(() => { if (sc) sc.scrollTo({ top: y }); });   // geen scrollsprong (#12)
}
function markVersen(on) {
  const n = $("#prio-note"); if (!n) return;
  if (on) n.innerHTML = `<span class="versen">bijwerken…</span>`;
}

// Vult hero-status + feedbackbalk + prioriteitlijst + info-strip met echte cockpit-data.
// Feedbacktegel: de TELLING is altijd de canonieke sweep-waarde (server muteert geen
// afgeleide teller). Een bevestigde post/skip markeert de Home-snapshot server-side als
// 'moet revalideren' (home_core.invalidate_feedback → `_revalidate`), zodat cockpitStale
// de bestaande achtergrond-refresh triggert die de tegel naar de sweep-waarde brengt.
// `homeFbDelta` is enkel een TRANSIËNTE client-optimalisatie die het korte venster tot
// die refresh overbrugt: toegepast op een cachede paint, gereset zodra een autoritatieve
// (fresh) read binnenkomt. Geen tweede waarheid — de server reconcilieert altijd.
// Feedback-voortgangsbalk (los renderbaar zodat een achtergrond-refresh de tegel naar de
// canonieke sweep-waarde kan brengen zónder de actieve prioriteitslijst te verstoren).
// Verwarm de gedeelde Feedback-queue en herlees de tegel — het HONESTE herstel bij een
// UNKNOWN open-set (koud proces / queue nog niet gebouwd). Reuse de bestaande queue-refresh
// (goedkoper dan de volledige Home-sweep); nooit de bevroren integer als 'actueel' tonen.
let fbWarmBezig = false;
function feedbackQueueWarm() {
  if (fbWarmBezig) return;
  fbWarmBezig = true;
  api("/api/feedback/queue?refresh=1")
    .then(() => api("/api/home/stats"))
    .then(s => { if (s && s.fs) renderFeedbackStrip(s.feedback, true); })
    .catch(() => {})
    .then(() => { fbWarmBezig = false; });
}

function renderFeedbackStrip(fbs, fresh) {
  fbs = fbs || {};
  const fb = $("#home-fb");
  if (!fb) return;
  if (fresh) homeFbDelta = { wachten: 0, gepost: 0 };     // autoritatieve read binnen → transiënt optimisme verrekend
  // Class 1: alleen een UNKNOWN open-set (koud proces / queue nog niet gebouwd → GEEN count,
  // wachten==null) toont 'bijwerken…'. Een STALE-maar-geldige open-set draagt de gereconcilieerde
  // count (skip/post al verwerkt) en wordt DIRECT getoond; de aanroeper ververst dan enkel
  // niet-blokkerend op de achtergrond (Round-2 regressie A: geen 12–20s wachten na skip/post).
  if (fbs.stale && fbs.wachten == null) {
    fb.classList.remove("skel-strip", "done");
    fb.innerHTML = `
      <div class="fb-strip-top">
        <span class="fb-strip-ic">${ic("message")}</span>
        <span class="fb-strip-t">Feedback bijwerken…</span>
        <span class="fb-strip-pct"></span>
      </div>
      <div class="mt-bar"><i style="width:0%"></i></div>
      <span class="fb-strip-sub">Even de actuele stand ophalen</span>`;
    return;
  }
  const w = Math.max(0, (fbs.wachten || 0) + homeFbDelta.wachten);
  const gepost = Math.max(0, (fbs.gepost || 0) + homeFbDelta.gepost);
  // pct opnieuw afleiden uit de (evt. optimistisch bijgestelde) getallen zodat de
  // balk intern consistent blijft; val terug op de serverwaarde als er geen basis is.
  const totaal = w + gepost;
  const pct = totaal ? Math.round(gepost / totaal * 100) : (fbs.pct != null ? fbs.pct : 100);
  fb.classList.remove("skel-strip");
  fb.classList.toggle("done", w === 0);
  fb.innerHTML = `
    <div class="fb-strip-top">
      <span class="fb-strip-ic">${ic(w ? "message" : "check")}</span>
      <span class="fb-strip-t">${w ? `<b>${w}</b> wachten op feedback` : "Alles beoordeeld"}</span>
      <span class="fb-strip-pct">${pct}%</span>
    </div>
    <div class="mt-bar"><i style="width:${pct}%"></i></div>
    <span class="fb-strip-sub">${gepost} vandaag gepost · ${pct}% afgerond</span>`;
}

function vulCockpit(s, fresh) {
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
  // In één bron (homeTel) zodat een afgehandelde rij de hero live kan bijwerken
  // zonder rebuild (work-queue-gevoel, #10).
  homeTel = { actie: team.actie || 0, aandacht: team.aandacht || 0, rustig: team.rustig || 0 };
  prioTekenStatus();

  // ── Feedback: dagelijkse kern als voortgangsbalk ──
  renderFeedbackStrip(fbs, fresh);

  // ── Prioriteit vandaag: gegroepeerd per atleet (wie → waarom → actie) ──
  const prio = s.prioriteit || [];
  lastPrioSig = prioSigMap(prio);      // Class 1: deze toegepaste set = de nieuwe autoritatieve diff-basis
  const box = $("#home-prio");
  if (box) {
    if (!prio.length) {
      box.innerHTML = `<div class="leeg small">${ic("check")}<p>Niks urgents nu — mooie dag om te coachen.</p></div>`;
    } else {
      box.innerHTML = "";
      prioOpenUk = null; prioSwipeEl = null;          // verse lijst → geen open rij meer
      prio.forEach(it => box.appendChild(prioItem(it)));
      // State herstellen na terugkeer (deeplink): heropen de rij die openstond.
      if (prioHerstelUk) {
        const her = box.querySelector(`.prio-item[data-uk="${prioHerstelUk}"] .prio-row`);
        if (her) prioToggle(her.closest(".prio-item"), true);
        prioHerstelUk = null;
      }
    }
  }

  // ── Info-strip (secundaire context, cyaan — geen alarm) ──
  // 'Vandaag gepost' stond hier én in de feedbackbalk (dubbel). We houden 't in de
  // feedbackbalk (daar hoort de metric inhoudelijk) en tonen hier alleen races.
  const inf = $("#home-info");
  if (inf) {
    inf.innerHTML = info.races
      ? `<div class="info-strip"><button class="info-chip" data-open-view="races">${ic("flag")} ${info.races} race${info.races === 1 ? "" : "s"} komende 7 dgn</button></div>`
      : "";
    $$("[data-open-view]", inf).forEach(b => b.addEventListener("click", () => openModuleFromNav(b.dataset.openView)));
  }
}

// ════════════════════════════════════════════════════════════════════════════
// PRIORITEIT-COCKPIT — tap = begrijpen (inline detail), swipe = snel handelen.
// Home blijft de werkplek: geen paginawissel voor de standaardactie. Alle
// detaildata zit al in de snapshot (nul extra fetch); alleen de gemiste sessies
// van een afhaker worden lazy per atleet geladen en client-side gecachet.
// ════════════════════════════════════════════════════════════════════════════
let prioOpenUk = null;      // welke rij staat inline open (max één)
let prioSwipeEl = null;     // welke rij toont swipe-acties (max één)
let prioHerstelUk = null;   // heropen deze rij na een lijst-herbouw (deeplink-terugkeer)
let homeScroll = 0;         // bewaarde scrollpositie van Home (state bij terugkeer)
let homeTel = { actie: 0, aandacht: 0, rustig: 0 };   // live team-status (één bron)
// Optimistische correctie op de Home-feedbackbalk na een Feedback-actie (send/skip),
// tot een autoritatieve server-refresh de echte stand levert. Zo klopt "wachten op
// feedback" meteen bij terugkeer naar Home, zonder Home te herbouwen of de
// server-snapshot te muteren.
let homeFbDelta = { wachten: 0, gepost: 0 };
function homeFbBijwerken(dWachten, dGepost) {
  homeFbDelta.wachten += dWachten; homeFbDelta.gepost += (dGepost || 0);
}
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// Hero-status + note uit één bron tekenen → een afgehandelde rij werkt de tellers
// live bij (geen dubbeltelling, geen rebuild).
function prioTekenStatus() {
  const hs = $("#hero-status");
  if (hs) {
    const c = [];
    if (homeTel.actie) c.push(`<span class="hs actie"><i></i>${homeTel.actie} actie</span>`);
    if (homeTel.aandacht) c.push(`<span class="hs aandacht"><i></i>${homeTel.aandacht} aandacht</span>`);
    if (homeTel.rustig) c.push(`<span class="hs rustig"><i></i>${homeTel.rustig} rustig</span>`);
    hs.innerHTML = c.join("") || `<span class="hs rustig"><i></i>iedereen bij</span>`;
  }
  const note = $("#prio-note");
  if (note && note.dataset.busy !== "1")
    note.textContent = (homeTel.actie || homeTel.aandacht)
      ? `${homeTel.actie} actie · ${homeTel.aandacht} aandacht` : "";
}
function prioTel(tier, delta) {
  if (tier === "actie") homeTel.actie = Math.max(0, homeTel.actie + delta);
  else if (tier === "aandacht") homeTel.aandacht = Math.max(0, homeTel.aandacht + delta);
  homeTel.rustig = Math.max(0, homeTel.rustig - delta);   // uit werklijst → rustig, en terug
  prioTekenStatus();
}

// Desktop-toetsenbord (§16): ↑/↓ = vorige/volgende prioriteit, Enter = openen,
// Esc = sluiten. Geen conflicterende shortcuts; alleen actief op Home. Enter/Esc
// zitten al op de rij; hier alleen de lijst-navigatie tussen rijen.
document.addEventListener("keydown", e => {
  if (huidigeView !== "home" || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
  const rows = $$("#home-prio .prio-row"); if (!rows.length) return;
  const cur = document.activeElement && document.activeElement.closest
    ? document.activeElement.closest(".prio-row") : null;
  let i = rows.indexOf(cur);
  i = e.key === "ArrowDown" ? (i < 0 ? 0 : Math.min(rows.length - 1, i + 1))
                            : (i < 0 ? rows.length - 1 : Math.max(0, i - 1));
  e.preventDefault(); rows[i].focus();
});

// Verticaal scrollen sluit een openstaande swipe-rij (nooit een verborgen actielaag
// laten hangen terwijl je wegscrollt, #5). Passief → geen invloed op scrollsnelheid.
$("#scroller")?.addEventListener("scroll", () => {
  if (prioSwipeEl && prioSwipeEl._snap) prioSwipeEl._snap("idle");
}, { passive: true });

// Workflow (swipe→rechts, groen) is UNIVERSEEL en identiek op elke rij: Gezien /
// Later. Context (swipe→links) is atleet-/type-afhankelijk: Dossier + hoogstens
// één type-deeplink. Zo heeft dezelfde gesture-richting altijd dezelfde betekenis.
const SOORT_IC = { belasting: "pulse", schema: "clock", compliance: "activity" };

function prioContext(it) {
  const dossier = { act: "dossier", label: "Dossier", icon: "user-plus" };
  // Eén signaal → toon ook de type-context op de swipe; meerdere → alleen Dossier
  // op de swipe, de per-signaal-contexten staan in het uitgeklapte detail (#9).
  const s0 = (it.signalen || [])[0];
  if (it.n_signalen === 1 && s0 && s0.context && s0.context[0]) return [s0.context[0], dossier];
  return [dossier];
}
function swBtn(a, cls) {
  return `<button class="pa-btn${cls ? " " + cls : ""}" data-act="${a.act}"${a.dagen ? ` data-dagen="${a.dagen}"` : ""} type="button">
    ${ic(a.icon)}<span>${a.label}</span></button>`;
}

// Eén prioriteit-item: swipe-lagen + gegroepeerde rij + (lazy) inline detail.
function prioItem(it) {
  const ctx = prioContext(it);
  const multi = it.n_signalen > 1;
  const wrap = document.createElement("div");
  wrap.className = "prio-item";
  wrap.dataset.uk = it.user_key; wrap.dataset.sig = it.signature || "";
  wrap._it = it;
  const secundair = multi
    ? `<span class="prio-chips">${(it.chips || []).map(c => `<span class="pc ${c.tier}">${esc(c.kort)}</span>`).join("")}</span>`
    : `<span class="prio-reden">${esc(it.reden)}</span>`;
  // Swipe = BULK over alle huidige signalen. Bij >1 signaal expliciet "Alles …" zodat
  // de coach niet denkt dat maar één aandachtspunt wordt geraakt.
  const gLabel = multi ? "Alles gezien" : "Gezien", lLabel = multi ? "Alles later" : "Later";
  wrap.innerHTML = `
    <div class="prio-swipe">
      <div class="pa-layer pa-left">${swBtn({ act: "gezien", label: gLabel, icon: "check" }, "primary")}${swBtn({ act: "later", label: lLabel, icon: "clock", dagen: 7 }, "later")}</div>
      <div class="pa-layer pa-right">${ctx.map(a => swBtn(a)).join("")}</div>
      <article class="prio-row ${it.tier}" role="button" tabindex="0"
        aria-expanded="false" aria-label="${esc(it.naam)} — ${multi ? it.n_signalen + " aandachtspunten" : esc(it.reden)}">
        <span class="prio-dot ${it.tier}"></span>
        <span class="avatar">${initialen(it.naam)}</span>
        <span class="prio-body">
          <span class="prio-naam">${esc(it.naam)}${multi ? `<span class="prio-count">${it.n_signalen}</span>` : ""}</span>
          ${secundair}
        </span>
        <span class="prio-actie">${ic("chevron")}</span>
      </article>
    </div>
    <div class="prio-detail" hidden></div>`;

  const row = wrap.querySelector(".prio-row");
  row.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); prioToggle(wrap); }
    if (e.key === "Escape") { prioToggle(wrap, false); prioSwipeDicht(wrap); }
  });
  wrap.querySelectorAll(".pa-btn").forEach(b =>
    b.addEventListener("click", e => { e.stopPropagation(); prioDoe(wrap, b.dataset.act, +b.dataset.dagen || 0); }));
  bindSwipe(wrap, row);
  return wrap;
}

// Inline detail openen/sluiten. Max één open: sluit eerst de vorige (rust, #8).
function prioToggle(wrap, force) {
  const detail = wrap.querySelector(".prio-detail");
  const row = wrap.querySelector(".prio-row");
  const open = force != null ? force : detail.hidden;
  prioSwipeDicht(wrap);                                     // swipe en expand bijten niet (#9)
  if (open) {
    if (prioOpenUk && prioOpenUk !== wrap.dataset.uk) {
      const vorige = document.querySelector(`.prio-item[data-uk="${prioOpenUk}"]`);
      if (vorige) prioToggle(vorige, false);
    }
    detail.innerHTML = prioDetailHtml(wrap._it);
    detail.hidden = false;
    wrap.classList.add("open"); row.setAttribute("aria-expanded", "true");
    prioOpenUk = wrap.dataset.uk;
    detail.querySelectorAll("[data-act]").forEach(b =>
      b.addEventListener("click", e => { e.stopPropagation(); prioDoe(wrap, b.dataset.act, +b.dataset.dagen || 0, b.dataset.soort || null); }));
    if ((wrap._it.signalen || []).some(s => s.soort === "compliance")) prioVulSessies(wrap);
    haptic(6);
  } else {
    detail.hidden = true; wrap.classList.remove("open");
    row.setAttribute("aria-expanded", "false");
    if (prioOpenUk === wrap.dataset.uk) prioOpenUk = null;
  }
}

// Detail = alle signalen van deze atleet (totaalbeeld). ELK signaal heeft zijn EIGEN
// Gezien/Later (per-signaal status) + eigen context-actie. Dossier is atleet-breed
// (één keer, onderaan). Bulk gaat via de swipe, niet via het detail.
// Home-detail = een ATHLETE BRIEFING, geen uitgeklapt legacy-paneel. Het toont
// alleen wat je nu over deze atleet moet weten: identiteit, reden voor aandacht,
// het dominante signaal, 2-3 ondersteunende feiten en de volgende coachactie.
// Zelfde data, zelfde optimistic-write-flow, zelfde routes.
function prioDetailHtml(it) {
  const sigs = it.signalen || [];
  const tone = dsWorstTone(sigs.map(s => dsTone(s.tier)));
  // Dominant signaal = het zwaarste; de rest is ondersteunende context.
  const hoofd = sigs.slice().sort((a, b) =>
    (dsTone(a.tier) === "is-critical" ? 0 : 1) - (dsTone(b.tier) === "is-critical" ? 0 : 1))[0];
  const bel = sigs.find(s => s.soort === "belasting");
  const pct = bel && bel.detail && bel.detail.pct != null ? bel.detail.pct : null;
  // Waarde-consistentie: de belasting-zin in de briefing komt uit DEZELFDE
  // canonieke detailvelden als het dominante cijfer rechtsboven — nooit een
  // voor-afgeronde bron-zin (+91%) naast het canonieke percentage (+92%).
  const bd = (bel && bel.detail) || {};
  const belZin = (bd.pct != null && bd.km_recent != null && bd.km_basis != null)
    ? `Volume ${bd.pct > 0 ? "+" : ""}${bd.pct}% deze week (${bd.km_recent} km vs gem. ${bd.km_basis} km/wk)` : "";
  const titelVan = s => (s.soort === "belasting" && belZin) ? belZin : s.reden;

  let h = `<div class="pb ${tone}">`;
  h += `<div class="pb-amb" aria-hidden="true"></div>`;
  // Identiteit + de reden dat deze atleet je aandacht vraagt.
  h += `<header class="pb-head">
    <span class="pb-orb">${esc(initialen(it.naam || ""))}</span>
    <div class="pb-id"><h3 class="pb-naam">${esc(it.naam || "")}</h3>
      <p class="pb-reden">${esc(hoofd
        ? (hoofd.soort === "belasting" && bd.pct != null
            ? `Belasting ${hoofd.tier === "actie" ? "hoog" : "let op"} · ${bd.pct > 0 ? "+" : ""}${bd.pct}% t.o.v. referentie`
            : titelVan(hoofd))
        : "geen open signaal")}</p></div>
    ${pct != null ? `<span class="pb-dom"><b>${pct > 0 ? "+" : ""}${esc(pct)}</b><i>%</i></span>` : ""}
  </header>`;

  // Ondersteunende feiten: elk signaal met zijn eigen afhandeling.
  h += `<div class="pd-signalen">` + sigs.map((s, i) => {
    const ctxBtn = (s.context && s.context[0]) ? swBtn(s.context[0]) : "";
    // Briefing = compact: het onderbouwende detail staat achter progressive
    // disclosure (open voor het dominante signaal), de acties blijven altijd zichtbaar.
    const open = s === hoofd;
    return `<div class="pd-s-blok ${dsTone(s.tier)}" data-soort="${s.soort}">
      ${dsAttnCard({ tone: dsTone(s.tier), icon: SOORT_IC[s.soort] || "activity",
                     title: titelVan(s),
                     meta: (s.soort === "belasting" && belZin) ? ""
                           : (s.kort && s.kort !== s.reden ? s.kort : "") })}
      <button type="button" class="ds-more pb-more" onclick="dsFoldToggle(this)">${open ? "Verberg" : "Toon"} onderbouwing</button>
      <div class="ds-fold${open ? " open" : ""}"><div class="pd-s-body">${prioSignaalBody(s)}</div></div>
      <div class="pd-s-work">
        <button class="pd-wbtn gezien" data-act="gezien" data-soort="${s.soort}" type="button">${ic("check")}<span>Gezien</span></button>
        <div class="pd-later"><span>Later</span>
          <button data-act="later" data-soort="${s.soort}" data-dagen="3" type="button">3d</button>
          <button data-act="later" data-soort="${s.soort}" data-dagen="7" type="button">7d</button>
          <button data-act="later" data-soort="${s.soort}" data-dagen="14" type="button">14d</button>
        </div>
      </div>
      ${ctxBtn ? `<div class="pd-s-acts">${ctxBtn}</div>` : ""}
    </div>`;
  }).join("") + `</div>`;

  // Volgende stap: door naar de athlete-context (zelfde gedeelde routes).
  h += `<div class="pd-acts pb-acts">${swBtn({ act: "workspace", label: "Open workspace", icon: "brain" })}${swBtn({ act: "dossier", label: "Dossier", icon: "user-plus" })}</div>`;
  h += `</div>`;
  return h;
}


// Type-specifiek detail per signaal (uit de snapshot; compliance-sessies lazy).
function prioSignaalBody(s) {
  const d = s.detail || {};
  if (s.soort === "belasting") {
    const chips = [];
    if (d.km_recent != null && d.km_basis != null) {
      const p = d.pct;
      chips.push(`<div class="pd-chip"><b>Volume${p != null ? " " + (p > 0 ? "+" : "") + p + "%" : ""}</b>
        <span>${d.km_recent} km deze week · basis ${d.km_basis} km/wk</span></div>`);
    }
    if (d.gevoel_recent != null || d.rpe_recent != null)
      chips.push(`<div class="pd-chip"><b>Gevoel / RPE</b>
        <span>gevoel ${d.gevoel_recent ?? "—"} vs ${d.gevoel_basis ?? "—"} · RPE ${d.rpe_recent ?? "—"} vs ${d.rpe_basis ?? "—"}</span></div>`);
    const meer = (d.signalen || []).slice(1).map(x => `<li>${esc(x)}</li>`).join("");
    const runs = (d.runs || []).map(r => `<li>${esc((r.datum || "").slice(5))} · ${r.km ?? "?"} km${r.naam ? " · " + esc(r.naam) : ""}</li>`).join("");
    return `${chips.length ? `<div class="pd-metrics">${chips.join("")}</div>` : ""}
      ${meer ? `<ul class="pd-sig">${meer}</ul>` : ""}
      ${runs ? `<p class="pd-sub">Recente trainingen</p><ul class="pd-runs">${runs}</ul>` : ""}`;
  }
  if (s.soort === "compliance") {
    return `<p class="pd-line">${d.n_low ?? "?"} van ${d.n_planned ?? "?"} geplande trainingen gemist of half — laatste 7 dagen${d.groep ? " · " + esc(d.groep) : ""}</p>
      <div class="pd-sessies"><div class="skel skel-line w60"></div><div class="skel skel-line w40"></div></div>`;
  }
  if (s.soort === "schema") {
    const eind = d.einddatum ? ` · einddatum ${esc(d.einddatum)}` : "";
    return `<p class="pd-line">${esc(s.reden)}${eind}${d.groep ? " · " + esc(d.groep) : ""}</p>
      ${d.verborgen ? `<p class="pd-sub">${d.verborgen} training(en) nog verborgen voor de atleet${d.zichtbaar_tot ? " · zichtbaar t/m " + esc(d.zichtbaar_tot) : ""}</p>` : ""}`;
  }
  return "";
}

// Lazy: gemiste sessies van een afhaker (1 request voor déze atleet, gecachet).
async function prioVulSessies(wrap) {
  const holder = wrap.querySelector(".pd-sessies");
  if (!holder) return;
  if (wrap._sessies) { holder.innerHTML = prioSessiesHtml(wrap._sessies); return; }
  const r = await api(`/api/home/prio/${encodeURIComponent(wrap.dataset.uk)}/trainingen`).catch(() => null);
  const rows = (r && r.trainingen) || [];
  wrap._sessies = rows;                                     // cache → tweede keer 0 requests
  if (holder.isConnected) holder.innerHTML = prioSessiesHtml(rows);
}
function prioSessiesHtml(rows) {
  if (!rows.length) return `<p class="muted klein">Geen losse sessies gevonden.</p>`;
  const pill = { gemist: "gemist", half: "half", gedaan: "gedaan" };
  return `<ul class="pd-sessies-lijst">${rows.map(t => `<li>
    <span class="pd-s-d">${esc((t.datum || "").slice(5))}</span>
    <span class="pd-s-t">${esc(t.type || "Training")}</span>
    ${t.km_planned != null ? `<span class="pd-s-km">${t.km_actual ?? 0}/${t.km_planned} km</span>` : ""}
    <span class="pd-s-st ${t.status}">${pill[t.status] || t.status}</span></li>`).join("")}</ul>`;
}

// SERIËLE write-keten per (atleet, soort): laatste intent (do/undo) wint altijd, ook
// bij snel do/undo → backendstate == UI. Per-signaal en bulk hebben eigen ketens.
const handledChains = {};
function stuurHandled(body) {
  const k = body.user_key + "|" + (body.soort || "bulk");
  handledChains[k] = (handledChains[k] || Promise.resolve())
    .then(() => jpost("/api/home/handled", body).catch(() => ({ ok: false })));
  return handledChains[k];
}

// Rij herbouwen zonder één signaal (voor per-signaal actie/undo) — spiegelt de
// backend-grouping: tier = hoogste resterende, chips/telling/signature opnieuw.
function herbouwIt(it, wegSoort) {
  const rank = t => (t === "actie" ? 0 : 1);
  const sigs = (it.signalen || []).filter(s => s.soort !== wegSoort)
    .sort((a, b) => rank(a.tier) - rank(b.tier) || a.soort.localeCompare(b.soort));
  const tier = sigs.some(s => s.tier === "actie") ? "actie" : "aandacht";
  return {
    ...it, signalen: sigs, n_signalen: sigs.length, tier,
    reden: sigs[0] ? sigs[0].reden : it.reden,
    chips: sigs.map(s => ({ tier: s.tier, kort: s.kort })),
    signature: sigs.map(s => s.soort + ":" + s.fingerprint).sort().join("|"),
  };
}
// Vervang een rij-element in-place door een nieuwe versie; heropen indien open was.
function prioVervang(oud, nieuwIt, open) {
  const parent = oud.parentNode, next = oud.nextSibling;
  const nw = prioItem(nieuwIt);
  nw._sessies = oud._sessies;                              // lazy compliance-cache behouden
  if (parent) parent.insertBefore(nw, next);
  if (prioSwipeEl === oud) prioSwipeEl = null;
  if (prioOpenUk === oud.dataset.uk) prioOpenUk = null;
  oud.remove();
  if (open) prioToggle(nw, true);
  return nw;
}
// Atleet blijft in de lijst maar wisselt van tier → hero/telling verschuiven (rustig
// blijft gelijk: de -1/+1 op rustig heffen elkaar op).
function prioTierWissel(oud, nieuw) {
  if (oud !== nieuw) { prioTel(oud, -1); prioTel(nieuw, +1); }
}

// Actie uitvoeren. Context = deeplink; workflow (gezien/later) = OPTIMISTIC: UI direct,
// backend-write async (#9/#10/#12). soort gezet + >1 signaal → alléén dat signaal;
// anders (bulk-swipe of laatste signaal) → hele rij. Mislukt de write en niet ge-undo'd
// → rollback naar exact de vorige rijstate.
function prioDoe(wrap, act, dagen, soort) {
  const it = wrap._it;
  // Cohesion: één gedeeld athlete-contract (geen caller-specific openDossier-hack).
  // openAthleteModule → #atleten/<uk> → reload-safe consume (pending-patroon).
  if (act === "dossier") { prioHerstelUk = prioOpenUk; openAthleteModule("atleten", it.user_key); return; }
  if (act === "workspace") { prioHerstelUk = prioOpenUk; openWorkspace(it.user_key); return; }
  if (act === "teampuls") { deepAtleet("teampuls", it.user_key); return; }
  // Cohesion (§6): een schema-signaal is 'schema loopt af' → primaire actie is de
  // Schema-workbench van DEZE atleet openen (verlengen/openen), niet eerst de
  // algemene schema-verloop-lijst. Onthoud de open rij voor terugkeer naar Home.
  if (act === "schema") { prioHerstelUk = prioOpenUk; openAthleteModule("schema", it.user_key); return; }
  if (act !== "gezien" && act !== "later") return;

  if (soort && it.n_signalen > 1) { prioSignaalDoe(wrap, act, dagen, soort); return; }   // per-signaal

  // Bulk (swipe) of laatste signaal → hele rij optimistic weg.
  const multi = it.n_signalen > 1;
  const body = { user_key: it.user_key, status: act };
  if (soort) body.soort = soort;
  if (act === "later") body.snooze_dagen = dagen || 7;
  const txt = act === "gezien" ? (multi ? "Alles gezien" : "Gemarkeerd als gezien")
    : `Later · ${dagen || 7} dagen${multi ? " (alles)" : ""}`;
  const undoBody = { user_key: it.user_key, undo: true }; if (soort) undoBody.soort = soort;
  prioSwipeDicht(wrap);
  prioVerwijder(wrap, txt, () => stuurHandled(undoBody));
  stuurHandled(body).then(r => { if (!r || !r.ok) prioRollback(wrap, "Opslaan mislukt — teruggezet."); });
}

// Per-signaal: alleen dit signaal dempen; rij blijft met de rest. Optimistic:
// chips/telling/tier direct bijwerken; undo/rollback herstelt exact de vorige rij.
function prioSignaalDoe(oudWrap, act, dagen, soort) {
  const it = oudWrap._it;
  const nieuwIt = herbouwIt(it, soort);
  const oldTier = it.tier, newTier = nieuwIt.tier;
  const txt = act === "gezien" ? "Signaal gezien" : `Signaal · later ${dagen || 7} dagen`;
  let cur = prioVervang(oudWrap, nieuwIt, true);           // rij zonder dit signaal, blijft open
  prioTierWissel(oldTier, newTier);
  haptic(10);
  let undone = false;
  const herstel = () => { cur = prioVervang(cur, it, prioOpenUk === it.user_key); prioTierWissel(newTier, oldTier); };
  prioToast(txt, () => { undone = true; herstel(); stuurHandled({ user_key: it.user_key, undo: true, soort }); });
  const body = { user_key: it.user_key, status: act, soort };
  if (act === "later") body.snooze_dagen = dagen || 7;
  stuurHandled(body).then(r => {
    if ((!r || !r.ok) && !undone) { herstel(); prioToastWeg(); melding("Opslaan mislukt — teruggezet.", true); }
  });
}

// Rij optimistisch verwijderen (work-queue: volgende schuift rustig op, geen rebuild).
function prioVerwijder(wrap, txt, onUndo) {
  const it = wrap._it;
  wrap._pos = { parent: wrap.parentNode, next: wrap.nextSibling };
  it._removed = true;
  if (prioOpenUk === wrap.dataset.uk) prioOpenUk = null;
  wrap.style.height = wrap.offsetHeight + "px";            // vaste hoogte → nette collapse
  requestAnimationFrame(() => wrap.classList.add("weg"));
  haptic(12);
  prioTel(it.tier, -1);                                    // hero + note direct bijwerken (#10)
  setTimeout(() => {
    if (it._removed && wrap.parentNode) { wrap.parentNode.removeChild(wrap); prioLeegCheck(); }
  }, reduceMotion() ? 0 : 240);
  prioToast(txt, () => { prioHerstel(wrap); if (onUndo) onUndo(); });
}

// Rij terugzetten op exact zijn oude plek (undo of rollback). Idempotent.
function prioHerstel(wrap) {
  const it = wrap._it;
  if (!it._removed) return;
  it._removed = false;
  wrap.classList.remove("weg"); wrap.style.height = "";
  const pos = wrap._pos;
  if (!wrap.parentNode && pos) {
    if (pos.next && pos.next.parentNode === pos.parent) pos.parent.insertBefore(wrap, pos.next);
    else if (pos.parent) pos.parent.appendChild(wrap);
  }
  prioTel(it.tier, +1);
  prioLeegCheck();
}
function prioRollback(wrap, msg) {
  if (!wrap._it._removed) return;                          // coach heeft al ge-undo'd → niks doen
  prioHerstel(wrap); prioToastWeg(); melding(msg, true);
}

// Toont een rustige lege staat als de werkvoorraad leeg raakt (zonder rebuild).
function prioLeegCheck() {
  const box = $("#home-prio"); if (!box) return;
  const leeg = !box.querySelector(".prio-item");
  let msg = box.querySelector(".prio-leeg");
  if (leeg && !msg) {
    msg = document.createElement("div"); msg.className = "leeg small prio-leeg";
    msg.innerHTML = `${ic("check")}<p>Alles verwerkt — mooie dag om te coachen.</p>`;
    box.appendChild(msg);
  } else if (!leeg && msg) msg.remove();
}

function prioToast(txt, undoFn) {
  let t = $("#prio-toast");
  if (!t) { t = document.createElement("div"); t.id = "prio-toast"; t.className = "prio-toast"; document.body.appendChild(t); }
  t.innerHTML = `<span>${esc(txt)}</span>${undoFn ? `<button class="pt-undo" type="button">Ongedaan</button>` : ""}`;
  requestAnimationFrame(() => t.classList.add("on"));
  clearTimeout(t._h);
  const hide = () => t.classList.remove("on");
  t._h = setTimeout(hide, undoFn ? 5000 : 2600);
  if (undoFn) t.querySelector(".pt-undo").onclick = () => { clearTimeout(t._h); hide(); undoFn(); };
}
function prioToastWeg() { const t = $("#prio-toast"); if (t) { clearTimeout(t._h); t.classList.remove("on"); } }

// ── Swipe = expliciete state machine op TOUCH EVENTS (muis = klik→detail) ─────
// Eindstates zijn ALTIJD één van: "idle" | "left" | "right" — nooit een losse
// translateX ertussenin. Een expliciete FASE (idle/undecided/dragging/vscroll/
// settled) bewaakt dat late events een reeds afgehandelde rij niet meer wijzigen.
// De engine draait op TOUCH events (niet pointer): op iOS Safari stopt
// preventDefault() alléén op een touchmove het native scrollen — op een pointermove
// niet — waardoor de pagina tijdens een horizontale swipe verticaal mee bewoog en
// Safari de gesture cancelde. Vóór H-lock preventen we niets (verticaal blijft
// native); zodra H-lock valt preventDefault elke touchmove → de swipe bezit de
// gesture en de pagina staat stil. Desktop/muis swipet niet (geen touch-events).
//
// INTENT — 3 fasen (UNDECIDED → HORIZONTAL | VERTICAL) op de DOMINANTE as met
// asymmetrische drempels: horizontaal lage drempel (natuurlijke swipe), verticaal
// wint alleen als 't duidelijk verticaal is; ambigu blijft UNDECIDED.
const SW_START = 6;      // px: hieronder = jitter/tap → nog niet beslissen
const SW_HLOCK = 8;      // px horizontale dominantie → swipe-lock (i.p.v. ratio 1.4)
const SW_VLOCK = 16;     // px verticale dominantie → native scroll (hoger, zodat swipe kans krijgt)
const SW_DREMPEL = 0.4, SW_FLICK = 0.5;   // eind-open bij 40% breedte of flick (px/ms)

// Tijdelijke gesture-diagnostiek — alleen met ?swdebug=1 (of localStorage bb_swdebug).
// Logt per gesture dx/dy/intent/lock-afstand/velocity/reden/cancel in een overlay met
// 'Kopieer' → JSON, zodat een echte iPhone-gesture teruggekoppeld kan worden (#6).
const SWDBG = (() => {
  let on = false;
  try {
    if (/[?&]swdebug=1/.test(location.search)) localStorage.setItem("bb_swdebug", "1");
    if (/[?&]swdebug=0/.test(location.search)) localStorage.removeItem("bb_swdebug");
    on = localStorage.getItem("bb_swdebug") === "1";
  } catch { }
  const buf = []; let box, pre;
  function ensure() {
    if (box) return;
    box = document.createElement("div"); box.id = "swdbg";
    box.style.cssText = "position:fixed;left:6px;right:6px;bottom:72px;z-index:9999;background:rgba(4,10,25,.93);color:#8fe6c2;font:11px/1.45 ui-monospace,Menlo,monospace;padding:8px;border:1px solid #2a6;border-radius:9px;max-height:42vh;overflow:auto;white-space:pre-wrap";
    const btn = document.createElement("button"); btn.type = "button"; btn.textContent = "Kopieer";
    btn.style.cssText = "position:sticky;top:0;float:right;background:#2a6;color:#022;border:0;border-radius:6px;padding:3px 10px;font:600 11px sans-serif";
    btn.onclick = () => { try { navigator.clipboard.writeText(JSON.stringify(buf, null, 1)); btn.textContent = "Gekopieerd"; setTimeout(() => (btn.textContent = "Kopieer"), 1200); } catch { } };
    pre = document.createElement("div"); box.appendChild(btn); box.appendChild(pre); document.body.appendChild(box);
  }
  return {
    get on() { return on; },
    push(e) {
      if (!on) return;
      buf.push(e); if (buf.length > 30) buf.shift();
      ensure();
      pre.textContent = buf.slice(-9).map(x => {
        const dY = (x.scrollLock != null && x.scrollEnd != null) ? (x.scrollEnd - x.scrollLock) : null;
        return `${x.intent || "–"} dx${x.dx} dy${x.dy}${dY != null ? ` ΔY${dY > 0 ? "+" : ""}${dY}` : ""} v${x.vx} → ${x.end}${x.cancel ? " ✖" : ""}${x.cancelable === false ? " nc" : ""}  ${(x.seq || []).join(">")}`;
      }).join("\n");
    },
  };
})();

// Discreet aan/uit in de GEÏNSTALLEERDE PWA (geen adresbalk voor ?swdebug=1): ~700ms
// stil drukken op de begroeting/datum in de hero toggelt de swipe-debug + herlaadt.
// Puur diagnostisch en tijdelijk; wordt na de swipe-afstemming weer verwijderd.
(function () {
  let t = null;
  const clr = () => { if (t) { clearTimeout(t); t = null; } };
  document.addEventListener("pointerdown", e => {
    if (!(e.target.closest && e.target.closest(".hero-greet, .hero-date"))) return;
    clr();
    t = setTimeout(() => {
      try {
        const on = localStorage.getItem("bb_swdebug") === "1";
        if (on) localStorage.removeItem("bb_swdebug"); else localStorage.setItem("bb_swdebug", "1");
      } catch { }
      location.reload();
    }, 700);
  });
  document.addEventListener("pointerup", clr);
  document.addEventListener("pointermove", clr);       // beweging = geen long-press
  document.addEventListener("pointercancel", clr);
})();

function bindSwipe(wrap, row) {
  const swipe = wrap.querySelector(".prio-swipe");
  const left = wrap.querySelector(".pa-left"), right = wrap.querySelector(".pa-right");
  let mL = 0, mR = 0, x0 = 0, y0 = 0, base = 0, dx = 0, touchId = null;
  let raf = 0, pending = null, didDrag = false, lastX = 0, lastT = 0, vx = 0, g = null, flushT = 0;
  // Expliciete gesture-fase — late lifecycle-events mogen een SETTLED rij nooit
  // opnieuw wijzigen (#4/#8): idle | undecided | dragging | vscroll | settled.
  let phase = "idle";

  const cancelRaf = () => { if (raf) { cancelAnimationFrame(raf); raf = 0; } pending = null; };
  const setX = px => {                              // per-frame één transform-write (compositor)
    pending = px;
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; if (pending == null) return; row.style.transform = pending ? `translate3d(${pending}px,0,0)` : ""; });
  };
  const revealClass = px => {
    const want = px > 0 ? "l" : px < 0 ? "r" : "";
    if (wrap.dataset.drag === want) return;
    wrap.dataset.drag = want;
    swipe.classList.toggle("swipe-l", px > 0);
    swipe.classList.toggle("swipe-r", px < 0);
  };
  // Debug: één record per gesture, geflusht ná alle terminal-events (zo zien we de
  // échte volgorde van up/lost/cancel op de iPhone). gp() logt een lifecycle-token.
  const gp = tok => { if (g) g.seq.push(tok); };
  const flushG = () => { flushT = 0; if (g) { SWDBG.push(g); g = null; } };
  const flushSoon = () => { if (!flushT) flushT = setTimeout(flushG, 200); };

  // DE enige plek die de eindstate zet — extern aanroepbaar via wrap._snap.
  function snap(state) {
    cancelRaf();
    row.style.transition = "";                      // CSS-transitie verzorgt de nette snap
    row.style.willChange = "";
    swipe.classList.remove("swipe-l", "swipe-r");
    if (state === "left") { row.style.transform = `translate3d(${mL}px,0,0)`; swipe.classList.add("swipe-l"); }
    else if (state === "right") { row.style.transform = `translate3d(${-mR}px,0,0)`; swipe.classList.add("swipe-r"); }
    else { row.style.transform = ""; }
    const open = state === "left" || state === "right";
    wrap.classList.toggle("swipe-open", open);
    wrap.dataset.sw = state; wrap.dataset.drag = "";
    if (open) { if (prioSwipeEl && prioSwipeEl !== wrap) prioSwipeEl._snap("idle"); prioSwipeEl = wrap; }
    else if (prioSwipeEl === wrap) prioSwipeEl = null;
  }
  wrap._snap = snap;

  const meet = () => { mL = left ? left.offsetWidth || 96 : 0; mR = right ? right.offsetWidth || 168 : 0; };

  // Bepaal de eindstate uit afstand/velocity en snap ernaartoe. Idempotent: draait
  // alleen als we nog aan het slepen zijn (eerste terminal-event wint).
  function settle() {
    if (phase !== "dragging") return;
    phase = "settled";
    let state = "idle";
    if (dx > 0) state = (dx >= mL * SW_DREMPEL || vx > SW_FLICK) ? "left" : "idle";
    else if (dx < 0) state = (-dx >= mR * SW_DREMPEL || vx < -SW_FLICK) ? "right" : "idle";
    snap(state);
    if (state !== "idle") haptic(8);
    if (g) { g.end = state; g.dxFinal = Math.round(dx); g.base = Math.round(base); g.mL = mL; g.mR = mR; gp("snap:" + state); }
  }

  // ── Touch-engine (iOS-correct) ───────────────────────────────────────────────
  // Waarom Touch Events i.p.v. Pointer Events: op iOS Safari stopt preventDefault()
  // op een POINTER-move het native scrollen NIET (scroll wordt door de onderliggende
  // touch-stream gedreven) → na H-lock bleef de pagina verticaal pannen en cancelde
  // Safari de gesture. Op een echte TOUCH-move wérkt preventDefault wél. Dus: vóór
  // H-lock niets preventen (verticaal blijft native); zodra H-lock valt preventDefault
  // elke touchmove → de horizontale swipe 'bezit' de gesture, de pagina staat stil.
  // Eén engine (touch drijft de swipe; click doet tap/desktop) → geen dubbele afhandeling.
  const scrollY = () => { const s = $("#scroller"); return s ? s.scrollTop : (window.scrollY || 0); };
  const huidigeTouch = e => { for (const t of e.changedTouches) if (t.identifier === touchId) return t; return null; };

  row.addEventListener("touchstart", e => {
    if (e.touches.length !== 1) { phase = "idle"; touchId = null; return; }   // multitouch → geen swipe
    if (flushT) { clearTimeout(flushT); flushT = 0; }
    if (g) { SWDBG.push(g); g = null; }             // vorige record afronden
    if (prioSwipeEl && prioSwipeEl !== wrap) prioSwipeEl._snap("idle");   // andere rij dicht (#5)
    meet();
    const t = e.changedTouches[0]; touchId = t.identifier;
    x0 = t.clientX; y0 = t.clientY; lastX = x0; lastT = performance.now(); vx = 0;
    base = wrap.dataset.sw === "left" ? mL : wrap.dataset.sw === "right" ? -mR : 0;  // vanaf huidige stand
    dx = base; didDrag = false; phase = "undecided";
    g = SWDBG.on ? { dx: 0, dy: 0, vx: 0, intent: null, reason: "", lockDist: null, cancel: false, end: null, seq: ["down"], scrollStart: scrollY(), scrollLock: null, scrollEnd: null, cancelable: null, dP: null } : null;
  }, { passive: true });

  row.addEventListener("touchmove", e => {
    if (phase !== "undecided" && phase !== "dragging") return;
    const t = huidigeTouch(e) || e.touches[0]; if (!t) return;
    const mx = t.clientX - x0, my = t.clientY - y0;
    if (g) { g.dx = Math.round(mx); g.dy = Math.round(my); }
    if (phase === "undecided") {                    // ── 3-fasen intent (thresholds ongewijzigd) ──
      const adx = Math.abs(mx), ady = Math.abs(my);
      if (adx < SW_START && ady < SW_START) return;                    // te klein → wacht
      if (adx > ady && adx >= SW_HLOCK) {                              // dominant horizontaal → swipe
        phase = "dragging"; didDrag = true; row.style.transition = "none"; row.style.willChange = "transform";
        if (g) { g.intent = "H"; g.reason = `adx${adx}>ady${ady}&≥${SW_HLOCK}`; g.lockDist = Math.round(Math.hypot(mx, my)); g.scrollLock = scrollY(); gp("hlock"); }
      } else if (ady > adx && ady >= SW_VLOCK) {                        // dominant verticaal → native scroll
        phase = "vscroll";
        if (g) { g.intent = "V"; g.reason = `ady${ady}>adx${adx}&≥${SW_VLOCK}`; g.lockDist = Math.round(Math.hypot(mx, my)); g.end = "scroll"; gp("vlock"); } flushSoon();
        return;
      } else return;                                                    // ambigu → BLIJF UNDECIDED (#3)
    }
    // phase === "dragging" → bezit de gesture: STOP native scroll (werkt op touchmove)
    if (e.cancelable) e.preventDefault();
    if (g) { g.cancelable = e.cancelable; g.dP = e.defaultPrevented; }
    const now = performance.now(), dt = now - lastT;
    if (dt > 0) vx = (t.clientX - lastX) / dt;      // snelheid voor flick-detectie
    lastX = t.clientX; lastT = now;
    dx = Math.max(-mR, Math.min(mL, base + mx));
    if (g) g.vx = +vx.toFixed(2);
    revealClass(dx);
    setX(dx);
  }, { passive: false });

  // touchend = normaal einde → settle naar de eindstate.
  row.addEventListener("touchend", e => {
    if (touchId != null && !huidigeTouch(e)) return;   // andere vinger losgelaten
    gp("up");
    if (phase === "dragging") settle();
    else { if (g && g.end == null) g.end = phase === "vscroll" ? "scroll" : "none"; phase = "idle"; }
    touchId = null;
    if (g) g.scrollEnd = scrollY();
    flushSoon();
  });
  // touchcancel = ECHTE systeem-onderbreking → veilig CLOSED.
  row.addEventListener("touchcancel", () => {
    gp("cancel");
    if (phase === "dragging") { phase = "settled"; snap("idle"); if (g) { g.cancel = true; g.end = "cancel"; gp("snap:idle"); } }
    else if (phase !== "settled") phase = "idle";
    touchId = null;
    if (g) g.scrollEnd = scrollY();
    flushSoon();
  });

  row.addEventListener("click", () => {
    if (didDrag) { didDrag = false; return; }       // synthetische click ná een drag negeren
    if (wrap.dataset.sw === "left" || wrap.dataset.sw === "right") { snap("idle"); return; }  // open → dicht
    prioToggle(wrap);
  });
}
function prioSwipeDicht(wrap) { if (wrap && wrap._snap) wrap._snap("idle"); }

// Deeplink naar de EXACTE atleet op een andere pagina. Onthoud de open rij zodat
// Home die na terugkeer heropent; Home-data zelf wordt niet zwaar herladen (#14).
function deepAtleet(view, uk, direct) {
  prioHerstelUk = prioOpenUk;
  homeScroll = $("#scroller") ? $("#scroller").scrollTop : 0;
  toonView(view);
  if (direct) { direct(); return; }                         // dossier: opent atleet zelf
  prioFocusKaart(view, uk);                                 // teampuls/schema: scroll + flash
}
// Poll tot de doelkaart in de (lui geladen) lijst staat, scroll ernaartoe + flash.
function prioFocusKaart(view, uk) {
  const sel = view === "teampuls" ? "#tp-signalen" : "#sv-lijst";
  let n = 0;
  (function zoek() {
    const el = document.querySelector(`${sel} [data-uk="${uk}"]`);
    if (el) {
      el.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "center" });
      el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
    } else if (n++ < 40) setTimeout(zoek, 80);
  })();
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
// ════════════════════════════════════════════════════════════════════════════
// GEDEELDE ATHLETE PICKER — één selectie-primitive (Schema, Intake-koppel, Atleten)
// Genormaliseerd view-model, canonieke groepsvolgorde + alfabetisch binnen groep,
// zoeken ALTIJD over alle groepen (nooit stil beperkt door een chip), keyboard
// (↑↓/Enter/Esc), navigate- vs confirm-modus. Geen intelligence, geen tweede
// waarheid, geen nieuwe identity: 'key' = FinalSurge user_key (of tijdelijk
// 'nieuw:naam' pre-link). Task-context bepaalt alleen de secundaire regel.
// ════════════════════════════════════════════════════════════════════════════
function renderPicker(cfg) {
  const mount = cfg.mount; if (!mount) return null;
  const _css = s => (window.CSS && CSS.escape) ? CSS.escape(String(s)) : String(s);
  const mode = cfg.mode || "navigate";          // 'navigate' | 'confirm'
  const withChips = cfg.chips !== false;
  let selKey = cfg.selectedKey || "";
  let groepFilter = "";                          // actieve chip ("" = alle)
  let focusKey = "";                             // keyboard-focus

  const zoekSvg = `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>`;
  const eigenSearch = !cfg.searchEl;
  mount.innerHTML =
    (eigenSearch ? `<div class="search pk-zoek">${zoekSvg}<input class="pk-in" placeholder="${esc(cfg.placeholder || "Zoek atleet")}" autocomplete="off"></div>` : "") +
    (withChips ? `<div class="chips pk-chips"></div>` : "") +
    `<div class="pk-roster" role="listbox"></div>`;
  const inEl = cfg.searchEl || mount.querySelector(".pk-in");
  const chipsEl = withChips ? mount.querySelector(".pk-chips") : null;
  const rosterEl = mount.querySelector(".pk-roster");
  const items = () => cfg.items || [];

  // Canonieke groepsvolgorde: bekende groepen eerst (in doorgegeven volgorde),
  // onbekende erachter op alfabet; 'Zonder groep' hoort apart (buiten deze lijst).
  function groepenInVolgorde(list) {
    const aanwezig = [...new Set(list.map(a => (a.groep || "").trim()).filter(Boolean))];
    const canon = (cfg.groupOrder || []).filter(g => aanwezig.includes(g));
    aanwezig.filter(g => !canon.includes(g)).sort((a, b) => a.localeCompare(b, "nl", { numeric: true })).forEach(g => canon.push(g));
    return canon;
  }
  function bouwChips() {
    if (!chipsEl) return;
    const groepen = groepenInVolgorde(items());
    chipsEl.innerHTML = `<button class="chip${groepFilter === "" ? " on" : ""}" data-g="">Alle</button>` +
      groepen.map(g => `<button class="chip${groepFilter === g ? " on" : ""}" data-g="${esc(g)}">${esc(g)}</button>`).join("");
  }
  chipsEl?.addEventListener("click", e => {
    const b = e.target.closest(".chip"); if (!b) return;
    groepFilter = b.dataset.g || "";
    chipsEl.querySelectorAll(".chip").forEach(c => c.classList.toggle("on", c === b));
    teken();
  });

  function gefilterd() {
    const f = (inEl && inEl.value || "").trim().toLowerCase();
    // Regel: zoeken gaat ALTIJD over alle groepen. De chip beperkt alleen als er
    // niet gezocht wordt — zo wordt een zoekopdracht nooit stil ingeperkt.
    return items().filter(a =>
      (f ? true : (!groepFilter || (a.groep || "").trim() === groepFilter)) &&
      (!f || (a.naam || "").toLowerCase().includes(f)));
  }
  const opNaam = arr => arr.slice().sort((x, y) => (x.naam || "").localeCompare(y.naam || "", "nl"));
  function rij(a) {
    const sub = cfg.secondary ? (cfg.secondary(a) || "") : "";
    return `<button class="pk-row${a.key === selKey ? " sel" : ""}" data-k="${esc(a.key)}" role="option" aria-selected="${a.key === selKey}">
      <span class="pk-av">${initialen(a.naam)}</span>
      <span class="pk-b"><span class="pk-nm">${esc(a.naam)}</span>${sub ? `<span class="pk-sub">${sub}</span>` : ""}</span>
      ${mode === "navigate" ? `<svg class="pk-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>` : ""}
    </button>`;
  }
  function teken() {
    const list = gefilterd();
    if (!list.length) { rosterEl.innerHTML = `<div class="pk-leeg">${esc(cfg.emptyText || "Geen atleet gevonden.")}</div>`; return; }
    const perGroep = {}, losse = [];
    list.forEach(a => { const g = (a.groep || "").trim(); if (g) { (perGroep[g] = perGroep[g] || []).push(a); } else losse.push(a); });
    let html = "";
    groepenInVolgorde(list).forEach(g => { html += `<p class="pk-ghead">${esc(g)}</p>` + opNaam(perGroep[g]).map(rij).join(""); });
    if (losse.length) html += `<p class="pk-ghead">Zonder groep</p>` + opNaam(losse).map(rij).join("");
    rosterEl.innerHTML = html;
    rosterEl.querySelectorAll(".pk-row").forEach(el => el.addEventListener("click", () => kies(el.dataset.k, true)));
    if (focusKey) rosterEl.querySelector(`.pk-row[data-k="${_css(focusKey)}"]`)?.classList.add("foc");
  }
  function kies(key, activated) {
    const a = items().find(x => x.key === key); if (!a) return;
    selKey = key; focusKey = key;
    if (mode === "navigate") { if (activated && cfg.onActivate) cfg.onActivate(a); }
    else { teken(); if (cfg.onSelect) cfg.onSelect(a); }
  }
  function beweeg(delta) {
    const keys = [...rosterEl.querySelectorAll(".pk-row")].map(el => el.dataset.k);
    if (!keys.length) return;
    let i = keys.indexOf(focusKey); i = i < 0 ? 0 : Math.min(keys.length - 1, Math.max(0, i + delta));
    focusKey = keys[i];
    rosterEl.querySelectorAll(".pk-row").forEach(el => el.classList.toggle("foc", el.dataset.k === focusKey));
    rosterEl.querySelector(`.pk-row[data-k="${_css(focusKey)}"]`)?.scrollIntoView({ block: "nearest" });
  }
  const onKey = e => {
    if (e.key === "ArrowDown") { e.preventDefault(); beweeg(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); beweeg(-1); }
    else if (e.key === "Enter") { if (focusKey) { e.preventDefault(); kies(focusKey, true); } }
    else if (e.key === "Escape") { if (inEl && inEl.value) { inEl.value = ""; teken(); } else if (cfg.onEscape) cfg.onEscape(); }
  };
  inEl?.addEventListener("input", teken);
  inEl?.addEventListener("keydown", onKey);

  bouwChips(); teken();
  if (cfg.autofocus && inEl) setTimeout(() => inEl.focus(), 40);
  return {
    setItems(newItems) { cfg.items = newItems; bouwChips(); teken(); },
    getSelected() { return items().find(x => x.key === selKey) || null; },
    setSelected(k) { selKey = k; focusKey = k; teken(); },
    focusSearch() { inEl && inEl.focus(); },
    herteken: teken,
  };
}

let dossierPicker = null;
let atletenOpenPending = "";              // atleet uit de route die geopend moet worden zodra de roster er is
let dossierGroepVolgorde = [];           // canonieke groepsvolgorde (voor koppel-picker)
// Gedeelde picker in een modal (desktop) / bottom-sheet (mobiel). Confirm-modus:
// selecteren markeert alleen; de write gebeurt pas op de bevestigknop.
function openAthletePickerOverlay(opts) {
  const ov = document.createElement("div");
  ov.className = "pk-overlay";
  ov.innerHTML = `<div class="pk-modal" role="dialog" aria-modal="true">
      <div class="pk-modal-h"><b>${esc(opts.title || "Kies atleet")}</b><button class="pk-x" aria-label="Sluiten">✕</button></div>
      <div class="pk-modal-body"></div>
      <div class="pk-modal-foot"><button class="btn ghost pk-cancel">Annuleren</button><button class="btn primary pk-confirm" disabled>${esc(opts.confirmLabel || "Kies")}</button></div>
    </div>`;
  document.body.appendChild(ov);
  const confirmBtn = ov.querySelector(".pk-confirm");
  const sluit = () => { ov.remove(); document.removeEventListener("keydown", onEsc); };
  const onEsc = e => { if (e.key === "Escape") sluit(); };
  document.addEventListener("keydown", onEsc);
  ov.addEventListener("click", e => { if (e.target === ov) sluit(); });     // backdrop = annuleren (geen write)
  ov.querySelector(".pk-x").onclick = sluit;
  ov.querySelector(".pk-cancel").onclick = sluit;
  const picker = renderPicker({
    mount: ov.querySelector(".pk-modal-body"), items: opts.items, groupOrder: opts.groupOrder || [],
    mode: "confirm", autofocus: true, placeholder: opts.placeholder || "Zoek atleet", emptyText: "Geen atleet gevonden.",
    secondary: a => a.groep ? esc(a.groep) : "", onSelect: a => { confirmBtn.disabled = !a; }, onEscape: sluit,
  });
  confirmBtn.onclick = () => { const a = picker.getSelected(); if (!a) return; sluit(); opts.onConfirm(a); };
}
function _dossierSecundair(a) {          // task-relevante info: intake + notities/docs
  const bits = [];
  if (a.heeft_intake) bits.push("intake");
  if (a.n_notities) bits.push(a.n_notities + " notitie(s)");
  if (a.n_documenten) bits.push(a.n_documenten + " document(en)");
  return bits.join(" · ");
}
function toonDossierLijstView() {        // alleen tonen/verbergen (master-detail)
  $("#d-lijst").hidden = false;
  if (isDesktop()) { if (!dossierSel) toonDetailLeeg(); }   // detail blijft staan naast de lijst
  // Telefoon: is er een atleet open (dossierSel), dan blijft het detail leidend —
  // een late roster-render (deep-link/refresh) mag de geopende atleet nooit clobberen.
  else if (dossierSel) { $(".md-list").hidden = true; $("#d-detail").hidden = false; }
  else { $(".md-list").hidden = false; $("#d-detail").hidden = true; }  // geen atleet → lijst
}
async function laadDossierLijst() {
  const box = $("#d-lijst");
  if (!dossierPicker) skeleton(box, 6);
  let data;
  try { data = await api("/api/atleten"); }
  catch { if (!dossierPicker) box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  dossierCache = data.atleten || [];
  dossierGroepVolgorde = data.groep_volgorde || [];
  fsActief = !!data.fs;
  const items = dossierCache.map(a => ({ ...a, key: a.id }));   // identity: id = user_key of store_key
  if (!items.length && !dossierPicker) {
    box.innerHTML = `<div class="leeg">${ic("users")}<p>${fsActief
      ? "Geen atleten." : "Nog geen atleten.<br>Koppel FinalSurge (FS_TOKEN) voor de volledige lijst."}</p></div>`;
    toonDossierLijstView(); return;
  }
  // Gedeelde Athlete Picker: group-first (canonieke volgorde), 'Zonder groep'
  // onderaan, zoeken over alle groepen. Eén keer bouwen (externe #d-zoek); daarna
  // setItems bij refresh — zo stapelen we geen listeners op de zoekinput.
  if (dossierPicker) { dossierPicker.setItems(items); }
  else {
    dossierPicker = renderPicker({
      mount: box, searchEl: $("#d-zoek"), items, groupOrder: data.groep_volgorde || [],
      selectedKey: dossierSel || "", mode: "navigate", emptyText: "Geen atleet gevonden.",
      secondary: _dossierSecundair, onActivate: a => openDossier(a.key),
    });
  }
  toonDossierLijstView();
  // Deep-link/refresh: eerst de lijst tekenen, DAARNA de atleet openen (detail wint als
  // laatste). Zelfde patroon als de cockpit (dcOpenPending) — geen race, elke breedte.
  if (atletenOpenPending) { const p = atletenOpenPending; atletenOpenPending = ""; openDossier(p); }
}
function tekenDossierLijst() { toonDossierLijstView(); dossierPicker && dossierPicker.herteken(); }
function initialen(naam) {
  const p = (naam || "?").trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase() || "?";
}

// (zoeken wordt door de gedeelde picker aan #d-zoek gebonden)
bindRefresh("a-refresh", () => { geladen.atleten = true; return laadDossierLijst(); });

async function openDossier(ident) {
  // Roster nog niet geladen? → onthoud en open zodra laadDossierLijst klaar is (detail
  // opent dan ná de lijst-render → geen clobber, reload-safe). Mirror van de cockpit.
  if (!dossierPicker) { atletenOpenPending = ident; if (!geladen.atleten) { geladen.atleten = true; laadDossierLijst(); } return; }
  dossierSel = ident;
  dossierPicker.setSelected(ident);          // rij licht op (desktop + mobiel)
  pushRoute("atleten", ident);              // deep-link: refresh houdt deze atleet open (#C)
  const wrap = $("#d-detail");
  if (!isDesktop()) { $(".md-list").hidden = true; $("#scroller").scrollTo({ top: 0 }); }  // telefoon: meteen 'in' de klant
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

  // Losse intake ('nieuw:…') koppelen aan een FinalSurge-account, zodat Schema en
  // het Masterbrein hem gaan gebruiken (die zoeken op user_key). Non-destructief.
  const isNieuw = !!(dos && dos.nieuw);
  const nieuwKey = dos ? dos.key : "";
  const suggestie = d.suggestie || null;                       // eenduidige FS-naam-match (kandidaat, geen auto-link)
  const fsKandidaten = dossierCache.filter(a => a.user_key);   // alleen echte FS-accounts
  // Koppel-actie: (1) name-merged FS-rij → koppel aan dit account; (2) losse orphan met
  // eenduidige naam-match → bied die match als KANDIDAAT (coach bevestigt); (3) anders
  // handmatig kiezen. Nooit blind auto-linken; de write gebeurt pas op de knop.
  const koppelActie = d.user_key
    ? `<button class="btn primary" id="kp-direct">Koppel aan dit account (${esc(d.naam)})</button>`
    : (suggestie
      ? `<button class="btn primary" id="kp-suggest">Koppel aan ${esc(suggestie.naam)}${suggestie.groep ? ` <span class="muted klein">(${esc(suggestie.groep)})</span>` : ""} — voorgestelde match</button>
         <button class="btn ghost" id="kp-open">Andere atleet kiezen&hellip;</button>`
      : `<button class="btn primary" id="kp-open">Kies FinalSurge-atleet&hellip;</button>`);
  const koppelHtml = isNieuw ? `
    <section class="panel open-static">
      <h3 class="panel-h">${ic("file")} Koppel intake aan FinalSurge</h3>
      <p class="hint">Deze intake staat nog los opgeslagen. Koppel hem aan het FinalSurge-account — daarna gebruikt Schema (en het Masterbrein) hem automatisch.</p>
      ${koppelActie}
    </section>` : "";
  const _redenLabel = r => r === "vervangen_bij_koppelen" ? "vervangen bij koppelen"
    : r === "opnieuw_overgenomen" ? "opnieuw overgenomen" : (r || "");
  const historieRijen = (dos && dos.historie && dos.historie.length) ? dos.historie.map(h => `
    <div class="doc"><span class="doc-d">${esc(h.bijgewerkt || h.gearchiveerd || "")}</span>
      <span>${esc(h.doel || "—")}${h.reden ? ` <span class="muted klein">(${esc(_redenLabel(h.reden))})</span>` : ""}</span></div>`).join("") : "";
  const historieHtml = historieRijen ? `
    <section class="panel">
      <button class="acc-toggle" data-target="d-hist">${ic("file")} Eerdere intakes (${dos.historie.length})</button>
      <div id="d-hist" class="collapse">${historieRijen}</div>
    </section>` : "";

  wrap.innerHTML = `
    <button class="btn ghost back" id="d-terug">${ic("back")} Alle atleten</button>
    <div class="d-head"><span class="avatar big">${initialen(d.naam)}</span>
      <div><h2 class="d-naam">${esc(d.naam)}</h2>
        ${d.groep ? `<p class="muted klein" style="margin:3px 0 0">${esc(d.groep)}</p>` : ""}</div></div>
    ${athleteNav("atleten", d.user_key)}

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

    ${koppelHtml}
    ${historieHtml}

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
  $("#d-terug").addEventListener("click", () => { dossierSel = null; pushRoute("atleten"); dossierPicker && dossierPicker.setSelected(""); toonDossierLijstView(); });

  const doeKoppel = async (userKey) => {
    if (!userKey) return melding("Kies eerst een atleet.", true);
    const r = await jpost("/api/intake/koppel", { nieuw_key: nieuwKey, user_key: userKey }).catch(() => null);
    if (!r || !r.ok) return melding(r?.err || "Koppelen mislukt.", true);
    melding(`Intake gekoppeld aan ${r.naam || "atleet"} — bouw nu het schema.`);
    vervalDossierLijst();
    // Cohesion (§10): primaire next-action voor een nieuw gekoppelde coaching-atleet
    // is 'Bouw schema' → open Schema direct op de canonieke user_key (geen re-search).
    // Het Dossier blijft één tik weg via de athlete-nav in de Schema-kop (secundair).
    openAthleteModule("schema", userKey);
  };
  $("#kp-direct")?.addEventListener("click", () => doeKoppel(d.user_key));
  $("#kp-suggest")?.addEventListener("click", () => suggestie && doeKoppel(suggestie.user_key));  // confirm = klik; geen auto-link
  $("#kp-open")?.addEventListener("click", () => openAthletePickerOverlay({
    title: `Koppel "${esc(d.naam)}" aan FinalSurge`,
    items: fsKandidaten.map(a => ({ key: a.user_key, naam: a.naam, groep: a.groep })),
    groupOrder: dossierGroepVolgorde,
    confirmLabel: "Koppel",
    onConfirm: a => doeKoppel(a.key),          // write pas na expliciete bevestiging
  }));

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

bindRefresh("i-refresh", laadInbox);
function laadIntake() { laadIntakeLink(); laadInbox(); laadOrphanIntakes(); }

// Historische, nog-niet-gekoppelde ('nieuw:') intakes zichtbaar maken in de Intake-
// module — pariteit met de Streamlit 'wachtende intakes'-lijst (§9). Bron =
// /api/intake/orphans, dat de intakes RECHTSTREEKS uit de store leest (niet via de
// verenigde roster, die een orphan bij een FS-namesake weg-mergt). Zo blijft een
// historische intake (bv. Dominique) zichtbaar en één tik van koppelen — met een
// eventuele voorgestelde FS-match. Geen nieuwe store, geen duplicatie.
async function laadOrphanIntakes() {
  const box = $("#i-orphans"); if (!box) return;
  const r = await api("/api/intake/orphans").catch(() => null);
  const orphans = (r && r.orphans) || [];
  if (!orphans.length) { box.innerHTML = ""; return; }
  box.innerHTML = `<p class="sec-label">Losse intakes — nog niet gekoppeld</p>
    <p class="hint">Overgenomen toen de atleet nog niet in FinalSurge stond (zichtbaar zolang ze los staan, net als in Streamlit). Koppel aan het FinalSurge-account zodra dat bestaat — daarna gebruikt Schema de intake.</p>
    <section class="lijst">${orphans.map(a => `
      <button class="listcard" data-orphan="${esc(a.key)}">
        <span class="avatar">${initialen(a.naam)}</span>
        <span class="lc-body"><span class="lc-title">${esc(a.naam)}</span>
          <span class="lc-sub">${a.suggestie ? "voorgestelde match: " + esc(a.suggestie.naam) : "losse intake · koppelen"}</span></span>${ic("chevron")}</button>`).join("")}</section>`;
  box.querySelectorAll("[data-orphan]").forEach(b =>
    b.addEventListener("click", () => openAthleteModule("atleten", b.dataset.orphan)));
}

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
// FEEDBACK — workbench: inbox (queue) → focus (planned↔actual + gesprek + editor)
// ════════════════════════════════════════════════════════════════════════════
// Los van Home (eigen state/DOM, geen swipe). Queue komt uit de fase-1 cache
// (/api/feedback/queue, stale-while-revalidate). Detail lazy per focus
// (/api/feedback/{id}), client-gecachet + volgende 1–2 vooraf geladen. Versturen =
// directe POST met idle→sending→sent|error; Overslaan = optimistic + Undo (de POST
// volgt pas ná het undo-venster → geen un-skip-endpoint nodig). Drafts per
// workout_key in localStorage. UI is voorbereid op recent_context (fase 4).
const FB = {
  items: [],            // zichtbare, gesorteerde queue
  pending: null,        // achtergrond-snapshot dat wacht op "N nieuwe — tik om te tonen"
  pendingInitial: false,// koude cache: eerste verse sweep is nog de INITIËLE lading (geen "N nieuwe")
  groups: [],           // [{key,label,count}] uit de backend-samenvatting
  group: "alle",        // actieve groep-filter (blijft binnen de sessie behouden)
  selId: null,          // gefocuste workout
  gepost: 0,            // vandaag verstuurd (lokaal bijgewerkt)
  detailCache: {},      // id -> detailpayload
  sentSet: new Set(),   // deze sessie verstuurd (SWR mag ze niet terugbrengen)
  skipSet: new Set(),   // optimistisch overgeslagen (idem, tot commit/rollback)
  summaryLog: [],       // sessie-samenvatting: UITSLUITEND geslaagde posts (workflow-state, in-memory)
  sending: false,
  recovering: false,    // FC-1: gerichte stale/not-found-recovery loopt (voorkomt refresh-loop)
  loaded: false,
  log: [],              // geïsoleerde Feedback-debuglog (ringbuffer, max 300)
  logOn: false,
};
const FB_CAT = { reactie: "Reactie", gevoel: "Gevoel", uitgevoerd: "Uitgevoerd" };

// ── Geïsoleerde Feedback-debuglog ────────────────────────────────────────────
// Volledig los van de Home-swipe-debug (SWDBG). Standaard UIT; aan/uit + wissen +
// kopiëren via Meer. Logt ALLEEN keys/tellingen/timings — nooit tekst/notities/
// comments/AI-output. Ringbuffer van 300 events zodat kopiëren op iPhone licht blijft.
try { FB.logOn = localStorage.getItem("fb_log_on") === "1"; } catch {}
function fbLog(ev, extra) {
  if (!FB.logOn) return;
  const vv = window.visualViewport;
  const it = FB.selId ? FB.items.find(i => i.id === FB.selId) : null;
  const dock = document.querySelector(".fb-dock");
  const e = Object.assign({
    t: new Date().toISOString(),
    ev,
    workout_key: FB.selId || null,
    athlete_key: it ? (it.athlete_key || null) : null,
    fbFocusId: FB.selId || null,
    queue_length: FB.items.length,
    pending_count: FB.pending ? FB.pending.length : 0,
    sent_set_size: FB.sentSet.size,
    skip_set_size: FB.skipSet.size,
    current_group: FB.group,
    current_category: it ? (it.categorie || null) : null,
    viewport_height: vv ? Math.round(vv.height) : null,
    dock_height: dock ? Math.round(dock.getBoundingClientRect().height) : null,
    keyboard_open: document.body.classList.contains("kb-open"),
  }, extra || {});
  FB.log.push(e);
  if (FB.log.length > 300) FB.log.splice(0, FB.log.length - 300);
  fbLogStatus();
}
function fbLogStatus() {
  const s = $("#fb-log-status"); if (!s) return;
  s.textContent = `Logging staat ${FB.logOn ? "AAN" : "uit"} · ${FB.log.length} events`;
  const t = $("#fb-log-toggle"); if (t) t.textContent = FB.logOn ? "Logging uit" : "Logging aan";
  const dbg = $("#fb-dbg"); if (dbg) dbg.classList.toggle("on", FB.logOn);
}
function fbLogBind() {
  // Feedback v1 (H): de Debug-knop is GEEN productie-UI. Toon hem alleen in expliciete
  // debug-modus (?swdebug=1 of localStorage bb_swdebug); anders volledig verbergen.
  let _dbgMode = false;
  try { _dbgMode = localStorage.getItem("bb_swdebug") === "1"; } catch {}
  const dbg = $("#fb-dbg");
  if (dbg && !_dbgMode) { dbg.hidden = true; const p = $("#fb-dbg-panel"); if (p) p.hidden = true; return; }
  if (dbg) { dbg.hidden = false; dbg.onclick = () => { const p = $("#fb-dbg-panel"); if (p) p.hidden = !p.hidden; }; }
  const t = $("#fb-log-toggle"); if (t) t.onclick = () => {
    FB.logOn = !FB.logOn; try { localStorage.setItem("fb_log_on", FB.logOn ? "1" : "0"); } catch {}
    fbLogStatus();
  };
  const c = $("#fb-log-copy"); if (c) c.onclick = () => {
    const txt = JSON.stringify(FB.log, null, 2);
    const out = $("#fb-log-out"); if (out) { out.hidden = false; out.value = txt; out.focus(); out.select(); }
    navigator.clipboard?.writeText(txt).then(() => melding(`Feedback-log gekopieerd (${FB.log.length}).`),
      () => melding("Selecteer de tekst hieronder en kopieer handmatig."));
  };
  const w = $("#fb-log-clear"); if (w) w.onclick = () => {
    FB.log = []; const out = $("#fb-log-out"); if (out) { out.value = ""; out.hidden = true; } fbLogStatus();
  };
  fbLogStatus();
}

// ── Sessie-samenvatting: één coaching-handover over UITSLUITEND geposte feedback ──
// Sessielog = client-side workflow-state (reset bij reload = Streamlit-sessieparity).
// Vult zich alleen via een server-bevestigde geslaagde post (fbSend), nooit uit drafts
// of skips. De AI-samenvatting draait server-side op de bewezen core.
function fbSummaryAppend(item, id, tekst) {
  const it = FB.items.find(i => i.id === id) || {};     // val terug op de zichtbare kaart
  const rec = {
    athlete_name: (item && item.athlete_name) || it.naam || "",
    workout_name: (item && item.workout_name) || it.workout || "Training",
    workout_key: (item && item.workout_key) || id,
    feedback_text: (item && item.feedback_text) || (tekst || "").trim(),
    // Feedback v1 (F): datum/groep meesturen voor per-datum/per-groep-samenvatting.
    datum: (item && item.datum) || it.datum || "",
    groep_label: (item && item.groep_label) || it.groep_label || "Overig",
  };
  if (!rec.feedback_text) return;
  if (FB.summaryLog.some(r => r.workout_key === rec.workout_key)) return;  // dubbel/retry telt niet
  FB.summaryLog.push(rec);
  fbSummaryUpdate();
}
function fbSummaryUpdate() {
  const box = $("#fb-summary"); if (!box) return;
  const n = FB.summaryLog.length;
  box.hidden = n < 1;                                   // pas tonen na ≥1 geslaagde post
  const lbl = $("#fb-sum-gen-lbl"); if (lbl) lbl.textContent = `Sessie-samenvatting (${n})`;
}
function fbSummaryText() { return $("#fb-sum-out")?.value || ""; }
async function fbSummaryGen() {
  if (!FB.summaryLog.length) return;
  // Coach-identiteit komt uit de authenticated login-context (/api/me → ingelogdeCoach).
  // Ontbreekt die, dan GEEN samenvatting onder een verzonnen naam — duidelijke fout.
  if (!ingelogdeCoach) return melding("Coach onbekend — log opnieuw in om een samenvatting te maken.", true);
  const btn = $("#fb-sum-gen"), lbl = $("#fb-sum-gen-lbl");
  if (btn) btn.disabled = true; if (lbl) lbl.textContent = "Samenvatten…";
  const r = await jpost("/api/feedback/summary",
    { coach: ingelogdeCoach, items: FB.summaryLog }).catch(() => null);
  if (btn) btn.disabled = false; fbSummaryUpdate();     // herstelt het label met de teller
  if (!r || !r.ok) return melding(r && r.err || "Samenvatten mislukt.", true);
  const panel = $("#fb-sum-panel"), out = $("#fb-sum-out");
  if (out) out.value = r.tekst || "";
  if (panel) panel.hidden = false;
}
function fbSummaryMailto(txt) {
  const emails = "jip_vanlent@hotmail.com,Remco-groen@hotmail.com";  // bestaande Streamlit-ontvangers
  const d = new Date();
  const dd = String(d.getDate()).padStart(2, "0"), mm = String(d.getMonth() + 1).padStart(2, "0");
  const subj = encodeURIComponent(`Coaching update ${dd}-${mm}-${d.getFullYear()} — ${ingelogdeCoach}`);
  return `mailto:${emails}?subject=${subj}&body=${encodeURIComponent(txt)}`;
}
function fbSummaryBind() {
  const g = $("#fb-sum-gen"); if (g) g.onclick = fbSummaryGen;
  const rg = $("#fb-sum-regen"); if (rg) rg.onclick = fbSummaryGen;
  const c = $("#fb-sum-copy"); if (c) c.onclick = () => { const t = fbSummaryText(); if (t) navigator.clipboard?.writeText(t).then(() => melding("Gekopieerd."), () => melding("Kopiëren mislukt — selecteer handmatig.", true)); };
  const w = $("#fb-sum-wa"); if (w) w.onclick = () => { const t = fbSummaryText(); if (t) window.open(`https://wa.me/?text=${encodeURIComponent(t)}`, "_blank"); };
  const m = $("#fb-sum-mail"); if (m) m.onclick = () => { const t = fbSummaryText(); if (t) window.open(fbSummaryMailto(t), "_blank"); };
  fbSummaryUpdate();
}

// ── Drafts (localStorage per workout_key) ────────────────────────────────────
const FB_DRAFT_KEY = "fb_drafts_v1";
function fbDrafts() { try { return JSON.parse(localStorage.getItem(FB_DRAFT_KEY) || "{}"); } catch { return {}; } }
function fbDraftsSet(o) { try { localStorage.setItem(FB_DRAFT_KEY, JSON.stringify(o)); } catch {} }
function fbDraftGet(id) { const d = fbDrafts()[id]; const t = (d && d.t) || ""; if (t) fbLog("draft_restore", { target: id, len: t.length }); return t; }
function fbDraftSave(id, t) { const o = fbDrafts(); if (t && t.trim()) o[id] = { t, ts: Date.now() }; else delete o[id]; fbDraftsSet(o); fbLog("draft_save", { target: id, len: (t || "").length }); }
function fbDraftClear(id) { const o = fbDrafts(); if (o[id]) { delete o[id]; fbDraftsSet(o); fbLog("draft_clear", { target: id }); } }
function fbDraftCleanup() {                          // >14 dagen oud → opruimen
  const o = fbDrafts(), cut = Date.now() - 14 * 864e5; let ch = false;
  for (const k in o) if (!o[k] || (o[k].ts || 0) < cut) { delete o[k]; ch = true; }
  if (ch) fbDraftsSet(o);
}

// ── Queue laden + stale-while-revalidate ─────────────────────────────────────
function fbFilterWeg(items) {                        // sessie: verstuurd/overgeslagen nooit tonen
  return (items || []).filter(i => !FB.sentSet.has(i.id) && !FB.skipSet.has(i.id));
}
function fbApplyQueue(items) {
  FB.items = fbFilterWeg(items);
  renderQueue(); fbUpdateInfo();
  if (isDesktop() && !FB.selId) renderFocusEmpty();
}
function fbRenderLoading() {                          // rustige "aan het bijwerken"-state (NIET empty)
  const g = $("#fb-groups"); if (g) g.hidden = true;
  $("#fb-nieuw").hidden = true;
  $("#fb-info").innerHTML = `<span class="versen">Feedback bijwerken…</span>`;
  skeleton($("#fb-queue"), 4);
}
// Diagnostische queue-fetch (fase 2.2 punt 1): meet requestduur + Server-Timing en
// geeft het backend-diag-blok terug voor de koude-start-analyse.
async function fbQueueGet(refresh) {
  const t0 = performance.now();
  let status = 0, st = null, data = null;
  try {
    const res = await fetch("/api/feedback/queue" + (refresh ? "?refresh=1" : ""), { headers: authHeaders() });
    status = res.status; st = res.headers.get("Server-Timing");
    if (status === 401) { toonLogin(); throw new Error("auth"); }
    data = await res.json();
  } catch { data = null; }
  return { data, ms: Math.round(performance.now() - t0), server_timing: st, status };
}
async function fbEnter() {                            // eerste keer openen van de pagina
  fbDraftCleanup(); fbLog("queue_enter");
  if (!FB.loaded) fbRenderLoading();
  const q = await fbQueueGet(false);
  const r = q.data;
  fbLog("queue_cache_result", { non_refresh_ms: q.ms, server_timing: q.server_timing, status: q.status,
    pending: !!(r && r.pending), items: (r && r.items ? r.items.length : 0), diag: (r && r.diag) || null });
  if (!r) { $("#fb-info").textContent = ""; if (!FB.items.length) $("#fb-queue").innerHTML = '<p class="muted center">Geen verbinding.</p>'; }
  else if (!r.fs) { $("#fb-info").textContent = "FinalSurge nog niet gekoppeld."; $("#fb-queue").innerHTML = ""; FB.loaded = true; }
  else if (r.pending && !(r.items && r.items.length)) {
    // Koude/onbevestigde cache: NIET als definitief "niets te beoordelen" tonen.
    FB.pendingInitial = true; fbRenderLoading(); fbLog("queue_empty_pending", { diag: r.diag || null });
  } else {
    FB.gepost = r.gepost || 0; FB.groups = r.groepen || [];
    fbApplyQueue(r.items || []); FB.loaded = true;
    fbLog("queue_cache_loaded", { cached: !!r.cached, queue_length: FB.items.length });
  }
  fbRefresh();                                        // achtergrond: verse sweep
}
async function fbRefresh() {                          // achtergrond-SWR: NOOIT stil hersorteren/muteren
  fbLog("queue_refresh_start");
  const q = await fbQueueGet(true);
  const r = q.data, dur = q.ms;
  if (!r || !r.fs || !Array.isArray(r.items)) {
    fbLog("queue_refresh_error", { queue_refresh_duration_ms: dur, server_timing: q.server_timing, status: q.status, diag: (r && r.diag) || null });
    if (FB.pendingInitial && !FB.items.length) { $("#fb-info").textContent = "Kon Feedback niet laden — trek omlaag of ververs."; }
    return;
  }
  FB.gepost = r.gepost != null ? r.gepost : FB.gepost;
  FB.groups = r.groepen || FB.groups;
  const fresh = fbFilterWeg(r.items);
  fbLog("queue_refresh_success", { queue_refresh_duration_ms: dur, server_timing: q.server_timing, queue_length: fresh.length, diag: r.diag || null });
  if (FB.pendingInitial) {                            // eerste bevestigde sweep = de initiële lading
    FB.pendingInitial = false; FB.loaded = true;
    fbApplyQueue(fresh); fbLog("queue_apply", { reason: "initial", queue_length: fresh.length });
    if (!fresh.length) fbLog("queue_empty_confirmed");
    return;
  }
  const same = FB.items.map(i => i.id).join("|") === fresh.map(i => i.id).join("|");
  if (same) {
    // Zelfde set/volgorde → geen mutatie voor de coach, maar wél verse data
    // (groep/preview) overnemen. Herteken de queue: identieke rijen, geen sprong.
    FB.items = fresh; FB.pending = null; fbNieuwBalk(0); renderQueue(); fbUpdateInfo(); return;
  }
  FB.pending = fresh;                                 // verschil → wacht op coach
  const nieuw = fresh.filter(i => !FB.items.some(c => c.id === i.id)).length;
  fbNieuwBalk(nieuw); fbUpdateInfo(); fbLog("queue_diff_found", { pending_count: nieuw });
}
function fbNieuwBalk(n) {
  const b = $("#fb-nieuw"); if (!b) return;
  if (!FB.pending) { b.hidden = true; return; }
  b.hidden = false;
  b.innerHTML = `${ic("refresh")} ${n > 0 ? `${n} nieuwe — tik om te tonen` : "Lijst bijwerken"}`;
}
function fbUpdateInfo() {
  const info = $("#fb-info"); if (!info) return;
  const n = FB.items.length;
  info.textContent = n
    ? `${n} in de wachtrij · ${FB.gepost || 0} vandaag verstuurd`
    : `${FB.gepost || 0} vandaag verstuurd — inbox leeg`;
}

// ── Groep-selector (compacte, horizontaal scrollbare pills; default Alle) ─────
function fbGroupOrder(items) {                        // aanwezige groepen in backend-volgorde
  const present = [...new Set(items.map(i => i.groep || "overig"))];
  const ordered = (FB.groups || []).map(g => g.key).filter(k => present.includes(k));
  present.forEach(k => { if (!ordered.includes(k)) ordered.push(k); });
  return ordered;
}
function renderGroupsBar() {
  const bar = $("#fb-groups"); if (!bar) return;
  const order = fbGroupOrder(FB.items);
  // tellingen uit de ZICHTBARE items (na sent/skip-filter) zodat pill-getallen kloppen
  const tel = {}; FB.items.forEach(i => { const g = i.groep || "overig"; tel[g] = (tel[g] || 0) + 1; });
  const label = k => (FB.groups.find(g => g.key === k) || {}).label || (FB.items.find(i => i.groep === k) || {}).groep_label || "Overig";
  if (order.length <= 1) { bar.hidden = true; return; }   // één groep → geen selector nodig
  let html = `<button class="fbg-pill${FB.group === "alle" ? " on" : ""}" type="button" data-g="alle">Alle <b>${FB.items.length}</b></button>`;
  order.forEach(k => { html += `<button class="fbg-pill${FB.group === k ? " on" : ""}" type="button" data-g="${esc(k)}">${esc(label(k))} <b>${tel[k]}</b></button>`; });
  bar.innerHTML = html; bar.hidden = false;
  $$(".fbg-pill", bar).forEach(p => p.onclick = () => {
    FB.group = p.dataset.g; fbLog("group_select", { current_group: FB.group });
    renderGroupsBar(); renderQueue();
  });
}

// Feedback v1 (E): leesbaar datumlabel (Vandaag/Gisteren/wd d mnd), lokaal (geen UTC-verschuiving).
function fbLocalISO(dd) {
  return `${dd.getFullYear()}-${String(dd.getMonth() + 1).padStart(2, "0")}-${String(dd.getDate()).padStart(2, "0")}`;
}
function fbDateLabel(d) {
  if (!d) return "Zonder datum";
  const dt = new Date(d + "T00:00:00");
  if (isNaN(dt)) return "Zonder datum";
  const wd = ["zo", "ma", "di", "wo", "do", "vr", "za"];
  const md = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  const iso = fbLocalISO(dt);
  const today = new Date();
  if (iso === fbLocalISO(today)) return "Vandaag";
  const y = new Date(today.getTime() - 864e5);
  if (iso === fbLocalISO(y)) return "Gisteren";
  return `${wd[dt.getDay()]} ${dt.getDate()} ${md[dt.getMonth()]}`;
}

// ── Queue renderen: DATUM-first (Feedback v1 E). De backend levert de ENIGE sort-waarheid
//    (datum → groep → categorie → athlete); we renderen die volgorde met datumkoppen, oudste
//    eerst, zodat de coach chronologisch werkt. Groep is een filter-pill; categorie zit op de rij. ─
function renderQueue() {
  const box = $("#fb-queue"); if (!box) return;
  renderGroupsBar();
  // valt de actieve groep weg uit de queue? dan terug naar Alle (nooit vast op leeg)
  if (FB.group !== "alle" && !FB.items.some(i => i.groep === FB.group)) FB.group = "alle";
  const shown = FB.group === "alle" ? FB.items : FB.items.filter(i => i.groep === FB.group);
  if (!shown.length) {
    box.innerHTML = `<div class="leeg">${ic("check")}<p>Niks te beoordelen — netjes bijgewerkt.</p></div>`;
    return;
  }
  // Groepeer per datum in de door de server geleverde volgorde (die is al datum-first).
  let html = "";
  const seen = [], byDate = {};
  shown.forEach(i => { const d = i.datum || ""; if (!(d in byDate)) { byDate[d] = []; seen.push(d); } byDate[d].push(i); });
  seen.forEach(d => {
    const rows = byDate[d];
    html += `<p class="fbq-groep">${esc(fbDateLabel(d))}<span>${rows.length}</span></p>`;
    html += rows.map(fbRowHtml).join("");
  });
  box.innerHTML = html;
  $$(".fbq-row", box).forEach(r => r.addEventListener("click", () => fbOpen(r.dataset.id, "row_tap")));
}
function fbRowHtml(it) {
  const sel = it.id === FB.selId ? " on" : "";
  const badge = `<span class="fb-badge ${it.categorie}">${FB_CAT[it.categorie] || ""}</span>`;
  const prev = it.preview ? `<span class="fbq-prev">${esc(it.preview)}</span>` : "";
  return `<button class="fbq-row${sel}" data-id="${esc(it.id)}">
    <span class="avatar">${initialen(it.naam)}</span>
    <span class="fbq-body">
      <span class="fbq-top"><span class="fbq-naam">${esc(it.voornaam || it.naam)}</span>${badge}</span>
      <span class="fbq-meta">${esc(it.datum)} · ${esc(it.workout)}</span>
      ${prev}
    </span>${ic("chevron")}</button>`;
}

// ── Focus (detail) ───────────────────────────────────────────────────────────
async function fbFetchDetail(id, preload) {
  if (FB.detailCache[id]) return FB.detailCache[id];
  fbLog(preload ? "preload_start" : "detail_fetch_start", { target: id });
  const t0 = performance.now();
  const d = await api("/api/feedback/" + encodeURIComponent(id)).catch(() => null);
  const dur = Math.round(performance.now() - t0);
  if (d && d.ok) {
    FB.detailCache[id] = d;
    // Structurele productdiagnose: alleen het geclassificeerde type (run/strength/…),
    // geen ruwe FinalSurge-veldscan meer (die tijdelijke onderzoeksdebug is verwijderd).
    fbLog(preload ? "preload_success" : "detail_fetch_success",
      { target: id, detail_fetch_duration_ms: dur, workout_type: d.workout_type || "unknown" });
  } else {
    fbLog(preload ? "preload_error" : "detail_fetch_error", { target: id, detail_fetch_duration_ms: dur });
  }
  return d || { ok: false, err: "Kon detail niet laden." };
}
function fbPreloadNext(id) {                          // volgende 1–2 vast ophalen (geen spinner later)
  const idx = FB.items.findIndex(i => i.id === id); if (idx < 0) return;
  FB.items.slice(idx + 1, idx + 3).forEach(it => { if (!FB.detailCache[it.id]) fbFetchDetail(it.id, true); });
}
async function fbOpen(id, reason) {
  FB.selId = id; renderQueue();
  const col = $("#fb-focus-col"); col.classList.add("on"); col.setAttribute("aria-hidden", "false");
  fbLockQueue(true);                                  // click-through hard blokkeren zolang focus open is
  fbLog("focus_open", { reason: reason || "open" });
  if (FB.detailCache[id]) renderFocus(FB.detailCache[id]);
  else { renderFocusSkeleton(id); const d = await fbFetchDetail(id); if (FB.selId === id) renderFocus(d); }
  fbPreloadNext(id);
}
function fbClose() {
  const col = $("#fb-focus-col");
  if (col) { col.classList.remove("on"); col.setAttribute("aria-hidden", "true"); }
  fbLockQueue(false);                                 // queue weer interactief
  fbKbClose();                                        // composer mode uit + VV-geometrie resetten
  fbLog("focus_close");
  FB.selId = null; renderQueue();
  if (isDesktop()) renderFocusEmpty();
}
function focusNextAfterAction(next) {
  fbLog("auto_next", { next: next ? next.id : null });
  if (next) fbOpen(next.id, "auto_next");
  else if (isDesktop()) { FB.selId = null; renderQueue(); renderFocusEmpty(); }
  else fbClose();
}
function renderFocusEmpty() {
  $("#fb-focus").innerHTML = `<div class="fb-focus-empty">${ic("message")}<p>Kies links een training om te beoordelen.</p></div>`;
}
function fbHeadHtml(naam, voornaam, datum, workout, cat) {
  return `<div class="fbf-head">
    <button class="fbf-back" id="fb-back" type="button" aria-label="Terug">${ic("back")}</button>
    <span class="avatar">${initialen(naam)}</span>
    <span class="fbf-htext"><h2>${esc(voornaam || naam || "")}</h2>
      <p>${esc(datum || "")} · ${esc(workout || "Training")}</p></span>
    ${cat ? `<span class="fb-badge ${cat}">${FB_CAT[cat] || ""}</span>` : ""}
  </div>`;
}
function fbDockHtml(id) {
  return `<div class="fb-dock">
    <textarea id="fb-ta" rows="3" placeholder="Schrijf een reactie, of genereer met AI…">${esc(fbDraftGet(id))}</textarea>
    <div class="fb-dock-row">
      <button class="btn" id="fb-gen" type="button">${ic("brain")} Genereer</button>
      <button class="btn primary" id="fb-send" type="button">${ic("message")} Versturen</button>
    </div>
    <div class="fb-dock-sec">
      <button class="btn ghost small" id="fb-copy" type="button">${ic("copy")} Kopieer</button>
      <button class="btn ghost small" id="fb-skip" type="button">Overslaan</button>
    </div>
  </div>`;
}
function fbBindDock(id) {
  const back = $("#fb-back"); if (back) back.onclick = fbClose;
  const ta = $("#fb-ta");
  if (ta) {
    ta.addEventListener("input", () => { fbDraftSave(id, ta.value); fbGrow(ta); });
    // kb-open = simpele UI-state (composer mode). GEEN keyboardhoogte-berekening:
    // in composer mode wordt de focus-view een normale scroll-flow en brengt Safari
    // zelf het gefocuste textarea boven het toetsenbord (zie styles.css).
    ta.addEventListener("focus", () => { fbKbOpen(); fbLog("keyboard_open", { via: "focus" }); });
    ta.addEventListener("blur", () => { fbKbClose(); fbLog("keyboard_close", { via: "blur" }); });
    fbGrow(ta);
  }
  // Primaire acties (Genereer/Versturen): bruikbaar met OPEN keyboard. Op iOS
  // blurt een gewone tap eerst de textarea (keyboard sluit → composer reflowt →
  // de click mist / komt te laat). mousedown vuurt vóór de blur; preventDefault
  // houdt de focus/het toetsenbord vast, waarna de click direct afvuurt. Zelfde
  // handlers (fbGen/fbSend) — geen dubbele logica, geen keyboardgeometrie.
  fbBindPrimary($("#fb-gen"), () => fbGen(id));
  fbBindPrimary($("#fb-send"), () => fbSend(id));
  const c = $("#fb-copy"); if (c) c.onclick = () => { navigator.clipboard?.writeText($("#fb-ta")?.value || "").then(() => melding("Gekopieerd.")); };
  const sk = $("#fb-skip"); if (sk) sk.onclick = () => fbSkip(id);
}
// Bind een primaire composer-actie zó dat een tap de editor NIET blurt (keyboard
// blijft open, geen reflow) en de click meteen afvuurt.
function fbBindPrimary(btn, handler) {
  if (!btn) return;
  btn.addEventListener("mousedown", e => e.preventDefault());   // houd focus/keyboard vast
  btn.onclick = handler;
}
// Begrensde textarea-groei: auto-size op content; de CSS `max-height` (stabiele vh,
// niet visualViewport) klemt de hoogte af → daarna interne scroll. Bewust GEEN
// live visualViewport.height meer, zodat de textarea niet mee-jittert tijdens de
// keyboardanimatie.
function fbGrow(ta) {
  if (!ta) return;
  // Actieve thread-scroller: desktop = .fbf-scroll; mobiel keyboard-open óók
  // .fbf-scroll (die is dan de eigen thread-scroller, zie CSS). Houd de onderkant
  // vast als de coach daar al keek — maar yank hem NIET naar beneden als hij omhoog
  // scrolde om context te lezen.
  const useScroll = isDesktop() || document.body.classList.contains("kb-open");
  const sc = useScroll ? $(".fbf-scroll") : null;
  const atBottom = sc ? (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 40) : false;
  ta.style.height = "auto";
  ta.style.height = (ta.scrollHeight + 2) + "px";     // CSS max-height klemt af (zie styles.css)
  if (sc && atBottom) sc.scrollTop = sc.scrollHeight;
}
// Desktop: toon bij openen de onderkant van de thread (laatste bericht + composer);
// context/plan blijft omhoog scrollbaar. Mobiel keyboard-dicht niet forceren.
function fbScrollThreadBottom() {
  if (!isDesktop()) return;
  const sc = $(".fbf-scroll"); if (sc) sc.scrollTop = sc.scrollHeight;
}

// ── Mobiele keyboard-open layout via de ECHTE zichtbare viewport ─────────────
// Root-fix iPhone-chat: bij open keyboard weet 100dvh de toetsenbordhoogte NIET, dus
// de composer viel in de onzichtbare onderhelft en de thread had geen eigen scroll.
// Nu zetten we de focus-kolom op visualViewport.height (de zichtbare hoogte boven het
// toetsenbord). Binnen die hoogte is het een normale flex-kolom (CSS): header vast,
// thread flex:1 met EIGEN scroll, composer in-flow eronder. Geen vaste vh-clearance.
// Alleen mobiel; desktop gebruikt geen keyboardgeometrie.
let _fbVV = null;
function fbApplyVV() {
  const vv = window.visualViewport, col = $("#fb-focus-col");
  if (!vv || !col) return;
  col.style.height = Math.round(vv.height) + "px";
  col.style.top = Math.round(vv.offsetTop) + "px";
}
function fbKbOpen() {
  document.body.classList.add("kb-open");
  if (isDesktop() || !window.visualViewport) return;   // desktop: geen VV-geometrie
  if (!_fbVV) {
    _fbVV = () => requestAnimationFrame(fbApplyVV);
    window.visualViewport.addEventListener("resize", _fbVV);
    window.visualViewport.addEventListener("scroll", _fbVV);
  }
  fbApplyVV();
  requestAnimationFrame(() => { const sc = $(".fbf-scroll"); if (sc) sc.scrollTop = sc.scrollHeight; });
}
function fbKbClose() {
  // Vóór de layout-reset vastleggen of de coach praktisch onderaan zat (kb-open
  // scroller-state). Alleen dán her-ankeren we straks; scrolde hij omhoog voor
  // context, dan forceren we niets.
  const sc = $(".fbf-scroll");
  const wasBottom = sc ? (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 40) : false;
  document.body.classList.remove("kb-open");
  const col = $("#fb-focus-col");
  if (col) { col.style.height = ""; col.style.top = ""; }   // terug naar CSS (100dvh / desktop)
  if (_fbVV && window.visualViewport) {
    window.visualViewport.removeEventListener("resize", _fbVV);
    window.visualViewport.removeEventListener("scroll", _fbVV);
    _fbVV = null;
  }
  if (wasBottom && !isDesktop()) fbReanchorBottomAfterClose();
}
// Bij keyboard-close wisselt de CSS synchroon terug naar de keyboard-dichte layout
// (thread-clearance 18px→170px, dock weer absolute), maar iOS animeert het toetsenbord
// ASYNC weg en de viewport groeit pas daarna terug. Zonder her-anker blijft scrollTop
// op de oude (kb-open) maxwaarde staan → de laatste ballon valt half achter de composer.
// Fix: wacht op het uitsettelen van visualViewport (debounce op de laatste resize, geen
// grote vaste timeout) en lijn dan de onderkant opnieuw uit. Alleen als de coach al
// onderaan zat (zie fbKbClose).
function fbReanchorBottomAfterClose() {
  const anchor = () => { const sc = $(".fbf-scroll"); if (sc) sc.scrollTop = sc.scrollHeight; };
  const vv = window.visualViewport;
  if (!vv) { requestAnimationFrame(() => requestAnimationFrame(anchor)); return; }
  let t = null, done = false;
  function settle() { clearTimeout(t); t = setTimeout(finish, 90); }   // 90ms ná laatste resize = uitgesetteld
  function finish() {
    if (done) return; done = true; clearTimeout(t);
    vv.removeEventListener("resize", settle);
    requestAnimationFrame(anchor);
  }
  vv.addEventListener("resize", settle);
  settle();                                   // start ook als er (bijna) geen resize meer volgt
  setTimeout(finish, 500);                    // absoluut vangnet
}
function renderFocusSkeleton(id) {
  const it = FB.items.find(i => i.id === id) || {};
  $("#fb-focus").innerHTML = fbHeadHtml(it.naam, it.voornaam, it.datum, it.workout, it.categorie)
    + `<div class="fbf-scroll"><div class="skel-card"><div class="skel skel-line w60"></div><div class="skel skel-line w40"></div></div></div>`
    + fbDockHtml(id);
  fbBindDock(id);
}
function renderFocus(d) {
  if (!d || !d.ok) {
    $("#fb-focus").innerHTML = fbHeadHtml("", "", "", "", "")
      + `<div class="fbf-scroll"><p class="muted center">${esc(d && d.err || "Kon detail niet laden.")}</p></div>`;
    const b = $("#fb-back"); if (b) b.onclick = fbClose; return;
  }
  $("#fb-focus").innerHTML = fbHeadHtml(d.naam, d.voornaam, d.datum, d.workout, d.categorie)
    + `<div class="fbf-scroll">${fbCtxHtml(d)}${fbPaHtml(d)}${fbThreadHtml(d)}</div>`
    + fbDockHtml(d.id);
  fbBindDock(d.id);
  fbScrollThreadBottom();                              // desktop: onderkant meteen in beeld
}
// Recente context — pas in fase 4 gevuld; informatief (cyaan), amber zéér terughoudend.
function fbCtxHtml(d) {
  const rc = d.recent_context; if (!rc || !rc.length) return "";
  return rc.map(c => `<div class="fb-ctx ${c.tone === "amber" ? "amber" : ""}">
    <b>${esc(c.label || "Context")}</b>${esc(c.text || "")}</div>`).join("");
}
function fbPaHtml(d) {                                // gepland (intentie) vs uitgevoerd — rustig, tabulair
  const g = d.gepland || {}, u = d.uitgevoerd || {}, afw = d.afwijking || {};
  const chip = (afw.relevance && afw.relevance !== "ignore" && afw.relevance !== "n/a" && afw.pct != null)
    ? ` <span class="fb-afw">${afw.pct > 0 ? "+" : ""}${afw.pct}%</span>` : "";
  const zp = z => z ? `<span class="fb-zone">Z${z.num}${z.naam ? " " + esc(z.naam) : ""}</span>` : "—";
  const rows = [];
  if (g.km != null || u.km != null) rows.push(["Afstand", g.km != null ? `${g.km} km` : "—", (u.km != null ? `${u.km} km` : "—") + chip]);
  if (g.min != null || u.min != null) rows.push(["Duur", g.min != null ? `${g.min} min` : "—", u.min != null ? `${u.min} min` : "—"]);
  if (u.pace) rows.push(["Tempo", "—", `${esc(u.pace)}/km`]);
  if (u.hr_avg) rows.push(["Hartslag", "—", `${esc(u.hr_avg)}${u.hr_max ? ` · max ${esc(u.hr_max)}` : ""}`]);
  // Zone-rij: geplande INTENTIE = enkelvoudige zone óf structuur "Z2 → Z3".
  // Uitgevoerd toont ALLEEN een zone als die betekenisvol is (backend geeft er
  // geen bij een gestructureerde/multi-zone training → geen misleidend gemiddelde).
  const gzone = g.structuur ? `<span class="fb-zone plan">${esc(g.structuur)}</span>` : zp(g.zone);
  if (g.zone || g.structuur || u.zone) rows.push(["Zone", gzone, zp(u.zone)]);
  const foot = (d.gevoel || d.rpe)
    ? `<p class="fb-pa-foot">${d.gevoel ? `Gevoel: ${esc(d.gevoel.label)}` : ""}${d.gevoel && d.rpe ? " · " : ""}${d.rpe ? `RPE ${esc(d.rpe)}` : ""}</p>` : "";
  // Kernintentie (ACTIVE-stappen) vs. volledige feitelijke structuur (fallback);
  // warming-up/cooling-down subtiel als context, niet concurrerend met de kern.
  const kernLbl = d.plan_is_kern ? "Kern" : "Structuur";
  const intentie = (d.workout || g.structuur)
    ? `<p class="fb-pa-intentie">${esc(d.workout || "Training")}${g.structuur ? ` · <b>${esc(kernLbl)}: ${esc(g.structuur)}</b>` : (d.is_structured ? " · gestructureerd" : "")}${d.plan_context ? `<span class="fb-pa-ctx">incl. ${esc(d.plan_context)}</span>` : ""}</p>` : "";
  if (!rows.length) return (intentie || foot) ? `<div class="fb-pa">${intentie}${foot}</div>` : "";
  return `<div class="fb-pa">${intentie}<table>
    <tr><th></th><th>Gepland</th><th>Uitgevoerd</th></tr>
    ${rows.map(r => `<tr><td class="lbl">${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join("")}
  </table>${foot}</div>`;
}
function fbThreadHtml(d) {
  const g = d.gesprek || [];
  const bubbels = g.length
    ? g.map(m => `<div class="fb-bub ${m.coach ? "coach" : "atl"}"><span class="fb-wie">${m.coach ? "Jij" : esc(m.wie || d.voornaam || "")}</span>${esc(m.tekst)}</div>`).join("")
    : `<p class="muted klein">Geen bericht van de atleet — reageer op de uitvoering.</p>`;
  return `<div class="fb-thread">${bubbels}</div>`;
}

// ── FC-1: gerichte stale/not-found-recovery (server-side restore is de primaire fix) ──
// Alleen voor de specifieke "Training niet meer in beeld"-respons: één queue-refresh +
// her-open dezelfde workout indien nog aanwezig. Geen refresh-loop, geen generieke
// auto-refresh voor andere fouten, geen auto-retry van de actie (voorkomt dubbelpost).
function fbIsStaleErr(r) { return !!(r && r.err && /in beeld/i.test(r.err)); }
async function fbStaleRecover(id) {
  if (FB.recovering) return false;                     // geen refresh-loop
  FB.recovering = true;
  try {
    fbLog("stale_recover_start", { target: id });
    await fbRefresh();                                 // één gerichte queue-refresh (bestaande primitive)
    const nog = FB.items.some(i => i.id === id);
    if (nog) fbOpen(id, "stale_recover");              // her-open dezelfde workout indien nog aanwezig
    fbLog("stale_recover_done", { target: id, still_present: nog });
    return nog;
  } finally {
    FB.recovering = false;
  }
}

// ── Acties: Genereer / Versturen (idle→sending→sent|error) / Overslaan ───────
async function fbGen(id) {
  const btn = $("#fb-gen"); if (btn) { btn.disabled = true; btn.innerHTML = `${ic("brain")} AI schrijft…`; }
  fbLog("generate_start"); const t0 = performance.now();
  const r = await jpost("/api/feedback/generate", { id }).catch(() => null);
  const dur = Math.round(performance.now() - t0);
  if (btn) { btn.disabled = false; btn.innerHTML = `${ic("brain")} Genereer`; }
  if (!r || !r.ok) {
    fbLog("generate_error", { generate_duration_ms: dur });
    if (fbIsStaleErr(r)) { melding("Even herladen…"); fbStaleRecover(id); return; }   // gerichte recovery i.p.v. dode kaart
    return melding(r && r.err || "Genereren mislukt.", true);
  }
  fbLog("generate_success", { generate_duration_ms: dur });
  const ta = $("#fb-ta"); if (ta) { ta.value = r.tekst || ""; fbDraftSave(id, ta.value); fbGrow(ta); ta.focus(); }
}
async function fbSend(id) {
  if (FB.sending || FB.sentSet.has(id)) { fbLog("send_blocked_duplicate", { target: id }); return; }  // dubbel-post-guard
  const ta = $("#fb-ta"), tekst = (ta && ta.value || "").trim();
  if (!tekst) return melding("Schrijf of genereer eerst een reactie.", true);
  const btn = $("#fb-send"); FB.sending = true;
  if (btn) { btn.disabled = true; btn.innerHTML = `${ic("clock")} Versturen…`; }
  fbLog("send_start", { target: id }); const t0 = performance.now();
  const r = await jpost("/api/feedback/post", { id, tekst }).catch(() => null);
  const dur = Math.round(performance.now() - t0);
  FB.sending = false;
  if (btn) { btn.disabled = false; btn.innerHTML = `${ic("message")} Versturen`; }
  if (!r || !r.ok) {
    fbLog("send_error", { target: id, send_duration_ms: dur });
    if (fbIsStaleErr(r)) { melding("Even herladen — je concept blijft staan."); fbStaleRecover(id); return; }  // gerichte recovery; draft behouden
    return melding(r && r.err || "Versturen mislukt — je concept staat er nog.", true);
  }
  fbLog("send_success", { target: id, send_duration_ms: dur });
  FB.sentSet.add(id); fbDraftClear(id);              // pas ná server-ok
  fbSummaryAppend(r.item, id, tekst);                // sessielog: alleen deze geslaagde post
  FB.gepost = (FB.gepost || 0) + 1;
  homeFbBijwerken(-1, +1);                            // Home-balk: één minder wachtend, één meer gepost
  const idx = FB.items.findIndex(i => i.id === id);
  if (idx >= 0) FB.items.splice(idx, 1);
  renderQueue(); fbUpdateInfo(); haptic(15);
  focusNextAfterAction(FB.items[idx] || FB.items[idx - 1] || null);
}
let fbPendingSkip = null;                            // actieve, nog-niet-gecommitte skip (voor flush bij verlaten)
function fbSkip(id) {                                 // optimistic; POST volgt ná het undo-venster
  const idx = FB.items.findIndex(i => i.id === id); if (idx < 0) return;
  const item = FB.items[idx];
  FB.items.splice(idx, 1); FB.skipSet.add(id);
  renderQueue(); fbUpdateInfo(); haptic(10); fbLog("skip_optimistic", { target: id });
  focusNextAfterAction(FB.items[idx] || FB.items[idx - 1] || null);
  const herstel = () => { FB.skipSet.delete(id); FB.items.splice(Math.min(idx, FB.items.length), 0, item); renderQueue(); fbUpdateInfo(); };
  let settled = false;
  const entry = {};
  const commit = async (keepalive = false) => {      // idempotent: hooguit één POST, ook als toast + flush samenvallen
    if (settled) return; settled = true;
    if (fbPendingSkip === entry) fbPendingSkip = null;
    const r = await jpost("/api/feedback/skip", { id }, "POST", keepalive).catch(() => null);
    if (!r || !r.ok) {
      fbLog("skip_error", { target: id });
      if (!keepalive) { herstel(); melding("Overslaan mislukt — teruggezet.", true); }  // bij unload niet terugrollen: pagina gaat weg
    } else { fbLog("skip_commit", { target: id }); homeFbBijwerken(-1, 0); }  // Home-balk: één minder wachtend
  };
  const undo = () => { if (settled) return; settled = true; if (fbPendingSkip === entry) fbPendingSkip = null; fbLog("skip_undo", { target: id }); herstel(); };
  entry.commit = () => commit(true);
  fbPendingSkip = entry;
  fbToast(`Training van ${item.voornaam || item.naam} overgeslagen`,
    undo,                                             // Ongedaan → exacte plek terug, geen backend-call
    () => commit(false));                             // venster voorbij → nu pas overslaan
}
// Verlaat de coach de app binnen het 5s-undo-venster, dan ging de skip vroeger
// verloren (nooit gepost) → in Streamlit bleef de training openstaan. Flush een
// hangende skip met keepalive zodat hij de unload overleeft en cross-app klopt.
function fbFlushPendingSkip() { if (fbPendingSkip) fbPendingSkip.commit(); }
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") fbFlushPendingSkip(); });
window.addEventListener("pagehide", fbFlushPendingSkip);
// Eén toast met gegarandeerd precies één afloop: Ongedaan óf commit (nooit beide).
function fbToast(txt, onUndo, onCommit, ms = 5000) {
  let t = $("#prio-toast");
  if (!t) { t = document.createElement("div"); t.id = "prio-toast"; t.className = "prio-toast"; document.body.appendChild(t); }
  t.innerHTML = `<span>${esc(txt)}</span><button class="pt-undo" type="button">Ongedaan</button>`;
  requestAnimationFrame(() => t.classList.add("on"));
  clearTimeout(t._h);
  let done = false;
  const finish = undo => { if (done) return; done = true; clearTimeout(t._h); t.classList.remove("on"); undo ? onUndo && onUndo() : onCommit && onCommit(); };
  t._h = setTimeout(() => finish(false), ms);
  t.querySelector(".pt-undo").onclick = () => finish(true);
}

// ── Balken/knoppen + toetsenbord (desktop) + keyboard-aware dock (mobiel) ─────
$("#fb-nieuw").addEventListener("click", () => {
  if (!FB.pending) return;
  const p = FB.pending; FB.pending = null; $("#fb-nieuw").hidden = true;
  fbApplyQueue(p); fbLog("queue_apply", { reason: "coach_tap", queue_length: p.length });
});
$("#fb-refresh").addEventListener("click", async () => {
  fbLog("queue_refresh_start", { reason: "manual" });
  // Feedback v1 (G): zichtbare loading-state zolang de refresh loopt; reset bij succes én fout.
  const btn = $("#fb-refresh");
  if (btn) { if (btn.dataset.busy === "1") return; btn.dataset.busy = "1"; btn.classList.add("spinning"); btn.disabled = true; }
  try {
    const r = await api("/api/feedback/queue?refresh=1").catch(() => null);
    if (r && r.fs && Array.isArray(r.items)) {
      FB.gepost = r.gepost || 0; FB.groups = r.groepen || FB.groups; FB.pending = null; FB.pendingInitial = false;
      $("#fb-nieuw").hidden = true; FB.loaded = true; fbApplyQueue(r.items);
      fbLog("queue_apply", { reason: "manual", queue_length: FB.items.length });
    }
  } finally {
    if (btn) { btn.classList.remove("spinning"); btn.disabled = false; btn.dataset.busy = ""; }
  }
});
document.addEventListener("keydown", e => {
  if (huidigeView !== "feedback") return;
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { if (FB.selId) { e.preventDefault(); fbSend(FB.selId); } return; }
  const t = e.target;                                 // sneltoetsen NOOIT tijdens typen
  if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.isContentEditable)) return;
  if (e.key === "ArrowDown") { e.preventDefault(); fbMove(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); fbMove(-1); }
  else if (e.key === "g" || e.key === "G") { if (FB.selId) { e.preventDefault(); fbGen(FB.selId); } }
  else if (e.key === "s" || e.key === "S") { if (FB.selId) { e.preventDefault(); fbSkip(FB.selId); } }
  else if (e.key === "Escape") { e.preventDefault(); fbClose(); }
});
function fbMove(dir) {
  if (!FB.items.length) return;
  let idx = FB.items.findIndex(i => i.id === FB.selId);
  idx = idx < 0 ? (dir > 0 ? 0 : FB.items.length - 1) : Math.max(0, Math.min(FB.items.length - 1, idx + dir));
  fbOpen(FB.items[idx].id, "keyboard_nav");
}
// Click-through hard blokkeren: zolang de mobiele focus open is, mag de
// achterliggende queue/kolom NIET interactief zijn (geen tap die op een
// blootliggende rij landt). Desktop = master-detail → queue blijft interactief.
function fbLockQueue(on) {
  if (isDesktop()) return;
  const q = document.querySelector(".fb-queue-col"); if (!q) return;
  if (on) { q.setAttribute("inert", ""); document.body.classList.add("fb-focus-open"); }
  else { q.removeAttribute("inert"); document.body.classList.remove("fb-focus-open"); }
}

// ════════════════════════════════════════════════════════════════════════════
// SCHEMA BOUWEN — opgeslagen intake → AI-plan → CSV-download voor FinalSurge
// ════════════════════════════════════════════════════════════════════════════
let schemaAtleten = [];
let schemaSelKey = "";          // laatst gekozen atleet (selected state)
let schemaPicker = null;
let schemaOpenPending = "";     // athlete uit de route die geopend moet worden zodra de roster er is
async function laadSchema() {
  const box = $("#sb-lijst"), info = $("#sb-info");
  $("#sb-werk").hidden = true; box.hidden = false;
  skeleton(box, 4);
  const r = await api("/api/schema/atleten").catch(() => null);
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  schemaAtleten = r.atleten || [];
  info.textContent = r.ai
    ? "Kies een atleet. De AI maakt een conceptplan waar je over spart; een bestaande intake wordt slim voorgevuld."
    : "AI-sleutel nog niet ingesteld.";
  if (!schemaAtleten.length) {
    box.innerHTML = `<div class="leeg">${ic("brain")}<p>Geen atleten gevonden.<br>Controleer de FinalSurge-koppeling.</p></div>`;
    return;
  }
  // Gedeelde Athlete Picker (navigate): kiezen opent direct de workbench.
  // Secundair = doel waar betrouwbaar (groep is de sectiekop). Canonieke groeps-
  // volgorde uit de server; zoeken over alle groepen; alfabetisch binnen groep.
  schemaPicker = renderPicker({
    mount: box,
    items: schemaAtleten,
    groupOrder: r.groep_volgorde || [],
    selectedKey: schemaSelKey,
    mode: "navigate",
    placeholder: "Zoek atleet",
    emptyText: "Geen atleet gevonden.",
    secondary: a => (a.heeft_intake && a.doel) ? esc(a.doel) : "",
    onActivate: a => { schemaSelKey = a.key; schemaWerk(a); },
  });
  if (schemaOpenPending) openSchemaAthlete(schemaOpenPending);   // deep-link/refresh: heropen de athlete-workbench
}

// ── Schema workbench (Slice 1): canonieke rows → week-preview → open/edit ─────
// GEEN FinalSurge-write in deze flow. De bestaande /api/schema/push-route blijft
// bestaan voor compat, maar wordt hier bewust niet aangeroepen. State/edits leven
// in-memory + een localStorage-draft (bewezen Feedback-patroon), zodat reload en
// navigatie niets verliezen. We hergebruiken NIET de Streamlit builder_state.json:
// dat is één live single-session-slot die Streamlit elke run leest — delen zou de
// PWA en de Streamlit-bouwer elkaars half-afgemaakte schema laten overschrijven.
let sbState = null;

const SB_TYPE_IC = { Run: "🏃", Bike: "🚴", Swim: "🏊", Strength: "🏋️",
  CrossTraining: "💪", Walk: "🚶", Rest: "😴" };
const sbTypeIc = t => SB_TYPE_IC[t] || "🏃";
const SB_DAG = ["ma", "di", "wo", "do", "vr", "za", "zo"];
function sbParseDate(s) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; }
function sbDagDatum(s) { const d = sbParseDate(s); return d ? `${SB_DAG[(d.getDay() + 6) % 7]} ${d.getDate()}/${d.getMonth() + 1}` : esc(s || ""); }
function sbLog(ev, data) { try { console.debug("[schema]", ev, data || {}); } catch {} }   // alleen keys/tellingen/timings, geen schema-inhoud
// Deterministische fingerprint van de plantekst (FNV-1a) — geen timestamp. Bepaalt
// of 'Bouw schema' de bestaande workbench mag hergebruiken (plan inhoudelijk gelijk).
function sbHash(s) { s = String(s || ""); let h = 0x811c9dc5 >>> 0; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(16); }
// Eén deterministische normalisatie vóór hashing: line-endings + trailing whitespace.
// Voorkomt dat onzichtbare whitespace-drift een rebuild forceert; niet inhoudelijk.
function sbNormPlan(s) { return String(s || "").replace(/\r\n?/g, "\n").split("\n").map(l => l.replace(/[ \t]+$/, "")).join("\n").trim(); }
function sbPlanHash() { return sbHash(sbNormPlan(sbState.plan)); }

// Schema-affecting config-fingerprint (Verlengen). ALLEEN velden die de uiteindelijke
// schema-inhoud kunnen veranderen; géén UI-only state (resolved/acks/allesKlopt/mode/
// _context/_verleng_laatste). Deterministisch: vaste veldvolgorde, genormaliseerde
// waarden → semantisch gelijke config = gelijke hash. Voorkomt onnodige plan-regen.
const SB_FP_FIELDS = ["doel", "startdatum", "weken", "schema_einddatum", "wedstrijddatum",
  "trainingsdagen", "sessies_per_week", "sleuteldagen", "dubbele_dagen", "zones", "zone_type",
  "huidig_volume", "tijd_per_training", "race_prioriteit", "tussenraces", "coach_notitie",
  "referentie_prestatie", "blessurehistorie", "andere_sporten", "op_tijd"];
function sbConfigFp(c) {
  c = c || sbState.config || {};
  return sbHash(SB_FP_FIELDS.map(k => k + "=" + sbNormPlan(String(c[k] == null ? "" : c[k]))).join("\n"));
}

// Draft (localStorage) — instant resume op hetzelfde device, geen server-churn.
const SB_DRAFT_KEY = "bb_schema_drafts";
function sbDraftsAll() { try { return JSON.parse(localStorage.getItem(SB_DRAFT_KEY) || "{}"); } catch { return {}; } }
function sbDraftsSet(o) { try { localStorage.setItem(SB_DRAFT_KEY, JSON.stringify(o)); } catch {} }
// Draft-id = atleet + modus, zodat Nieuw en Verlengen elkaar NOOIT overschrijven.
function sbDraftId(key, mode) { return key + "::" + (mode || "nieuw"); }
function sbDraftSave() { if (!sbState || !sbState.key) return; const o = sbDraftsAll(); o[sbDraftId(sbState.key, sbState.mode)] = { ts: Date.now(), s: sbState }; sbDraftsSet(o); }
function sbDraftLoad(key, mode) { const d = sbDraftsAll()[sbDraftId(key, mode)]; return d && d.s ? d.s : null; }
function sbDraftClear(key, mode) { const o = sbDraftsAll(); const id = sbDraftId(key, mode); if (o[id]) { delete o[id]; sbDraftsSet(o); } }
let _sbSaveT = null;
function sbDebouncedSave() { clearTimeout(_sbSaveT); _sbSaveT = setTimeout(sbDraftSave, 400); }
(function sbDraftCleanup() { const o = sbDraftsAll(); const cut = Date.now() - 14 * 864e5; let ch = false; for (const k in o) if ((o[k].ts || 0) < cut) { delete o[k]; ch = true; } if (ch) sbDraftsSet(o); })();

// ══ Schema flow (Slice 2): config → conceptplan → AI-sparfase → Slice-1 workbench ══
// Stage-aware: één draft per atleet bewaart config, actuele planversie, chat én
// (na Bouw schema) de workbench-rows. Re-entry/reload herstelt exact de juiste fase.
function schemaWerk(a, mode) {
  mode = mode || "nieuw";
  pushRoute("schema", a.key);            // deep-link: refresh/terug houdt deze athlete-workbench (#coherentie)
  $("#sb-lijst").hidden = true;
  $("#sb-werk").hidden = false;
  const draft = sbDraftLoad(a.key, mode);
  // Coherentie: een CONFIG-draft is alleen geldig zolang de canonieke intake niet
  // wijzigde. Na (her)koppelen verandert a.intake_stamp → een oude/lege config-draft
  // is dan stale → verse canonieke prefill i.p.v. lege velden. Gevorderde stages
  // (plan/workbench) dragen echt coachwerk en blijven behouden.
  const configStale = draft && draft.stage === "config" && (draft.intake_stamp || "") !== (a.intake_stamp || "");
  if (draft && draft.stage && !configStale) {
    sbState = draft; sbState.naam = a.naam; sbState.mode = mode;
    // PF-2: een herstelde draft mag zijn zones NIET als 'vers uit FinalSurge' blijven
    // presenteren — die read is van een eerder moment. Downgrade naar RESTORED zodat de
    // coach ziet dat verversen zinvol is; een expliciete refresh zet 'm weer op FRESH.
    if (sbState.zones_status === "FRESH") sbState.zones_status = "RESTORED";
    // 'publish' is een live check → val terug op de workbench (rows intact); coach opent preview opnieuw.
    if ((sbState.stage === "workbench" || sbState.stage === "publish") && sbState.weken && sbState.weken.length) {
      // Draft met rows maar zonder hash (bv. gebouwd op een oudere versie) → backfill:
      // die rows hóren bij dit plan, dus 'Bouw schema' mag ze straks hergebruiken.
      if (!sbState.built_plan_hash) sbState.built_plan_hash = sbPlanHash();
      sbState.stage = "workbench"; return sbRenderWorkbench();
    }
    if (sbState.stage === "plan") return sbRenderPlan();
    if (sbState.stage === "herijking") return sbRenderHerijking();
    if (sbState.stage === "config") return sbRenderConfig();
  }
  sbState = null;                       // geen geldige draft → schone lei (geen leak)
  if (mode === "verlengen") sbStartVerleng(a);
  else sbStartConfig(a);
}

// Modus-schakelaar (Nieuw | Verlengen). Draft is per key+mode geïsoleerd, dus wisselen
// bewaart de huidige modus en herstelt (of start) de andere zonder te clobberen.
function sbModeBar(active) {
  const t = m => m === "verlengen" ? "Verlengen" : "Nieuw";
  return `<div class="sb-modebar" id="sb-modebar">${["nieuw", "verlengen"].map(m =>
    `<button type="button" class="sb-modebtn ${m === active ? "on" : ""}" data-mode="${m}">${t(m)}</button>`).join("")}</div>`;
}
function sbWireModeBar() {
  const bar = $("#sb-modebar"); if (!bar) return;
  bar.querySelectorAll(".sb-modebtn").forEach(b => b.addEventListener("click", () => {
    const m = b.dataset.mode; if (m === (sbState && sbState.mode)) return;
    const a = { key: sbState.key, naam: sbState.naam };
    if (sbState) sbDraftSave();          // huidige modus bewaren
    schemaWerk(a, m);
  }));
}

function sbBackToList() { sbState = null; pushRoute("schema"); laadSchema(); }
function sbToonLijst() { $("#sb-werk").hidden = true; $("#sb-lijst").hidden = false; }
// Deep-link: open (of markeer voor openen zodra de roster geladen is) een athlete-
// workbench uit de route. Hergebruikt de bestaande hash-routing (geen nieuwe laag).
function openSchemaAthlete(ident) {
  const a = (schemaAtleten || []).find(x => x.key === ident);
  if (a) { schemaOpenPending = ""; schemaWerk(a); }
  else { schemaOpenPending = ident; }
}

// ── Fase 1 — schema-instellingen (modus NIEUW), slimme prefill ───────────────
async function sbStartConfig(a) {
  const wrap = $("#sb-werk");
  wrap.innerHTML = `<button class="btn ghost back" id="sb-terug">${ic("back")} Alle atleten</button>
    <div class="d-head"><span class="avatar big">${initialen(a.naam)}</span>
      <div><h2 class="d-naam">${esc(a.naam)}</h2><p class="muted klein" id="sb-cfg-load">Instellingen laden…</p></div>
      ${athleteNav("schema", a.key)}</div>`;
  $("#sb-terug").addEventListener("click", sbBackToList);
  const r = await api("/api/schema/config?key=" + encodeURIComponent(a.key)).catch(() => null);
  if (!r || !r.ok) { const l = $("#sb-cfg-load"); if (l) l.textContent = "Kon instellingen niet laden."; return; }
  sbState = { key: a.key, naam: a.naam, mode: "nieuw", stage: "config", config: r.config || {},
    context: r.context || {}, plan: "", planEdited: false, prevPlan: null, chat: [],
    intake_stamp: r.intake_stamp || (a.intake_stamp || ""),      // canonieke-intake-versie van deze prefill
    zones_status: r.zones_status || "", zone_fingerprint: r.zone_fingerprint || "" };  // PF-2 zone-versheid
  sbState.config.mode = "nieuw";
  sbDraftSave();
  sbRenderConfig();
}

// ── Verlengen — slimme herijking i.p.v. intakeformulier ──────────────────────
async function sbStartVerleng(a) {
  const wrap = $("#sb-werk");
  wrap.innerHTML = `<button class="btn ghost back" id="sb-terug">${ic("back")} Alle atleten</button>
    ${sbModeBar("verlengen")}
    <div class="d-head"><span class="avatar big">${initialen(a.naam)}</span>
      <div><h2 class="d-naam">${esc(a.naam)}</h2><p class="muted klein" id="sb-vl-load">Vorige blok evalueren…</p></div></div>`;
  $("#sb-terug").addEventListener("click", sbBackToList);
  sbWireModeBar();
  const r = await api("/api/schema/verleng?key=" + encodeURIComponent(a.key)).catch(() => null);
  if (!$("#sb-vl-load")) return;                 // navigatie weg tijdens laden → geen state zetten (leak-safe)
  if (!r || !r.ok) { const l = $("#sb-vl-load"); if (l) l.textContent = r?.err || "Kon vorige blok niet evalueren."; return; }
  sbState = { key: a.key, naam: a.naam, mode: "verlengen", stage: "herijking",
    config: r.config || {}, context: r.context || {}, plan: "", planEdited: false, prevPlan: null, chat: [],
    vorig_blok: r.vorig_blok || {}, herijking: r.herijking || [], readiness: r.readiness || {},
    vragen: r.vragen || [], acks: {}, resolved: {}, allesKlopt: false };
  sbState.config.mode = "verlengen";
  sbLog("verleng_start", { key: a.key, readiness: (r.readiness || {}).status,
    items: (r.herijking || []).length, bron: (r.vorig_blok || {}).bron });
  sbDraftSave();
  sbRenderHerijking();
}

const SB_HERIJK_GROEP = [
  ["veranderd", "Veranderd", "BeBetter heeft dit met actuele data geactualiseerd"],
  ["aandacht", "Aandacht", "Weeg dit mee in het nieuwe blok"],
  ["controleren", "Nog controleren", "Kort bevestigen of aanpassen"],
  ["geldig", "Nog geldig", "Ongewijzigd overgenomen"],
];

function sbVorigBlokHtml(vb) {
  const p = vb.periode || {}, rij = [], einde = vb.blok_einde || vb.laatste_datum;
  if (p.van || einde) rij.push(`trainingsperiode ${esc(p.van || "?")} – ${esc(einde || "?")}`);
  if (vb.frequentie) rij.push(`${esc(vb.frequentie)}×/week gepland`);
  if (vb.doel) rij.push(`vorig doel: ${esc(vb.doel)}`);
  let status = "";
  if (vb.loopt_nog) status = `<span class="sb-vb-tag">loopt nog · blok-einde ${esc(einde)}</span>`;
  else if (vb.afgelopen_dagen != null) status = `<span class="sb-vb-tag">vorig blok eindigde ${vb.afgelopen_dagen} dag(en) geleden (${esc(einde)})</span>`;
  else status = `<span class="sb-vb-tag warn">geen lopend schema gevonden — controleer de startdatum</span>`;
  // TRAINING ≠ DOELRACE: toon de afsluitende doelrace apart, niet als 'laatste training'.
  const dr = vb.doelrace;
  const race = dr ? `<span class="sb-vb-race">🏁 afsluitende doelrace: ${esc(dr.naam || "race")} op ${esc(dr.datum)}${dr.toekomstig ? " (nog te lopen)" : ""} — vervolgblok start hierná</span>` : "";
  return `<div class="sb-vorigblok">
    <p class="sb-vb-h">${ic("check")} Vorige blok <span class="muted klein">— ${esc(vb.bron || "onbekend")}</span></p>
    <p class="sb-vb-rij">${rij.map(x => `<span>${esc(x)}</span>`).join("")}</p>
    ${status}${race}</div>`;
}

// ── Readiness = ÉÉN afgeleide waarheid uit de ACTUELE state ───────────────────
// Bepaalt overal (banner-tekst, aantal, klik-target, plan-gate) dezelfde unresolved-
// set uit config + kritiek-acks + coach-bevestigingen. Geen backend-snapshot of
// per-onderdeel eigen logica meer.
// Normaliseer de herijking-state-vorm. Cruciaal voor drafts van vóór een veld-
// introductie (bv. herstelde draft zonder `resolved`): zonder dit lazen render en
// klik-handlers een undefined map → TypeError → knop 'doet niets'. Eén plek, altijd.
function sbEnsureVerleng() {
  if (!sbState) return;
  if (!sbState.acks || typeof sbState.acks !== "object") sbState.acks = {};
  if (!sbState.resolved || typeof sbState.resolved !== "object") sbState.resolved = {};
  if (typeof sbState.allesKlopt !== "boolean") sbState.allesKlopt = false;
}
function sbItemResolved(it, i) {
  const acks = sbState.acks || {}, resolved = sbState.resolved || {};
  if (it.kritiek) return !!acks[i];                        // kritiek: expliciete erkenning
  if (it.status !== "controleren") return true;            // geldig/veranderd/info = geen actie
  if (it.sleutel === "doel")                               // waarde-vereist: leeg → weer open (case 6)
    return !!(((sbState.config || {}).doel || "").trim());
  return !!sbState.allesKlopt || !!resolved[i];            // bevestigd/gecorrigeerd
}
function sbUnresolved() {
  const items = sbState.herijking || [], out = [];
  items.forEach((it, i) => {
    const actie = it.kritiek || it.status === "controleren";
    if (actie && !sbItemResolved(it, i)) out.push(i);
  });
  return out;
}
function sbReadinessState() {
  const c = sbState.config || {}, un = sbUnresolved();
  const ontbreekt = [];
  if (!((c.doel || "").trim())) ontbreekt.push("doel");
  if (!((c.zones || "").trim())) ontbreekt.push("zones");
  const laatste = c._verleng_laatste || "";
  const overlap = !!(laatste && c.startdatum && c.startdatum <= laatste);
  const kritiek = un.filter(i => (sbState.herijking[i] || {}).kritiek).length;
  let status = "klaar", reden = "";
  if (ontbreekt.length) { status = "geblokkeerd"; reden = "Kernconfig ontbreekt: " + ontbreekt.join(", "); }
  else if (overlap) { status = "geblokkeerd"; reden = "Startdatum ligt op/vóór het bestaande blok"; }
  else if (un.length) status = "controle";
  return { status, reden, unresolved: un, kritiek, controle: un.length - kritiek,
           te_controleren: un.length, overlap };
}

function sbReadinessHtml(rs) {
  if (rs.status === "geblokkeerd") return `<button type="button" class="sb-ready blok" id="sb-ready-nav">${ic("close")} Kan nog niet verlengen — ${esc(rs.reden || "ontbrekende gegevens")}. <span class="sb-ready-hint">Klik om het op te lossen</span></button>`;
  if (rs.status === "controle") return `<button type="button" class="sb-ready controle" id="sb-ready-nav">${ic("note")} Bijna klaar — controleer nog ${rs.te_controleren} punt(en)${rs.kritiek ? `, waarvan ${rs.kritiek} aandachtspunt` : ""}. <span class="sb-ready-hint">Klik naar het eerste punt</span></button>`;
  return `<div class="sb-ready klaar">${ic("check")} Klaar om te verlengen — BeBetter heeft voldoende actuele context.</div>`;
}

// Springt naar het eerste ACTUEEL onopgeloste punt (nooit naar een reeds resolved item).
function sbReadinessNav() {
  const rs = sbReadinessState();
  if (rs.unresolved.length) {
    const el = $("#sb-hi-" + rs.unresolved[0]);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1200);
      const btn = el.querySelector("[data-corr],[data-ack],[data-confirm]"); if (btn) setTimeout(() => btn.focus(), 300);
      return;
    }
  }
  const t = rs.overlap ? $("#vl-start") : ($("#sb-nieuweperiode") || $("#vl-gen"));
  t?.scrollIntoView({ behavior: "smooth", block: "center" }); t?.focus?.();
}

function sbHerijkItemHtml(it, idx) {
  const resolved = sbItemResolved(it, idx);
  const val = it.actueel || it.oud || "";
  let body = `<span class="sb-hi-label">${esc(it.label)}</span>`;
  if (it.status === "veranderd") body += `<span class="sb-hi-delta">${esc(it.oud || "onbekend")} → <b>${esc(it.actueel)}</b></span>`;
  else if (val) body += `<span class="sb-hi-val">${esc(val)}</span>`;
  if (it.bron) body += `<span class="sb-hi-bron">${esc(it.bron)}${it.zekerheid ? " · zekerheid " + esc(it.zekerheid) : ""}</span>`;
  const bewerkbaar = ["trainingsdagen", "doel", "frequentie"];
  let act = "";
  if (it.kritiek) {
    act = `<button class="btn ${resolved ? "ghost" : "primary"} sm" data-ack="${idx}">${resolved ? ic("check") + " meegenomen" : "Meegenomen"}</button>`;
  } else if (it.status === "controleren") {
    // 'doel' is waarde-vereist (geen los Klopt); overige controleren: Klopt of Aanpassen.
    if (it.sleutel !== "doel")
      act += `<button class="btn ${resolved ? "ghost" : "primary"} sm" data-confirm="${idx}">${resolved ? ic("check") + " bevestigd" : "Klopt"}</button>`;
    if (bewerkbaar.includes(it.sleutel))
      act += `<button class="btn ghost sm" data-corr="${idx}" data-sleutel="${esc(it.sleutel)}">Aanpassen</button>`;
  }
  const cls = it.status + ((it.kritiek || it.status === "controleren") && resolved ? " resolved" : "");
  return `<div class="sb-hi ${cls}" id="sb-hi-${idx}">${body}<div class="sb-hi-act">${act}</div>
    <div class="sb-hi-edit" id="sb-hi-edit-${idx}" hidden></div></div>`;
}

function sbRenderHerijking() {
  sbEnsureVerleng();                        // state-vorm normaliseren vóór render/klik (bron-fix)
  const c = sbState.config, vb = sbState.vorig_blok || {}, items = sbState.herijking || [];
  const groepen = SB_HERIJK_GROEP.map(([st, titel, sub]) => {
    const list = items.map((it, i) => [it, i]).filter(([it]) => it.status === st);
    if (!list.length) return "";
    return `<div class="sb-hg"><p class="sb-hg-h">${esc(titel)} <span class="muted klein">— ${esc(sub)}</span></p>
      ${list.map(([it, i]) => sbHerijkItemHtml(it, i)).join("")}</div>`;
  }).join("");
  const vragen = (sbState.vragen || []).length ? `
    <div class="sb-hg"><p class="sb-hg-h">Mini-update <span class="muted klein">— alleen wat we nog niet weten (optioneel)</span></p>
      ${sbState.vragen.map((q, i) => `<div class="sb-vraag"><label class="lbl">${esc(q.vraag)}</label>
        <input type="text" id="sb-vraag-${i}" data-sleutel="${esc(q.sleutel)}" placeholder="optioneel"></div>`).join("")}</div>` : "";
  $("#sb-werk").innerHTML = `
    <button class="btn ghost back" id="sb-terug">${ic("back")} Alle atleten</button>
    ${sbModeBar("verlengen")}
    <div class="sb-context"><div class="sb-ctx-head"><span class="avatar big">${initialen(sbState.naam)}</span>
      <div><h2 class="d-naam">${esc(sbState.naam)}</h2><p class="muted klein">Verlengen · herijking</p></div>${athleteNav("schema", sbState.key)}</div></div>
    ${sbVorigBlokHtml(vb)}
    <p class="sb-herijk-intro">${ic("brain")} BeBetter heeft dit herijkt — controleer alleen wat veranderd of onzeker is.</p>
    <div class="sb-nieuweperiode" id="sb-nieuweperiode">
      <div><label class="lbl">Nieuwe start</label><input type="date" id="vl-start" value="${esc(c.startdatum)}"></div>
      <div><label class="lbl">Weken</label><input type="number" id="vl-weken" min="1" max="52" value="${esc(c.weken)}"></div>
      <p class="hint" id="vl-startwarn"></p>
    </div>
    ${groepen}
    ${vragen}
    <div class="sb-herijk-foot" id="sb-herijk-foot">${sbFootHtml()}</div>`;
  $("#sb-terug").addEventListener("click", sbBackToList);
  sbWireModeBar();
  $("#scroller").scrollTo({ top: 0 });
  $("#vl-start").addEventListener("input", sbVlPeriode);
  $("#vl-weken").addEventListener("input", sbVlPeriode);
  $("#sb-werk").querySelectorAll("[data-ack]").forEach(b => b.addEventListener("click", () => {
    sbEnsureVerleng(); const i = +b.dataset.ack; sbState.acks[i] = !sbState.acks[i]; sbDraftSave(); sbRenderHerijking();
  }));
  $("#sb-werk").querySelectorAll("[data-confirm]").forEach(b => b.addEventListener("click", () => {
    sbEnsureVerleng(); const i = +b.dataset.confirm; sbState.resolved[i] = !sbState.resolved[i]; sbDraftSave(); sbRenderHerijking();
  }));
  $("#sb-werk").querySelectorAll("[data-corr]").forEach(b => b.addEventListener("click", () => sbHerijkCorrect(+b.dataset.corr, b.dataset.sleutel)));
  sbWireFoot();
  sbVlGate();
}

// De foot (banner + Alles klopt + Maak vervolgplan) wordt uit de ACTUELE readiness
// gebouwd, zodat banner/aantal/gate altijd dezelfde waarheid tonen.
function sbFootHtml() {
  const rs = sbReadinessState();
  const openControle = (sbState.herijking || []).some((it, i) =>
    !it.kritiek && it.status === "controleren" && it.sleutel !== "doel" && !sbItemResolved(it, i));
  return `${sbReadinessHtml(rs)}
    ${openControle && !sbState.allesKlopt ? `<button class="btn ghost block" id="vl-allesklopt">${ic("check")} Alles klopt</button>` : ""}
    <button class="btn primary block" id="vl-gen">${ic("brain")} Maak vervolgplan</button>
    <p class="hint" id="vl-status"></p>`;
}
function sbWireFoot() {
  const ak = $("#vl-allesklopt"); if (ak) ak.addEventListener("click", () => { sbState.allesKlopt = true; sbDraftSave(); sbRenderHerijking(); });
  $("#sb-ready-nav")?.addEventListener("click", sbReadinessNav);
  $("#vl-gen")?.addEventListener("click", sbVerlengGen);
}
// Live update van banner/aantal/gate zonder de item-editors te herrenderen (behoudt
// invoerfocus). Voor tekstinvoer; toggles/erkenning doen een volledige re-render.
function sbRefreshFoot() {
  const foot = $("#sb-herijk-foot"); if (foot) { foot.innerHTML = sbFootHtml(); sbWireFoot(); }
  sbVlGate();
}

function sbVlPeriode() {
  const c = sbState.config;
  c.startdatum = $("#vl-start").value || c.startdatum;
  c.weken = $("#vl-weken").value || c.weken;
  const warn = $("#vl-startwarn"), laatste = c._verleng_laatste || "";
  if (warn) warn.textContent = (laatste && c.startdatum && c.startdatum <= laatste)
    ? `⚠️ Start ligt op/vóór de laatste geplande training (${laatste}) — verzet de start ná het bestaande blok.` : "";
  sbDebouncedSave(); sbRefreshFoot();
}

// Plan-gate = dezelfde afgeleide readiness. 'Maak vervolgplan' kan alléén bij KLAAR
// (geen unresolved, geen ontbrekende kernconfig, geen overlap).
function sbVlGate() {
  const rs = sbReadinessState();
  const btn = $("#vl-gen"); if (btn) btn.disabled = rs.status !== "klaar";
  const st = $("#vl-status");
  if (st) st.textContent =
    rs.status === "klaar" ? "" :
    rs.overlap ? "Verzet eerst de startdatum ná het bestaande blok." :
    (rs.status === "geblokkeerd") ? (rs.reden || "") :
    rs.kritiek ? "Erken eerst de aandachtspunt(en)." :
    "Bevestig of pas de te controleren punten aan (of ‘Alles klopt’).";
}

function sbHerijkCorrect(idx, sleutel) {
  sbEnsureVerleng();
  const box = $("#sb-hi-edit-" + idx); if (!box) return;
  if (!box.hidden) { box.hidden = true; box.innerHTML = ""; return; }
  const c = sbState.config;
  // Bij een correctie geldt het item als opgelost (bevestigd óf gewijzigd). Voor 'doel'
  // is resolution waarde-gebaseerd (leeg → weer open), dus daar geen vlag; wel live refresh.
  const markResolved = () => { if (sleutel !== "doel") sbState.resolved[idx] = true; sbRefreshFoot(); };
  if (sleutel === "doel") {
    box.innerHTML = `<textarea id="corr-doel" rows="2" placeholder="nieuw hoofddoel voor dit blok">${esc(c.doel || "")}</textarea>`;
    box.hidden = false;
    $("#corr-doel").addEventListener("input", e => { c.doel = e.target.value; sbDebouncedSave(); sbRefreshFoot(); });
  } else if (sleutel === "trainingsdagen") {
    box.innerHTML = sbDagenEditorHtml("corr-dagen", c.trainingsdagen || "");
    box.hidden = false;
    sbWireDagenEditor(box, "corr-dagen", v => { c.trainingsdagen = v; markResolved(); });
  } else if (sleutel === "frequentie") {
    // Beschikbare dagen ≠ sessies/week ≠ sleuteldagen ≠ dubbele dagen — expliciet apart.
    box.innerHTML = `
      <label class="lbl">Gewenste sessies per week</label>
      <input type="text" id="corr-spw" value="${esc(c.sessies_per_week || "")}" placeholder="bijv. 8 of 7-9">
      <label class="lbl">Sleutel-/kwaliteitsdagen</label>
      ${sbDagenEditorHtml("corr-sleutel", c.sleuteldagen || "")}
      <label class="lbl">Dubbele-sessiedagen (optioneel)</label>
      ${sbDagenEditorHtml("corr-dubbel", c.dubbele_dagen || "")}`;
    box.hidden = false;
    $("#corr-spw").addEventListener("input", e => { c.sessies_per_week = e.target.value.trim(); sbDebouncedSave(); markResolved(); });
    sbWireDagenEditor(box, "corr-sleutel", v => { c.sleuteldagen = v; markResolved(); });
    sbWireDagenEditor(box, "corr-dubbel", v => { c.dubbele_dagen = v; markResolved(); });
  }
}

function sbDagenEditorHtml(id, waarde) {
  const sel = sbDagenUitString(waarde || "");
  return `<div class="sb-dagen" id="${id}">${SB_DAG.map((d, i) =>
    `<button type="button" class="sb-dag ${sel.includes(i) ? "on" : ""}" data-d="${i}">${d[0].toUpperCase() + d.slice(1)}</button>`).join("")}</div>`;
}
function sbWireDagenEditor(box, id, set) {
  const wrap = box.querySelector("#" + id); if (!wrap) return;
  wrap.querySelectorAll(".sb-dag").forEach(b => b.addEventListener("click", () => {
    b.classList.toggle("on");
    set([...wrap.querySelectorAll(".sb-dag.on")].map(x => +x.dataset.d).sort((p, q) => p - q).map(i => SB_DAG[i]).join("/"));
    sbDebouncedSave();
  }));
}

async function sbVerlengGen() {
  const btn = $("#vl-gen"); if (btn.disabled) return;
  // mini-update-antwoorden → coachinstructie (in-app, niet extern verstuurd)
  const c = sbState.config, extra = [];
  (sbState.vragen || []).forEach((q, i) => {
    const v = ($("#sb-vraag-" + i) || {}).value; if (v && v.trim()) {
      if (q.sleutel === "trainingsdagen" && !c.trainingsdagen) c.trainingsdagen = v.trim();
      else extra.push(v.trim());
    }
  });
  if (extra.length) c.coach_notitie = ((c.coach_notitie || "") + " " + extra.join(" ")).trim();
  // Fast-path: als de schema-affecting config niet is gewijzigd sinds het huidige plan
  // gemaakt werd én er al een plan is, NIET opnieuw genereren (AI is nondeterministisch
  // → zou de planhash veranderen en een onnodige generate_csv forceren). Terug naar de
  // bestaande workbench als de rows nog bij dit plan horen, anders naar de plan-stap.
  const fp = sbConfigFp(c);
  const planExists = !!(sbState.plan && sbState.plan.trim());
  if (planExists && sbState.plan_input_fp === fp) {
    const rowsMatch = !!(sbState.weken && sbState.weken.length) && sbState.built_plan_hash === sbPlanHash();
    sbLog("schema_reuse", { mode: "verlengen", stap: "plan", reuse: true, target: rowsMatch ? "workbench" : "plan" });
    if (rowsMatch) { sbState.stage = "workbench"; sbDraftSave(); sbRenderWorkbench(); haptic(8); return; }
    sbState.stage = "plan"; sbDraftSave(); sbRenderPlan(); return;
  }
  sbLog("schema_reuse", { mode: "verlengen", stap: "plan", reuse: false, reason: planExists ? "config_changed" : "no_plan" });
  btn.disabled = true; btn.textContent = "AI bouwt het vervolgplan…";
  const st = $("#vl-status"); if (st) st.textContent = "BeBetter bouwt logisch voort op het vorige blok. Dit kan even duren.";
  const t0 = performance.now();
  const r = await jpost("/api/schema/plan", { key: sbState.key, config: sbState.config }).catch(() => null);
  sbLog("plan_gen", { key: sbState.key, mode: "verlengen", ms: Math.round(performance.now() - t0), ok: !!(r && r.ok) });
  if (!r || !r.ok) { btn.disabled = false; btn.innerHTML = `${ic("brain")} Maak vervolgplan`; if (st) st.textContent = ""; return melding(r?.err || "Plan mislukt.", true); }
  if (r.context_blob) sbState.config._context = r.context_blob;
  if (r.context) sbState.context = r.context;
  sbState.plan = r.plan || ""; sbState.planEdited = false; sbState.prevPlan = null; sbState.chat = [];
  sbState.plan_input_fp = fp;                 // vastleggen: dit plan hoort bij deze config
  sbState.stage = "plan"; sbDraftSave();
  sbRenderPlan();
}

const SB_DAG_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"];
function sbDagenUitString(s) { const p = (s || "").toLowerCase().split(/[^a-z]+/).filter(Boolean); return SB_DAG.map((d, i) => i).filter(i => p.includes(SB_DAG[i])); }
function sbDagenNaarString() { return [...$("#cfg-dagen").querySelectorAll(".sb-dag.on")].map(b => +b.dataset.d).sort((x, y) => x - y).map(i => SB_DAG[i]).join("/"); }

// Display-samenvatting; de AI-harde-eisen komen server-side uit _harde_eisen_secties
// (enige bron voor het model). Deze lijst spiegelt dezelfde config-velden.
function sbAfspraken(c) {
  const dagen = sbDagenUitString(c.trainingsdagen || ""), out = [];
  if (c.doel) out.push("Doel: " + c.doel);
  if (c.weken) out.push(`Periode: ${c.weken} weken · ${c.startdatum || "?"}${c.schema_einddatum ? " → " + c.schema_einddatum : ""}`);
  if (c.wedstrijddatum) out.push("Hoofddoel: " + c.wedstrijddatum);
  out.push(dagen.length ? `Trainingsdagen (${dagen.length}/week): ${dagen.map(i => SB_DAG_NL[i]).join(", ")}`
                        : "Trainingsdagen: nog niet gekozen — de AI kiest ze zelf");
  if (c.sessies_per_week) out.push("Sessies/week: " + c.sessies_per_week);
  out.push("Plannen op: " + (c.op_tijd ? "tijd (minuten)" : "afstand (km)"));
  out.push(`Zones (${c.zone_type || "tempo"}): ${c.zones ? "ingesteld" : "—"}`);
  if (c.huidig_volume) out.push("Huidig volume: " + c.huidig_volume);
  if (c.tijd_per_training) out.push("Tijd/training: " + c.tijd_per_training);
  if (c.race_prioriteit) out.push("Race: " + c.race_prioriteit);
  if (c.coach_notitie) out.push("Coachinstructie: " + c.coach_notitie.split("\n")[0]);
  out.push("Variatie verplicht; op elke trainingsdag een training.");
  return out;
}
function sbRefreshAfspraken() { const ul = $("#cfg-afspraken"); if (ul) ul.innerHTML = sbAfspraken(sbState.config).map(a => `<li>${esc(a)}</li>`).join(""); }

// Verplichte velden vóór plan-generatie (geen gokken; coach vult ontbrekende in).
function sbConfigValid(c) {
  const m = [];
  if (!(c.doel || "").trim()) m.push("doel");
  if (!sbDagenUitString(c.trainingsdagen || "").length) m.push("trainingsdagen");
  if (!(c.startdatum || "").trim()) m.push("startdatum");
  if (!(parseInt(c.weken, 10) > 0)) m.push("weken");
  if (c._periode_invalid) m.push("geldige einddatum");   // einddatum vóór start → plan-gate dicht
  return m;
}
function sbUpdateGate() {
  const miss = sbConfigValid(sbState.config), btn = $("#cfg-gen"), st = $("#cfg-status");
  if (!btn) return;
  btn.disabled = miss.length > 0;
  if (st) st.textContent = miss.length ? "Vul eerst in: " + miss.join(", ") + "."
                                       : "BeBetter maakt het conceptplan. Dit kan even duren.";
}

function sbSyncConfig() {
  const c = sbState.config;
  c.doel = $("#cfg-doel").value; c.startdatum = $("#cfg-start").value; c.weken = $("#cfg-weken").value;
  c.schema_einddatum = ($("#cfg-eind") || {}).value || "";        // nu een echt bewerkbaar veld
  c.wedstrijddatum = ($("#cfg-race-datum") || {}).value || "";
  c.trainingsdagen = sbDagenNaarString(); c.sessies_per_week = ($("#cfg-sessies") || {}).value || "";
  c.huidig_volume = $("#cfg-vol").value; c.tijd_per_training = ($("#cfg-tijd") || {}).value || "";
  c.race_prioriteit = $("#cfg-race").value; c.coach_notitie = $("#cfg-notitie").value;
  // op_tijd wordt door de segment-knop gezet (sbWireUitvoer); hier niet overschrijven.
  sbDebouncedSave();
}

// Compacte NL-datum (voor de periode-samenvatting). Geen tweede date-engine: puur weergave.
function sbDatumKort(iso) {
  const d = sbParseDate(iso); if (!d) return esc(iso || "");
  const mnd = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  return `${d.getDate()} ${mnd[d.getMonth()]}`;
}
// Wedstrijddatum ≠ schema-einddatum (§8): ligt de hoofddoel-race ná het schema-einde, toon
// dat als coherente info (geen foutmelding). Beide dezelfde-dag of leeg → geen regel.
function sbPeriodeGap(c) {
  if (c._periode_invalid) return `<p class="sb-periode-gap warn">${ic("alert")} ${esc(c._periode_err || "De einddatum ligt vóór de startdatum.")}</p>`;
  if (!c.wedstrijddatum || !c.schema_einddatum || c.wedstrijddatum <= c.schema_einddatum) return "";
  return `<p class="sb-periode-gap">${ic("flag")} Dit blok eindigt ${sbDatumKort(c.schema_einddatum)} · hoofddoel ${sbDatumKort(c.wedstrijddatum)}</p>`;
}
function sbRefreshPeriodeGap() {
  const el = $("#cfg-periode-gap"); if (el) el.innerHTML = sbPeriodeGap(sbState.config);
}
// Canonieke periode via de server (§6): één bron `_bereken_periode`, geen frontend-date-
// engine. `leading` bepaalt welk laatst-bewerkte veld leidt: "eind" → server berekent weken
// uit de einddatum; anders (weken/start) → einddatum uit de weken. Beide velden blijven zo
// altijd coherent, zonder stille tegenstrijdige waarden.
async function sbRecalcPeriode(leading) {
  if (!sbState) return;
  const start = ($("#cfg-start") || {}).value || "", weken = ($("#cfg-weken") || {}).value || "",
    eind = ($("#cfg-eind") || {}).value || "";
  const qs = leading === "eind"
    ? `start=${encodeURIComponent(start)}&einddatum=${encodeURIComponent(eind)}`
    : `start=${encodeURIComponent(start)}&weken=${encodeURIComponent(weken)}`;
  const r = await api("/api/schema/periode?" + qs).catch(() => null);
  if (!r || !r.ok || !sbState) return;
  const c = sbState.config;
  // Ongeldige periode (einddatum vóór start): NIET stil corrigeren — markeer, toon de fout,
  // blokkeer de plan-gate, en laat de coach-invoer staan zodat hij hem kan herstellen.
  if (r.geldig === false) {
    c._periode_invalid = true; c._periode_err = r.err || "Ongeldige periode.";
    sbRefreshPeriodeGap(); sbRefreshAfspraken(); sbUpdateGate(); sbDebouncedSave();
    return;
  }
  c._periode_invalid = false; c._periode_err = "";
  c.weken = String(r.weken); c.schema_einddatum = r.einddatum;
  const wIn = $("#cfg-weken"), eIn = $("#cfg-eind");
  if (wIn && leading !== "weken") wIn.value = c.weken;   // niet het veld dat de coach net typt overschrijven
  if (eIn && leading === "weken") eIn.value = c.einddatum || r.einddatum;
  if (eIn && leading !== "eind") eIn.value = r.einddatum;
  sbRefreshPeriodeGap(); sbRefreshAfspraken(); sbUpdateGate(); sbDebouncedSave();
}

// ── PF-2 — expliciete zone-refresh + bronstatus ──────────────────────────────
// Een expliciete coach-refresh forceert ALTIJD een verse zone-read (los van draft/
// fingerprint) en werkt enkel de zonebron-context bij; workbench/plan/coach-edits
// (PF-1) blijven ongemoeid. Mislukt de verse read → eerlijk "laatst bekend/niet
// beschikbaar", nooit stil oude zones als actueel.
const SB_ZONE_STATUS = {
  FRESH: { txt: "vers uit FinalSurge", cls: "ok" },
  RESTORED: { txt: "laatst geladen — ververs voor de nieuwste", cls: "warn" },
  LAST_KNOWN: { txt: "laatst bekend — kon niet verversen", cls: "warn" },
  UNAVAILABLE: { txt: "geen zones beschikbaar", cls: "warn" },
};
function sbZoneStatusHtml() {
  const m = SB_ZONE_STATUS[sbState && sbState.zones_status];
  const status = m ? `<span class="sb-zone-status ${m.cls}">· ${esc(m.txt)}</span>` : "";
  return `${status} <button type="button" class="btn ghost mini" id="sb-zone-refresh">${ic("refresh")} Ververs zones</button>`;
}
function sbWireZoneRefresh() {
  const b = $("#sb-zone-refresh"); if (b) b.addEventListener("click", sbRefreshZones);
}
async function sbRefreshZones() {
  if (!sbState || !sbState.key) return;
  if (sbState.stage === "config") sbSyncConfig();          // pending veld-edits eerst borgen
  const b = $("#sb-zone-refresh"); if (b) { b.disabled = true; b.textContent = "Verversen…"; }
  const r = await api("/api/schema/zones?key=" + encodeURIComponent(sbState.key)).catch(() => null);
  if (!sbState) return;
  if (!r || !r.ok) {                                        // transport faalde → nooit als 'fresh' tonen
    sbState.zones_status = (sbState.config && sbState.config.zones) ? "LAST_KNOWN" : "UNAVAILABLE";
    melding("Zones konden niet worden ververst. Laatst bekende zones blijven zichtbaar.", true);
  } else {
    // Alleen de zonebron bijwerken — géén schema-inhoud aanraken (PF-1 authority intact).
    if (sbState.config) { sbState.config.zones = r.zones || ""; sbState.config.zone_type = r.zone_type || "tempo"; }
    sbState.zones_status = r.zones_status || "UNAVAILABLE";
    sbState.zone_fingerprint = r.zone_fingerprint || "";
    melding(r.zones_status === "FRESH" ? "Zones ververst uit FinalSurge."
            : "Zones konden niet vers worden gelezen — laatst bekende zones getoond.", r.zones_status !== "FRESH");
  }
  sbDraftSave();
  // Her-render de HUIDIGE fase; bestaande state blijft ongemoeid (config + workbench-rijen).
  const stage = sbState.stage;
  if (stage === "workbench") sbRenderWorkbench();
  else if (stage === "plan") sbRenderPlan();
  else if (stage === "herijking") sbRenderHerijking();
  else sbRenderConfig();
}

function sbRenderConfig() {
  const c = sbState.config, sel = sbDagenUitString(c.trainingsdagen);
  $("#sb-werk").innerHTML = `
    <button class="btn ghost back" id="sb-terug">${ic("back")} Alle atleten</button>
    ${sbModeBar("nieuw")}
    <div class="sb-context"><div class="sb-ctx-head"><span class="avatar big">${initialen(sbState.naam)}</span>
      <div><h2 class="d-naam">${esc(sbState.naam)}</h2><p class="muted klein">Nieuw schema · instellingen</p></div>${athleteNav("schema", sbState.key)}</div></div>
    <div class="sb-cfg">
      <div class="sb-cfg-grid">
        <div><label class="lbl">Doel</label><textarea id="cfg-doel" rows="2" placeholder="bijv. 10km in sub 50">${esc(c.doel)}</textarea></div>

        <p class="sb-cfg-sec">Periode</p>
        <div class="sb-cfg-row3">
          <div><label class="lbl">Startdatum</label><input type="date" id="cfg-start" value="${esc(c.startdatum)}"></div>
          <div><label class="lbl">Weken</label><input type="number" id="cfg-weken" min="1" max="52" value="${esc(c.weken)}"></div>
          <div><label class="lbl">Einddatum</label><input type="date" id="cfg-eind" value="${esc(c.schema_einddatum || "")}"></div></div>

        <p class="sb-cfg-sec">Hoofddoel <span class="muted klein">— mag ná het schema-einde liggen</span></p>
        <div class="sb-cfg-row2">
          <div><label class="lbl">Wedstrijddatum <span class="muted klein">(doeldatum)</span></label><input type="date" id="cfg-race-datum" value="${esc(c.wedstrijddatum || "")}"></div>
          <div><label class="lbl">Race-prioriteit</label><input type="text" id="cfg-race" placeholder="bijv. A-race" value="${esc(c.race_prioriteit)}"></div></div>
        <div id="cfg-periode-gap">${sbPeriodeGap(c)}</div>

        <p class="sb-cfg-sec">Beschikbaarheid <span class="muted klein">— dagen ≠ sessies/week</span></p>
        <div><label class="lbl">Trainingsdagen</label>
          <div class="sb-dagen" id="cfg-dagen">${SB_DAG.map((d, i) => `<button type="button" class="sb-dag ${sel.includes(i) ? "on" : ""}" data-d="${i}">${d[0].toUpperCase() + d.slice(1)}</button>`).join("")}</div></div>
        <div class="sb-cfg-row2">
          <div><label class="lbl">Sessies per week <span class="muted klein">(optioneel)</span></label><input type="number" id="cfg-sessies" min="1" max="14" placeholder="bijv. 4" value="${esc(c.sessies_per_week || "")}"></div>
          <div></div></div>

        <p class="sb-cfg-sec">Belastbaarheid</p>
        <div class="sb-cfg-row2">
          <div><label class="lbl">Huidig volume</label><input type="text" id="cfg-vol" placeholder="bijv. 25-30 km/week" value="${esc(c.huidig_volume)}"></div>
          <div><label class="lbl">Tijd per training</label><input type="text" id="cfg-tijd" placeholder="bijv. 45-60 min" value="${esc(c.tijd_per_training || "")}"></div></div>

        <p class="sb-cfg-sec">Uitvoerwijze</p>
        <div><label class="lbl">Trainingen plannen op</label>
          <div class="seg sb-uitvoer" id="cfg-uitvoer" data-value="${c.op_tijd ? "tijd" : "afstand"}">
            <button type="button" data-v="afstand" class="${c.op_tijd ? "" : "on"}">Afstand (km)</button>
            <button type="button" data-v="tijd" class="${c.op_tijd ? "on" : ""}">Tijd (minuten)</button></div></div>

        <div><label class="lbl">Coachinstructies</label><textarea id="cfg-notitie" rows="2" placeholder="bijv. rustig opbouwen; meer tempowerk richting 10km">${esc(c.coach_notitie)}</textarea></div>
        <div class="sb-zones"><span class="lbl">Zones · ${esc(c.zone_type || "tempo")} (uit FinalSurge — enige intensiteitsbron) ${sbZoneStatusHtml()}</span>
          <pre class="sb-zonebox">${esc(c.zones || "geen zones gevonden in FinalSurge")}</pre></div>
      </div>
      <aside class="sb-afspraken">
        <p class="sb-afspraken-h">${ic("check")} Schema-afspraken</p>
        <ul id="cfg-afspraken">${sbAfspraken(c).map(a => `<li>${esc(a)}</li>`).join("")}</ul>
        <button class="btn primary block" id="cfg-gen">${ic("brain")} Genereer conceptplan</button>
        <p class="hint" id="cfg-status">BeBetter maakt het conceptplan. Dit kan even duren.</p>
      </aside>
    </div>
    <section class="sb-known">
      <p class="sb-known-h">${ic("brain")} Bekende atleetcontext <span class="muted klein">— wat BeBetter al weet (weegt de AI mee)</span></p>
      <div id="sb-known-body" class="sb-known-body"><p class="muted klein">Context laden…</p></div>
      <p class="hint">Klopt iets niet of ontbreekt het? Voeg het toe bij <b>Coachinstructies</b> hierboven — de AI neemt dat mee. (Dossier-bewerking volgt later.)</p>
    </section>`;
  $("#sb-terug").addEventListener("click", sbBackToList);
  sbWireModeBar();
  $("#scroller").scrollTo({ top: 0 });
  $("#cfg-dagen").querySelectorAll(".sb-dag").forEach(b => b.addEventListener("click", () => { b.classList.toggle("on"); sbSyncConfig(); sbRefreshAfspraken(); sbUpdateGate(); }));
  // Gewone velden: sync + afspraken + gate.
  ["cfg-doel", "cfg-race-datum", "cfg-race", "cfg-sessies", "cfg-vol", "cfg-tijd", "cfg-notitie"].forEach(id =>
    $("#" + id).addEventListener("input", () => { sbSyncConfig(); sbRefreshAfspraken(); sbRefreshPeriodeGap(); sbUpdateGate(); }));
  // Periode (§6): één canonieke server-berekening; het laatst-bewerkte veld leidt.
  $("#cfg-start").addEventListener("input", () => { sbSyncConfig(); sbRecalcPeriode("weken"); });   // start wijzigt → einddatum uit weken
  $("#cfg-weken").addEventListener("input", () => { sbSyncConfig(); sbRecalcPeriode("weken"); });   // weken leidt → einddatum
  $("#cfg-eind").addEventListener("input", () => { sbSyncConfig(); sbRecalcPeriode("eind"); });     // einddatum leidt → weken
  // Uitvoerwijze km/min (§7): zet op_tijd; bestaande build/publish-logica gebruikt dit.
  $("#cfg-uitvoer").querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    const seg = $("#cfg-uitvoer"); seg.dataset.value = b.dataset.v;
    seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    sbState.config.op_tijd = (b.dataset.v === "tijd"); sbSyncConfig(); sbRefreshAfspraken();
  }));
  $("#cfg-gen").addEventListener("click", sbGenPlan);
  sbWireZoneRefresh();                      // PF-2: expliciete verse zone-read
  sbUpdateGate();                          // begintoestand: knop uit tot verplichte velden kloppen
  sbLoadContext(sbState.key);              // 'Bekende atleetcontext' lazy laden
}

// Masterbrein: toon wat BeBetter al over de atleet weet (lazy; leak-safe).
async function sbLoadContext(key) {
  const box = $("#sb-known-body"); if (!box) return;
  const r = await api("/api/schema/context?key=" + encodeURIComponent(key)).catch(() => null);
  if (!$("#sb-known-body") || !sbState || sbState.key !== key) return;   // atleet gewisseld → niet renderen (geen leak)
  if (!r || !r.ok) { box.innerHTML = `<p class="muted klein">Context niet beschikbaar.</p>`; return; }
  if (r.used) sbLog("context_used", r.used);                            // traceability, geen gevoelige tekst
  const secties = r.secties || [];
  box.innerHTML = secties.map(s => `
    <div class="sb-known-sec${s.onbekend ? " leeg" : ""}">
      <p class="sb-known-t">${esc(s.titel)}</p>
      ${s.onbekend ? `<p class="sb-known-onb">onbekend</p>`
                   : `<ul>${s.regels.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`}
    </div>`).join("") || `<p class="muted klein">Nog niets bekend — vul de configuratie in.</p>`;
}

async function sbGenPlan() {
  sbSyncConfig();
  const miss = sbConfigValid(sbState.config);
  if (miss.length) return melding("Vul eerst in: " + miss.join(", ") + ".", true);
  const btn = $("#cfg-gen"); if (btn.disabled) return;
  btn.disabled = true; btn.textContent = "AI bouwt het conceptplan…";
  const st = $("#cfg-status"); st.textContent = "BeBetter maakt het conceptplan. Dit kan even duren — niet nogmaals klikken.";
  const t0 = performance.now();
  const r = await jpost("/api/schema/plan", { key: sbState.key, config: sbState.config }).catch(() => null);
  sbLog("plan_gen", { key: sbState.key, ms: Math.round(performance.now() - t0), ok: !!(r && r.ok) });
  if (!r || !r.ok) { btn.disabled = false; btn.innerHTML = `${ic("brain")} Genereer conceptplan`; st.textContent = ""; return melding(r?.err || "Plan mislukt.", true); }
  if (r.context_blob) sbState.config._context = r.context_blob;   // hergebruik in chat (geen refetch)
  if (r.context) sbState.context = r.context;
  sbState.plan = r.plan || ""; sbState.planEdited = false; sbState.prevPlan = null; sbState.chat = [];
  sbState.stage = "plan"; sbDraftSave();
  sbRenderPlan();
}

// ── Fase 2 — conceptplan (read-first) + AI-sparfase ──────────────────────────
function sbPlanHtml(plan) { return esc(plan || "").replace(/\n/g, "<br>"); }
function sbChatHtml() {
  if (!sbState.chat || !sbState.chat.length)
    return `<p class="sb-chat-empty">Stel een vraag of geef een wijziging — ik pas het hele plan consistent aan.</p>`;
  return sbState.chat.map(m => `<div class="sb-bub ${m.role === "user" ? "me" : "ai"}">${esc(m.content)}${m.updated ? `<span class="sb-bub-tag">plan bijgewerkt</span>` : ""}</div>`).join("");
}
function sbChatScroll() { const l = $("#sb-chat-log"); if (l) l.scrollTop = l.scrollHeight; }

function sbRenderPlan() {
  const doel = (sbState.context && sbState.context.doel) || "conceptplan";
  $("#sb-werk").innerHTML = `
    <button class="btn ghost back" id="sb-terug">${ic("back")} Instellingen</button>
    <div class="sb-context"><div class="sb-ctx-head"><span class="avatar big">${initialen(sbState.naam)}</span>
      <div><h2 class="d-naam">${esc(sbState.naam)}</h2>
        <p class="muted klein">${esc(doel)}${sbState.planEdited ? " · handmatig aangepast" : ""}</p></div>
      ${athleteNav("schema", sbState.key)}
      <button class="btn primary" id="sb-build">${ic("check")} Bouw schema</button></div></div>
    <div class="sb-plan-grid">
      <div class="sb-plan-col">
        <div class="sb-plan-head"><span class="lbl">Conceptplan</span>
          <div class="sb-plan-acts">
            ${sbState.prevPlan ? `<button class="btn ghost sm" id="sb-undo">${ic("refresh")} Undo AI-wijziging</button>` : ""}
            <button class="btn ghost sm" id="sb-edit-toggle">${ic("note")} Handmatig bewerken</button></div></div>
        <div class="sb-plan-read" id="sb-plan-read">${sbPlanHtml(sbState.plan)}</div>
        <textarea class="sb-plan-edit" id="sb-plan-edit" rows="20" hidden>${esc(sbState.plan)}</textarea>
      </div>
      <aside class="sb-chat">
        <p class="sb-chat-h">${ic("brain")} Sparren met je assistent-coach</p>
        <div class="sb-chat-log" id="sb-chat-log">${sbChatHtml()}</div>
        <div class="sb-chat-input">
          <textarea id="sb-chat-ta" rows="2" placeholder="bijv. maak week 4 rustiger, of: meer tempowerk richting 10km"></textarea>
          <button class="btn primary" id="sb-chat-send">${ic("message")} Vraag / wijzig</button></div>
        <p class="hint" id="sb-chat-status"></p>
      </aside>
    </div>`;
  $("#sb-terug").addEventListener("click", () => {
    if (sbState.mode === "verlengen") { sbState.stage = "herijking"; sbDraftSave(); return sbRenderHerijking(); }
    sbState.stage = "config"; sbDraftSave(); sbRenderConfig();
  });
  $("#sb-build").addEventListener("click", sbBuildSchema);
  $("#sb-edit-toggle").addEventListener("click", sbToggleManualEdit);
  $("#sb-chat-send").addEventListener("click", sbChatSend);
  if (sbState.prevPlan) $("#sb-undo").addEventListener("click", sbUndoPlan);
  $("#scroller").scrollTo({ top: 0 });
  sbChatScroll();
}

function sbToggleManualEdit() {
  const read = $("#sb-plan-read"), edit = $("#sb-plan-edit");
  if (edit.hidden) { edit.hidden = false; read.hidden = true; edit.value = sbState.plan; edit.focus(); }
  else {
    if (edit.value !== sbState.plan) { sbState.plan = edit.value; sbState.planEdited = true; sbDraftSave(); }
    sbRenderPlan();                                // toont edited-markering + read-view
  }
}
function sbUndoPlan() {
  if (!sbState.prevPlan) return;
  sbState.plan = sbState.prevPlan; sbState.prevPlan = null; sbState.planEdited = false;
  sbState.chat.push({ role: "assistant", content: "Laatste AI-wijziging teruggedraaid." });
  sbDraftSave(); sbRenderPlan();
}

async function sbChatSend() {
  const ta = $("#sb-chat-ta"), tekst = (ta.value || "").trim();
  if (!tekst) return;
  const send = $("#sb-chat-send"); if (send.disabled) return;
  send.disabled = true; ta.disabled = true;
  sbState.chat.push({ role: "user", content: tekst });
  $("#sb-chat-log").innerHTML = sbChatHtml(); sbChatScroll(); ta.value = "";
  const st = $("#sb-chat-status"); st.textContent = "De assistent-coach denkt na…";
  const hist = sbState.chat.map(m => ({ role: m.role, content: m.content }));
  const t0 = performance.now();
  const r = await jpost("/api/schema/chat", { key: sbState.key, config: sbState.config, plan: sbState.plan, history: hist }).catch(() => null);
  sbLog("chat", { key: sbState.key, ms: Math.round(performance.now() - t0), ok: !!(r && r.ok), updated: !!(r && r.plan_updated) });
  send.disabled = false; ta.disabled = false; st.textContent = "";
  if (!r || !r.ok) {                              // fout → plan blijft intact, retry mogelijk
    sbState.chat.push({ role: "assistant", content: (r && r.err) || "Er ging iets mis — probeer het opnieuw." });
    $("#sb-chat-log").innerHTML = sbChatHtml(); sbChatScroll(); sbDraftSave(); return;
  }
  const msg = { role: "assistant", content: r.reply || "Oké." };
  if (r.plan_updated && r.plan) {
    sbState.prevPlan = sbState.plan;             // één-staps undo
    sbState.plan = r.plan; sbState.planEdited = false; msg.updated = true;
    if (r.truncated) msg.content += " (⚠️ respons afgekapt — vraag zo nodig ‘ga verder’.)";
  }
  sbState.chat.push(msg); sbDraftSave();
  sbRenderPlan();                                 // plan-update + chat atomair zichtbaar
}

async function sbBuildSchema() {
  const edit = $("#sb-plan-edit");
  if (edit && !edit.hidden && edit.value !== sbState.plan) { sbState.plan = edit.value; sbState.planEdited = true; }
  // Plan inhoudelijk ongewijzigd sinds de laatste build → hergebruik de bestaande
  // workbench (geen generate_csv), met behoud van edits/include/selectie/state.
  const cur = sbPlanHash(), heeftRows = !!(sbState.weken && sbState.weken.length);
  const reuse = heeftRows && sbState.built_plan_hash === cur;
  sbLog("build_decision", { rows: heeftRows ? sbState.weken.length : 0,
    stored: sbState.built_plan_hash || null, current: cur, equal: sbState.built_plan_hash === cur,
    branch: reuse ? "reuse" : "rebuild" });
  if (reuse) { sbState.stage = "workbench"; sbDraftSave(); sbRenderWorkbench(); haptic(8); return; }
  const btn = $("#sb-build"); if (btn.disabled) return;
  btn.disabled = true; btn.textContent = "Schema opbouwen…";
  const st = $("#sb-chat-status"); if (st) st.textContent = "De weken worden opgebouwd. Dit kan even duren…";
  const t0 = performance.now();
  const r = await jpost("/api/schema/csv", { key: sbState.key, config: sbState.config, plan: sbState.plan }).catch(() => null);
  sbLog("csv_gen", { key: sbState.key, ms: Math.round(performance.now() - t0), ok: !!(r && r.ok), n: ((r && r.rijen) || []).length });
  if (!r || !r.ok) { btn.disabled = false; btn.innerHTML = `${ic("check")} Bouw schema`; if (st) st.textContent = ""; return melding(r?.err || "Schema mislukt.", true); }
  sbEnterWorkbench(r); haptic(15);
}

// ══ Fase 4 — veilige publicatie naar FinalSurge (preview → expliciete write) ══
// Enige write-input = de actuele workbench-rows (included + edits). Geen optimistic
// success; UI-status volgt de backend. Idempotent via een stabiel write_id.
const SB_PUB_STAT = { nieuw: "Nieuw", bestaande_op_datum: "Bestaande training op deze datum",
  mogelijk_duplicaat: "Mogelijk duplicaat" };
const SB_RES_STAT = { success: "Gepubliceerd", failed: "Mislukt",
  builder_failed: "Gepubliceerd — WorkoutBuilder mislukt" };

// PF-1: is de numerieke meetwaarde (km/min) handmatig gewijzigd t.o.v. de
// gegenereerde waarde? Dan is de ingediende waarde autoritatief voor de FinalSurge-
// write (geen her-afleiding uit de description). Losser dan `edited` (die ook op
// naam/beschrijving vlagt) — alleen een échte km/min-wijziging telt hier.
function sbMeasureEdited(r) {
  const o = r._orig || {};
  return r.planned_km !== (o.planned_km ?? null) || r.planned_min !== (o.planned_min ?? null);
}

function sbRowsPayload() {                            // exacte, actuele rows (incl. edits + include-state)
  const out = [];
  sbState.weken.forEach(w => w.rows.forEach(r => out.push({
    id: r.id, included: !!r.included, edited: !!r.edited, measure_edited: sbMeasureEdited(r),
    date: r.date, activity_type: r.activity_type, name: r.name,
    planned_km: r.planned_km, planned_min: r.planned_min, description: r.description,
  })));
  return out;
}

async function sbPublishPreview() {
  sbState.publish = { write_id: "w" + Date.now() + Math.random().toString(36).slice(2, 8),
    state: "checking", results: null, acked: false };
  sbState.stage = "publish"; sbDraftSave();
  $("#sb-werk").innerHTML = `<button class="btn ghost back" id="sb-pub-back">${ic("back")} Terug naar schema</button>
    <p class="hint">Publicatie controleren — bestaande FinalSurge-planning wordt gecheckt…</p>`;
  $("#sb-pub-back").addEventListener("click", sbPublishBack);
  const r = await jpost("/api/schema/publish/preview",
    { key: sbState.key, config: sbState.config, rows: sbRowsPayload() }).catch(() => null);
  if (!sbState || sbState.stage !== "publish") return;          // weg genavigeerd → niet renderen
  if (!r || !r.ok) { melding(r?.err || "Preview mislukt.", true); return sbPublishBack(); }
  sbState.publish.preview = r; sbState.publish.state = r.valid ? "ready" : "error";
  sbDraftSave(); sbRenderPublish();
}
function sbPublishBack() { sbState.stage = "workbench"; sbDraftSave(); sbRenderWorkbench(); }

function sbRenderPublish() {
  const p = sbState.publish, pv = p.preview || {}, c = pv.counts || {}, dr = pv.date_range;
  const resById = {}; (p.results || []).forEach(x => resById[x.id] = x);
  const done = p.state === "success" || p.state === "partial_failure";
  const inc = [];
  sbState.weken.forEach(w => w.rows.forEach(r => { if (r.included) inc.push(r); }));

  const rijHtml = (pv.items || []).map(it => {
    const res = resById[it.id];
    const label = res ? (SB_RES_STAT[res.status] || res.status) : (SB_PUB_STAT[it.status] || it.status);
    const cls = res ? (res.status === "failed" ? "fail" : (res.status === "builder_failed" ? "warn" : "ok"))
                    : (it.status === "nieuw" ? "" : "warn");
    const meta = it.planned_km != null ? `${it.planned_km} km` : (it.planned_min != null ? `${it.planned_min} min` : "");
    return `<div class="sb-pub-row">
      <span class="sb-row-day">${sbDagDatum(it.date)}</span>
      <span class="sb-row-ic">${sbTypeIc(it.activity_type)}</span>
      <span class="sb-row-name">${esc(it.name)}</span>
      <span class="sb-row-meta">${esc(meta)}</span>
      <span class="sb-pub-stat ${cls}">${esc(label)}${res && res.err ? ` · ${esc(res.err)}` : ""}</span>
    </div>`;
  }).join("");

  let cta = "", banner = "";
  if (p.state === "error") {
    banner = `<div class="sb-pub-banner fail">${(pv.errors || []).map(e => esc(e)).join("<br>")}</div>`;
  } else if (p.state === "writing") {
    cta = `<button class="btn primary block" id="sb-pub-go" disabled>${p.progress || "Publiceren…"}</button>`;
  } else if (p.state === "success") {
    banner = `<div class="sb-pub-banner ok">${ic("check")} ${p.counts.success} trainingen gepubliceerd naar FinalSurge` +
      `${dr ? ` (${esc(dr.van)} – ${esc(dr.tot)})` : ""}.` +
      `${p.counts.builder_failed ? ` ${p.counts.builder_failed}× WorkoutBuilder-detail mislukt (trainingen staan er wel).` : ""}</div>`;
    cta = `<div class="sb-tools"><button class="btn ghost" id="sb-pub-workbench">${ic("back")} Terug naar schema</button>
      <button class="btn ghost" id="sb-pub-list">${ic("back")} Alle atleten</button>
      <button class="btn" id="sb-pub-new">${ic("plus")} Nieuwe planning starten</button></div>`;
  } else if (p.state === "partial_failure") {
    banner = `<div class="sb-pub-banner warn">${p.counts.success} gepubliceerd · ${p.counts.failed} mislukt. ` +
      `De succesvolle trainingen staan al in FinalSurge; retry stuurt alleen de mislukte opnieuw.</div>`;
    cta = `<div class="sb-tools"><button class="btn primary" id="sb-pub-retry">${ic("refresh")} Probeer ${p.counts.failed} mislukte opnieuw</button>
      <button class="btn ghost" id="sb-pub-workbench">${ic("back")} Terug naar schema</button></div>`;
  } else {  // ready
    const conflicts = c.conflicts || 0;
    const ackHtml = conflicts
      ? `<label class="sb-pub-ack"><input type="checkbox" id="sb-pub-ack"> Ik heb de ${conflicts} aandachtspunten (bestaande/duplicaat) gecontroleerd en wil toch publiceren.</label>`
      : "";
    banner = conflicts
      ? `<div class="sb-pub-banner warn">Let op: ${conflicts} van de ${c.included} trainingen vallen op een datum met een bestaande FinalSurge-training. Bestaande trainingen worden NIET overschreven of verwijderd — je voegt toe.</div>`
      : `<div class="sb-pub-banner ok">${c.included} trainingen klaar om toe te voegen. Geen conflicten met bestaande planning gevonden.</div>`;
    cta = ackHtml + `<button class="btn primary block" id="sb-pub-go"${conflicts ? " disabled" : ""}>${ic("check")} Publiceer ${c.included} trainingen naar FinalSurge</button>`;
  }

  $("#sb-werk").innerHTML = `
    <button class="btn ghost back" id="sb-pub-back">${ic("back")} Terug naar schema</button>
    <div class="sb-context"><div class="sb-ctx-head"><span class="avatar big">${initialen(sbState.naam)}</span>
      <div><h2 class="d-naam">${esc(sbState.naam)}</h2><p class="muted klein">Publiceren naar FinalSurge</p></div>${athleteNav("schema", sbState.key)}</div>
      <div class="sb-chips">
        <span class="sb-chip">${c.included || 0} publiceren</span>
        ${c.excluded ? `<span class="sb-chip">${c.excluded} uitgesloten</span>` : ""}
        ${c.edited ? `<span class="sb-chip">${c.edited} aangepast</span>` : ""}
        ${c.conflicts ? `<span class="sb-chip warn">${c.conflicts} let op</span>` : ""}
        ${c.builder ? `<span class="sb-chip">${c.builder} met WorkoutBuilder</span>` : ""}
        ${dr ? `<span class="sb-chip">${esc(dr.van)} – ${esc(dr.tot)}</span>` : ""}
      </div>
    </div>
    ${banner}
    <div class="sb-pub-list">${rijHtml}</div>
    <div class="sb-pub-cta">${cta}</div>`;
  $("#sb-pub-back").addEventListener("click", () => { if (p.state !== "writing") sbPublishBack(); });
  const ack = $("#sb-pub-ack");
  if (ack) ack.addEventListener("change", () => { const g = $("#sb-pub-go"); if (g) g.disabled = !ack.checked; });
  $("#sb-pub-go")?.addEventListener("click", () => sbDoPublish(inc));
  $("#sb-pub-retry")?.addEventListener("click", () => sbDoPublish(inc.filter(r => (resById[r.id] || {}).status === "failed")));
  $("#sb-pub-workbench")?.addEventListener("click", sbPublishBack);
  $("#sb-pub-list")?.addEventListener("click", () => { sbState = null; laadSchema(); });
  $("#sb-pub-new")?.addEventListener("click", () => { const k = sbState.key, n = sbState.naam, m = sbState.mode; sbDraftClear(k, m); sbState = null; schemaWerk({ key: k, naam: n }, m); });
  $("#scroller").scrollTo({ top: 0 });
}

// Irreversibele write-state-machine. Publiceert in batches → echte teller; idempotent
// via het stabiele write_id (server slaat al-geschreven rijen over). Backend = waarheid.
async function sbDoPublish(rowsToWrite) {
  const p = sbState.publish;
  if (p.state === "writing") return;                 // single-submit
  const rows = (rowsToWrite || []).map(r => ({
    id: r.id, included: true, edited: !!r.edited, date: r.date, activity_type: r.activity_type,
    name: r.name, planned_km: r.planned_km, planned_min: r.planned_min, description: r.description,
  }));
  if (!rows.length) return;
  p.state = "writing"; p.progress = `Publiceren 0 / ${rows.length}…`; sbRenderPublish();
  const BATCH = 8;
  const merged = {}; (p.results || []).forEach(x => merged[x.id] = x);   // behoud eerdere successen
  let written = 0, hardError = false;
  for (let i = 0; i < rows.length; i += BATCH) {
    const chunk = rows.slice(i, i + BATCH);
    const r = await jpost("/api/schema/publish",
      { key: sbState.key, config: sbState.config, rows: chunk, write_id: p.write_id }).catch(() => null);
    if (!r || !r.ok) { hardError = true; melding(r?.err || "Publiceren mislukt.", true); break; }
    (r.results || []).forEach(x => merged[x.id] = x);
    written += chunk.length;
    p.progress = `Publiceren ${Math.min(written, rows.length)} / ${rows.length}…`;
    const go = $("#sb-pub-go"); if (go) go.textContent = p.progress;
  }
  p.results = Object.values(merged);
  const fail = p.results.filter(x => x.status === "failed").length;
  const ok = p.results.filter(x => x.status === "success" || x.status === "builder_failed").length;
  const bf = p.results.filter(x => x.status === "builder_failed").length;
  p.counts = { success: ok, failed: fail, builder_failed: bf };
  p.state = hardError ? "partial_failure" : (fail ? "partial_failure" : "success");
  sbLog("publish", { key: sbState.key, success: ok, failed: fail, builder_failed: bf });
  sbDraftSave(); sbRenderPublish(); haptic(fail ? 30 : 20);
}

// ── Fase 3 — bestaande Slice-1 workbench (rows uit de actuele planversie) ─────
function sbEnterWorkbench(r) {
  sbState.weken = (r.weken || []).map(w => ({
    week_index: w.week_index, label: w.label, datumrange: w.datumrange, week_start: w.week_start,
    rows: (w.rows || []).map(row => ({
      id: row.id, date: row.date, activity_type: row.activity_type || "Run", name: row.name || "",
      planned_km: row.planned_km ?? null, planned_min: row.planned_min ?? null, description: row.description || "",
      included: true, edited: false,
      _orig: { name: row.name || "", planned_km: row.planned_km ?? null, planned_min: row.planned_min ?? null, description: row.description || "" },
    })),
  }));
  sbState.csv = r.csv || "";
  if (r.context) sbState.context = r.context;
  sbState.selectedWeek = sbState.weken[0] ? sbState.weken[0].week_index : null;
  sbState.openRow = null; sbState.stage = "workbench";
  sbState.built_plan_hash = sbPlanHash();              // deze rows horen bij dit plan (genormaliseerd)
  sbDraftSave();
  sbRenderWorkbench();
}

// Fase B — de workbench zelf.
function sbRenderWorkbench() {
  const ctx = sbState.context || {};
  $("#sb-werk").innerHTML = `
    <button class="btn ghost back" id="sb-terug">${ic("back")} Alle atleten</button>
    <div class="sb-context">
      <div class="sb-ctx-head"><span class="avatar big">${initialen(sbState.naam)}</span>
        <div><h2 class="d-naam">${esc(sbState.naam)}</h2>
          <p class="muted klein">${ctx.doel ? esc(ctx.doel) : "nieuw schema"}</p></div>
        ${athleteNav("schema", sbState.key)}</div>
      <div class="sb-chips">
        <span class="sb-chip">🆕 nieuw</span>
        ${ctx.weken ? `<span class="sb-chip">${esc(String(ctx.weken))} weken</span>` : ""}
        ${ctx.trainingsdagen ? `<span class="sb-chip">${esc(ctx.trainingsdagen)}</span>` : ""}
        <span class="sb-chip">zones · ${esc((sbState.config && sbState.config.zone_type) || ctx.zone_bron || "tempo")}</span>
        <span class="sb-chip sb-chip-sel"></span>
      </div>
      <div class="sb-zone-fresh klein muted">Zones ${sbZoneStatusHtml()}</div>
    </div>
    <div class="sb-grid">
      <div class="sb-master">
        <div class="sb-weeknav" id="sb-weeknav" hidden></div>
        <div class="sb-weeks" id="sb-weeks"></div>
        <div class="sb-tools">
          <button class="btn primary" id="sb-publish">${ic("check")} Controleer publicatie</button>
          <button class="btn ghost" id="sb-replan">${ic("back")} Plan aanpassen</button>
          <button class="btn ghost" id="sb-download">${ic("download")} Download CSV</button>
        </div>
      </div>
      <aside class="sb-detail" id="sb-detail"></aside>
    </div>
    <div class="sb-focus" id="sb-focus" hidden></div>`;
  $("#sb-terug").addEventListener("click", () => { sbState = null; laadSchema(); });
  $("#sb-publish").addEventListener("click", sbPublishPreview);
  $("#sb-download").addEventListener("click", sbDownload);
  $("#sb-replan").addEventListener("click", () => { sbState.stage = "plan"; sbDraftSave(); sbRenderPlan(); });
  $("#scroller").scrollTo({ top: 0 });
  sbWasDesktop = isDesktop();
  sbWireZoneRefresh();                      // PF-2: expliciete verse zone-read (workbench)
  sbRenderWeeks();
  sbRenderDetail();
  sbUpdateChips();
}

function sbFindRow(id) { for (const w of sbState.weken) { const r = w.rows.find(x => x.id === id); if (r) return r; } return null; }
function sbWeekVanRow(id) { return sbState.weken.find(w => w.rows.some(r => r.id === id)); }

function sbRenderWeeks() {
  const host = $("#sb-weeks"), nav = $("#sb-weeknav"); if (!host) return;
  const desktop = isDesktop();
  if (desktop || sbState.weken.length <= 1) { nav.hidden = true; }
  else {
    nav.hidden = false;
    nav.innerHTML = sbState.weken.map(w =>
      `<button class="sb-weekchip ${w.week_index === sbState.selectedWeek ? "on" : ""}" data-wk="${w.week_index}">${esc(w.label)}</button>`).join("");
    nav.querySelectorAll(".sb-weekchip").forEach(b => b.addEventListener("click", () => {
      sbState.selectedWeek = +b.dataset.wk; sbDraftSave(); sbRenderWeeks();
    }));
  }
  const weken = desktop ? sbState.weken : sbState.weken.filter(w => w.week_index === sbState.selectedWeek);
  host.innerHTML = weken.map(sbWeekHtml).join("") || `<p class="muted center">Geen trainingen herkend.</p>`;
  host.querySelectorAll("[data-row]").forEach(el => el.addEventListener("click", e => {
    if (e.target.closest(".sb-inc")) return; sbOpenRow(el.dataset.row);
  }));
  host.querySelectorAll(".sb-inc").forEach(el => el.addEventListener("click", e => {
    e.stopPropagation(); sbToggleInclude(el.dataset.inc);
  }));
}

function sbWeekHtml(w) {
  const km = w.rows.filter(r => r.included).reduce((s, r) => s + (r.planned_km || 0), 0);
  const kmStr = km ? `<span class="sb-week-km">${Math.round(km)} km</span>` : "";
  return `<section class="sb-week">
    <div class="sb-week-h"><span class="sb-week-t">${esc(w.label)}</span>
      ${w.datumrange ? `<span class="sb-week-sub">${esc(w.datumrange)}</span>` : ""}${kmStr}</div>
    <div class="sb-rows">${w.rows.map(sbRowHtml).join("")}</div>
  </section>`;
}

function sbRowHtml(r) {
  const meta = r.planned_km != null ? `${r.planned_km} km` : (r.planned_min != null ? `${r.planned_min} min` : "");
  return `<div class="sb-row ${r.included ? "" : "excl"} ${sbState.openRow === r.id ? "open" : ""}" data-row="${r.id}">
    <button class="sb-inc ${r.included ? "on" : ""}" data-inc="${r.id}" aria-label="Meenemen of uitsluiten">${r.included ? ic("check") : ""}</button>
    <span class="sb-row-day">${sbDagDatum(r.date)}</span>
    <span class="sb-row-ic">${sbTypeIc(r.activity_type)}</span>
    <span class="sb-row-name">${esc(r.name)}${r.edited ? `<span class="sb-edit-dot" title="handmatig aangepast"></span>` : ""}</span>
    <span class="sb-row-meta">${esc(meta)}</span>
  </div>`;
}

function sbOpenRow(id) { sbState.openRow = id; sbDraftSave(); if (isDesktop()) { sbRenderWeeks(); sbRenderDetail(); } else sbRenderFocus(); }
function sbCloseDetail() { sbState.openRow = null; sbDraftSave(); const f = $("#sb-focus"); if (f) { f.hidden = true; f.innerHTML = ""; } sbRenderWeeks(); sbRenderDetail(); }

function sbRenderDetail() {
  const host = $("#sb-detail"); if (!host) return;
  if (!isDesktop()) { host.innerHTML = ""; return; }        // mobiel gebruikt de focus-overlay
  const r = sbState.openRow ? sbFindRow(sbState.openRow) : null;
  if (!r) { host.innerHTML = `<div class="sb-detail-empty">${ic("note")}<p>Kies een training om te bekijken of aan te passen.</p></div>`; return; }
  host.innerHTML = sbEditHtml(r);
  sbBindEdit(host, r);
}

function sbRenderFocus() {
  const r = sbState.openRow ? sbFindRow(sbState.openRow) : null;
  const f = $("#sb-focus"); if (!f) return;
  if (!r) { f.hidden = true; f.innerHTML = ""; return; }
  f.hidden = false;
  f.innerHTML = `<div class="sb-focus-in">
    <button class="btn ghost back" id="sb-focus-back">${ic("back")} Terug naar week</button>
    ${sbEditHtml(r)}</div>`;
  f.querySelector("#sb-focus-back").addEventListener("click", sbCloseDetail);
  sbBindEdit(f, r);
}

function sbEditHtml(r) {
  const showKm = r.planned_km != null || ["Run", "Bike", "Swim"].includes(r.activity_type);
  const showMin = r.planned_min != null;
  return `<div class="sb-edit">
    <div class="sb-edit-h"><span class="sb-row-ic big">${sbTypeIc(r.activity_type)}</span>
      <p class="sb-edit-day">${sbDagDatum(r.date)} · ${esc(r.activity_type)}</p>
      <label class="sb-edit-inc"><input type="checkbox" data-ef="included" ${r.included ? "checked" : ""}> meenemen</label></div>
    <label class="lbl">Naam</label>
    <input type="text" data-ef="name" value="${esc(r.name)}">
    ${showKm ? `<label class="lbl">Afstand (km)</label><input type="number" step="0.1" inputmode="decimal" data-ef="planned_km" value="${r.planned_km != null ? r.planned_km : ""}">` : ""}
    ${showMin ? `<label class="lbl">Duur (min)</label><input type="number" step="1" inputmode="numeric" data-ef="planned_min" value="${r.planned_min != null ? r.planned_min : ""}">` : ""}
    <label class="lbl">Beschrijving</label>
    <textarea data-ef="description" rows="5">${esc(r.description)}</textarea>
    <button class="btn ghost sb-revert ${r.edited ? "" : "hidden"}" data-revert="${r.id}">${ic("refresh")} Herstel naar gegenereerd</button>
  </div>`;
}

function sbBindEdit(root, r) {
  root.querySelectorAll("[data-ef]").forEach(el => {
    const f = el.dataset.ef;
    el.addEventListener(el.type === "checkbox" ? "change" : "input", () => {
      if (f === "included") { r.included = el.checked; sbDraftSave(); sbRenderWeeks(); sbUpdateChips(); return; }
      let v = el.value;
      if (f === "planned_km" || f === "planned_min") { v = v.trim() === "" ? null : parseFloat(v); if (v != null && isNaN(v)) v = null; }
      r[f] = v;
      sbMarkEdited(r);
      root.querySelector(".sb-revert")?.classList.toggle("hidden", !r.edited);
      sbDebouncedSave();
      sbRenderWeeks();            // aparte subtree → focus in dit veld blijft behouden
    });
  });
  root.querySelector("[data-revert]")?.addEventListener("click", () => sbRevert(r));
}

function sbMarkEdited(r) {
  const o = r._orig || {};
  r.edited = r.name !== o.name || r.planned_km !== o.planned_km || r.planned_min !== o.planned_min || r.description !== o.description;
}
function sbRevert(r) {
  const o = r._orig || {};
  r.name = o.name; r.planned_km = o.planned_km; r.planned_min = o.planned_min; r.description = o.description; r.edited = false;
  sbDraftSave(); sbRenderWeeks(); if (isDesktop()) sbRenderDetail(); else sbRenderFocus();
}
function sbToggleInclude(id) {
  const r = sbFindRow(id); if (!r) return;
  r.included = !r.included; sbDraftSave(); sbRenderWeeks(); sbUpdateChips();
  if (isDesktop() && sbState.openRow === id) sbRenderDetail();
  haptic(8);
}
function sbUpdateChips() {
  const el = $(".sb-chip-sel"); if (!el) return;
  const total = sbState.weken.reduce((n, w) => n + w.rows.length, 0);
  const incl = sbState.weken.reduce((n, w) => n + w.rows.filter(r => r.included).length, 0);
  el.textContent = `${incl}/${total} geselecteerd`;
}

// Download reflecteert edits + includes (rows = canonieke bron). GEEN write.
function sbDownload() {
  const q = s => { s = String(s ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const lines = ["Date,ActivityType,WorkoutName,PlannedTimeMinutes,PlannedDistance,mi/km/m/y,WorkoutDescription"];
  sbState.weken.forEach(w => w.rows.forEach(r => { if (!r.included) return;
    lines.push([r.date, r.activity_type, q(r.name), r.planned_min ?? "", r.planned_km ?? "", "km", q(r.description)].join(",")); }));
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  const dl = document.createElement("a"); dl.href = url; dl.download = `Schema - ${sbState.naam}.csv`;
  document.body.appendChild(dl); dl.click(); dl.remove(); URL.revokeObjectURL(url);
}

// Breakpoint-wissel: layout opnieuw kiezen zonder state te verliezen.
let sbWasDesktop = null;
window.addEventListener("resize", () => {
  if (!sbState || huidigeView !== "schema" || !$("#sb-weeks")) return;
  const d = isDesktop(); if (d === sbWasDesktop) return;
  sbWasDesktop = d;
  sbRenderWeeks(); sbRenderDetail();
  const f = $("#sb-focus");
  if (f) { if (d) { f.hidden = true; f.innerHTML = ""; } else if (sbState.openRow) sbRenderFocus(); }
});
// Schema-refresh behoudt de ACTIEVE atleet + workbench (live-fix #9): ververst de
// roster, maar heropent daarna dezelfde athlete-workbench in dezelfde modus met de
// draft intact (PF-1). Geen actieve workbench → gewoon de lijst verversen.
bindRefresh("sb-refresh", async () => {
  const st = sbState;
  if (st && st.key) sbDraftSave();                 // flush vóór reload (PF-1)
  geladen.schema = true;
  await laadSchema();
  if (st && st.key) {
    const a = (schemaAtleten || []).find(x => x.key === st.key);
    if (a) schemaWerk(a, st.mode);                  // zelfde atleet + modus terug, draft-restore
  }
});

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
bindRefresh("rc-refresh", () => { geladen.races = true; return laadRaces(); });

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
  el.dataset.uk = it.user_key || "";                 // doel voor Home-deeplink (flash)
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
    ${it.verborgen ? `<p class="muted klein">${it.verborgen} training(en) nog verborgen voor de atleet${it.zichtbaar_tot ? " · zichtbaar t/m " + esc(it.zichtbaar_tot) : ""}</p>` : ""}
    ${it.user_key ? `<div class="sv-acts"><button class="btn ghost small" data-open-schema>${ic("clock")} Schema openen</button></div>` : ""}`;
  // Cohesion (§8): vanuit schema-verloop direct naar de Schema-workbench van DEZE
  // atleet — geen algemene picker, dezelfde canonical user_key via het contract.
  if (it.user_key) el.querySelector("[data-open-schema]").addEventListener("click",
    () => openAthleteModule("schema", it.user_key));
  return el;
}
bindRefresh("sv-refresh", () => { geladen["schema-verloop"] = true; return laadSchemaVerloop(); });

// ════════════════════════════════════════════════════════════════════════════
// TEAMPULS — belasting-signalen (gezien/dossier) + AI-weekbriefing
// ════════════════════════════════════════════════════════════════════════════
async function laadTeampuls(force = false) {
  const box = $("#tp-signalen"), info = $("#tp-info");
  info.textContent = force ? "Belasting-signalen herberekenen (alle atleten)…" : "Belasting-signalen laden…";
  skeleton(box, 3);
  // Coach Read Performance v1: briefing PARALLEL starten (onafhankelijk van signalen —
  // niet serieel erna) en signalen als FAST READ tonen (bestaande stand direct, geen
  // 30-45s recompute op page-open). Is de stand STALE-but-valid of nog niet berekend,
  // dan haalt de client de verse stand op de achtergrond op en reconcilieert.
  laadBriefing(force);
  const r = await api(`/api/teampuls/signalen${force ? "?force=true" : ""}`).catch(() => null);
  if (!tpRenderSignalen(r, force)) return;
  if (!force && r && (r.stale || r.pending)) {
    api("/api/teampuls/signalen?force=true")
      .then(fresh => { if (fresh && fresh.fs) tpRenderSignalen(fresh, true); })
      .catch(() => {});
  }
}

// Rendert de signalen-lijst + info-kop uit een payload; herbruikbaar voor de fast-read
// én de achtergrond-reconcile. Geeft false terug bij een terminale toestand (geen
// verbinding / niet gekoppeld) zodat de aanroeper stopt.
function tpRenderSignalen(r, isFresh) {
  const box = $("#tp-signalen"), info = $("#tp-info");
  if (!box || !info) return false;
  if (!r) { info.textContent = ""; box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return false; }
  if (!r.fs) { info.textContent = "FinalSurge nog niet gekoppeld."; box.innerHTML = ""; return false; }
  genMount("#tp-genbar", r.generation);                    // v2: gedeelde generation-coherentie
  if (r.pending && !isFresh) {
    // Nog geen opgeslagen stand → laat de skeletons staan; de force-reconcile vult ze.
    info.textContent = "Belasting-signalen worden voor het eerst berekend…";
    return true;
  }
  const items = r.items || [];
  // ÉÉN productcontract Teampuls vs Home (§8 / finding #5 — geen twee waarheden, wél
  // twee projecties): TEAMPULS = observatie/monitoring van trainingsBELASTING over het
  // HELE team (volume/gevoel/RPE/notities), toont ook wat je al zag. HOME = jouw actuele
  // ACTIElijst (compliance + aflopend schema + belasting) en verbergt wat je afvinkte
  // (gezien/later). Daarom kan een atleet met hoge belasting hier staan zonder op Home te
  // staan: óf het is geen Home-actiebron (bv. losse klacht), óf je handelde het al af.
  // De brug van observatie → actie is de 'Dossier →'-knop per kaart (zelfde atleet).
  const versLabel = (!r.vers && r.datum) ? ` · <span class="muted klein">stand ${esc(r.datum)} · verversen…</span>` : "";
  info.innerHTML = `Belasting-monitoring — teambrede observatie uit volume, gevoel, RPE en notities. Dit is niet je Home-actielijst: een atleet kan hier staan zonder een openstaande Home-actie (al afgehandeld, of geen actiebron). Handel af via <b>Dossier →</b>. `
    + (items.length ? `<b>${r.hoog || 0}</b> hoge belasting · <b>${items.length}</b> in beeld · ${esc(r.datum || "")}${versLabel}` : `alles binnen de marge · ${esc(r.datum || "")}${versLabel}`);
  box.innerHTML = "";
  if (!items.length) { box.innerHTML = `<div class="leeg">${ic("check")}<p>Geen belasting-signalen — iedereen binnen de marge.</p></div>`; }
  else items.forEach(it => box.appendChild(pulsItem(it)));
  return true;
}

function pulsItem(it) {
  const el = document.createElement("article");
  el.className = "rij-kaart puls-kaart " + (it.ernst === "hoog" ? "ernst-hoog" : "ernst-let");
  el.dataset.uk = it.user_key || "";                 // doel voor Home-deeplink (flash)
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
  // Cohesion-fix: open het dossier van DEZE atleet i.p.v. de algemene atletenlijst
  // (de user_key was al bekend maar werd weggegooid). Via het canonieke contract.
  el.querySelector("[data-dossier]").addEventListener("click", () => openAthleteModule("atleten", it.user_key));
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
bindRefresh("tp-refresh", () => laadTeampuls(true));

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
bindRefresh("ad-refresh", async () => {
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
// ════════════════════════════════════════════════════════════════════════════
// DOSSIER FASE B — read-only Masterbrein-cockpit (view "dossier")
// Leeslaag op Masterbrein V2: Z0 statuskop · Z1 aandacht · Z2 recent veranderd ·
// Z3 dynamische domeinen · Z4 tijdlijn (capture OFF → eerlijke empty) · Z5 lichte
// provenance + "Waarom?". Strikt read-only; geen writes, geen edits. Zie
// dossier-fase-b-cockpit-design.md.
// ════════════════════════════════════════════════════════════════════════════
let dcPicker = null, dcCache = [], dcSel = "", dcOpenPending = "", dcGroepVolgorde = [];
const dcLog = (ev, data) => { try { console.debug("[dossier]", ev, data || ""); } catch {} };

const _DC_OVERALL = { GOOD: "Goed", STABLE: "Stabiel", ATTENTION: "Aandacht", INSUFFICIENT_DATA: "Te weinig data" };
const _DC_TRUTH = { ATHLETE_REPORTED: "atleet-gemeld", COACH_REPORTED: "coach-gemeld",
  DERIVED: "afgeleid", FACT: "feit", AI_INTERPRETATION: "AI-duiding", UNKNOWN: "onbekend" };
const _DC_KIND_IC = { complaint: "alert", load_signal: "pulse", possible_relation: "pulse",
  zone_review: "brain", recovery_neg: "clock", conflict: "alert", source_gap: "alert" };

function dcToonLijst() {
  const v = $('.view[data-view="dossier"]');
  if (v) v.classList.toggle("has-athlete", !!dcSel);
  $("#dc-lijst").hidden = false;
  const lijst = $(".view[data-view='dossier'] .md-list");
  // Met een open atleet is de athlete-lijst geen visueel fundament meer: het dossier
  // vult het canvas en wisselen gaat via de compacte switcher. Zonder open atleet is
  // de lijst juist de hoofdingang.
  if (!dcPicker) { /* roster nog niet geladen — laat staan wat er staat */ }
  else if (dcSel) { lijst.hidden = true; $("#dc-detail").hidden = false; }
  else { lijst.hidden = false; $("#dc-detail").hidden = true; }
}

$("#dc-switch")?.addEventListener("click", () => dcOpenSwitcher());
function dcOpenSwitcher() {
  if (!dcCache.length) { laadDossierCockpit(); return; }
  openAthletePickerOverlay({
    title: "Wissel van atleet", confirmLabel: "Openen", placeholder: "Zoek atleet",
    items: dcCache.map(a => ({ ...a, key: a.id })), groupOrder: dcGroepVolgorde,
    onConfirm: a => openAthleteModule("dossier", a.key),
  });
}


async function laadDossierCockpit() {
  const box = $("#dc-lijst");
  if (!dcPicker) skeleton(box, 6);
  let data;
  try { data = await api("/api/atleten"); }
  catch { if (!dcPicker) box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  dcCache = data.atleten || [];
  dcGroepVolgorde = data.groep_volgorde || [];
  const items = dcCache.map(a => ({ ...a, key: a.id }));
  if (!items.length && !dcPicker) {
    box.innerHTML = `<div class="leeg">${ic("users")}<p>Geen atleten.</p></div>`; dcToonLijst(); return;
  }
  if (dcPicker) { dcPicker.setItems(items); }
  else {
    dcPicker = renderPicker({
      mount: box, searchEl: $("#dc-zoek"), items, groupOrder: data.groep_volgorde || [],
      selectedKey: dcSel || "", mode: "navigate", emptyText: "Geen atleet gevonden.",
      secondary: a => (a.heeft_intake && a.doel) ? esc(a.doel) : "",
      onActivate: a => openDossierCockpit(a.key),
    });
  }
  dcToonLijst();
  if (dcOpenPending) { const p = dcOpenPending; dcOpenPending = ""; openDossierCockpit(p); }
}

bindRefresh("dc-refresh", () => { geladen.dossier = true; return laadDossierCockpit(); });

async function openDossierCockpit(ident) {
  // roster nog niet geladen? → onthoud en open zodra laadDossierCockpit klaar is
  if (!dcPicker) { dcOpenPending = ident; if (!geladen.dossier) { geladen.dossier = true; laadDossierCockpit(); } return; }
  dcSel = ident;
  document.querySelector('.view[data-view="dossier"]').classList.add("has-athlete");
  const _r = dcCache.find(a => a.id === ident);
  if ($("#dc-switch-av")) $("#dc-switch-av").textContent = _r ? initialen(_r.naam) : "—";
  if ($("#dc-switch-nm")) $("#dc-switch-nm").textContent = _r ? _r.naam : "Kies atleet";
  if ($("#dc-switch-sub")) $("#dc-switch-sub").textContent = _r && _r.groep ? _r.groep : "Geheugen";
  dcPicker.setSelected(ident);
  dcToonLijst();                       // met open atleet valt de lijst weg (canvas wint)
  pushRoute("dossier", ident);
  const wrap = $("#dc-detail");
  if (!isDesktop()) { $(".view[data-view='dossier'] .md-list").hidden = true; $("#scroller").scrollTo({ top: 0 }); }
  wrap.hidden = false;
  wrap.innerHTML = '<div class="dc-load"><p class="muted center">Cockpit laden…</p></div>';
  let r;
  try { r = await api("/api/cockpit?key=" + encodeURIComponent(ident)); }
  catch { r = null; }
  if (!wrap || dcSel !== ident) return;                       // leak guard: andere atleet gekozen
  if (!r || !r.ok) {
    // Totale onverwachte fout (na per-stage-isolatie zeldzaam): eerlijk als INTERNE
    // fout labelen, niet als generieke 'bronfout'. Niets-bekend ≠ waar.
    wrap.innerHTML = `<div class="dc-err">${ic("alert")}<p>De centrale atleetcontext kon nu niet worden opgebouwd (interne fout — geen bronfout). Dit betekent <b>niet</b> dat er niets bekend is.</p>
      <button class="btn ghost" onclick="openDossierCockpit('${esc(ident)}')">Opnieuw</button></div>`;
    return;
  }
  dcLog("cockpit_open", { key: ident, overall: r.status && r.status.overall });
  dcRender(wrap, r);
}

function dcProv(p) {
  if (!p) return "";
  const parts = [];
  if (p.truth_type) parts.push(_DC_TRUTH[p.truth_type] || p.truth_type);
  if (p.source) parts.push(p.source);
  if (p.observed_at) parts.push(p.observed_at);
  if (p.status) parts.push(String(p.status).toLowerCase());
  if (p.strength) parts.push(String(p.strength).toLowerCase());
  return esc(parts.join(" · "));
}

// Presentatie-opschoning van registry-labels: technische sleutel-suffixen
// (uuid's) horen niet in de coach-UI. Alleen weergave — de onderliggende
// registry-key en het Waarom?-spoor blijven onaangetast.
function dcPrettyLabel(l) {
  return String(l || "")
    .replace(/[.\s]*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*$/i, "");
}

// Zelfde provenance-keten als platte tekst (de DS-primitives escapen zelf).
function dcProvText(p) {
  if (!p) return "";
  const parts = [];
  if (p.truth_type) parts.push(_DC_TRUTH[p.truth_type] || p.truth_type);
  if (p.source) parts.push(p.source);
  if (p.observed_at) parts.push(p.observed_at);
  if (p.status) parts.push(String(p.status).toLowerCase());
  if (p.strength) parts.push(String(p.strength).toLowerCase());
  return parts.join(" · ");
}

// ── DOSSIER: living memory ───────────────────────────────────────────────────
// Tijd is hier het ruimtelijke principe. Eén verticale geheugen-spine: VANDAAG is
// het sterkste punt, ouder werk verzwakt naar achteren, en de planning ligt subtiel
// vooruit (gestippeld). Geen document met history-rows, maar een kaart van hoe deze
// atleet hier is gekomen.

// Eén knooppunt op de spine. `weight` (1=nu … 4=ver terug) stuurt contrast/schaal;
// `future` maakt het knooppunt vooruitkijkend (open ring i.p.v. gevulde stip).
function dcNode(n) {
  return `<li class="dc-node w${n.weight || 2}${n.future ? " is-future" : ""} ${n.tone || "is-calm"}">
    <span class="dc-node-dot"></span>
    <div class="dc-node-b">
      ${n.when ? `<span class="dc-node-when">${esc(n.when)}</span>` : ""}
      <span class="dc-node-t">${esc(n.title)}</span>
      ${n.sub ? `<span class="dc-node-s">${esc(n.sub)}</span>` : ""}
      ${n.meta ? `<span class="dc-node-m">${esc(n.meta)}</span>` : ""}
    </div></li>`;
}
function dcEra(label, nodes, cls) {
  return `<section class="dc-era ${cls || ""}">
    <h3 class="ds-label dc-era-l">${esc(label)}</h3>
    <ul class="dc-spine-list">${nodes}</ul></section>`;
}

function dcRender(wrap, vm) {
  const st = vm.status || {}, rel = st.reliability || {};
  const relTxt = rel.level === "green" ? "bronnen vers"
    : rel.core_gap ? "kernbron uitgevallen — oordeel onzeker"
    : "let op: bron(nen) verouderd of onvolledig";
  const relTone = dsTone(rel.level || "unknown");
  const attn = vm.attention || [], chg = vm.changes || [];
  const tl = vm.timeline || {}, tlv = tl.events || [];
  const plan = vm.planning || { rows: [] };
  const lo = vm.load_observation;
  const attnTone = attn.length ? dsTone("aandacht") : "is-calm";

  let h = `<div class="dc-memory ${attn.length ? attnTone : relTone}">`;
  // Zelfde achtergrondwereld als Workspace: ambient haze + orbits + vignette.
  h += `<div class="dc-bg" aria-hidden="true"><div class="dc-amb"></div>${wsOrbits()}<div class="ws-vig"></div></div>`;
  h += `<header class="dc-head2">
    <div class="dc-id2"><span class="dc-orbwrap"><i class="dc-orb-halo"></i><span class="dc-orb">${esc(initialen(vm.naam || vm.key))}</span></span>
      <div><h2 class="dc-name">${esc(vm.naam || vm.key)}</h2>
        <p class="dc-sub">${vm.groep ? esc(vm.groep) + '<span class="sep">·</span>' : ""}${dsChip(_DC_OVERALL[st.overall] || st.overall || "—", relTone)}${dsFresh(rel.level || "unknown", relTxt)}</p></div></div>
    <div class="dc-nav2">${athleteNav("dossier", vm.key)}</div>
  </header>`;

  // Partial-truth diagnostic: één build-stage faalde → alleen dát stuk mist, de rest klopt.
  const diag = vm.build_diagnostic || [];
  if (diag.length) {
    h += `<div class="dc-diag">${ic("alert")}<span>Enkele onderdelen konden niet worden berekend (${esc(diag.map(d => d.stage).join(", "))}). De overige bekende kennis hieronder klopt — dit is een interne fout, <b>geen</b> bronfout.</span></div>`;
  }

  h += `<div class="dc-mem-grid"><div class="dc-spine">`;

  // ── VANDAAG: het sterkste punt op de lijn ──
  // Waarde-consistentie: het percentage in de load-signaalkaart volgt de
  // canonieke `delta_pct` (load_metric) — nooit een voor-afgerond bron-%
  // (+91%) boven het canonieke oordeel (+92%) op hetzelfde scherm.
  const canonPct = t => (lo && lo.delta_pct != null && t)
    ? String(t).replace(/[+-]?\d+(?:[.,]\d+)?%/, `${lo.delta_pct > 0 ? "+" : ""}${lo.delta_pct}%`)
    : t;
  let nu = attn.map(c => dcNode({
    weight: 1, tone: dsTone("aandacht"), title: c.title,
    sub: (c.kind === "load_signal" ? canonPct(c.why) : c.why) || "",
    meta: c.prov ? dcProvText(c.prov) : "",
  })).join("");
  if (lo) {
    const sev = lo.ernst === "hoog" ? "hoog" : "let op";
    const delta = (lo.delta_pct != null) ? ` · +${lo.delta_pct}% t.o.v. referentie` : "";
    let reden;
    if (lo.afgehandeld) reden = "eerder afgehandeld — geen open Home-actie";
    else if (lo.home_action && lo.ernst === "hoog") reden = "open Home-actie";
    else reden = "monitoring — nog geen coachactie";
    const loadCarded = attn.some(c => c.kind === "load_signal");
    nu += dcNode({ weight: 1, tone: dsTone(lo.ernst), title: `Belasting ${sev}${delta}`,
      sub: (lo.signalen && !loadCarded) ? lo.signalen : "", meta: `${reden} (Teampuls)` });
  }
  if (!nu) nu = dcNode({ weight: 1, tone: "is-success", title: "Geen actiepunten",
    sub: st.insufficient ? "Te weinig data voor een oordeel — geen betrouwbare actiepunten."
                         : `geen actieve klacht of signaal bekend${rel.level === "green" ? " (bronnen vers)" : ""}` });
  h += `<section class="dc-era dc-now dc-attn">
    <h3 class="ds-label dc-era-l">Aandacht nu · vandaag</h3>
    <ul class="dc-spine-list">${nu}</ul></section>`;

  // ── RECENT VERANDERD ──
  h += dcEra("Recent veranderd", chg.length
    ? chg.map(c => dcNode({ weight: 2, when: c.effective_at || "", title: c.title })).join("")
    : dcNode({ weight: 3, title: "Geen recente wijziging in het beeld van deze atleet." }),
    "dc-changes");

  // ── HISTORIE: verder terug = zwakker ──
  h += `<section class="dc-era dc-timeline"><h3 class="ds-label dc-era-l">Longitudinale historie</h3>`;
  if (tl.empty_reason) {
    h += `<p class="dc-empty-tl">Er is nog geen longitudinale tijdlijn vastgelegd. BeBetter bouwt de historie op vanaf het moment dat history-capture wordt geactiveerd (vanaf-nu; geen terugwerkende reconstructie). <b>‘Geen events’ betekent hier niet ‘geen historie’</b> — alleen dat er nog niets is vastgelegd.</p>`;
  } else {
    h += `<ul class="dc-spine-list">` + tlv.map((e, i) => dcNode({
      weight: Math.min(4, 2 + Math.floor(i / 4)),
      when: e.effective_at || e.recorded_at || "", title: e.title || e.event_type })).join("") + `</ul>`;
  }
  h += `</section>`;

  // ── VOORUIT: doelen & planning liggen vóór ons op de lijn ──
  h += `<section class="dc-era dc-planning dc-ahead">
    <h3 class="ds-label dc-era-l">Doelen &amp; planning</h3><ul class="dc-spine-list">`;
  h += (plan.rows && plan.rows.length)
    ? plan.rows.map(r => dcNode({ weight: 2, future: true, title: r.value, sub: r.label })).join("")
    : dcNode({ weight: 3, future: true, title: "Geen doel of planning vastgelegd." });
  h += `</ul></section></div>`;                        // /spine

  // ── BEWIJS naast het verhaal ──
  h += `<aside class="dc-evidence">`;
  h += `<section class="dc-sec dc-domains">` + (vm.domains || []).map(d => `
    <details class="ds-disc dc-dom${d.onbekend ? " leeg" : ""}"${d.open ? " open" : ""}>
      <summary>${esc(d.titel)}${d.onbekend ? ` <span class="muted klein">— onbekend</span>` : ""}</summary>
      ${d.onbekend ? "" : `<div class="ds-disc-body"><ul class="dc-reg">` + d.regels.map(r => `
        <li>
          <div class="dc-reg-main"><span class="dc-lbl">${esc(dcPrettyLabel(r.label))}</span><span class="dc-val">${esc(r.value)}</span></div>
          <div class="dc-reg-meta">${r.prov ? `<span class="dc-prov">${dcProv(r.prov)}</span>` : ""}
            ${r.evidence_id ? `<button class="dc-why" data-id="${esc(r.evidence_id)}" data-key="${esc(vm.key)}">Waarom?</button>` : ""}</div>
        </li>`).join("") + `</ul></div>`}
    </details>`).join("") + `</section>`;
  const src = vm.source_health || [];
  if (src.length) {
    h += `<details class="ds-disc dc-sec dc-src"><summary>Bronnen &amp; betrouwbaarheid</summary>
      <div class="ds-disc-body"><ul class="dc-srclist">` +
      src.map(x => `<li><span class="dc-src-n">${esc(x.source)}</span>
        <span class="dc-src-s ${x.available ? (x.stale ? "warn" : "ok") : "bad"}">${x.available ? (x.stale ? "verouderd" : "vers") : "uitgevallen"}</span>
        ${x.error ? `<span class="muted klein">${esc(x.error)}</span>` : ""}</li>`).join("") +
      `</ul></div></details>`;
  }
  h += `</aside></div></div>`;

  wrap.innerHTML = h;
  wrap.querySelectorAll(".dc-why").forEach(b => b.addEventListener("click", () => dcWaarom(b)));
}


function dcGoSchema(key) {
  // Genormaliseerd naar het canonieke contract (was hand-rolled pushState + applyRoute).
  openAthleteModule("schema", key);
}

async function dcWaarom(btn) {
  const id = btn.dataset.id, key = btn.dataset.key;
  if (btn._open) { const n = btn.nextElementSibling; if (n && n.classList.contains("dc-why-box")) n.remove(); btn._open = false; btn.textContent = "Waarom?"; return; }
  btn.textContent = "Laden…";
  const r = await api(`/api/cockpit/explain?key=${encodeURIComponent(key)}&id=${encodeURIComponent(id)}`).catch(() => null);
  btn.textContent = "Verberg";
  const ex = (r && r.ok && r.explain) || null;
  const box = document.createElement("div");
  box.className = "dc-why-box";
  if (!ex || ex.error) { box.innerHTML = `<p class="muted klein">Onderbouwing niet beschikbaar.</p>`; }
  else {
    const chain = (ex.provenance || []).map(p => `<li>${esc(p.key || p.source || "")}${p.observed_at ? ` · ${esc(p.observed_at)}` : ""}${p.truth_type ? ` · ${esc(_DC_TRUTH[p.truth_type] || p.truth_type)}` : ""}</li>`).join("");
    box.innerHTML = `<p class="klein"><b>${esc(_DC_TRUTH[ex.truth_type] || ex.truth_type || "")}</b>${ex.strength ? ` · ${esc(String(ex.strength).toLowerCase())}` : ""}${ex.observed_at ? ` · ${esc(ex.observed_at)}` : ""}</p>
      ${ex.sources && ex.sources.length ? `<p class="klein">Bronnen: ${esc(ex.sources.join(", "))}</p>` : ""}
      ${chain ? `<ul class="dc-why-chain">${chain}</ul>` : ""}`;
  }
  btn.insertAdjacentElement("afterend", box);
  btn._open = true;
}

// ══════════ Athlete Workspace (Coach Cockpit v2) ══════════════════════════════
// De centrale dagelijkse athlete-werkplek. Fast-read shell (/api/workspace/{key} —
// alleen goedkope stores) toont direct: aandacht nu · live belasting · schema-signaal ·
// feedback-status · snelle acties (bestaande routes/authority). De rijke context
// (doel/planning/klachten) komt LAZY en parallel uit het bestaande /api/cockpit, zodat
// een trage load-/feedback-refresh de shell of de andere secties nooit blokkeert.
let wsSel = "", wsOpenPending = "", wsCache = [], wsGroepVolgorde = [], wsRosterKlaar = false;

// De athlete-lijst is GEEN visueel fundament meer. In een actieve athlete-context
// hoort ~90% van de aandacht bij die atleet; wisselen gebeurt via een compacte
// switcher die de BESTAANDE overlay-picker opent (zelfde component, zelfde routes).
function wsSwitchVul(naam, sub) {
  const av = $("#ws-switch-av"), nm = $("#ws-switch-nm"), sb = $("#ws-switch-sub");
  if (av) av.textContent = naam ? initialen(naam) : "—";
  if (nm) nm.textContent = naam || "Kies atleet";
  if (sb) sb.textContent = sub || "Workspace";
}
function wsOpenSwitcher() {
  if (!wsCache.length) { laadWorkspace(); return; }
  openAthletePickerOverlay({
    title: "Wissel van atleet", confirmLabel: "Openen", placeholder: "Zoek atleet",
    items: wsCache.map(a => ({ ...a, key: a.id })), groupOrder: wsGroepVolgorde,
    onConfirm: a => openWorkspace(a.key),
  });
}
$("#ws-switch")?.addEventListener("click", wsOpenSwitcher);

// `laadWorkspace` laadt alleen nog de roster die de switcher voedt — geen lijst-UI.
async function laadWorkspace() {
  let data;
  try { data = await api("/api/atleten"); }
  catch { return; }
  wsCache = data.atleten || [];
  wsGroepVolgorde = data.groep_volgorde || [];
  wsRosterKlaar = true;
  if (wsOpenPending) { const p = wsOpenPending; wsOpenPending = ""; wsShow(p); }
  else if (!wsSel) wsLeegScherm();
}
bindRefresh("ws-refresh", () => { if (wsSel) return wsShow(wsSel); geladen.workspace = true; return laadWorkspace(); });

// Geen atleet gekozen → een rustige, uitnodigende scène (geen lege lijst).
function wsLeegScherm() {
  const wrap = $("#ws-detail"); if (!wrap) return;
  wrap.innerHTML = `<div class="ws-empty">
    <div class="ws-empty-orb"></div>
    <h2>Kies een atleet</h2>
    <p>De workspace toont wat er nu speelt bij één atleet: aandacht, belasting, doel en feedback.</p>
    <button type="button" class="btn primary" onclick="wsOpenSwitcher()">Atleet kiezen</button>
  </div>`;
  wsSwitchVul("", "Workspace");
}

// Entry point — athlete-aware maar bewust BUITEN _ATHLETE_VIEWS (Cohesion-contract
// byte-identiek). Schrijft de route en laadt de shell via wsShow.
function openWorkspace(user_key) {
  if (!user_key) { toonView("workspace"); return; }
  if (huidigeView !== "workspace") toonView("workspace");
  const h = "#workspace/" + encodeURIComponent(user_key);
  if (location.hash !== h) { try { history.pushState(null, "", h); } catch {} }
  wsShow(user_key);
}

async function wsShow(ident) {
  if (!wsRosterKlaar) { wsOpenPending = ident; if (!geladen.workspace) { geladen.workspace = true; laadWorkspace(); } return; }
  wsSel = ident;
  pushRoute("workspace", ident);
  const roster = wsCache.find(a => a.id === ident);
  wsSwitchVul(roster ? roster.naam : "", roster && roster.groep ? roster.groep : "Workspace");
  const wrap = $("#ws-detail");
  $("#scroller").scrollTo({ top: 0 });
  wrap.innerHTML = `<div class="ws-loading">${wsSkel(4)}</div>`;
  let r;
  try { r = await api("/api/workspace/" + encodeURIComponent(ident)); }
  catch { r = null; }
  if (!wrap || wsSel !== ident) return;                    // leak guard: andere atleet gekozen
  if (!r || r.fs === false) { wrap.innerHTML = `<p class="muted center">FinalSurge nog niet gekoppeld.</p>`; return; }
  if (!r.ok) {
    wrap.innerHTML = `<div class="dc-err">${ic("alert")}<p>De workspace kon nu niet worden opgebouwd (interne fout — geen bronfout).</p>
      <button class="btn ghost" onclick="openWorkspace('${esc(ident)}')">Opnieuw</button></div>`;
    return;
  }
  wsRender(wrap, r);
  wsLoadDeep(wrap, ident);                                  // rijke context lazy + parallel
}

// ── DE ATHLETE CANVAS (north-star pass) ─────────────────────────────────────
// Workspace is een performance command scene: een gelaagd focal-systeem in het
// midden (ringen + medaillon + signaal-schijf die de ringen overlapt), context
// als translucent glas-panes links en rechts, een meedoende achtergrond
// (ambient haze + orbitale lijnen + vignette) en onderaan een geïntegreerde
// actiebalk. Zelfde data, zelfde acties, zelfde routes — alleen de presentatie.

// Randloze skeleton voor de lazy deep-slots.
function wsSkel(n) {
  return Array.from({ length: n || 2 },
    (_, i) => `<div class="ds-skel ${i % 2 ? "w60" : "w80"}"></div>`).join("");
}

// Grote datalijn met glow-punten — ALLEEN echte reeksen (de runs uit de captured
// stand). Vloeiende curve (Catmull-Rom→bezier), area-verloop, punt per meting.
// Geen library, geen canvas: één inline SVG-string. Leeg bij < 2 punten.
let _wsChartN = 0;
// Locale-presentatie (lokaal, geen app-brede formatter): NL-decimaalkomma.
// Gehele getallen blijven schoon (36 → "36"), decimalen krijgen een komma
// (36.4 → "36,4"). Puur presentationeel; verandert geen enkele waarde.
function nlNum(x) {
  if (x == null || x === "") return "";
  const n = Number(x);
  if (!isFinite(n)) return String(x);
  return (Math.round(n * 100) / 100).toString().replace(".", ",");
}

function wsChart(vals, o) {
  o = o || {};
  const v = (vals || []).map(Number).filter(n => isFinite(n));
  if (v.length < 2) return "";
  const w = o.w || 260, h = o.h || 72, pad = 8;
  // `min0` + `ref`: cumulatieve reeksen tekenen vanaf 0 en mogen een echte
  // referentiewaarde (bv. km_basis_week) als gestippelde lijn dragen — zo leest
  // de grafiek in dezelfde richting als het signaal (semantiek, geen decoratie).
  const ref = (o.ref != null && isFinite(Number(o.ref))) ? Number(o.ref) : null;
  const min = o.min0 ? 0 : Math.min(...v);
  const max = Math.max(...v, ref != null ? ref : -Infinity);
  const span = (max - min) || 1;
  const yOf = n => h - pad - ((n - min) / span) * (h - pad * 3);
  const refLine = ref != null
    ? `<line class="ws-chart-ref" x1="${pad}" y1="${yOf(ref).toFixed(1)}" x2="${w - pad}" y2="${yOf(ref).toFixed(1)}"/>
       <text class="ws-chart-reflbl" x="${pad + 2}" y="${(yOf(ref) - 5).toFixed(1)}">REF ${esc(nlNum(ref))}</text>`
    : "";
  const pts = v.map((n, i) => [pad + (i / (v.length - 1)) * (w - pad * 2), yOf(n)]);
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    d += ` C${(p1[0] + (p2[0] - p0[0]) / 6).toFixed(1)} ${(p1[1] + (p2[1] - p0[1]) / 6).toFixed(1)},` +
         `${(p2[0] - (p3[0] - p1[0]) / 6).toFixed(1)} ${(p2[1] - (p3[1] - p1[1]) / 6).toFixed(1)},` +
         `${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  const uid = "wsg" + (++_wsChartN);
  const last = pts[pts.length - 1];
  const area = o.area === false ? "" :
    `<defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="currentColor" stop-opacity=".26"/>
      <stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
    <path fill="url(#${uid})" stroke="none" d="${d} L${(w - pad).toFixed(1)} ${h - 2} L${pad} ${h - 2} Z"/>`;
  return `<svg class="ws-chart ${o.cls || ""}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    ${area}${refLine}
    <path class="ws-chart-line" d="${d}"/>
    ${pts.map(p => `<circle class="ws-chart-dot" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.6"/>`).join("")}
    <circle class="ws-chart-tip" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="4"/></svg>`;
}

// Achtergrondlaag: canvas-brede orbitale lijnen + een vaste constellation.
// Puur decoratief (geen data, geen suggestie van een persoon), statisch.
// Z0 — omgeving: verre traces, constellation en het perspectiefveld dat naar
// de atleet convergeert. Statisch en decoratief (geen data).
function wsOrbits() {
  const stars = [[150, 130, 1.4, .4], [420, 70, 1, .25], [880, 52, 1.4, .4],
    [1210, 120, 1.1, .3], [1340, 420, 1.3, .35], [90, 470, 1.2, .3],
    [240, 820, 1.3, .3], [1150, 800, 1.2, .25], [640, 120, 1, .2],
    [1050, 250, 1, .25], [340, 300, .9, .2], [1290, 640, 1, .22]];
  return `<svg class="ws-orbits" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <path class="ws-tr" d="M-40 620 C300 520 700 500 1480 590"/>
    <path class="ws-tr" d="M-40 700 C360 620 760 610 1480 680"/>
    <path class="ws-tr" d="M120 -40 C240 220 320 420 340 780"/>
    <path class="ws-tr" d="M1330 -40 C1240 240 1180 460 1170 820"/>
    <g class="ws-fl">
      <path d="M180 900 L648 560"/><path d="M420 900 L678 578"/>
      <path d="M1260 900 L792 560"/><path d="M1030 900 L762 578"/>
      <ellipse cx="720" cy="748" rx="560" ry="104"/>
      <ellipse cx="720" cy="756" rx="380" ry="72"/>
    </g>
    ${stars.map((d, i) => `<circle class="ws-star${i % 5 === 2 ? " tw" : ""}" cx="${d[0]}" cy="${d[1]}" r="${d[2]}" opacity="${d[3]}"/>`).join("")}</svg>`;
}

// Weekstrip: de laatste 7 dagen t/m de stand-datum, met de echte dag-totalen
// (runs uit de captured stand, gesommeerd per dag). Rustdagen tonen eerlijk leeg.
function wsWeekStrip(runs, standDatum) {
  const parse = d => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d || ""));
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const end = parse(standDatum) || parse((runs[runs.length - 1] || {}).datum);
  if (!end || !(runs || []).length) return "";
  const per = {};
  for (const r of runs) { const k = String(r.datum || "").slice(0, 10);
    per[k] = (per[k] || 0) + (Number(r.km) || 0); }
  const DAG = ["ZO", "MA", "DI", "WO", "DO", "VR", "ZA"];
  const cols = [];
  let max = 1;
  for (let i = 6; i >= 0; i--) {
    const d = new Date(end.getFullYear(), end.getMonth(), end.getDate() - i);
    const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const km = per[k] || 0; max = Math.max(max, km);
    cols.push({ dag: DAG[d.getDay()], km });
  }
  return `<div class="ws-wk">` + cols.map(c => {
    const hp = Math.round(c.km / max * 100);
    const kmTxt = c.km ? nlNum(Math.round(c.km * 10) / 10) : "";
    return `<div class="${c.km ? "on" : "off"}"><em>${esc(kmTxt)}</em>
      <i style="height:${c.km ? Math.max(hp, 8) : 0}%"></i><span>${c.dag}</span></div>`;
  }).join("") + `</div>`;
}

// Belastingsinstrument: ÉÉN geïntegreerd cockpit-instrument i.p.v. losse weekstrip +
// chart. Dag-energie (pulsen op de baseline) + cumulatieve trend die daarbovenuit
// stijgt (VLAK op rustdagen — cumulatief stijgt of blijft gelijk) + referentiedrempel
// + eind-node (= origin van de kern-connector). Zelfde bronvelden (runs/km_recent/
// km_basis_week), geen nieuwe/afgeleide fake data; geen data → "" (caller toont leeg).
function wsLoadInstrument(bel) {
  const runs = (bel.runs || []);
  const parse = d => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d || ""));
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const end = parse(bel.datum) || parse((runs[runs.length - 1] || {}).datum);
  if (!end || !runs.length) return "";
  const per = {};
  for (const r of runs) { const k = String(r.datum || "").slice(0, 10);
    per[k] = (per[k] || 0) + (Number(r.km) || 0); }
  const DAG = ["ZO", "MA", "DI", "WO", "DO", "VR", "ZA"];
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(end.getFullYear(), end.getMonth(), end.getDate() - i);
    const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    days.push({ dag: DAG[d.getDay()], km: per[k] || 0 });
  }
  let acc = 0; days.forEach(d => { acc += d.km; d.cum = acc; });
  const ref = (bel.km_basis_week != null && isFinite(Number(bel.km_basis_week))) ? Number(bel.km_basis_week) : null;
  const maxDaily = Math.max(1, ...days.map(d => d.km));
  const cumMax = Math.max(1, acc, ref != null ? ref : 0);
  const N = days.length, padL = 30, padR = 32, span = 320 - padL - padR;
  const xi = i => padL + (N > 1 ? (i / (N - 1)) * span : 0);
  const yCum = v => 100 - (v / cumMax) * 86;
  const bars = days.map((d, i) => { const x = xi(i);
    if (!d.km) return `<rect class="li-bar rest" x="${(x - 4.5).toFixed(1)}" y="97" width="9" height="3" rx="1.5"/>`;
    const h = (d.km / maxDaily) * 30;
    return `<rect class="li-bar" x="${(x - 4.5).toFixed(1)}" y="${(100 - h).toFixed(1)}" width="9" height="${h.toFixed(1)}" rx="2.5"/>`;
  }).join("");
  const vals = days.map((d, i) => d.km
    ? `<text class="li-val" x="${xi(i).toFixed(1)}" y="${(100 - (d.km / maxDaily) * 30 - 4).toFixed(1)}">${esc(nlNum(Math.round(d.km * 10) / 10))}</text>`
    : "").join("");
  const dayl = days.map((d, i) => `<text class="li-day${d.km ? " on" : ""}" x="${xi(i).toFixed(1)}" y="116">${esc(d.dag)}</text>`).join("");
  const pts = days.map((d, i) => [xi(i), yCum(d.cum)]);
  const line = "M" + pts.map(p => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" L");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)} 100 L${pts[0][0].toFixed(1)} 100 Z`;
  const tip = pts[pts.length - 1];
  const yRef = ref != null ? yCum(ref) : null;
  return `<svg class="ws-loadinst" viewBox="0 0 320 128" style="color:var(--tone)" aria-hidden="true">
    <defs><linearGradient id="ws-liarea" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="currentColor" stop-opacity=".24"/>
      <stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient>
      <linearGradient id="ws-liref" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="var(--ds-accent)" stop-opacity="0"/>
        <stop offset="0.22" stop-color="var(--ds-accent)" stop-opacity=".7"/>
        <stop offset="0.8" stop-color="var(--ds-accent)" stop-opacity=".5"/>
        <stop offset="1" stop-color="var(--ds-accent)" stop-opacity="0"/></linearGradient></defs>
    <line class="li-base" x1="14" y1="100" x2="306" y2="100"/>
    ${yRef != null ? `<line class="li-ref" x1="14" y1="${yRef.toFixed(1)}" x2="306" y2="${yRef.toFixed(1)}"/>
      <text class="li-reflbl" x="46" y="${(yRef - 4).toFixed(1)}">REF ${esc(nlNum(ref))}</text>` : ""}
    ${bars}${vals}
    <path class="li-area" d="${area}"/>
    <path class="li-cum" d="${line}"/>
    <circle class="li-tip-o" cx="${tip[0].toFixed(1)}" cy="${tip[1].toFixed(1)}" r="6"/>
    <circle class="li-tip" cx="${tip[0].toFixed(1)}" cy="${tip[1].toFixed(1)}" r="3.4"/>
    ${dayl}
  </svg>`;
}

// De ATHLETE CORE: een abstracte, ruimtelijke intelligentie-kern — GEEN mens.
// Geen avatar/bust/portret/silhouet; de menslijn is bewust verlaten. De kern is
// een glazen sphere (wireframe-meridianen + inner-particles + hotspot-bloom),
// omgeven door gekantelde orbit-ringen waarvan er ÉÉN de eerlijke load-ratio als
// instrument draagt, staand op een radar-basis. Het dominante signaal (focal)
// leeft geïntegreerd IN de kern. Reageert volledig op toon + echte data.
function wsCore(focal) {
  const f = focal || {};
  const R = 252, C = 2 * Math.PI * R;
  // Instrument-ring: eerlijke mapping — ratio>=1: dim ring = 100% referentie
  // bereikt, felle sweep = overshoot (max één extra ronde); ratio<1: voortgang.
  // Geen data → geen boog (de decoratieve ringen blijven, het instrument niet).
  let inst = "";
  if (f.gaugeFrac != null) {
    const dash = Math.max(f.gaugeFrac * C, 0);
    inst = `<g transform="translate(340 332) rotate(22) scale(1 .60)">
      ${f.gaugeDim ? `<circle class="ws-inst-dim" r="${R}"/>` : ""}
      <circle class="ws-inst-v" r="${R}" transform="rotate(-90)"
        style="stroke-dasharray:${dash.toFixed(1)} ${(C - dash).toFixed(1)};--wsd:${dash.toFixed(1)}"/>
      <circle class="ws-inst-cap" cx="0" cy="-${R}" r="4.5"/></g>`;
  }
  const val = String(f.value == null ? "" : f.value);
  const big = val.length > 4 ? " txt" : "";
  return `<div class="ws-core ${f.tone || ""}">
    <div class="ws-aura" aria-hidden="true"></div>
    <svg class="ws-rings" viewBox="0 0 680 680" aria-hidden="true">
      <g class="ws-ringspin"><ellipse class="ws-ring r1" cx="340" cy="332" rx="300" ry="96" transform="rotate(-15 340 332)"/></g>
      <g class="ws-ringspin rev"><ellipse class="ws-ring r3" cx="340" cy="332" rx="180" ry="286" transform="rotate(12 340 332)"/></g>
      ${inst}
      <circle class="ws-onode" cx="118" cy="214" r="5"/>
      <circle class="ws-onode n2" cx="150" cy="470" r="4"/>
    </svg>
    <svg class="ws-sphere" viewBox="0 0 680 680" aria-hidden="true">
      <defs>
        <radialGradient id="ws-glass" cx="42%" cy="36%" r="72%">
          <stop offset="0" stop-color="rgba(120,180,255,.18)"/>
          <stop offset="42%" stop-color="rgba(30,64,120,.30)"/>
          <stop offset="82%" stop-color="rgba(10,26,52,.62)"/>
          <stop offset="100%" stop-color="rgba(6,16,34,.82)"/>
        </radialGradient>
        <radialGradient id="ws-wash" cx="50%" cy="70%" r="60%">
          <stop offset="0" stop-color="var(--tone)" stop-opacity=".32"/>
          <stop offset="60%" stop-color="var(--tone)" stop-opacity=".05"/>
          <stop offset="100%" stop-color="var(--tone)" stop-opacity="0"/>
        </radialGradient>
        <radialGradient id="ws-field" cx="50%" cy="52%" r="52%">
          <stop offset="0" stop-color="var(--tone)" stop-opacity=".26"/>
          <stop offset="46%" stop-color="var(--tone)" stop-opacity=".07"/>
          <stop offset="100%" stop-color="var(--tone)" stop-opacity="0"/>
        </radialGradient>
        <linearGradient id="ws-merid" x1="0" y1="0" x2="0" y2="1" gradientUnits="objectBoundingBox">
          <stop offset="0" stop-color="rgba(174,214,255,.55)"/>
          <stop offset="0.5" stop-color="rgba(150,198,255,.07)"/>
          <stop offset="1" stop-color="rgba(174,214,255,.55)"/>
        </linearGradient>
        <radialGradient id="ws-ifield" cx="44%" cy="40%" r="60%">
          <stop offset="0" stop-color="rgba(120,172,255,.16)"/>
          <stop offset="58%" stop-color="rgba(58,108,190,.05)"/>
          <stop offset="100%" stop-color="rgba(30,60,120,0)"/>
        </radialGradient>
        <radialGradient id="ws-occ" cx="50%" cy="84%" r="48%">
          <stop offset="0" stop-color="rgba(2,7,18,.6)"/>
          <stop offset="100%" stop-color="rgba(2,7,18,0)"/>
        </radialGradient>
        <clipPath id="ws-sph"><circle cx="340" cy="332" r="150"/></clipPath>
        <clipPath id="ws-sphi"><circle cx="340" cy="332" r="112"/></clipPath>
      </defs>
      <circle cx="340" cy="332" r="150" fill="url(#ws-glass)"/>
      <circle cx="340" cy="332" r="150" fill="url(#ws-wash)"/>
      <g clip-path="url(#ws-sph)">
        <circle cx="340" cy="332" r="150" fill="url(#ws-field)"/>
        <circle cx="340" cy="332" r="112" fill="url(#ws-ifield)"/>
        <path class="ws-shell-rim" d="M262 296 A112 112 0 0 1 356 224"/>
        <path class="ws-shell-rim dim" d="M412 366 A112 112 0 0 1 372 428"/>
        <ellipse class="ws-readplane" cx="340" cy="300" rx="118" ry="44"/>
        <path class="ws-sph-grad" d="M338 188 A82 150 0 0 0 316 452"/>
        <path class="ws-sph-grad" d="M352 214 A106 150 0 0 1 372 456"/>
        <path class="ws-sph-line" d="M196 342 A150 46 0 0 0 408 360"/>
        <path class="ws-sph-line t" d="M214 316 A150 100 0 0 0 300 430" opacity=".5"/>
        <path class="ws-sph-line" d="M248 276 A146 30 0 0 1 372 269" opacity=".4"/>
        <path class="ws-sph-line" d="M236 392 A150 40 0 0 0 344 404" opacity=".3"/>
        <g class="ws-dataflow">
          <path class="ws-flow f1" d="M330 196 Q300 258 340 330"/>
          <path class="ws-flow f2" d="M452 342 Q392 320 344 332"/>
          <path class="ws-flow f3" d="M252 402 Q306 362 340 336"/>
          <path class="ws-flow f4" d="M398 224 Q366 276 342 328"/>
        </g>
        <path class="ws-sph-seg" d="M300 230 A140 118 0 0 1 416 286" opacity=".42"/>
        <path class="ws-sph-seg" d="M232 316 A150 46 0 0 1 268 300" opacity=".5"/>
        <path class="ws-sph-seg" d="M404 402 A150 46 0 0 1 440 384" opacity=".3"/>
        <circle class="ws-sph-dot t" cx="300" cy="300" r="1.5"/><circle class="ws-sph-dot" cx="386" cy="322" r="1.6"/>
        <circle class="ws-sph-dot" cx="352" cy="368" r="1.2"/><circle class="ws-sph-dot t" cx="312" cy="356" r="1.4"/>
        <circle class="ws-sph-dot" cx="372" cy="286" r="1.1"/><circle class="ws-sph-dot" cx="330" cy="398" r="1.3"/>
        <circle class="ws-sph-dot" cx="356" cy="312" r="1"/><circle class="ws-sph-dot" cx="318" cy="330" r="1.1"/>
        <circle cx="340" cy="332" r="150" fill="url(#ws-occ)"/>
        <g class="ws-corelight">
          <ellipse class="cl-bloom" cx="340" cy="356" rx="30" ry="64" opacity=".38"/>
          <path class="cl-col" d="M334 300 L346 300 L343 392 L337 392 Z" opacity=".5"/>
          <ellipse class="cl-mid" cx="340" cy="374" rx="11" ry="28" opacity=".6"/>
          <ellipse class="cl-core" cx="340" cy="378" rx="5" ry="16" opacity=".95"/>
        </g>
        <line class="ws-scan" x1="236" y1="300" x2="444" y2="300"/>
      </g>
      <circle class="ws-sph-rim" cx="340" cy="332" r="150"/>
      <path class="ws-sph-refr" d="M232 250 A150 150 0 0 1 430 232" style="opacity:.75;stroke-width:1.6"/>
      <path class="ws-sph-refr" d="M250 430 A150 150 0 0 0 300 470" style="opacity:.28;stroke-width:1.1"/>
    </svg>
    <svg class="ws-front" viewBox="0 0 680 680" aria-hidden="true">
      <g transform="translate(340 332) rotate(22) scale(1 .60)">
        <path class="ws-front-arc" d="M -238 84 A 252 252 0 0 0 96 233"/></g>
      <circle class="ws-fnode" cx="470" cy="452" r="4.5"/>
    </svg>
    <div class="ws-read">
      <span class="ws-read-l">${esc(f.label || "")}${f.word ? ` · ${esc(f.word)}` : ""}</span>
      <span class="ws-read-v${big}">${esc(val)}${f.unit ? `<i>${esc(f.unit)}</i>` : ""}</span>
      ${f.sub ? `<span class="ws-read-s">${esc(f.sub)}</span>` : ""}
    </div>
  </div>`;
}

// Eén regel context: tone-streep + tekst + optionele waarde. Vervangt de kaart.
function wsLine(l) {
  return `<div class="ws-line ${l.tone || "is-calm"}">
    ${l.icon ? `<span class="ws-line-ic">${ic(l.icon)}</span>` : ""}
    <span class="ws-line-b"><span class="ws-line-t">${esc(l.title)}</span>
      ${l.sub ? `<span class="ws-line-s">${esc(l.sub)}</span>` : ""}</span>
    ${l.value ? `<span class="ws-line-v">${esc(l.value)}</span>` : ""}</div>`;
}

// Compact identity-medaillon in de identity-zone: initialen + statusring. De
// identiteit staat hier één keer klein en helder; de centrale kern (wsCore) is
// bewust abstract (geen mens), dus de naam wordt niet dominant herhaald.
function wsAnchor(naam, tone) {
  return `<span class="ws-anchor ${tone}"><span class="ws-orb"><i></i>${esc(initialen(naam))}</span></span>`;
}

function wsRender(wrap, vm) {
  noteGeneration(vm.generation);                           // adopteer generatie vóór eigen banner
  const key = vm.key, naam = vm.naam || key;
  const bel = vm.belasting || {}, fb = vm.feedback || {}, sc = vm.schema;
  const attn = vm.attention || [];
  const gen = vm.generation || {}, gfr = gen.freshness || {};
  const tone = dsWorstTone(attn.map(a => dsTone(a.tier)));
  const belTone = dsTone(bel.ernst || "calm");

  // Focal-ladder MET eigenaar (ongewijzigd contract): één dominante waarde.
  let focal;
  if (bel.actief && bel.pct != null) {
    focal = { owner: "bel-pct", tone: belTone, label: "Belastingssignaal",
      word: bel.ernst === "hoog" ? "Verhoogd" : "Let op",
      value: (bel.pct > 0 ? "+" : "") + bel.pct, unit: "%",
      sub: bel.km_recent != null
        ? `${nlNum(bel.km_recent)} km · referentie ${nlNum(bel.km_basis_week)} km/wk`
        : (bel.reden || "") };
  } else if (bel.km_recent != null) {
    focal = { owner: "bel-km", tone: "is-calm", label: "Weekvolume", value: nlNum(bel.km_recent), unit: "km",
      sub: bel.km_basis_week != null ? `referentie ${nlNum(bel.km_basis_week)} km/wk · binnen de marge` : "binnen de marge" };
  } else if (attn.length) {
    focal = { owner: "attn", tone, label: "Aandacht", value: attn.length,
      unit: attn.length === 1 ? "punt" : "punten", sub: attn[0].kort || "" };
  } else {
    focal = { owner: "rust", tone: "is-success", label: "Status", value: "Rustig",
      sub: "geen open actiepunt" };
  }
  const owns = s => focal.owner === s;
  let ratioLbl = "";
  if ((owns("bel-pct") || owns("bel-km")) && bel.km_recent != null && bel.km_basis_week) {
    const ratio = bel.km_recent / bel.km_basis_week;
    focal.gaugeFrac = ratio >= 1 ? Math.min(ratio - 1, 1) : ratio;
    focal.gaugeDim = ratio >= 1;
    ratioLbl = (Math.round(ratio * 10) / 10).toFixed(1).replace(".", ",") + "×";
  }

  const chip = attn.length
    ? dsChip(tone === "is-critical" ? "actie" : "aandacht", tone)
    : dsChip("rustig", "is-calm");
  const fresh = bel.datum ? dsFresh(gfr.belasting || "unknown",
    gfr.belasting === "fresh" ? "belasting vers" : `stand ${bel.datum}`) : "";

  let h = genBanner(vm.generation);
  h += `<div class="ws-scene ${tone}">`;
  // Z0 — omgeving
  h += `<div class="ws-bg" aria-hidden="true"><div class="ws-amb"></div><div class="ws-haze"></div>${wsOrbits()}<div class="ws-vig"></div></div>`;
  // Z1 — cockpitgeometrie: gebroken bogen, gidslijnen, data-nodes
  h += `<svg class="ws-geo" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <circle class="ws-arc a2" cx="700" cy="430" r="418" stroke-dasharray="600 2026" transform="rotate(-206 700 430)"/>
    <circle class="ws-arc a3" cx="748" cy="470" r="332" stroke-dasharray="360 1726" transform="rotate(24 748 470)"/>
    <circle class="ws-arc a4" cx="700" cy="450" r="368"/>
    <circle class="ws-arc a1" cx="688" cy="452" r="272" stroke-dasharray="410 1299" transform="rotate(118 688 452)"/>
    <path class="ws-gd" d="M700 40 L700 132"/>
    <path class="ws-gd" d="M330 452 L262 452"/><path class="ws-gd" d="M1140 452 L1078 452"/>
    <path class="ws-trace" d="M96 250 C240 232 360 250 470 300"/>
    <path class="ws-trace t" d="M1330 250 C1200 236 1090 256 986 306"/>
    <path class="ws-trace" d="M232 690 C360 654 470 640 560 636"/>
    <path class="ws-trace t" d="M1208 700 C1080 662 980 648 900 640"/>
    <g class="ws-cross"><path d="M300 150 h12 M306 144 v12"/></g>
    <g class="ws-cross"><path d="M1128 158 h12 M1134 152 v12"/></g>
    <g class="ws-cross"><path d="M214 552 h12 M220 546 v12"/></g>
    <g class="ws-cross"><path d="M1214 552 h12 M1220 546 v12"/></g>
    <circle class="ws-anode" cx="360" cy="196" r="1.6"/><circle class="ws-anode" cx="1086" cy="210" r="1.6"/>
    <circle class="ws-anode" cx="470" cy="726" r="1.6"/><circle class="ws-anode" cx="972" cy="726" r="1.6"/>
    ${attn.length ? `<circle class="ws-nd" cx="497" cy="372" r="5"/>` : ""}
    <circle class="ws-nd2" cx="452" cy="641" r="3.5"/>
    <g class="ws-floor">
      <path d="M60 940 L672 700"/><path d="M1380 940 L768 700"/>
      <path d="M380 950 L700 700"/><path d="M1060 950 L740 700"/>
      <ellipse cx="720" cy="726" rx="540" ry="98"/>
      <ellipse cx="720" cy="732" rx="360" ry="66"/>
      <ellipse cx="720" cy="738" rx="190" ry="36"/>
    </g>
  </svg>`;

  // Z2 — athlete-vlak: identity (één keer, klein) + de abstracte Athlete Core
  // (geen mens) + radar-basis. Het dominante signaal leeft geïntegreerd in de kern.
  h += `<div class="ws-stagez ${focal.tone || tone}">
    <div class="ws-id2">${wsAnchor(naam, tone)}<b class="ws-name">${esc(naam)}</b>${chip}${fresh}</div>
    ${wsCore(focal)}
    <div class="ws-plat" aria-hidden="true"><svg viewBox="0 0 600 172">
      <path class="ws-beam" d="M286 -4 L314 -4 L338 66 L262 66 Z"/>
      <ellipse class="ws-pg" cx="300" cy="78" rx="250" ry="48"/>
      <ellipse class="ws-pe" cx="300" cy="78" rx="256" ry="52"/>
      <ellipse class="ws-pe d" cx="300" cy="80" rx="190" ry="38"/>
      <ellipse class="ws-pe" cx="300" cy="82" rx="120" ry="24" style="opacity:.6"/>
      <ellipse class="ws-pe d" cx="300" cy="84" rx="64" ry="13"/>
      <line class="ws-ptick" x1="60" y1="78" x2="80" y2="78"/><line class="ws-ptick" x1="520" y1="78" x2="540" y2="78"/>
      <line class="ws-ptick" x1="120" y1="112" x2="134" y2="104"/><line class="ws-ptick" x1="480" y1="104" x2="466" y2="112"/>
      <line class="ws-ptick" x1="230" y1="128" x2="238" y2="120"/><line class="ws-ptick" x1="370" y1="120" x2="362" y2="128"/>
      <path class="ws-plead" d="M120 62 A200 44 0 0 1 300 40"/>
      ${bel.actief ? `<path class="ws-ptrack" d="M300 96 L300 168"/>
      <circle class="ws-pout" cx="300" cy="96" r="3.4"/>` : ""}</svg></div>
  </div>`;

  // Z3 — fragmenten (borderless, ruimtelijk, asymmetrisch)
  // Waarde-consistentie: belasting-zin uit dezelfde canonieke velden als het signaal.
  const belZin = (bel.pct != null && bel.km_recent != null && bel.km_basis_week != null)
    ? `Volume <b>${bel.pct > 0 ? "+" : ""}${bel.pct}%</b> deze week — ${nlNum(bel.km_recent)} km tegenover een referentie van ${nlNum(bel.km_basis_week)} km/wk.`
    : "";
  const attnMeta = [attn.length ? (attn[0].tier || "") : "", bel.datum ? `stand ${bel.datum}` : ""]
    .concat(attn.slice(1).map(a => a.kort || "")).filter(Boolean).join(" · ");
  const attnTxt = attn.length
    ? ((attn[0].soort === "belasting" && belZin) ? belZin : esc(attn[0].kort || ""))
    : "";
  h += `<div class="ws-frag ws-frag-attn ${tone}">
      <span class="ws-tick"></span>
      <h3 class="ds-label">Aandacht nu</h3>
      ${attn.length ? `<p class="ws-attn-t">${attnTxt}</p>
        ${attnMeta ? `<p class="ws-attn-m">${esc(attnMeta)}</p>` : ""}`
      : `<p class="ws-attn-t calm">Geen open actiepunt uit belasting, compliance, schema of feedback.</p>`}
    </div>
    ${attn.length ? `<svg class="ws-conn" viewBox="0 0 56 92" aria-hidden="true"><path d="M0 8 C20 26 34 54 48 84"/></svg>` : ""}`;

  const nRuns = (bel.runs || []).length;
  let loadFrag = "";
  if (bel.km_recent != null) {
    loadFrag = `<div class="ws-frag ws-frag-load ${bel.actief ? belTone : ""}">
      <span class="ws-scrim" aria-hidden="true"></span>
      <h3 class="ds-label">Belastingsinstrument · 7 dagen<em>${nRuns ? `${nRuns} runs` : ""}</em></h3>
      <div class="ws-kmrow"><span class="ws-km">${esc(nlNum(bel.km_recent))}<i> km deze week</i></span>
        ${ratioLbl ? `<span class="ws-rt">${esc(ratioLbl)}</span>` : ""}</div>
      ${wsLoadInstrument(bel)}
      <div class="ws-load-m"><span>cumulatief weekvolume</span>
        ${nRuns ? `<span>laatste ${esc(String((bel.runs[nRuns - 1] || {}).datum || ""))}</span>` : ""}</div>
    </div>`;
  } else {
    loadFrag = `<div class="ws-frag ws-frag-load">
      <span class="ws-scrim" aria-hidden="true"></span>
      <h3 class="ds-label">Belasting</h3>
      <p class="ws-attn-t calm">Geen belastingstand bekend.</p></div>`;
  }
  h += loadFrag;
  // Zichtbare relatie belasting-fragment ↔ centrale kern (tweede verbinding):
  // strak geïntegreerd — duidelijke origin (cluster) en destination (kern-node).
  if (bel.km_recent != null)
    h += `<svg class="ws-conn2 ${bel.actief ? belTone : "is-calm"}" viewBox="0 0 150 132" aria-hidden="true">
      <path class="d" d="M4 128 C40 120 66 108 84 86"/>
      <path d="M84 86 C104 60 126 34 146 6"/>
      <circle cx="4" cy="128" r="2.4"/></svg>`;

  let planHead = sc ? wsLine({ tone: dsTone(sc.tier), icon: "clock",
    title: sc.kort || "schema-signaal", sub: sc.einddatum ? `t/m ${sc.einddatum}` : "" }) : "";
  h += `<div class="ws-frag ws-frag-plan ${sc ? dsTone(sc.tier) : ""}">
    <span class="ws-scrim" aria-hidden="true"></span><span class="ws-hang" aria-hidden="true"></span>
    <h3 class="ds-label">Doel &amp; planning</h3>
    ${planHead}<div id="ws-plan" class="ws-deep-slot">${wsSkel(2)}</div>
    <button type="button" class="ws-cta quiet" onclick="openAthleteModule('schema','${esc(key)}')">Schema openen</button>
  </div>`;

  const fbTone = fb.status === "unknown" ? "is-unknown" : (fb.open ? "is-attention" : "is-success");
  const fbBody = fb.status === "unknown"
    ? `<p class="ws-attn-t calm">Feedback-status wordt bijgewerkt…</p>`
    : `<div class="ws-fb ${fbTone}"><span class="ws-fb-badge">${fb.open || 0}</span>
        <span class="ws-fb-t">${fb.open ? `${fb.open} open reactie${fb.open !== 1 ? "s" : ""}<small>vraagt aandacht</small>` : `alles beantwoord<small>geen open reacties</small>`}</span></div>`;
  h += `<div class="ws-frag ws-frag-fb ${fbTone}">
    <span class="ws-scrim" aria-hidden="true"></span><span class="ws-hang" aria-hidden="true"></span>
    <h3 class="ds-label">Feedback</h3>${fbBody}
    <div id="ws-context" class="ws-deep-slot">${wsSkel(2)}</div>
    <button type="button" class="ws-cta quiet" onclick="openAthleteModule('dossier','${esc(key)}')">Cockpit openen</button>
  </div>`;

  const srcRow = (lbl, state, ver) => {
    const t = dsTone(state);
    const word = state === "fresh" ? "vers" : (state === "stale" ? "eerder" : state || "onbekend");
    return `<li class="${t}"><i class="ds-dot"></i><span>${esc(lbl)}</span>
      <em>${esc([String(ver || "").slice(0, 10), word].filter(Boolean).join(" · "))}</em></li>`;
  };
  const sv = gen.source_versions || {};
  h += `<div class="ws-frag ws-frag-src">
    <span class="ws-src-rail" aria-hidden="true"></span>
    <h3 class="ds-label">Bronnen</h3><ul class="ws-src">
    ${srcRow("Belasting", gfr.belasting, sv.belasting)}
    ${srcRow("Overzicht", gfr.home, sv.home)}
    ${srcRow("Feedback", gfr.feedback, sv.feedback)}</ul></div>`;

  // Z4 — command: de natuurlijke uitgang van de cockpitbeslissing. Instrument-strip
  // met lead-in (waaróm), één dominante trigger en stille secundaire controls.
  h += `<nav class="ws-dock ${attn.length ? tone : "is-calm"}">
    ${bel.actief ? `<div class="ws-cmd-lead">
        <span class="ttl">Volgende actie</span>
        <span class="st">belastingssignaal ${esc(bel.ernst === "hoog" ? "verhoogd" : "let op")}</span>
      </div>
      <button type="button" class="ws-cmd" onclick="wsMarkeerGezien('${esc(key)}','${esc(bel.ernst || "let_op")}')"><span class="ws-plug" aria-hidden="true"></span><span class="ws-cmd-chip">${ic("check")}</span>Belasting gezien</button>` : ""}
    <div class="ws-util">
      <button type="button" onclick="deepAtleet('teampuls','${esc(key)}')">Teampuls</button>
      <button type="button" onclick="openAthleteModule('atleten','${esc(key)}')">Profiel</button>
      ${athleteNav("workspace", key)}
    </div>
  </nav>`;

  h += `</div>`;
  wrap.innerHTML = h;
  wrap.dataset.belOwned = owns("bel-pct") ? "1" : "";
}

// Progressive disclosure: klap het blok NA de knop open/dicht (CSS grid-rows).
function dsFoldToggle(btn) {
  const f = btn.nextElementSibling;
  if (f && f.classList.contains("ds-fold")) f.classList.toggle("open");
}

// Rijke context lazy + parallel uit het bestaande cockpit-endpoint. Faalt/traag → de
// shell blijft staan; alleen deze twee slots tonen een nette fallback.
async function wsLoadDeep(wrap, ident) {
  let r;
  try { r = await api("/api/cockpit?key=" + encodeURIComponent(ident)); }
  catch { r = null; }
  if (!wrap || wsSel !== ident) return;                    // leak guard
  const plan = $("#ws-plan"), ctx = $("#ws-context");
  if (!r || !r.ok) {
    if (plan) plan.innerHTML = `<p class="ws-calm">Doel &amp; planning nu niet beschikbaar.</p>`;
    if (ctx) ctx.innerHTML = `<p class="ws-calm">Context nu niet beschikbaar.</p>`;
    return;
  }
  if (plan) {
    const rows = (r.planning && r.planning.rows) || [];
    // Geen doel → ontworpen rustige lege staat (geen kale zin in een kaart).
    plan.innerHTML = rows.length ? dsKv(rows)
      : `<div class="ws-goal"><div class="ws-goal-ring"><i></i></div>
          <p>Nog geen doel vastgelegd.<small>Leg een race- of trainingsdoel vast — het masterbrein plant erop.</small></p></div>`;
  }
  if (ctx) {
    const attn = (r.attention || []).filter(c => c.kind === "complaint" || c.kind === "contradiction");
    const lo = r.load_observation;
    let c = "";
    if (attn.length) c += attn.map(a => wsLine({
      tone: dsTone("aandacht"), icon: _DC_KIND_IC[a.kind] || "alert",
      title: a.title || "", sub: a.why || "",
    })).join("");
    // Bezit de stage de belasting al (focal + waarom-kaart), dan is de observatie
    // hier ruis: we herhalen hem niet.
    if (lo && lo.signalen && wrap.dataset.belOwned !== "1")
      c += dsStream([{ text: `Belasting-observatie: ${lo.signalen}`, tone: dsTone(lo.ernst) }]);
    ctx.innerHTML = c || `<p class="ws-calm">Geen actieve klacht of tegenstrijdigheid bekend.</p>`;
  }
}

// Snelle actie 'Belasting gezien' — dezelfde canonieke authority als Teampuls
// (/api/teampuls/gezien → belasting.markeer_gezien onder de stand-lock). Geen nieuwe write.
async function wsMarkeerGezien(key, ernst) {
  try {
    await jpost("/api/teampuls/gezien", { user_key: key, ernst });
    melding("Belasting-signaal gezien");
    if (wsSel === key) wsShow(key);                        // shell herladen (verse generatie)
  } catch { melding("Kon niet opslaan", true); }
}

laders.strippen = laad;
laders.atleten = laadDossierLijst;
laders.dossier = laadDossierCockpit;
laders.workspace = laadWorkspace;
laders.intake = laadIntake;
laders.documenten = laadDocs;
laders.feedback = fbEnter;
laders.schema = laadSchema;
laders.races = laadRaces;
laders["schema-verloop"] = laadSchemaVerloop;
laders.teampuls = laadTeampuls;
laders.admin = laadAdmin;
fbLogBind();
fbSummaryBind();
if ("serviceWorker" in navigator) {
  // Bij een nieuwe deploy installeert de nieuwe SW (skipWaiting + clients.claim) en
  // neemt de controle over → 'controllerchange'. De AL geladen pagina draait dan nog
  // de oude JS; daarom herladen we één keer zodat de nieuwe app.js/css meteen actief
  // wordt (anders bleef een tab op de oude bundel hangen). Draft-state overleeft de
  // reload (localStorage). Eerste installatie (nog geen controller) → niet herladen.
  let _hadCtrl = !!navigator.serviceWorker.controller, _swReloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!_hadCtrl) { _hadCtrl = true; return; }     // eerste claim, geen update
    if (_swReloaded) return; _swReloaded = true;
    location.reload();
  });
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
toonOffline();
if (navigator.onLine) flush();

// Verse gegevens zonder polling: keert de coach ná >30s terug naar de tab, dan
// laten we de lui-geladen lijsten (atleten/schema) hervalideren zodat een nieuwe
// intake niet minutenlang stale blijft. Nooit tijdens een open dossier/workbench,
// dus geen contextverlies. (#D)
let _laatstZichtbaar = Date.now();
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  const weg = Date.now() - _laatstZichtbaar; _laatstZichtbaar = Date.now();
  if (weg < 30000) return;                              // korte tab-switch: laat staan
  geladen.atleten = false; geladen.schema = false;      // eerstvolgende opening haalt vers op
  if (huidigeView === "atleten" && !dossierSel) { geladen.atleten = true; laadDossierLijst(); }
  const sbLijst = $("#sb-lijst");
  if (huidigeView === "schema" && sbLijst && sbLijst.offsetParent !== null) { geladen.schema = true; laadSchema(); }
});

applyRoute();                                           // herstel view/atleet uit de URL (#C), val terug op Home
