// BeBetter PWA (proto). Vanilla JS, geen build. Drie modules op één shell:
// strippenkaart, dossier en intake-inbox — allemaal op dezelfde data als Streamlit.
// Laat de dingen zien die Streamlit niet kan: direct reageren zonder herladen,
// swipe-om-af-te-boeken, installeren als app, en werken zonder netwerk (queue).

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = (u, opt) => fetch(u, opt).then(r => r.json());
const jpost = (u, body, method = "POST") => api(u, {
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const haptic = ms => navigator.vibrate?.(ms);

// ── Tab-navigatie ────────────────────────────────────────────────────────────
const laders = {};   // view -> laadfunctie (eenmalig lui laden per tab)
const geladen = {};
function toonView(view) {
  $$(".tab").forEach(t => t.classList.toggle("on", t.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("on", v.dataset.view === view));
  if (laders[view] && !geladen[view]) { geladen[view] = true; laders[view](); }
}
$$(".tab").forEach(t => t.addEventListener("click", () => toonView(t.dataset.view)));

// ── Uitklappers + segmenten ────────────────────────────────────────────────
document.querySelectorAll(".acc-toggle").forEach(btn =>
  btn.addEventListener("click", () => $("#" + btn.dataset.target).classList.toggle("open")));
document.querySelectorAll(".seg").forEach(seg =>
  seg.addEventListener("click", e => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    seg.dataset.value = b.dataset.v;
    seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  }));

function melding(txt, isErr = false) {
  const m = $("#msg");
  m.textContent = txt; m.classList.toggle("err", isErr); m.hidden = !txt;
  if (txt) setTimeout(() => { m.hidden = true; }, 4000);
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
// Chrome/Edge geven een echte install-prompt (beforeinstallprompt). Safari niet,
// daar installeer je via het menu; dan tonen we uitleg i.p.v. "er gebeurt niks".
let deferred = null;
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); deferred = e; });
window.addEventListener("appinstalled", () => { $("#install").hidden = true; melding("Geïnstalleerd 🎉"); });

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
  if (isIOS) melding("iPhone/iPad: tik op de deelknop (vierkant met pijltje) → ‘Zet op beginscherm’.");
  else if (isSafari) melding("Safari op Mac: menubalk ‘Archief’ → ‘Voeg toe aan Dock’.");
  else melding("Klik op het installeer-icoon rechts in de adresbalk, of het menu (⋮) → ‘App installeren’.");
});
if (matchMedia("(display-mode: standalone)").matches) $("#install").hidden = true;

// ── Lijst laden en tekenen ─────────────────────────────────────────────────
async function laad() {
  let data;
  try { data = await api("/api/kaarten"); }
  catch { $("#bron").textContent = "offline — laatste bekende stand"; return; }
  $("#bron").textContent = data.cloud
    ? "verbonden met de gedeelde opslag (GitHub)"
    : "lokale opslag (zelfde bestand als Streamlit lokaal)";
  const lijst = $("#lijst");
  lijst.innerHTML = "";
  if (!data.kaarten.length) {
    lijst.innerHTML = '<p class="muted" style="text-align:center;margin-top:20px">Nog geen strippenkaarten. Voeg er hierboven een toe.</p>';
    return;
  }
  data.kaarten.forEach(k => lijst.appendChild(kaartEl(k)));
}

function kaartEl(k) {
  const el = $("#kaart-tpl").content.firstElementChild.cloneNode(true);
  el.dataset.naam = k.naam; el.dataset.totaal = k.totaal; el.dataset.gebruikt = k.gebruikt;
  $(".k-naam", el).textContent = k.naam;
  $(".k-tel", el).textContent = k.telefoon || "geen nummer";
  $(".k-rest", el).textContent = `${k.rest} van ${k.totaal} over`;
  $(".bar-fill", el).style.width = (k.totaal ? (k.gebruikt / k.totaal) * 100 : 0) + "%";
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

// ── Afboeken: direct zichtbaar (optimistisch), daarna server ───────────────
function optimistischAf(el) {
  const tot = +el.dataset.totaal, geb = +el.dataset.gebruikt + 1;
  el.dataset.gebruikt = geb;
  const rest = Math.max(0, tot - geb);
  const restEl = $(".k-rest", el);
  restEl.textContent = `${rest} van ${tot} over`;
  restEl.classList.remove("bump"); void restEl.offsetWidth; restEl.classList.add("bump");
  $(".bar-fill", el).style.width = (tot ? geb / tot * 100 : 0) + "%";
  const fg = $(".swipe-fg", el);
  fg.classList.remove("flash"); void fg.offsetWidth; fg.classList.add("flash");
  $(".k-af", el).disabled = rest <= 0;
  return rest;
}

async function afboek(naam, el) {
  if (+el.dataset.totaal - +el.dataset.gebruikt <= 0) return;
  haptic(15);
  optimistischAf(el);   // meteen zichtbaar, geen herlaad-flikker
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

// ── Swipe-om-af-te-boeken (muis + touch via pointer events) ────────────────
function addSwipe(el) {
  const fg = $(".swipe-fg", el);
  let x0 = 0, dx = 0, drag = false;
  fg.addEventListener("pointerdown", e => {
    if (e.target.closest("button,a")) return;   // knoppen blijven gewoon werken
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

// ── Nieuwe kaart ───────────────────────────────────────────────────────────
$("#n-add").addEventListener("click", async () => {
  const naam = $("#n-naam").value.trim(), telefoon = $("#n-tel").value.trim();
  const aantal = +$("#n-aantal").dataset.value;
  if (!naam) return melding("Vul een naam in.", true);
  const r = await api("/api/kaarten", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ naam, aantal, telefoon }),
  }).catch(() => null);
  if (!r) return melding("Geen verbinding.", true);
  if (!r.ok) return melding(r.err, true);
  $("#n-naam").value = ""; $("#n-tel").value = "";
  melding(`${naam} toegevoegd.`); laad();
});

// ── Bulk-import ────────────────────────────────────────────────────────────
let bulkText = "";
$("#b-vcf").addEventListener("change", async e => {
  const f = e.target.files[0];
  if (f) { bulkText = await f.text(); melding(`${f.name} gekozen — klik op Controleer.`); }
});
$("#b-check").addEventListener("click", async () => {
  const text = ($("#b-text").value + "\n" + bulkText).trim();
  if (!text) return melding("Plak namen of kies een .vcf-bestand.", true);
  const pv = await api("/api/import/preview", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
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
      <button class="btn primary" id="b-do" ${pv.nieuw.length ? "" : "disabled"}>✓ ${pv.nieuw.length} toevoegen</button>
      <button class="btn ghost" id="b-cancel">Annuleer</button>
    </div>`;
  $("#b-do")?.addEventListener("click", async () => {
    const aantal = +$("#b-aantal").dataset.value;
    const r = await api("/api/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: pv.nieuw.concat(pv.bestaat), aantal }),
    });
    if (!r.ok) return melding(r.err, true);
    box.innerHTML = ""; $("#b-text").value = ""; bulkText = "";
    melding(`${r.toegevoegd} toegevoegd${r.aangevuld ? `, ${r.aangevuld} nummer aangevuld` : ""}.`);
    laad();
  });
  $("#b-cancel")?.addEventListener("click", () => { box.innerHTML = ""; });
}

const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ════════════════════════════════════════════════════════════════════════════
// DOSSIER — store-only 360° per atleet (intake, notities, documenten, geheugen)
// ════════════════════════════════════════════════════════════════════════════
let dossierCache = [];

async function laadDossierLijst() {
  const box = $("#d-lijst");
  box.innerHTML = '<p class="muted center">Laden…</p>';
  let data;
  try { data = await api("/api/dossier/athletes"); }
  catch { box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  dossierCache = data.athletes || [];
  tekenDossierLijst("");
}

function tekenDossierLijst(filter) {
  const box = $("#d-lijst");
  $("#d-detail").hidden = true; box.hidden = false;
  const f = filter.trim().toLowerCase();
  const rijen = dossierCache.filter(a => !f || (a.naam || "").toLowerCase().includes(f));
  if (!rijen.length) {
    box.innerHTML = `<p class="muted center">${dossierCache.length
      ? "Geen atleet gevonden." : "Nog geen intakes opgeslagen."}</p>`;
    return;
  }
  box.innerHTML = "";
  rijen.forEach(a => {
    const el = document.createElement("article");
    el.className = "rij-kaart";
    el.innerHTML = `
      <div class="rij-top">
        <h3>${esc(a.naam)}${a.nieuw ? ' <span class="tag">nieuw</span>' : ""}</h3>
        <span class="chev">›</span>
      </div>
      ${a.doel ? `<p class="muted klein">${esc(a.doel)}</p>` : ""}
      <div class="meta">
        ${a.n_notities ? `🗒️ ${a.n_notities}` : ""}
        ${a.n_documenten ? ` &nbsp; 📄 ${a.n_documenten}` : ""}
      </div>`;
    el.addEventListener("click", () => openDossier(a.key));
    box.appendChild(el);
  });
}

$("#d-zoek").addEventListener("input", e => tekenDossierLijst(e.target.value));

async function openDossier(key) {
  const wrap = $("#d-detail");
  $("#d-lijst").hidden = true; wrap.hidden = false;
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
        <button class="btn danger-ghost mini" data-del-note="${i}">🗑</button></div>
      <p>${esc(n.tekst || "")}</p>
    </div>`).join("") || '<p class="muted klein">Nog geen notities.</p>';

  const docs = d.documenten.map(x => `
    <div class="doc">
      <span class="doc-d">${esc(x.datum || "")}</span>
      <span>${esc(x.type || "")}${x.onderwerp ? " — " + esc(x.onderwerp) : ""}</span>
    </div>`).join("") || '<p class="muted klein">Nog geen documenten.</p>';

  const p = d.profiel;
  const wrap = $("#d-detail");
  wrap.innerHTML = `
    <button class="btn ghost small" id="d-terug">‹ Terug naar lijst</button>
    <h2 class="d-naam">${esc(d.naam)}${d.nieuw ? ' <span class="tag">nieuw</span>' : ""}</h2>

    <section class="panel open-static">
      <h3 class="panel-h">📝 Intake &amp; doel</h3>
      ${velden}
    </section>

    <section class="panel open-static">
      <h3 class="panel-h">🗒️ Coach-notities <span class="muted klein">(gedeeld Jip &amp; Remco)</span></h3>
      <div class="row">
        <input id="nt-tekst" placeholder="Nieuwe notitie…">
        <div class="seg" id="nt-coach" data-value="Jip">
          <button data-v="Jip" class="on">Jip</button>
          <button data-v="Remco">Remco</button>
        </div>
        <button class="btn primary" id="nt-add">➕</button>
      </div>
      <div id="nt-lijst">${notities}</div>
    </section>

    <section class="panel">
      <button class="acc-toggle" data-target="d-docs">📄 Documenten (${d.documenten.length})</button>
      <div id="d-docs" class="collapse">${docs}</div>
    </section>

    <section class="panel">
      <button class="acc-toggle" data-target="d-prof">🧠 Coach-geheugen</button>
      <div id="d-prof" class="collapse">
        <p class="hint">Wat de AI over deze atleet weet. Groeit mee bij feedback in Streamlit;
          jouw aanpassing is leidend.${p.bijgewerkt ? " Laatst bijgewerkt: " + esc(p.bijgewerkt) + "." : ""}</p>
        <textarea id="pf-tekst" rows="5" placeholder="Nog leeg.">${esc(p.tekst || "")}</textarea>
        <button class="btn primary" id="pf-save">💾 Geheugen opslaan</button>
      </div>
    </section>`;

  // Uitklappers + segmenten binnen het dossier activeren
  wrap.querySelectorAll(".acc-toggle").forEach(btn =>
    btn.addEventListener("click", () => $("#" + btn.dataset.target).classList.toggle("open")));
  wrap.querySelectorAll(".seg").forEach(seg => seg.addEventListener("click", e => {
    const b = e.target.closest("button[data-v]"); if (!b) return;
    seg.dataset.value = b.dataset.v;
    seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  }));

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
      const i = +btn.dataset.delNote;
      const r = await api(`/api/dossier/${encodeURIComponent(d.key)}/note/${i}`, { method: "DELETE" }).catch(() => null);
      if (!r || !r.ok) return melding(r?.err || "Verwijderen mislukt.", true);
      openDossier(d.key); vervalDossierLijst();
    }));

  $("#pf-save").addEventListener("click", async () => {
    const r = await jpost(`/api/dossier/${encodeURIComponent(d.key)}/profiel`,
      { tekst: $("#pf-tekst").value }).catch(() => null);
    if (!r || !r.ok) return melding(r?.err || "Opslaan mislukt.", true);
    melding("Geheugen opgeslagen.");
  });
}

// notitie/doc-tellingen kunnen na een wijziging kloppen bij terugkeer naar de lijst
function vervalDossierLijst() { geladen.dossier = false; laders.dossier = laadDossierLijst; laadDossierLijst(); }

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
         <button class="btn small" id="i-copy">📋 Kopieer</button></div>
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
  box.innerHTML = '<p class="muted center">Laden…</p>';
  const r = await api("/api/intake/inbox").catch(() => null);
  if (!r) { box.innerHTML = '<p class="muted center">Geen verbinding.</p>'; return; }
  const inbox = r.inbox || [];
  if (!inbox.length) { box.innerHTML = '<p class="muted center">Nog geen nieuwe inzendingen.</p>'; return; }
  box.innerHTML = "";
  inbox.forEach(sub => {
    const rijen = sub.rijen.map(x =>
      `<tr><td>${esc(x.vraag)}</td><td>${esc(x.antwoord)}</td></tr>`).join("");
    const el = document.createElement("article");
    el.className = "rij-kaart";
    el.innerHTML = `
      <h3>${esc(sub.naam)}</h3>
      <p class="muted klein">ingezonden ${esc(sub.ingezonden)}${sub.email ? " · " + esc(sub.email) : ""}</p>
      <button class="acc-toggle sub" data-open>Bekijk antwoorden ▾</button>
      <div class="collapse"><table class="pv-tbl">${rijen}</table></div>
      <div class="row">
        <button class="btn primary" data-take>➕ Overnemen als intake</button>
        <button class="btn danger-ghost" data-del>🗑</button>
      </div>`;
    el.querySelector("[data-open]").addEventListener("click", e =>
      e.target.nextElementSibling.classList.toggle("open"));
    el.querySelector("[data-take]").addEventListener("click", async () => {
      const r2 = await api(`/api/intake/inbox/${encodeURIComponent(sub.id)}/take`, { method: "POST" }).catch(() => null);
      if (!r2 || !r2.ok) return melding(r2?.err || "Overnemen mislukt.", true);
      melding(`'${r2.naam}' overgenomen — staat nu in Dossier.`);
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
laders.dossier = laadDossierLijst;
laders.intake = laadIntake;
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
toonOffline();
if (navigator.onLine) flush();
laad();
