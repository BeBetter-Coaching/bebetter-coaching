// BeBetter PWA — strippenkaart (proto). Vanilla JS, geen build.
// Laat de dingen zien die Streamlit niet kan: direct reageren zonder herladen,
// swipe-om-af-te-boeken, installeren als app, en werken zonder netwerk (queue).

const $ = (s, r = document) => r.querySelector(s);
const api = (u, opt) => fetch(u, opt).then(r => r.json());
const haptic = ms => navigator.vibrate?.(ms);

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

// ── App installeren (beforeinstallprompt) ──────────────────────────────────
let deferred = null;
window.addEventListener("beforeinstallprompt", e => {
  e.preventDefault(); deferred = e; $("#install").hidden = false;
});
$("#install").addEventListener("click", async () => {
  if (!deferred) return;
  deferred.prompt(); await deferred.userChoice;
  deferred = null; $("#install").hidden = true;
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

// ── Start ──────────────────────────────────────────────────────────────────
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
toonOffline();
if (navigator.onLine) flush();
laad();
