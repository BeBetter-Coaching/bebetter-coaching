"""FinalSurge-koppeling voor de PWA — read-only roster + trainingsdata.

Hergebruikt fs_client.py (Bearer-token REST-API op beta.finalsurge.com). Het
token komt uit de env-var FS_TOKEN (hetzelfde token dat al in Streamlit-secrets
staat), gezet op Render. Zonder token degradeert alles netjes (heeft_token()
False, lege lijsten) zodat de app nooit crasht — precies zoals Documenten zonder
AI-key blijft werken.

Bewust ALLEEN LEZEN in v1: roster + recente trainingen. Dit ontgrendelt de
volledige atletenlijst, echte data voor de dashboard-ringen en (straks) Feedback.
Workouts naar FinalSurge terugschrijven (schema-push) is een aparte, latere stap.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS                                  # PWA-veilig: geen Streamlit-import


def heeft_token() -> bool:
    """Is er een FinalSurge-token (env-var of lokaal)? Zonder token = alles leeg."""
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def roster() -> list[dict]:
    """Volledige atletenlijst uit FinalSurge (naam + user_key + groep + e-mail)."""
    if not heeft_token():
        return []
    try:
        atleten = FS.get_athletes()
    except Exception:
        return []
    out = []
    for a in atleten:
        out.append({
            "user_key": a.get("user_key", ""),
            "naam": a.get("name", "") or (a.get("first_name", "") + " " + a.get("last_name", "")).strip(),
            "voornaam": a.get("first_name", ""),
            "groep": a.get("group", ""),
            "email": a.get("email", ""),
        })
    out.sort(key=lambda x: str(x["naam"]).lower())
    return out


def recente_trainingen(user_key: str, dagen: int = 14) -> list[dict]:
    """Uitgevoerde trainingen van de afgelopen `dagen` — voor dashboard-signalen."""
    if not user_key or not heeft_token():
        return []
    einde = date.today()
    start = einde - timedelta(days=dagen)
    try:
        workouts = FS.get_workouts_deduped(user_key, start, einde)
    except Exception:
        return []
    gedaan = [w for w in workouts if FS.is_executed_workout(w)] if hasattr(FS, "is_executed_workout") else workouts
    return gedaan


def weeksamenvatting(user_key: str) -> dict:
    """Compact signaal per atleet: aantal uitgevoerde trainingen deze week (ma-zo)."""
    if not user_key or not heeft_token():
        return {"deze_week": 0}
    vandaag = date.today()
    maandag = vandaag - timedelta(days=vandaag.weekday())
    try:
        workouts = FS.get_workouts_deduped(user_key, maandag, vandaag)
        gedaan = [w for w in workouts if FS.is_executed_workout(w)]
        return {"deze_week": len(gedaan)}
    except Exception:
        return {"deze_week": 0}
