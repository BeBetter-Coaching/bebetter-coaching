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
import threading
import types
from datetime import date, datetime

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


def _atleten_objs() -> list:
    """Vlakke atletenlijst (met all_groups) — voor belasting.check_alle."""
    try:
        groepen = FS.get_athletes_by_group()
        return [a for members in groepen.values() for a in members]
    except Exception:
        return []


def _belasting_vandaag(atleten: list) -> list:
    """Belasting-signalen van vandaag — ONAFHANKELIJK van of Teampuls geopend is.

    Is de opgeslagen dagstand niet van vandaag, dan berekenen we de signalen hier
    (belasting.dagelijkse_check, per dag gecachet). Op Render draait dat inclusief
    AI-duiding; faalt de AI/berekening (bv. lokaal zonder key), dan vallen we terug
    op de laatst opgeslagen stand — nooit een leeg scherm door een AI-hapering.
    Home gebruikt alleen de rúwe signaaltekst, niet de AI-duiding."""
    try:
        import belasting
    except Exception:
        return []
    try:
        if belasting.laad_stand().get("datum") != date.today().isoformat():
            try:
                belasting.dagelijkse_check(atleten)     # berekent + slaat op (per dag gecachet)
            except Exception:
                pass                                     # val terug op opgeslagen stand
        return belasting.zichtbare_resultaten(belasting.laad_stand())
    except Exception:
        return []


# ── Snapshot (stale-while-revalidate) — twee lagen, duurzaam en gedeeld ──────
# Doel: na een Render-deploy/restart NOOIT meer een koude 20-30s Home-load, en
# beide coaches (later meerdere instances) delen dezelfde snapshot.
#
# Laag 1  in-memory (_MEM): warme reads ~0 ms; verdwijnt bij restart.
# Laag 2  GitHub-store (intake_store.load/save_home_snapshot): overleeft deploys,
#         gedeeld tussen coaches/instances, SHA-based concurrency in _save_json.
#
# Leespad (refresh=False) doet NOOIT de zware berekening — dat houdt het kritieke
# renderpad snel: geheugen → anders één GitHub-GET (~honderden ms) → anders een
# 'pending'-payload zodat de client skeletons toont en op de achtergrond ververst.
# De ~26s sweep gebeurt uitsluitend in refresh=True, met single-flight zodat twee
# gelijktijdige verouderde loads niet allebei dezelfde zware refresh starten.

_MEM: dict = {}                          # laatst bekende snapshot in dit proces
_FLAG_LOCK = threading.Lock()
_REFRESHING = False                      # draait er al een refresh op deze instance?


def _valid(snap) -> bool:
    """Een bruikbare snapshot: FS antwoordde écht (atleten>0) en prioriteit is
    berekend. Zo herkennen we een mislukte/incomplete sweep (transiënte nullen,
    FS onbereikbaar) en overschrijven we goede data er niet mee."""
    return bool(snap and snap.get("fs") and snap.get("prioriteit") is not None
                and snap.get("atleten", 0) > 0)


def _current() -> dict:
    """Beste bekende snapshot: eerst geheugen, anders de duurzame store (die dan
    ook het geheugen opwarmt — het post-restart-pad, ~GET i.p.v. 26s rebuild)."""
    global _MEM
    if _valid(_MEM):
        return _MEM
    if intake_store is not None:
        try:
            durable = intake_store.load_home_snapshot()
        except Exception:
            durable = {}
        if _valid(durable):
            _MEM = durable
            return durable
    return {}


def _persist(data: dict) -> None:
    """Bewaar in beide lagen. GitHub-fout mag Home nooit breken (geheugen blijft)."""
    global _MEM
    _MEM = data
    if intake_store is not None:
        try:
            intake_store.save_home_snapshot(data)
        except Exception:
            pass


def cockpit(refresh: bool = False) -> dict:
    """Home-cockpit. Standaard direct uit de cache (geheugen→store); refresh=True
    herbouwt (single-flight) en behoudt bij mislukking de laatst geldige snapshot."""
    if not _heeft_token():
        return {"fs": False}

    if not refresh:
        snap = _current()
        if snap:
            return {**snap, "cached": True}
        # Nog nooit opgebouwd (eerste-ooit): geen zware sweep in het renderpad.
        # Client toont shell + skeletons en triggert de achtergrond-refresh.
        return {"fs": True, "prioriteit": None, "pending": True, "cached": False,
                "datum": date.today().isoformat(), "berekend": None}

    # ── refresh=True: single-flight ──
    global _REFRESHING
    with _FLAG_LOCK:
        bezig = _REFRESHING
        if not bezig:
            _REFRESHING = True
    if bezig:
        # Er draait al een refresh op deze instance → geen tweede zware sweep.
        snap = _current()
        if snap:
            return {**snap, "cached": True, "verversen_bezig": True}
        return {"fs": True, "prioriteit": None, "pending": True, "cached": False}

    try:
        data = _bereken()
        if _valid(data):
            data["cached"] = False
            _persist(data)
            return data
        # Mislukte/incomplete refresh → gooi bruikbare oude data niet weg.
        oud = _current()
        if oud:
            return {**oud, "cached": True, "refresh_mislukt": True}
        return {**data, "cached": False}
    finally:
        with _FLAG_LOCK:
            _REFRESHING = False


def _bereken() -> dict:
    """De zware berekening (alleen bij refresh). SERIEEL: elke sweep parallelt
    intern al over de roster; vier tegelijk → throttling/transiënte nullen.

    TIER-LOGICA (per atleet, gededupliceerd op user_key): één rij per atleet,
    HOOGSTE ernst wint (actie > aandacht). actie = afhakers, belasting 'hoog',
    schema verlopen. aandacht = belasting 'let op', schema loopt af binnen 7 dagen.
    Team-status telt DISTINCT atleten per tier; rustig = atleten − actie − aandacht.
    Geen samengestelde/fysiologische score — enkel telling van bestaande signalen."""
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
    atleten_objs = _atleten_objs()
    try:
        atleten = len(FS.get_athletes())
    except Exception:
        atleten = len(atleten_objs)
    groepen = 0
    try:
        groepen = len(FS.get_athletes_by_group())
    except Exception:
        pass

    # Belasting-signalen van vandaag — berekend als de dagstand ontbreekt (los van Teampuls)
    bel = _belasting_vandaag(atleten_objs)
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
        "berekend": datetime.now().isoformat(timespec="seconds"),
        "datum": date.today().isoformat(),
    }
