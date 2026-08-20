"""Masterbrein v2 — zone-evidence (Fase A).

Persoonlijke FinalSurge-zones = enige intensiteitswaarheid. Boundary-correctheid
loopt via de bewezen `fs_client.zone_van_waarde` (niet opnieuw uitvinden). Geen
VDOT-target-truth. Deze module maakt alleen zone-EVIDENCE + een pure helper om
een gemeten waarde in een zone te plaatsen; het schakelt GEEN locked Feedback-/
Schema-zonelogica om.
"""
from __future__ import annotations

from datetime import date

from . import recency
from .models import FACT, FS, HIGH, STALE, ACTIVE, Evidence, stable_id


def _pace_to_sec(pace) -> float | None:
    """'5:30' of '5:30/km' → seconden per km. None bij onbruikbaar."""
    if pace is None:
        return None
    s = str(pace).split("/")[0].strip()
    if ":" in s:
        try:
            m, sec = s.split(":")
            return int(m) * 60 + int(sec)
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


def zone_of(zones_struct: list, *, hr=None, pace=None, is_pace: bool):
    """Canonieke zone-classificatie voor Masterbrein via `fs_client.classify_pace_hr_zone`
    (ÉÉN classifier als waarheid — dezelfde als Feedback). Geeft de VOLLEDIGE status terug
    ({status, num, naam, nearest_num, ...}) of None. Masterbrein mag out-of-range abstraheren,
    maar nooit als valse membership presenteren (geen stille nearest-zone clamp meer)."""
    try:
        import fs_client as FS
    except Exception:
        return None
    if is_pace:
        waarde = _pace_to_sec(pace)
    else:
        try:
            waarde = float(hr) if hr else None
        except Exception:
            waarde = None
    if waarde is None:
        return None
    return FS.classify_pace_hr_zone(zones_struct or [], waarde, is_pace=is_pace)


def build(raw: dict, health_by_source: dict, athlete_key: str, today: date) -> list:
    """Zone-evidence uit de opgehaalde zone-tabel. STALE als de fetch te oud is
    (last_success buiten het freshness-venster) — live-zones mogen niet eeuwig
    als vers gelden."""
    z = raw.get("zones") or {}
    struct = z.get("zones") or []
    if not struct:
        return []
    h = health_by_source.get("fs.zones")
    fetched = (h.last_success[:10] if (h and h.last_success) else today.isoformat())
    fresh = recency.within(fetched, today, recency.ZONES_FRESH) or fetched == today.isoformat()
    ev = Evidence(
        key="zones.personal",
        domain="zones",
        value=z.get("zones_text", ""),
        truth_type=FACT,
        status=ACTIVE if fresh else STALE,
        strength=HIGH,
        source="fs.zones",
        source_kind=FS,
        observed_at=fetched,
        athlete_key=athlete_key,
        unit=("min/km" if z.get("zone_type") == "tempo" else "bpm"),
        detail={"zone_type": z.get("zone_type", ""), "count": len(struct),
                "fetched_at": fetched, "fresh": bool(fresh)},
        id=stable_id("fs.zones", "zones.personal", fetched),
    )
    return [ev]
