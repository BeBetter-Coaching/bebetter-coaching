"""Masterbrein v2 — L4 longitudinale patronen (Fase A).

Minimale maar echte verbanden over meerdere trainingen/weken. Correlatie ≠
causaliteit: taal blijft `well_tolerated` / `possible_relation` / `review_candidate`,
nooit "X veroorzaakt Y". Elk patroon draagt provenance naar de onderliggende
evidence en krijgt alleen strength ≥ MEDIUM bij voldoende consistente datapunten.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import activity
from . import zones as _zones
from .models import (ACTIVE, DERIVED, HIGH, LOW, MEDIUM, RECURRING, UNKNOWN,
                     derived_evidence)

# Alleen een ECHTE volumetoename telt als "load↑". Een HERVATTING na een
# onderbreking is géén goed-verdragen belastingtoename — die loopt via
# capacity.handle_carefully, niet via well_tolerated/possible_relation.
_LOAD_UP = {"opbouwend"}
_EASY_HINTS = ("duur", "rustig", "herstel", "easy", "recovery", "z1", "z2", "zone 1", "zone 2")


def _by_key(evidence, key):
    return next((e for e in evidence if e.key == key), None)


def _active_complaints(evidence):
    return [e for e in evidence if e.domain == "health" and e.key.startswith("complaint.")
            and not e.key.startswith("complaint.mention.")
            and e.status in (ACTIVE, RECURRING)]


def _structural_over_zone(raw: dict, evidence, athlete_key: str, today: date):
    """Conservatief: tel recente EASY-bedoelde runs die feitelijk in een harde zone
    (>= Z4) zijn uitgevoerd. Eén afwijking is geen patroon."""
    z = raw.get("zones") or {}
    struct = z.get("zones") or []
    ztype = z.get("zone_type")
    if not struct or ztype not in ("tempo", "hartslag"):
        return None
    is_pace = ztype == "tempo"
    cutoff = today - timedelta(days=42)
    over, considered = 0, 0
    dates = []
    for e in raw.get("training_log") or []:
        if not activity.is_running_activity(e):
            continue                                 # nooit fiets-HR/-pace tegen running-zones
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except Exception:
            continue
        if d < cutoff or d > today or not e.get("completed") or e.get("is_race"):
            continue
        text = f"{e.get('name','')} {e.get('description','')}".lower()
        if not any(h in text for h in _EASY_HINTS):
            continue
        zn = _zones.zone_of(struct, hr=e.get("hr_avg"), pace=e.get("pace"), is_pace=is_pace)
        if not zn:
            continue
        considered += 1
        if zn.get("num", 0) >= 4:
            over += 1
            dates.append(d.isoformat())
    if considered < 3:
        return None                                  # onvoldoende sample → geen patroon
    if over == 0:
        label = "WITHIN_EXPECTATION"
    elif over < 3:
        label = "OCCASIONAL_OVER"
    else:
        label = "REPEATED_OVER"

    # review-candidate: herhaald over + goede feedback + geen negatieve health/recovery
    if label == "REPEATED_OVER":
        rpe = _by_key(evidence, "recovery.rpe_trend")
        feel = _by_key(evidence, "recovery.feeling_trend")
        bad_recovery = (rpe and rpe.value == "zwaarder") or (feel and feel.value == "slechter")
        if not _active_complaints(evidence) and not bad_recovery:
            label = "ZONE_REVIEW_CANDIDATE"

    return derived_evidence("zones.structural_over", "zones", label, status=ACTIVE,
                            strength=(MEDIUM if considered >= 4 else LOW),
                            provenance=["fs.training_log", "fs.zones"], window="6w",
                            athlete_key=athlete_key,
                            detail={"considered": considered, "over": over, "dates": dates})


def all(evidence, raw: dict, athlete_key: str, today: date) -> list:
    out = []
    trend = _by_key(evidence, "load.trend")
    rpe = _by_key(evidence, "recovery.rpe_trend")
    feel = _by_key(evidence, "recovery.feeling_trend")
    interruption = _by_key(evidence, "load.interruption")
    active = _active_complaints(evidence)

    load_up = bool(trend and str(trend.value) in _LOAD_UP)
    rpe_ok = not (rpe and rpe.value == "zwaarder")
    feel_ok = not (feel and feel.value == "slechter")

    # A. load well tolerated
    if load_up and rpe_ok and feel_ok and not active:
        prov = [e.id for e in (trend, rpe, feel) if e]
        strength = MEDIUM if (rpe or feel) else LOW
        out.append(derived_evidence("load.well_tolerated", "training_response", True,
                                    status=ACTIVE, strength=strength, provenance=prov,
                                    window="4w", athlete_key=athlete_key,
                                    detail={"reason": "load↑ + RPE/gevoel niet verslechterd + geen actieve klacht"}))

    # C. load + complaint → possible relation (nooit causaal)
    if load_up and active:
        comp = active[0]
        strength = MEDIUM if comp.status == RECURRING else LOW
        out.append(derived_evidence("load.possible_relation", "training_response",
                                    "possible_relation", status=ACTIVE, strength=strength,
                                    provenance=[trend.id, comp.id] if trend else [comp.id],
                                    window="4w", athlete_key=athlete_key,
                                    detail={"complaint": comp.value, "note": "associatie, geen causaliteit"}))

    # D. interruption + return → capacity context
    if interruption:
        out.append(derived_evidence("capacity.handle_carefully", "training_response", True,
                                    status=ACTIVE, strength=MEDIUM, provenance=[interruption.id],
                                    window="10w", athlete_key=athlete_key,
                                    detail={"reason": interruption.value}))

    # E. structural over-zone
    soz = _structural_over_zone(raw, evidence, athlete_key, today)
    if soz:
        out.append(soz)

    return out
