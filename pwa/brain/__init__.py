"""Masterbrein v2 — centrale intelligence-kernel (Fase A, shadow mode).

Draait NAAST het production-pad (pwa/athlete_context.py). Geen consumer schakelt
in Fase A om. Lagen: sources(+health) → evidence → derivations → patterns →
state(+good-is-good) → projections. AI blijft buiten dit pakket.
"""
from __future__ import annotations

from . import (complaints, contradictions, derive, events, history, history_store,
               models, patterns, projections, recency, shadow, snapshot, sources,
               state, zones)
from .models import (AthleteState, Evidence, SourceHealth, SCHEMA_VERSION,
                     ACTIVE, RECENT, RECURRING, RESOLVED, HISTORICAL, STALE, CONFLICT,
                     GOOD, STABLE, ATTENTION, INSUFFICIENT_DATA,
                     FACT, DERIVED, ATHLETE_REPORTED, COACH_REPORTED, AI_INTERPRETATION,
                     HIGH, MEDIUM, LOW, UNKNOWN)
from .state import assemble, build_athlete_state, explain

__all__ = [
    "build_athlete_state", "assemble", "explain",
    "AthleteState", "Evidence", "SourceHealth", "SCHEMA_VERSION",
    "projections", "snapshot", "shadow", "sources", "state", "derive",
    "patterns", "complaints", "contradictions", "zones", "recency", "models",
    "events", "history", "history_store",
]
