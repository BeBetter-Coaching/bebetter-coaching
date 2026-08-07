"""Schema-verloop voor de PWA — wanneer loopt bij wie het schema af.

Hergebruikt fs_client.get_schema_end_dates: laatste geplande structured workout
per atleet, days_left, en zichtbaarheid voor de atleet (hide-instelling).
Puur lezend — geen WRITE.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS

try:
    import intake_store
except Exception:
    intake_store = None


def heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def verloop(horizon_days: int = 60) -> dict:
    """Schema-einddatums, genormaliseerd + gecategoriseerd voor de lijst."""
    if not heeft_token():
        return {"items": [], "fs": False}
    on_hold = set()
    try:
        if intake_store:
            on_hold = set((intake_store.load_on_hold() or {}).keys())
    except Exception:
        pass
    try:
        rijen = FS.get_schema_end_dates(horizon_days=horizon_days, on_hold_keys=on_hold)
    except Exception:
        return {"items": [], "fs": True, "err": "Kon FinalSurge niet bereiken."}

    items = []
    for r in rijen:
        dl = r.get("days_left")
        naam = r.get("name", "")
        if dl is None:
            status = "geen"                      # geen (echt) schema
        elif dl < 0:
            status = "verlopen"
        elif dl <= 7:
            status = "bijna"                     # loopt bijna af
        else:
            status = "loopt"
        items.append({
            "naam": naam,
            "voornaam": r.get("first_name") or (naam.split(" ")[0] if naam else ""),
            "groep": r.get("group") or "",
            "laatste": r.get("last_date"),
            "dagen": dl,
            "status": status,
            "verborgen": r.get("hidden_count") or 0,
            "zichtbaar_tot": r.get("visible_until"),
        })
    return {"items": items, "fs": True}
