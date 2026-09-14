// Trainingsweekend — openbare pagina. Geen login. De server bepaalt of het formulier
// er is (open, of testmodus met een beheersessie) en welke kosten zichtbaar zijn;
// deze pagina toont alleen wat /api/weekend teruggeeft en bevat zelf geen bedragen.
const $ = s => document.querySelector(s);
const q = new URLSearchParams(location.search);
const testGevraagd = q.get("test") === "1";

// Zelfde sessietoken als de PWA (localStorage) — alleen relevant voor testmodus.
const token = (() => { try { return localStorage.getItem("bb_token") || ""; } catch { return ""; } })();
const headers = extra => Object.assign(token ? { Authorization: "Bearer " + token } : {}, extra || {});

function euro(cent) {
  if (cent === null || cent === undefined) return "nog niet vastgesteld";
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" }).format(cent / 100);
}
function tijdstip(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return new Intl.DateTimeFormat("nl-NL", { dateStyle: "long", timeStyle: "short", timeZone: "Europe/Amsterdam" }).format(d);
}

let staat = null;

function akkoordTekst(k) {
  return `Ik ga akkoord met de deelnemersprijs van ${euro(k.deelnemersprijs_cent)}, de aanbetaling van `
    + `${euro(k.aanbetaling_cent)}, de betaaltermijn en de voorwaarden (versie ${k.voorwaarden_versie}).`;
}

function render(d) {
  staat = d;
  $("#wk-laden").hidden = true;
  $("#wk-testbalk").hidden = !d.testmodus;
  $("#wk-gesloten").hidden = d.formulier;
  $("#wk-gesloten-tekst").textContent = d.melding || "";
  $("#wk-form").hidden = !d.formulier;
  const k = d.kosten;
  $("#wk-kosten").hidden = !k;
  if (k) {
    $("#wk-prijs").textContent = euro(k.deelnemersprijs_cent);
    $("#wk-aanbetaling").textContent = euro(k.aanbetaling_cent);
    $("#wk-termijn").textContent = k.betaaltermijn || "Nog niet vastgesteld.";
    $("#wk-voorwaarden-tekst").textContent = k.voorwaarden || "Nog niet vastgesteld.";
    $("#wk-versie").textContent = k.voorwaarden_versie ? `versie ${k.voorwaarden_versie}` : "";
    $("#wk-akkoord-tekst").textContent = akkoordTekst(k);
    const mist = d.kosten_ontbreken || [];
    $("#wk-onvolledig").hidden = !mist.length;
    $("#wk-onvolledig").textContent = mist.length ? `Test: nog niet ingevuld — ${mist.join(", ")}.` : "";
  }
}

async function laad() {
  try {
    const r = await fetch(`/api/weekend${testGevraagd ? "?test=1" : ""}`, { headers: headers(), cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    render(await r.json());
  } catch {
    $("#wk-laden").textContent = "De inschrijfinformatie kon niet worden geladen. Probeer het later opnieuw.";
  }
}

function fout(txt) {
  const el = $("#wk-fout");
  el.textContent = txt; el.hidden = !txt;
  if (txt) el.scrollIntoView({ block: "center", behavior: "smooth" });
}

$("#wk-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (!staat || !staat.formulier) return;
  const f = e.target;
  const body = {
    naam: f.naam.value, email: f.email.value, telefoon: f.telefoon.value, website: f.website.value,
    bevestig_deelname: f.bevestig_deelname.checked, akkoord_voorwaarden: f.akkoord_voorwaarden.checked,
    voorwaarden_versie: staat.kosten ? staat.kosten.voorwaarden_versie : null,
    test: !!staat.testmodus,
  };
  if (!body.naam.trim() || !body.email.trim() || !body.telefoon.trim()) return fout("Vul je naam, e-mailadres en telefoonnummer in.");
  if (!body.bevestig_deelname) return fout("Bevestig dat je je definitief inschrijft.");
  if (!body.akkoord_voorwaarden) return fout("Ga akkoord met de kosten en voorwaarden om je in te schrijven.");
  fout("");
  const btn = $("#wk-verstuur");
  btn.disabled = true; btn.textContent = "Bezig met inschrijven…";
  try {
    const r = await fetch("/api/weekend/inschrijven", {
      method: "POST", headers: headers({ "Content-Type": "application/json" }), body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) return toonDank(d, body);
    if (r.status === 409 || r.status === 403) await laad();          // voorwaarden gewijzigd of dicht
    fout(d.err || "Inschrijven lukte niet. Probeer het zo nog eens.");
  } catch {
    fout("Geen verbinding. Controleer je internet en probeer het opnieuw.");
  }
  btn.disabled = false; btn.textContent = "Definitief inschrijven";
});

function toonDank(d, body) {
  $("#wk-form").hidden = true;
  $("#wk-dank").hidden = false;
  $("#wk-dank-tekst").textContent = d.test
    ? "Testinschrijving — deze telt niet mee als echte inschrijving."
    : "Dit is wat je hebt bevestigd.";
  const a = d.akkoord || {};
  const rijen = d.ingeschreven_op ? [
    ["Naam", body.naam.trim()], ["E-mail", body.email.trim()], ["Telefoon", body.telefoon.trim()],
    ["Deelnemersprijs", euro(a.deelnemersprijs_cent)], ["Aanbetaling", euro(a.aanbetaling_cent)],
    ["Voorwaarden", `versie ${a.voorwaarden_versie}`], ["Ingeschreven op", tijdstip(d.ingeschreven_op)],
  ] : [];
  const dl = $("#wk-samenvatting");
  dl.replaceChildren(...rijen.flatMap(([k, v]) => {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    return [dt, dd];
  }));
  $("#wk-dank").scrollIntoView({ block: "start", behavior: "smooth" });
}

laad();
