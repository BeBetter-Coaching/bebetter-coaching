"""Masterbrein v2 — L3 deterministische afleidingen (Fase A).

Pure derivaties uit harde/gerapporteerde evidence. Hergebruikt de bewezen
`athlete_context.training_summary` (km/runs/trend/onderbreking) en de
compliance-semantiek van `dossier._workout_score` (zonder pandas). Elke afgeleide
draagt provenance en een strength o.b.v. de sample.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import recency
from .models import (ACTIVE, DERIVED, HIGH, LOW, MEDIUM, UNKNOWN, Evidence,
                     derived_evidence)

try:
    import athlete_context as _ac
except Exception:                                    # pragma: no cover
    _ac = None


# ── Pure businessregel: afstandsafwijking ────────────────────────────────────
# Banden (centraal i.p.v. prompttekst):
#   <10%      NEGLIGIBLE  → niet benoemen
#   10–<20%   NOTABLE     → benoembaar; bij goede RPE/gevoel niet problematiseren
#   >=20%     CLEAR       → benoemen, maar niet automatisch negatief
# Let op het 15–20%-gat: de oude businessregel definieert 10–15 en 20 los. Meest
# backward-compatible interpretatie = 10–20 als één NOTABLE-band (15–20 gedraagt
# zich als 10–15), zodat er geen stil gat ontstaat. Bewust hier expliciet gemaakt.
def distance_deviation(planned_km, actual_km, felt=None, effort=None) -> dict | None:
    try:
        p = float(planned_km or 0)
        a = float(actual_km or 0)
    except Exception:
        return None
    if p <= 0:
        return None
    pct = (a - p) / p * 100.0
    ab = abs(pct)
    if ab < 10:
        band = "NEGLIGIBLE"
    elif ab < 20:
        band = "NOTABLE"
    else:
        band = "CLEAR"
    bad = False
    try:
        if felt is not None and float(felt) >= 4:
            bad = True
        if effort is not None and float(effort) >= 8:
            bad = True
    except Exception:
        pass
    report = band != "NEGLIGIBLE"
    problematize = report and bad          # CLEAR is niet automatisch negatief
    return {"pct": round(pct, 1), "band": band, "report": report,
            "problematize": problematize, "direction": "over" if pct > 0 else "under"}


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def _week_mon(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _compliance(log: list, today: date) -> dict | None:
    """8-weekse compliance via de bewezen _workout_score-semantiek (geen pandas)."""
    cutoff = today - timedelta(weeks=8)
    scores = []
    for e in log or []:
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except Exception:
            continue
        if d > today or d < cutoff or e.get("is_race"):
            continue
        planned = bool(e.get("planned_km") or e.get("planned_min") or e.get("description"))
        if not planned:
            continue
        if not e.get("completed"):
            scores.append(0.0)
            continue
        pk, pm = _num(e.get("planned_km")), _num(e.get("planned_min"))
        if pk:
            scores.append(min((_num(e.get("actual_km")) or 0) / pk, 1.0))
        elif pm:
            scores.append(min((_num(e.get("actual_min")) or 0) / pm, 1.0))
        else:
            scores.append(1.0)
    if not scores:
        return None
    return {"pct": round(sum(scores) / len(scores) * 100), "n": len(scores)}


def _score_trend(log: list, today: date, veld: str) -> dict | None:
    """Trend van felt/effort: recent (14d) vs basis (14–42d ervoor)."""
    g14 = today - timedelta(days=14)
    g42 = today - timedelta(days=42)
    recent, basis = [], []
    for e in log or []:
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except Exception:
            continue
        if d > today or not e.get("completed"):
            continue
        v = _num(e.get(veld))
        if not v or v <= 0:
            continue
        if d > g14:
            recent.append(v)
        elif d > g42:
            basis.append(v)
    if len(recent) < 3 or len(basis) < 3:
        return None
    r = sum(recent) / len(recent)
    b = sum(basis) / len(basis)
    return {"recent": round(r, 2), "basis": round(b, 2), "delta": round(r - b, 2),
            "n_recent": len(recent), "n_basis": len(basis)}


def _duration_per_week(log: list, today: date) -> float | None:
    mon0 = _week_mon(today)
    weeks = {mon0 - timedelta(weeks=w) for w in range(4)}
    total, seen = 0.0, False
    for e in log or []:
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except Exception:
            continue
        if not e.get("completed") or _week_mon(d) not in weeks:
            continue
        m = _num(e.get("actual_min"))
        if m:
            total += m
            seen = True
    return round(total / 4, 0) if seen else None


def all(raw: dict, athlete_key: str, today: date, base_evidence: list) -> list:
    """Alle Fase-A-derivaties. `base_evidence` levert provenance-ankers (bv. zones)."""
    log = raw.get("training_log") or []
    out: list = []
    prov_log = ["fs.training_log"]

    ts = _ac.training_summary(log, today) if _ac else {}
    if ts:
        km = ts.get("km_per_week")
        runs = ts.get("runs_per_week")
        n_weeks_data = sum(1 for e in log if e.get("completed"))
        strength = MEDIUM if n_weeks_data >= 3 else LOW
        if km is not None:
            out.append(derived_evidence("load.km_per_week", "load", km, status=ACTIVE,
                                        strength=strength, provenance=prov_log, window="4w",
                                        athlete_key=athlete_key, unit="km/week",
                                        detail={"trend": ts.get("trend")}))
        if runs is not None:
            out.append(derived_evidence("load.runs_per_week", "load", runs, status=ACTIVE,
                                        strength=strength, provenance=prov_log, window="4w",
                                        athlete_key=athlete_key, unit="runs/week"))
        if ts.get("trend"):
            out.append(derived_evidence("load.trend", "load", ts["trend"], status=ACTIVE,
                                        strength=strength, provenance=prov_log, window="4v4",
                                        athlete_key=athlete_key))
        if ts.get("onderbreking"):
            out.append(derived_evidence("load.interruption", "load", ts["onderbreking"],
                                        status=ACTIVE, strength=MEDIUM, provenance=prov_log,
                                        window="10w", athlete_key=athlete_key))

    dpw = _duration_per_week(log, today)
    if dpw is not None:
        out.append(derived_evidence("load.min_per_week", "load", dpw, status=ACTIVE,
                                    strength=LOW, provenance=prov_log, window="4w",
                                    athlete_key=athlete_key, unit="min/week"))

    comp = _compliance(log, today)
    if comp:
        out.append(derived_evidence("training.compliance", "training_response", comp["pct"],
                                    status=ACTIVE, strength=(MEDIUM if comp["n"] >= 4 else LOW),
                                    provenance=prov_log, window="8w", athlete_key=athlete_key,
                                    unit="%", detail={"n": comp["n"]}))

    for veld, key in (("effort", "recovery.rpe_trend"), ("felt", "recovery.feeling_trend")):
        tr = _score_trend(log, today, veld)
        if tr:
            direction = "stabiel"
            # felt: hoger = slechter; effort: hoger = zwaarder
            if tr["delta"] >= 0.5:
                direction = "zwaarder" if veld == "effort" else "slechter"
            elif tr["delta"] <= -0.5:
                direction = "lichter" if veld == "effort" else "beter"
            out.append(derived_evidence(key, "recovery", direction, status=ACTIVE,
                                        strength=MEDIUM, provenance=prov_log, window="14v28",
                                        athlete_key=athlete_key, detail=tr))

    # afstandsafwijking op recente trainingen (met planned + actual)
    for e in log:
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except Exception:
            continue
        if not recency.within(d.isoformat(), today, recency.COMPLAINT_RECENT) or e.get("is_race"):
            continue
        dev = distance_deviation(e.get("planned_km"), e.get("actual_km"),
                                 e.get("felt"), e.get("effort"))
        if not dev or dev["band"] == "NEGLIGIBLE":
            continue
        out.append(derived_evidence(
            f"training.distance_deviation.{e.get('workout_key') or d.isoformat()}",
            "training_response", dev["band"], status=ACTIVE, strength=LOW,
            provenance=["fs.training_log"], window=d.isoformat(), athlete_key=athlete_key,
            observed_at=d.isoformat(), detail=dev))

    return out
