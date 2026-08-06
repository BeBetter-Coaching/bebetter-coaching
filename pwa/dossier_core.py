"""Gedeelde dossier-logica (store-only) — bruikbaar door de PWA-API.

Toont het deel van het atleet-dossier dat volledig uit de gedeelde opslag komt
(`intake_store`): intake & doel, coach-notities, documenten-logboek en het
coach-geheugen. Bewust ZONDER de FinalSurge-trainingsdata/grafieken: die vergen
een ingelogde FinalSurge-sessie en horen bij de 'lastige' migratiestap. Deze
module blijft daarom puur op de GitHub-backed store en deelt één bron met
Streamlit (wijziging hier zie je daar en andersom).

Geen `st.`-aanroepen: alleen pure functies en opslag-operaties.
"""

from __future__ import annotations

import os
import sys
from datetime import date

# repo-root op het pad zodat we het bestaande intake_store kunnen hergebruiken
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import intake_store  # noqa: E402


# Zelfde veld-volgorde en labels als het Streamlit-dossier, zodat het overzicht
# 1-op-1 herkenbaar is.
_INTAKE_VELDEN = [
    ("Doel", "doel"),
    ("Motivatie", "motivatie"),
    ("Wedstrijd", "wedstrijddatum_tekst"),
    ("Referentieprestatie", "referentie_prestatie"),
    ("PR's", "prs"),
    ("Loopervaring", "loopervaring"),
    ("Huidig volume", "huidig_volume"),
    ("Trainingsdagen", "trainingsdagen"),
    ("Tijd per training", "tijd_per_training"),
    ("Slaap/leefritme", "slaap"),
    ("Herstelcapaciteit", "herstelcapaciteit"),
    ("Blessurehistorie", "blessurehistorie"),
    ("Huidige klachten", "huidige_klachten"),
    ("Vindt leuk", "leuk"),
    ("Vindt niet leuk", "niet_leuk"),
    ("Eerdere schema-ervaring", "eerdere_schemas"),
    ("Wat werkte", "wat_werkte"),
    ("Wat niet werkte", "wat_niet_werkte"),
    ("Coach-notitie (intake)", "coach_notitie"),
]


def cloud_backed() -> bool:
    return intake_store.is_cloud_backed()


def _naam(key: str, intake: dict) -> str:
    """Weergavenaam: athlete_name als die er is, anders uit de sleutel afgeleid."""
    naam = (intake or {}).get("athlete_name") or (intake or {}).get("naam")
    if naam:
        return naam
    if key.startswith("nieuw:"):
        return key[6:].replace("_", " ").title()
    return key


def list_athletes() -> list[dict]:
    """Alle atleten met een opgeslagen intake, gesorteerd op naam.

    Basis is `intakes.json` (elke intake draagt athlete_name). Per atleet tellen
    we hoeveel coach-notities en documenten er zijn, zodat het overzicht meteen
    laat zien waar wat leeft.
    """
    intakes = intake_store.load_intakes()
    try:
        notes = intake_store.load_notes()
    except Exception:
        notes = {}
    try:
        docs = intake_store.load_documenten()
    except Exception:
        docs = {}

    out: list[dict] = []
    for key, ik in intakes.items():
        doel = (ik.get("doel") or "").split("\n")[0].strip()
        out.append({
            "key": key,
            "naam": _naam(key, ik),
            "doel": doel[:90],
            "nieuw": key.startswith("nieuw:"),
            "n_notities": len(notes.get(key, []) or []),
            "n_documenten": len(docs.get(key, []) or []),
            "bijgewerkt": ik.get("updated_at", ""),
        })
    out.sort(key=lambda a: (a["naam"] or "").lower())
    return out


def get_dossier(key: str) -> dict | None:
    """Volledig store-dossier voor één atleet, of None als onbekend."""
    intakes = intake_store.load_intakes()
    ik = intakes.get(key)
    if ik is None:
        return None

    velden = [
        {"label": lbl, "waarde": ik.get(k)}
        for lbl, k in _INTAKE_VELDEN
        if ik.get(k)
    ]

    try:
        notes = intake_store.load_notes().get(key, []) or []
    except Exception:
        notes = []
    try:
        docs = intake_store.load_documenten().get(key, []) or []
    except Exception:
        docs = []
    try:
        prof = intake_store.load_profielen().get(key, {}) or {}
    except Exception:
        prof = {}

    return {
        "key": key,
        "naam": _naam(key, ik),
        "nieuw": key.startswith("nieuw:"),
        "bijgewerkt": ik.get("updated_at", ""),
        "velden": velden,
        "notities": notes,
        "documenten": docs,
        "profiel": {
            "tekst": prof.get("profiel", ""),
            "bijgewerkt": prof.get("bijgewerkt", ""),
            "n": prof.get("n", 0),
        },
    }


def add_note(key: str, coach: str, tekst: str) -> tuple[bool, str]:
    """Voeg een coach-notitie toe (nieuwste eerst), gedeeld met Streamlit."""
    tekst = (tekst or "").strip()
    if not tekst:
        return False, "Lege notitie."
    coach = (coach or "").strip() or "Coach"
    notes = intake_store.load_notes()
    notes.setdefault(key, []).insert(0, {
        "datum": date.today().isoformat(),
        "coach": coach,
        "tekst": tekst,
    })
    return intake_store.save_notes(notes)


def delete_note(key: str, index: int) -> tuple[bool, str]:
    """Verwijder de notitie op positie `index` (nieuwste = 0)."""
    notes = intake_store.load_notes()
    lst = notes.get(key, [])
    if 0 <= index < len(lst):
        lst.pop(index)
        notes[key] = lst
        return intake_store.save_notes(notes)
    return True, ""


def save_profiel(key: str, tekst: str) -> tuple[bool, str]:
    """Bewaar (de door de coach aangepaste) coach-geheugentekst."""
    profielen = intake_store.load_profielen()
    prev = profielen.get(key, {}) or {}
    profielen[key] = {
        "profiel": (tekst or "").strip(),
        "bijgewerkt": date.today().isoformat(),
        "n": prev.get("n", 0),
    }
    return intake_store.save_profielen(profielen)
