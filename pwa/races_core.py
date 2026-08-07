"""Races-module voor de PWA — aankomende races per atleet, met race-wens.

Hergebruikt fs_client.get_upcoming_races (leest is_race-workouts + bestaande
coach-comments = wens al gegeven). Het plaatsen van een race-wens is een
WRITE-actie die exact fs_client.post_comment hergebruikt (net als feedback).
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS

_cache: dict[str, dict] = {}                        # workout_key -> race-dict


def heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def _wens(race: dict) -> str:
    """De laatste coach-comment als lopende wenstekst (of '')."""
    coach = [c for c in (race.get("comments") or [])
             if isinstance(c, dict) and not c.get("is_athlete")]
    for c in reversed(coach):
        t = (c.get("comment") or "").strip()
        if t:
            return t
    return ""


def komende(days_ahead: int = 42) -> dict:
    """Aankomende races, genormaliseerd voor de lijst."""
    if not heeft_token():
        return {"items": [], "fs": False}
    try:
        races = FS.get_upcoming_races(days_ahead=days_ahead)
    except Exception:
        return {"items": [], "fs": True, "err": "Kon FinalSurge niet bereiken."}

    items = []
    for r in races:
        wid = r.get("workout_key", "")
        _cache[wid] = r
        naam = r.get("athlete_name", "")
        items.append({
            "id": wid,
            "naam": naam,
            "voornaam": r.get("athlete_first_name") or (naam.split(" ")[0] if naam else ""),
            "datum": (r.get("workout_date") or "")[:10],
            "race": r.get("workout_name") or "Race",
            "type": r.get("race_type") or "",
            "wens_gegeven": bool(r.get("wish_given")),
            "wens": _wens(r),
        })
    return {"items": items, "fs": True}


def _coach_athlete_key(athlete_key: str):
    try:
        for a in FS.get_athletes():
            if a.get("user_key") == athlete_key:
                return a.get("coach_athlete_key")
    except Exception:
        pass
    return None


def plaats_wens(wid: str, tekst: str) -> bool:
    """Plaats een race-wens als coach-comment. WRITE-actie (post_comment)."""
    r = _cache.get(wid)
    if not r:
        raise ValueError("Race niet meer in beeld — ververs de lijst.")
    tekst = (tekst or "").strip()
    if not tekst:
        raise ValueError("Lege race-wens.")
    ak = r.get("athlete_key", "")
    wk = r.get("workout_key", "")
    if not (ak and wk):
        raise ValueError("Geen FinalSurge-koppeling voor deze race.")
    FS.post_comment(workout_key=wk, user_key=ak, comment=tekst,
                    coach_athlete_key=_coach_athlete_key(ak))
    return True
