// Weekendbeheer — Jip, Remco en Tim. Alle data komt uit /api/weekend/beheer*, die de
// server alleen aan een beheersessie geeft. Deze pagina verbergt niets om te beveiligen.
const $ = s => document.querySelector(s);
const getToken = () => { try { return localStorage.getItem("bb_token") || ""; } catch { return ""; } };
const setToken = t => { try { t ? localStorage.setItem("bb_token", t) : localStorage.removeItem("bb_token"); } catch {} };
const escAttr = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
function tijdstip(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d)) return "";
  return new Intl.DateTimeFormat("nl-NL", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Amsterdam" }).format(d);
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
function toonLogin(fout = "") {
  $("#wb-app").hidden = true; $("#wb-login").hidden = false;
  $("#wb-who").hidden = false; $("#wb-pw").hidden = true; loginWie = null;
  $("#wb-login-err").textContent = fout; $("#wb-login-err").hidden = !fout;
}
document.querySelectorAll(".wb-who").forEach(b => b.addEventListener("click", () => {
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

// ── Renderen ────────────────────────────────────────────────────────────────
let data = null;
let rol = "";

function renderStatus() {
  const open = data.open, mist = data.ontbreekt || [];
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
}

function renderKosten(forceer = false) {
  const f = $("#wb-kosten"), inst = data.instellingen;
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
}

function optie(labels, huidig) {
  return Object.entries(labels).map(([k, l]) => `<option value="${escAttr(k)}"${k === huidig ? " selected" : ""}>${escAttr(l)}</option>`).join("");
}

function renderLijst() {
  const toonTest = $("#wb-toon-test").checked;
  const t = data.tellingen, L = data.labels;
  const teller = (n, lbl) => `<span class="wb-teller"><b>${n}</b> ${escAttr(lbl)}</span>`;
  const groep = (titel, inhoud) => `<div class="wb-tgroep"><span class="wb-tgroep-lbl">${titel}</span>${inhoud}</div>`;
  const perStatus = veld => Object.entries(L[veld]).map(([k, l]) => teller(t[veld][k], l.toLowerCase())).join("");
  // Tellingen zonder testinschrijvingen; die staan er apart naast.
  $("#wb-tellers").innerHTML = groep("Totaal", teller(t.totaal, t.totaal === 1 ? "inschrijving" : "inschrijvingen")
      + (t.test ? teller(t.test, t.test === 1 ? "test" : "tests") : ""))
    + groep("Inschrijving", perStatus("inschrijfstatus"))
    + groep("Betaling", perStatus("betaalstatus"));

  const versie = data.instellingen.voorwaarden_versie || 0;
  const rijen = data.inschrijvingen.filter(r => toonTest || !r.test);
  if (!rijen.length) {
    $("#wb-rijen").innerHTML = `<p class="wb-leeg">${data.inschrijvingen.length ? "Alleen testinschrijvingen — zet ‘Testinschrijvingen tonen’ aan." : "Nog geen inschrijvingen."}</p>`;
    return;
  }
  $("#wb-rijen").innerHTML = rijen.map(r => {
    const a = r.akkoord || {};
    const tags = [
      r.test ? `<span class="wb-tag is-attention">Test${r.test_door ? " · " + escAttr(r.test_door) : ""}</span>` : "",
      r.mogelijk_dubbel ? `<span class="wb-tag is-attention">Mogelijk dubbel</span>` : "",
      a.voorwaarden_versie !== versie ? `<span class="wb-tag is-stale">Andere versie dan huidig</span>` : "",
    ].join("");
    const hist = (r.historie || []).slice().reverse().map(h =>
      `<li>${escAttr(tijdstip(h.op))} · ${escAttr(h.door)}: ${escAttr((L[h.veld] || {})[h.van] || h.van)} → ${escAttr((L[h.veld] || {})[h.naar] || h.naar)}</li>`).join("");
    return `<article class="wb-rij${r.test ? " is-test" : ""}${r.inschrijfstatus === "geannuleerd" ? " is-geannuleerd" : ""}">
      <div class="wb-rij-kop"><h3>${escAttr(r.naam)}</h3>${tags}</div>
      <div class="wb-contact"><span>${escAttr(r.email)}</span><span>${escAttr(r.telefoon)}</span></div>
      <dl class="wb-akkoord">
        <dt>Ingeschreven</dt><dd>${escAttr(tijdstip(r.ingeschreven_op))}</dd>
        <dt>Akkoord prijs</dt><dd>${escAttr(euro(a.deelnemersprijs_cent))}</dd>
        <dt>Akkoord aanbetaling</dt><dd>${escAttr(euro(a.aanbetaling_cent))}</dd>
        <dt>Voorwaarden</dt><dd>versie ${escAttr(a.voorwaarden_versie)}</dd>
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

function render(forceerKosten = false) {
  $("#wb-login").hidden = true; $("#wb-app").hidden = false;
  $("#wb-wie").textContent = data.wie ? `Ingelogd als ${data.wie}` : "";
  $("#wb-naar-app").hidden = rol !== "coach";
  renderStatus(); renderKosten(forceerKosten); renderLijst();
}

async function laad(forceerKosten = false) {
  data = await api("/api/weekend/beheer");
  render(forceerKosten);
}
function metNieuweData(d, forceerKosten = false) { data = { ...d, wie: data.wie }; render(forceerKosten); }

// ── Acties ──────────────────────────────────────────────────────────────────
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
  } catch (err) { if (err.message !== "auth") toast(err.message, true); }
  btn.disabled = false;
});

$("#wb-open-btn").addEventListener("click", async () => {
  const open = !data.open;
  const ok = await bevestig(open ? "Inschrijving openen?" : "Inschrijving sluiten?",
    open ? `Vanaf nu kan iedereen met de link zich definitief inschrijven met voorwaardenversie ${data.instellingen.voorwaarden_versie}.`
      : "Bezoekers zien weer dat de inschrijving binnenkort opent. Bestaande inschrijvingen blijven staan.",
    open ? "Openen" : "Sluiten");
  if (!ok) return;
  try { metNieuweData(await post("/api/weekend/beheer/inschrijving-open", { open })); toast(open ? "Inschrijving is open." : "Inschrijving is gesloten."); }
  catch (err) { if (err.message !== "auth") toast(err.message, true); }
});

$("#wb-rijen").addEventListener("change", async e => {
  const sel = e.target.closest("select[data-veld]");
  if (!sel) return;
  const { id, veld, verwacht } = sel.dataset;
  sel.disabled = true;
  try {
    metNieuweData(await post(`/api/weekend/beheer/inschrijvingen/${encodeURIComponent(id)}/${veld}`, { waarde: sel.value, verwacht }));
    toast(`${veld === "betaalstatus" ? "Betaalstatus" : "Inschrijfstatus"} bijgewerkt.`);
  } catch (err) {
    sel.value = verwacht; sel.disabled = false;
    if (err.message !== "auth") toast(err.message, true);
  }
});

$("#wb-rijen").addEventListener("click", async e => {
  const b = e.target.closest("[data-weg]");
  if (!b) return;
  const ok = await bevestig("Testinschrijving verwijderen?", "Alleen testinschrijvingen kunnen weg. Dit is niet terug te draaien.", "Verwijderen");
  if (!ok) return;
  try { metNieuweData(await api(`/api/weekend/beheer/inschrijvingen/${encodeURIComponent(b.dataset.weg)}`, { method: "DELETE" })); toast("Testinschrijving verwijderd."); }
  catch (err) { if (err.message !== "auth") toast(err.message, true); }
});

$("#wb-toon-test").addEventListener("change", () => data && renderLijst());
$("#wb-ververs").addEventListener("click", () => laad().then(() => toast("Bijgewerkt.")).catch(err => { if (err.message !== "auth") toast(err.message, true); }));

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
