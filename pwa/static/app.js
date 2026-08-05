// BeBetter PWA — strippenkaart (proto). Praat met /api/*, dat op dezelfde opslag
// werkt als Streamlit. Vanilla JS, geen build-stap.

const $ = (s, r = document) => r.querySelector(s);
const api = (u, opt) => fetch(u, opt).then(r => r.json());

// ── Uitklappers + segmenten ────────────────────────────────────────────────
document.querySelectorAll(".acc-toggle").forEach(btn => {
  btn.addEventListener("click", () => $("#" + btn.dataset.target).classList.toggle("open"));
});
document.querySelectorAll(".seg").forEach(seg => {
  seg.addEventListener("click", e => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    seg.dataset.value = b.dataset.v;
    seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  });
});

// ── Meldingen ──────────────────────────────────────────────────────────────
function melding(txt, isErr = false) {
  const m = $("#msg");
  m.textContent = txt;
  m.classList.toggle("err", isErr);
  m.hidden = !txt;
  if (txt) setTimeout(() => { m.hidden = true; }, 4000);
}

// ── Lijst laden en tekenen ─────────────────────────────────────────────────
async function laad() {
  const data = await api("/api/kaarten");
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
  $(".k-naam", el).textContent = k.naam;
  $(".k-tel", el).textContent = k.telefoon || "geen nummer";
  $(".k-rest", el).textContent = `${k.rest} van ${k.totaal} over`;
  $(".bar-fill", el).style.width = (k.totaal ? (k.gebruikt / k.totaal) * 100 : 0) + "%";
  $(".k-laatst", el).textContent = k.laatst ? "Laatst afgeboekt: " + k.laatst : "";

  const afBtn = $(".k-af", el);
  afBtn.disabled = k.rest <= 0;
  afBtn.addEventListener("click", () => afboeken(k.naam, el, afBtn));
  $(".k-terug", el).disabled = k.gebruikt <= 0;
  $(".k-terug", el).addEventListener("click", () => actie(`/api/kaarten/${encodeURIComponent(k.naam)}/terug`, "POST"));
  $(".k-del", el).addEventListener("click", () => {
    if (confirm(`Strippenkaart van ${k.naam} verwijderen?`))
      actie(`/api/kaarten/${encodeURIComponent(k.naam)}`, "DELETE");
  });
  return el;
}

async function actie(url, method) {
  const r = await api(url, { method });
  if (!r.ok) return melding(r.err || "Er ging iets mis.", true);
  laad();
}

// ── Afboeken toont het WhatsApp-blok op de kaart ───────────────────────────
async function afboeken(naam, el, btn) {
  btn.disabled = true;
  const r = await api(`/api/kaarten/${encodeURIComponent(naam)}/afboeken`, { method: "POST" });
  if (!r.ok) { melding(r.err || "Afboeken mislukt.", true); return laad(); }
  await laad();
  // toon het whatsapp-blok op de zojuist getekende (nieuwe) kaart
  const kaart = [...document.querySelectorAll(".kaart")]
    .find(c => $(".k-naam", c).textContent === naam);
  if (kaart) {
    const wa = $(".wa", kaart);
    $(".wa-msg", wa).textContent = r.info.bericht;
    const link = $(".wa-btn", wa);
    if (r.info.wa_link) { link.href = r.info.wa_link; link.style.display = ""; }
    else { link.style.display = "none";
      $(".wa-msg", wa).textContent = r.info.bericht + "  (geen telefoonnummer bekend — vul het bij de kaart in)"; }
    wa.classList.remove("hidden");
    kaart.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

// ── Nieuwe kaart ───────────────────────────────────────────────────────────
$("#n-add").addEventListener("click", async () => {
  const naam = $("#n-naam").value.trim();
  const telefoon = $("#n-tel").value.trim();
  const aantal = +$("#n-aantal").dataset.value;
  if (!naam) return melding("Vul een naam in.", true);
  const r = await api("/api/kaarten", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ naam, aantal, telefoon }),
  });
  if (!r.ok) return melding(r.err, true);
  $("#n-naam").value = ""; $("#n-tel").value = "";
  melding(`${naam} toegevoegd.`);
  laad();
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
  if (!pv.nieuw.length && !pv.bestaat.length) {
    box.innerHTML = '<p class="muted">Niks gevonden om te importeren.</p>';
    return;
  }
  const rows = (pv.nieuw.length ? pv.nieuw : pv.bestaat)
    .map(r => `<tr><td>${esc(r.naam)}</td><td>${esc(r.telefoon || "—")}</td></tr>`).join("");
  let waarschuwing = "";
  if (pv.zonder_nr.length)
    waarschuwing = `<p class="hint">⚠️ ${pv.zonder_nr.length} zonder bruikbaar nummer (kaart wordt wel aangemaakt, nummer later invullen).</p>`;
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

// ── PWA service worker ─────────────────────────────────────────────────────
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/sw.js").catch(() => {});

laad();
