"""Feedback-module voor de PWA — AI-concept op de trainingen van atleten.

Hergebruikt fs_client (welke trainingen aandacht nodig hebben) + ai_feedback
(het AI-concept, in de stijl van de coach). V1 = ophalen + concept genereren +
kopiëren; het terugschrijven van de reactie naar FinalSurge is een aparte
write-stap (net als de schema-push) en volgt later.

Lui importeren: ai_feedback importeert ai_client → anthropic.Anthropic() dat
zonder ANTHROPIC_API_KEY al bij import crasht. Daarom pas binnen genereer().
fs_client is veilig te importeren (geen AI). De volledige workout-dicts cachen
we kort in het geheugen, zodat genereer() niet de zware lijst-call hoeft te
herhalen.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS                                  # veilig: geen AI

_cache: dict[str, dict] = {}                            # workout_key -> volledige workout_data


def heeft_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def _reacties(w: dict) -> list[str]:
    out = []
    for c in (w.get("athlete_comments") or []):
        if isinstance(c, str):
            tekst = c
        elif isinstance(c, dict):
            tekst = c.get("comment") or c.get("text") or c.get("message") or ""
        else:
            tekst = ""
        if tekst.strip():
            out.append(tekst.strip())
    return out


def te_beoordelen(days_back: int = 2) -> dict:
    """Trainingen die coaching-aandacht nodig hebben, genormaliseerd voor de lijst."""
    if not heeft_token():
        return {"items": [], "fs": False}
    try:
        workouts = FS.get_workouts_needing_feedback(days_back=days_back)
    except Exception:
        return {"items": [], "fs": True, "err": "Kon FinalSurge niet bereiken."}

    items = []
    for w in workouts:
        wid = w.get("workout_key") or (str(w.get("athlete_key", "")) + ":" + str(w.get("workout_date", "")))
        _cache[wid] = w
        naam = w.get("athlete_name", "")
        items.append({
            "id": wid,
            "naam": naam,
            "voornaam": w.get("athlete_first_name") or (naam.split(" ")[0] if naam else ""),
            "datum": (w.get("workout_date") or "")[:10],
            "workout": w.get("workout_name") or "Training",
            "notitie": (w.get("post_notes") or "").strip(),
            "reacties": _reacties(w),
        })
    return {"items": items, "fs": True}


def genereer(wid: str) -> str:
    """AI-concept voor de training met dit id (uit de gecachete lijst)."""
    w = _cache.get(wid)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst en probeer opnieuw.")
    import ai_feedback                                   # lui: pas hier is de key nodig
    return ai_feedback.generate_feedback(w)
