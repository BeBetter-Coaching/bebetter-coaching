"""Masterbrein v2 — minimale, expliciete contradiction-set (Fase A).

Geen generieke conflict-AI. Vier expliciete uitkomsttypes:
  • auto-resolve  (live FS-zones > intake-zones; recent actual load > oud volume)
  • coach-check / CONFLICT (on_hold + recente echte training) → zichtbaar, niet stil opgelost
  • beide-behouden (coach vs athlete) → afgehandeld in complaints-lifecycle
Conflicten worden zelf Evidence met provenance.
"""
from __future__ import annotations

from datetime import date, timedelta

from .models import (ACTIVE, CONFLICT, DERIVED, HISTORICAL, LOW, MEDIUM,
                     derived_evidence)


def detect(evidence, raw: dict, athlete_key: str, today: date) -> list:
    out = []
    intake = raw.get("intake") or {}

    # 1. live FS-zones > intake-zones (auto-resolve voor "wat geldt nu")
    live_zones = ((raw.get("zones") or {}).get("zones_text") or "").strip()
    intake_zones = (intake.get("zones") or "").strip()
    if live_zones and intake_zones and live_zones[:40] != intake_zones[:40]:
        out.append(derived_evidence(
            "precedence.zones", "zones", "live_fs_wins", status=ACTIVE, strength=MEDIUM,
            provenance=["fs.zones"], window="now", athlete_key=athlete_key,
            detail={"resolution": "auto", "winner": "fs.zones",
                    "superseded": "intake.zones (→ HISTORICAL)"}))

    # 2. recent actual load > oud intake-volume (auto-resolve)
    km = next((e for e in evidence if e.key == "load.km_per_week"), None)
    intake_vol = (intake.get("huidig_volume") or "").strip()
    if km is not None and intake_vol and str(km.value) not in intake_vol:
        out.append(derived_evidence(
            "precedence.load", "load", "recent_actual_wins", status=ACTIVE, strength=MEDIUM,
            provenance=[km.id], window="4w", athlete_key=athlete_key,
            detail={"resolution": "auto", "winner": "recent_actual", "old": intake_vol,
                    "recent": f"{km.value} km/week"}))

    # 3. on_hold + recente echte training → CONFLICT (coach-check, niet auto-oplossen)
    on_hold = raw.get("on_hold")
    if isinstance(on_hold, dict) and on_hold.get("since"):
        since = str(on_hold.get("since"))[:10]
        recent_runs = []
        for e in raw.get("training_log") or []:
            try:
                d = date.fromisoformat(str(e.get("date"))[:10])
            except Exception:
                continue
            if e.get("completed") and d.isoformat() >= since and (e.get("actual_km") or 0) > 0:
                recent_runs.append(d.isoformat())
        if recent_runs:
            out.append(derived_evidence(
                "conflict.on_hold_vs_activity", "training_response",
                "on_hold maar recent getraind", status=CONFLICT, strength=MEDIUM,
                provenance=["on_hold", "fs.training_log"], window=since, athlete_key=athlete_key,
                detail={"since": since, "runs": recent_runs[:5],
                        "resolution": "coach_check"}))
    return out
