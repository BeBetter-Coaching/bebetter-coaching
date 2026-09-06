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

_cache: dict[str, dict] = {}                        # workout_key -> race-dict (begrensd)
_CACHE_MAX = 400                                    # ruim boven elke realistische raceslijst


def _prune_cache() -> None:
    """Houd de wens-lookup begrensd; dicts bewaren invoegvolgorde, dus de oudste gaat eruit."""
    while len(_cache) > _CACHE_MAX:
        _cache.pop(next(iter(_cache)), None)


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


# ── Het Home-chip-venster ────────────────────────────────────────────────────
# De Home-chip belooft "races komende N dagen zonder wens". Die belofte en de Races-
# pagina moeten dezelfde datum- én filterlogica gebruiken, anders opent een chip van 9
# een pagina met 60. Daarom staat het venster HIER, wordt het door home_core gelezen
# voor de telling, en past de Races-pagina exact hetzelfde filter toe.
CHIP_DAGEN = 7
CHIP_SCOPE = "7d"                                   # route-token (#races/7d)


def chip_count() -> int:
    """Het getal op de Home-chip: races binnen CHIP_DAGEN waarvoor nog geen wens staat.
    Zelfde bron + filter als `komende(days_ahead=CHIP_DAGEN, alleen_zonder_wens=True)`."""
    if not heeft_token():
        return 0
    try:
        return sum(1 for r in FS.get_upcoming_races(days_ahead=CHIP_DAGEN)
                   if not r.get("wish_given"))
    except Exception:
        return 0


def komende(days_ahead: int = 42, alleen_zonder_wens: bool = False) -> dict:
    """Aankomende races, genormaliseerd voor de lijst.

    `alleen_zonder_wens` = het actionable deel (wat de Home-chip telt); met
    days_ahead=CHIP_DAGEN levert dat exact `chip_count()` items."""
    if not heeft_token():
        return {"items": [], "fs": False}
    try:
        races = FS.get_upcoming_races(days_ahead=days_ahead)
    except Exception:
        return {"items": [], "fs": True, "err": "Kon FinalSurge niet bereiken."}
    if alleen_zonder_wens:
        races = [r for r in races if not r.get("wish_given")]

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
    # `_cache` is de lookup voor `plaats_wens`. Hij werd alleen maar aangevuld en nooit
    # opgeschoond: elke race die ooit is getoond bleef (mét comments) hangen zolang het
    # proces leefde. We legen hem NIET per listing — twee coaches delen dit proces en een
    # gefilterde weergave mag de wens-lookup van de ander niet wegnemen — maar begrenzen
    # hem op de oudst-ingevoegde entries. Een gepruned item levert exact het bestaande
    # gedrag op: "Race niet meer in beeld — ververs de lijst."
    _prune_cache()
    return {"items": items, "fs": True,
            "dagen": days_ahead, "alleen_zonder_wens": bool(alleen_zonder_wens)}


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
