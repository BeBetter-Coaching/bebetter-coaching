"""Masterbrein v2 — centraal recency-beleid (Fase A).

Eén plek voor tijdvensters, per BETEKENIS (niet één universeel klacht-venster).
Waar het architectuurrapport een drempel als arbitrair markeerde, staat
`provisional=True` + een reden — dat is een voorlopige keuze, geen fysiologische
waarheid. De bewezen v1-waarden (athlete_context.py / belasting.py) worden
hergebruikt zodat gedrag herkenbaar blijft.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Window:
    days: int
    reason: str
    provisional: bool = False


# ── Klachten ─────────────────────────────────────────────────────────────────
COMPLAINT_ACUTE = Window(7, "acute klacht = kort venster; sluit aan op belasting.py (7d)")
COMPLAINT_RECENT = Window(21, "recent venster; = _KLACHT_RECENT_DAGEN uit v1")
COMPLAINT_RECURRING_HISTORY = Window(90, "hoe ver terug tellen voor 'terugkerend'", provisional=True)
COMPLAINT_RECURRING_MIN = 2                 # zelfde klacht op ≥ dit aantal datums = terugkerend (v1)
INTAKE_COMPLAINT_STALE = Window(120, "intake-klacht ouder dan dit = mogelijk verouderd (v1)")

# ── Belasting / load ─────────────────────────────────────────────────────────
LOAD_SIGNAL_FRESH = Window(3, "opgeslagen belasting-stand vers; = _BELASTING_STAND_DAGEN uit v1")
LOAD_TREND_WEEKS = 4                        # 4 vs 4 weken (v1 training_summary)
INTERRUPTION_WEEKS = 10                     # onderbreking-scan-venster (v1)

# ── Coach ────────────────────────────────────────────────────────────────────
COACH_NOTE_RECENT = Window(45, "coach-observatie recent; = _NOTE_RECENT_DAGEN uit v1")
COACH_MEMORY_UNDATED_STRENGTH_LOW = True    # ongedateerde coachkennis → strength LOW

# ── Lifestyle / zones / races ────────────────────────────────────────────────
LIFESTYLE_STALE = Window(120, "lifestyle geldig tot gewijzigd; STALE-grens arbitrair", provisional=True)
ZONES_FRESH = Window(7, "live FS-zones; freshness-grens arbitrair", provisional=True)
RACE_UPCOMING = Window(90, "kalender-horizon voor komende races (v1 labels +90d)")


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def age_days(observed, today: date):
    d = _d(observed)
    if not d:
        return None
    return (today - d).days


def within(observed, today: date, window: Window) -> bool:
    n = age_days(observed, today)
    return n is not None and 0 <= n <= window.days
