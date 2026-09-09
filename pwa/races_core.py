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
            # canonieke FinalSurge-identiteit: hiermee draagt navigatie vanuit Races de
            # atleet mee in de ROUTE (#workspace/<key> etc.), refresh-vast en zonder een
            # tweede, sessiegebonden atleetselectie.
            "atleet_key": r.get("athlete_key", ""),
            "datum": (r.get("workout_date") or "")[:10],
            "race": r.get("workout_name") or "Race",
            "type": r.get("race_type") or "",
            # de eigen omschrijving bij de race-workout (coachtekst/doel). Stond al in de
            # bron maar werd hier weggegooid; puur passthrough, geen interpretatie.
            "beschrijving": (r.get("description") or "").strip(),
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


# ══════════════════════════════════════════════════════════════════════════════
# COACHHULP — compacte, read-only context bij ÉÉN race
# ══════════════════════════════════════════════════════════════════════════════
# Doel: genoeg context om zelf een persoonlijke succeswens te schrijven, zonder een
# tweede Workspace in Races te bouwen. Alles komt uit bestaande, canonieke bronnen:
# de racegegevens die de lijst al heeft, plus de GEDEELDE AthleteState-read
# (`athlete_read.get_state`) die Workspace, Dossier, Home, Teampuls en Feedback ook
# gebruiken. Geen nieuwe store, geen tweede klachtselectie, geen eigen engine.
#
# Harde regels:
#   • klachten uitsluitend via `adapter.actuele_klachten` (canoniek ACTIVE/RECENT);
#     een historisch/terugkerend patroon zonder recente melding komt hier NOOIT in;
#   • lukt de gedeelde read niet, dan zeggen we dat (`context_onzeker`) in plaats van
#     stilte te presenteren als 'geen bijzonderheden';
#   • read-only: deze functies posten nooit iets naar FinalSurge.

def _dagen_tot(iso: str):
    from datetime import date
    try:
        return (date.fromisoformat(str(iso or "")[:10]) - date.today()).days
    except ValueError:
        return None


def _atleetcontext(user_key: str) -> dict:
    """Canonieke atleetcontext voor de wens: doel, actuele klachten, recente belasting.

    Leest de GEDEELDE AthleteState (hot-read als de cockpit van deze atleet net is
    bekeken). Nooit fataal: een gefaalde read is ONZEKER, geen 'niets aan de hand'."""
    if not user_key:
        return {"context_onzeker": True}
    try:
        import athlete_read as _read
        from brain import adapter as _ad, projections as _proj
        state = _read.get_state(user_key).state
        if state is None:
            return {"context_onzeker": True}
        evs = _proj.for_dossier(state)["evidence"]

        def _val(key):
            e = next((x for x in evs if x.get("key") == key), None)
            return e.get("value") if e else None

        km, trend = _val("load.km_per_week"), _val("load.trend")
        belasting = ""
        if km is not None:
            belasting = f"~{km} km/week"
            if trend:
                belasting += f" (trend: {trend})"
        return {
            "doel": _val("goal.doel") or "",
            "klachten": _ad.actuele_klachten(evs),
            "belasting": belasting,
            "context_onzeker": False,
        }
    except Exception:
        return {"context_onzeker": True}


def coachhulp(wid: str) -> dict:
    """Compacte coachcontext bij één race. Read-only, nooit een write."""
    r = _cache.get(wid)
    if not r:
        raise ValueError("Race niet meer in beeld — ververs de lijst.")
    naam = r.get("athlete_name", "")
    ctx = _atleetcontext(r.get("athlete_key", ""))
    return {
        "id": wid,
        "naam": naam,
        "voornaam": r.get("athlete_first_name") or (naam.split(" ")[0] if naam else ""),
        "atleet_key": r.get("athlete_key", ""),
        "race": r.get("workout_name") or "Race",
        "type": r.get("race_type") or "",
        "datum": (r.get("workout_date") or "")[:10],
        "dagen_tot": _dagen_tot(r.get("workout_date")),
        "beschrijving": (r.get("description") or "").strip(),
        "wens": _wens(r),
        **ctx,
    }


def _voorstel_context(h: dict) -> str:
    """De contextregels die met het wens-voorstel meegaan. DETERMINISTISCH: alleen wat
    de canonieke bronnen echt leveren, verbatim en zonder gevolgtrekking. Geen enkel
    veld wordt ingevuld of afgerond als het ontbreekt — dan blijft de regel gewoon weg
    en schrijft het model een neutrale wens."""
    regels = []
    if h.get("beschrijving"):
        regels.append(f"Omschrijving bij de race (van de coach): {h['beschrijving'][:300]}")
    if h.get("doel"):
        regels.append(f"Doel van deze atleet: {h['doel']}")
    if h.get("belasting"):
        regels.append(f"Recente hardloopbelasting: {h['belasting']}.")
    for k in (h.get("klachten") or [])[:2]:
        wanneer = (f", voor het laatst ~{k['laatst_dagen']}d geleden gemeld"
                   if isinstance(k.get("laatst_dagen"), int) else "")
        regels.append(
            f"Actuele klacht rond {k['area']}{wanneer}. Je mag hier hooguit kort en "
            f"bemoedigend naar verwijzen. Geen diagnose, geen behandeladvies, geen "
            f"voorspelling over hoe het zal gaan.")
    if h.get("context_onzeker"):
        # Eerlijk over onzekerheid: liever een neutrale wens dan een verzonnen persoonlijke.
        regels.append("De achtergrondcontext van deze atleet is nu niet beschikbaar. "
                      "Schrijf een korte, neutrale succeswens en verzin geen voorbereiding, "
                      "doel, tijd of vorm.")
    return "\n".join(regels)


def voorstel(wid: str) -> dict:
    """Één kort wens-VOORSTEL voor deze race. Genereert alleen tekst en post NOOIT iets;
    de coach neemt het voorstel expliciet over en verstuurt zelf.

    Hergebruikt de bestaande, productie-bewezen `ai_feedback.generate_race_wish` (dezelfde
    generator als de Streamlit-races-pagina) met een deterministisch opgebouwde context.
    Geen tweede generatiesysteem."""
    h = coachhulp(wid)
    import ai_feedback
    tekst = ai_feedback.generate_race_wish(
        first_name=h["voornaam"] or h["naam"] or "",
        race_name=h["race"], race_type=h["type"], race_date=h["datum"],
        context=_voorstel_context(h),
    )
    return {"tekst": (tekst or "").strip(),
            "persoonlijk": bool(h.get("doel") or h.get("klachten") or h.get("beschrijving")),
            "context_onzeker": bool(h.get("context_onzeker"))}
