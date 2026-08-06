"""Gedeelde intake-logica — publiek klantformulier + coach-inbox.

Deelt één bron met Streamlit via `intake_store`: het publieke formulier schrijft
naar de intake-inbox (`intake_inbox.json`), de coach reviewt en neemt over als
intake (`intakes.json`). De deelbare link wordt beschermd met een token
(`intake_link.json`). Gedrag is 1-op-1 gelijk aan de Streamlit-modules
(`intake_form.py` + de inbox in `intake_page.py`).

Geen `st.`-aanroepen: alleen pure functies en opslag-operaties. De volledige URL
van de deelbare link stelt de voorkant zelf samen uit de eigen origin + token,
zodat deze module hosting-onafhankelijk blijft.
"""

from __future__ import annotations

import os
import secrets
import sys
import uuid
from datetime import date, datetime

# repo-root op het pad zodat we het bestaande intake_store kunnen hergebruiken
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import intake_store  # noqa: E402


# Keuze-opties gelijk aan de coach-intake, zodat overnemen 1-op-1 werkt.
KWALITEIT = ["Weinig/geen", "Enige ervaring", "Regelmatig"]
HERSTEL = ["Langzaam", "Normaal", "Snel"]
WERKDRUK = ["Laag", "Normaal", "Hoog"]
ONDERGROND = ["Weg", "Trail", "Baan", "Loopband"]

# Toegestane tekstvelden uit het publieke formulier (strippen + opslaan).
_TEKST_VELDEN = [
    "naam", "email", "leeftijd", "horloge", "doel", "wedstrijddatum_tekst",
    "huidig_volume", "langste_afstand", "referentie_prestatie", "loopervaring",
    "prs", "trainingsdagen", "tijd_per_training", "eerdere_schemas",
    "wat_werkte", "wat_niet_werkte", "leuk", "niet_leuk", "slaap",
    "blessurehistorie", "huidige_klachten", "andere_sporten", "motivatie",
    "notities",
]

# Labels voor de inbox-weergave bij de coach (zelfde set als Streamlit).
INBOX_LABELS = [
    ("E-mail", "email"), ("Leeftijd", "leeftijd"), ("Horloge", "horloge"),
    ("Doel", "doel"), ("Wedstrijd", "wedstrijddatum_tekst"),
    ("Volume/wk", "huidig_volume"), ("Langste loop", "langste_afstand"),
    ("Referentie", "referentie_prestatie"), ("Loopervaring", "loopervaring"),
    ("PR's", "prs"), ("Trainingsdagen", "trainingsdagen"), ("Tijd/training", "tijd_per_training"),
    ("Kwaliteitservaring", "kwaliteitservaring"), ("Ondergrond", "loopondergrond"),
    ("Eerdere schema's", "eerdere_schemas"), ("Wat werkte", "wat_werkte"),
    ("Wat niet werkte", "wat_niet_werkte"), ("Vindt leuk", "leuk"), ("Vindt niks", "niet_leuk"),
    ("Herstel", "herstelcapaciteit"), ("Werkdruk", "werkdruk"), ("Slaap", "slaap"),
    ("Blessures", "blessurehistorie"), ("Klachten", "huidige_klachten"),
    ("Andere sporten", "andere_sporten"), ("Motivatie", "motivatie"), ("Overig", "notities"),
]


def cloud_backed() -> bool:
    return intake_store.is_cloud_backed()


# ── Deelbare-link-token ─────────────────────────────────────────────────────
def link_token() -> str:
    try:
        return (intake_store.load_intake_link() or {}).get("token", "")
    except Exception:
        return ""


def new_link_token() -> str:
    """Genereer + bewaar een nieuwe token (maakt oude links ongeldig)."""
    token = secrets.token_urlsafe(9)
    intake_store.save_intake_link({"token": token})
    return token


def token_valid(token: str) -> bool:
    huidig = link_token()
    return bool(huidig) and secrets.compare_digest(token or "", huidig)


# ── Publiek formulier ───────────────────────────────────────────────────────
def _keuze(waarde, opts: list[str], fallback: str) -> str:
    return waarde if waarde in opts else fallback


def sanitize_velden(raw: dict) -> dict:
    """Maak een schoon, opslagbaar velden-dict van ruwe formulier-input."""
    raw = raw or {}
    velden = {k: str(raw.get(k, "") or "").strip() for k in _TEKST_VELDEN}
    velden["kwaliteitservaring"] = _keuze(raw.get("kwaliteitservaring"), KWALITEIT, "Enige ervaring")
    velden["herstelcapaciteit"] = _keuze(raw.get("herstelcapaciteit"), HERSTEL, "Normaal")
    velden["werkdruk"] = _keuze(raw.get("werkdruk"), WERKDRUK, "Normaal")
    ondergrond = raw.get("loopondergrond") or []
    if isinstance(ondergrond, str):
        ondergrond = [ondergrond]
    ondergrond = [o for o in ondergrond if o in ONDERGROND]
    velden["loopondergrond"] = ondergrond or ["Weg"]
    return velden


def get_submission(iid: str) -> dict:
    """Bestaande inzending ophalen (voor 'aanvullen'); leeg als niet gevonden."""
    if not iid:
        return {}
    try:
        return (intake_store.load_intake_inbox() or {}).get(iid, {}) or {}
    except Exception:
        return {}


def public_submit(raw: dict, resume_id: str = "") -> tuple[bool, str]:
    """Sla een publieke inzending op. Naam en doel zijn verplicht.

    Met een bestaand ``resume_id`` wordt dezelfde inzending bijgewerkt i.p.v. een
    nieuwe aangemaakt (zelfde gedrag als de Streamlit-aanvullink).
    """
    velden = sanitize_velden(raw)
    if not velden["naam"] or not velden["doel"]:
        return False, "Vul in elk geval je naam en je doel in."
    try:
        inbox = intake_store.load_intake_inbox()
    except Exception:
        inbox = {}
    _id = resume_id if (resume_id and resume_id in inbox) else \
        f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    inbox[_id] = {**velden, "status": "nieuw",
                  "ingezonden": datetime.now().isoformat(timespec="minutes")}
    return intake_store.save_intake_inbox(inbox)


# ── Coach-inbox ─────────────────────────────────────────────────────────────
def inbox_list() -> list[dict]:
    """Wachtende inzendingen (status 'nieuw'), nieuwste eerst, met nette rijen."""
    try:
        inbox = intake_store.load_intake_inbox()
    except Exception:
        inbox = {}
    out: list[dict] = []
    for iid, sub in sorted(inbox.items(), reverse=True):
        if sub.get("status") != "nieuw":
            continue
        rijen = []
        for lbl, k in INBOX_LABELS:
            v = sub.get(k)
            if isinstance(v, list):
                v = ", ".join(v)
            if v and str(v).strip():
                rijen.append({"vraag": lbl, "antwoord": str(v)})
        out.append({
            "id": iid,
            "naam": sub.get("naam", "?"),
            "doel": (sub.get("doel", "") or "")[:90],
            "email": sub.get("email", ""),
            "ingezonden": sub.get("ingezonden", ""),
            "rijen": rijen,
        })
    return out


def inbox_take(iid: str) -> tuple[bool, str, str]:
    """Neem een inzending over als nieuwe-klant-intake. Geeft (ok, err, naam)."""
    try:
        inbox = intake_store.load_intake_inbox()
    except Exception:
        inbox = {}
    sub = inbox.get(iid)
    if not sub:
        return False, "Inzending niet gevonden.", ""
    naam = (sub.get("naam") or "Nieuwe klant").strip()
    key = "nieuw:" + naam.lower().replace(" ", "_")
    velden = {k: v for k, v in sub.items() if k not in ("status", "ingezonden")}
    intakes = intake_store.load_intakes()
    intakes[key] = {"athlete_name": naam, **velden, "updated_at": date.today().isoformat()}
    ok, err = intake_store.save_intakes(intakes)
    if not ok:
        return False, err, naam
    inbox[iid]["status"] = "verwerkt"
    intake_store.save_intake_inbox(inbox)
    return True, "", naam


def inbox_delete(iid: str) -> tuple[bool, str]:
    try:
        inbox = intake_store.load_intake_inbox()
    except Exception:
        inbox = {}
    if iid in inbox:
        inbox.pop(iid)
        return intake_store.save_intake_inbox(inbox)
    return True, ""
