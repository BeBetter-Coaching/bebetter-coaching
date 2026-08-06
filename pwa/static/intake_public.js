// Publiek klant-intakeformulier — geen login, token in de link beschermt.
// Schrijft naar dezelfde intake-inbox als Streamlit (via /api/intake/public/*).
const $ = s => document.querySelector(s);
const q = new URLSearchParams(location.search);
const token = q.get("token") || "";
const resume = q.get("resume") || "";

function melding(txt, isErr = false) {
  const m = $("#msg");
  m.textContent = txt; m.classList.toggle("err", isErr); m.hidden = !txt;
  if (txt) { window.scrollTo({ top: 0, behavior: "smooth" }); }
}

function vulVoor(pre) {
  if (!pre || !Object.keys(pre).length) return;
  const f = $("#f");
  for (const el of f.elements) {
    if (!el.name || !(el.name in pre)) continue;
    const v = pre[el.name];
    if (el.type === "checkbox") continue;
    if (v != null) el.value = v;
  }
  // Ondergrond (checkboxes)
  const ond = pre.loopondergrond || [];
  if (Array.isArray(ond) && ond.length) {
    document.querySelectorAll("#ondergrond input").forEach(c => { c.checked = ond.includes(c.value); });
  }
  if (pre.naam) $("#welkom").textContent =
    `Welkom terug, ${pre.naam}! Je eerdere antwoorden staan er alvast in — vul aan of pas aan, en verstuur onderaan.`;
}

async function start() {
  const r = await fetch(`/api/intake/public/check?token=${encodeURIComponent(token)}&resume=${encodeURIComponent(resume)}`)
    .then(x => x.json()).catch(() => null);
  if (!r || !r.ok) { $("#ongeldig").hidden = false; return; }
  $("#app").hidden = false;
  vulVoor(r.prefill);
}

$("#f").addEventListener("submit", async e => {
  e.preventDefault();
  if (!$("#bevestig").checked) {
    return melding("Zet eerst het vinkje ‘Ja, ik ben klaar…’ aan en klik dan op Verstuur. "
      + "Zo voorkomen we dat het formulier per ongeluk te vroeg wordt verzonden.", true);
  }
  const f = e.target;
  const velden = {};
  for (const el of f.elements) {
    if (el.name && el.type !== "checkbox") velden[el.name] = el.value;
  }
  velden.loopondergrond = [...document.querySelectorAll("#ondergrond input:checked")].map(c => c.value);
  if (!velden.naam?.trim() || !velden.doel?.trim()) {
    return melding("Vul in elk geval je naam en je doel in.", true);
  }
  const btn = f.querySelector("button[type=submit]");
  btn.disabled = true; btn.textContent = "Versturen…";
  const r = await fetch("/api/intake/public/submit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, resume, velden }),
  }).then(x => x.json()).catch(() => null);
  if (r && r.ok) {
    $("#app").hidden = true; $("#dank").hidden = false; $("#msg").hidden = true;
    window.scrollTo({ top: 0 });
  } else {
    btn.disabled = false; btn.textContent = "Verstuur intake";
    melding(r?.err || "Er ging iets mis bij het versturen. Probeer het zo nog eens.", true);
  }
});

start();
