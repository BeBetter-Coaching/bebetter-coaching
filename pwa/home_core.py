"""Home-cockpit voor de PWA — van signaal naar wie/waarom/actie.

Bundelt de home-intelligentie in één payload: team-status, feedback-voortgang,
en vooral de **Prioriteit vandaag**-lijst: individuele atleten die aandacht of
actie vragen, met de reden erbij en waar de coach naartoe moet. Uitsluitend echte
data — belasting-signalen (opgeslagen stand), afhakers (compliance) en aflopende
schema's. Geen verzonnen scores.

belasting → dossier importeert streamlit+pandas op moduleniveau (niet in de
PWA-omgeving) → stubben, net als teampuls_core/admin_core. We raken alleen de
pure lees-functies aan (laad_stand/zichtbare_resultaten).
"""
from __future__ import annotations

import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

for _m in ("streamlit", "pandas"):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except Exception:
            sys.modules[_m] = types.ModuleType(_m)

import fs_client as FS
import feedback_core                                   # _filter_skipped (geen streamlit)

try:
    import intake_store
except Exception:
    intake_store = None


def _heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def _voornaam(naam: str, first: str = "") -> str:
    return first or (naam or "").split(" ")[0]


def _belasting_stand() -> list:
    """Opgeslagen belasting-signalen (goedkoop, geen FS/AI). Leeg = nog niet
    berekend vandaag (Teampuls openen berekent 'm) → dan simpelweg geen rijen."""
    try:
        import belasting
        return belasting.zichtbare_resultaten(belasting.laad_stand())
    except Exception:
        return []


def cockpit() -> dict:
    """Volledige home-payload. Zware FS-sweeps draaien SERIEEL (elk parallelt
    intern al over de roster; vier tegelijk → throttling/transiënte nullen)."""
    if not _heeft_token():
        return {"fs": False}

    try:
        on_hold = set((intake_store.load_on_hold() or {}).keys()) if intake_store else set()
    except Exception:
        on_hold = set()

    # ── Sweeps (serieel, betrouwbaar) ──
    wachten = gepost = 0
    try:
        wk, stats = FS.get_workouts_needing_feedback(7, None, False, True,
                                                     {"los schema"}, True)
        wachten = len(feedback_core._filter_skipped(wk))
        gepost = stats.get("posted_today", 0)
    except Exception:
        pass
    try:
        alerts = FS.get_compliance_alerts(7, on_hold, {"los schema"})
    except Exception:
        alerts = []
    try:
        schema_rows = FS.get_schema_end_dates(60, on_hold)
    except Exception:
        schema_rows = []
    try:
        races = sum(1 for r in FS.get_upcoming_races(7) if not r.get("wish_given"))
    except Exception:
        races = 0
    try:
        atleten = len(FS.get_athletes())
    except Exception:
        atleten = 0
    try:
        groepen = len(FS.get_athletes_by_group())
    except Exception:
        groepen = 0

    bel = _belasting_stand()
    bel_hoog = sum(1 for b in bel if b.get("ernst") == "hoog")

    # ── Prioriteit vandaag: één rij per atleet, hoogste tier wint ──
    prio: dict[str, dict] = {}

    def _add(uk, naam, first, tier, reden, view, actie):
        if not uk:
            return
        rank = 0 if tier == "actie" else 1
        bestaand = prio.get(uk)
        if bestaand and bestaand["_rank"] <= rank:
            return                                     # al een even/urgenter signaal
        prio[uk] = {
            "user_key": uk, "naam": naam, "voornaam": _voornaam(naam, first),
            "tier": tier, "reden": reden, "view": view, "actie": actie,
            "_rank": rank,
        }

    # Afhakers = actie (rood)
    for a in alerts:
        _add(a.get("user_key"), a.get("name", ""), a.get("first_name", ""), "actie",
             f'{a.get("n_low", 0)} van {a.get("n_planned", 0)} trainingen gemist',
             "teampuls", "Bekijken")

    # Schema loopt af / verlopen (alleen wie een schema HAD; 'geen schema' = ruis, hoort in Schema-verloop)
    for r in schema_rows:
        d = r.get("days_left")
        if d is None:
            continue
        if d < 0:
            _add(r.get("user_key"), r.get("name", ""), r.get("first_name", ""), "actie",
                 f"schema {abs(d)} dag{'en' if abs(d) != 1 else ''} verlopen", "schema-verloop", "Schema openen")
        elif d <= 7:
            _add(r.get("user_key"), r.get("name", ""), r.get("first_name", ""), "aandacht",
                 f"schema loopt af over {d} dag{'en' if d != 1 else ''}", "schema-verloop", "Schema openen")

    # Belasting-signalen (hoog = actie, let op = aandacht) — reden = de echte signaaltekst
    for b in bel:
        tier = "actie" if b.get("ernst") == "hoog" else "aandacht"
        reden = (b.get("signalen") or ["belasting-signaal"])[0]
        _add(b.get("user_key"), b.get("naam", ""), "", tier, reden, "teampuls", "Bekijken")

    items = sorted(prio.values(), key=lambda x: (x["_rank"], x["naam"]))
    for it in items:
        it.pop("_rank", None)

    n_actie = sum(1 for i in items if i["tier"] == "actie")
    n_aandacht = sum(1 for i in items if i["tier"] == "aandacht")
    rustig = max(atleten - n_actie - n_aandacht, 0)
    totaal = wachten + gepost
    pct = int(gepost / totaal * 100) if totaal else 100

    return {
        "fs": True,
        "atleten": atleten,
        "groepen": groepen,
        "team": {"actie": n_actie, "aandacht": n_aandacht, "rustig": rustig},
        "feedback": {"wachten": wachten, "gepost": gepost, "pct": pct},
        "info": {"races": races, "gepost": gepost},
        "belasting": {"totaal": len(bel), "hoog": bel_hoog},
        "prioriteit": items[:8],
        "prioriteit_totaal": len(items),
    }
