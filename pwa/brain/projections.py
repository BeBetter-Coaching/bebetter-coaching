"""Masterbrein v2 — L6 task projections (Fase A, alleen shadow).

Pure functies die dezelfde AthleteState filteren/herlabelen per taak. Ze bouwen
GEEN eigen waarheid en schakelen geen production consumer om. Elke projectie
levert een andere subset uit één bron van waarheid.
"""
from __future__ import annotations

from . import recency
from .models import (ACTIVE, ATTENTION, CONFLICT, HIGH, MEDIUM, RECENT, RECURRING,
                     RESOLVED, HISTORICAL)


def _dump(evs) -> list:
    return [e.to_dict() for e in evs]


def _is_complaint_group(e) -> bool:
    return e.domain == "health" and e.key.startswith("complaint.") \
        and not e.key.startswith("complaint.mention.")


def _task_gaps(state, relevant_sources) -> list:
    return [s for s in state.source_gaps if s in relevant_sources]


# ── SCHEMA — planning-context ────────────────────────────────────────────────
def for_schema(state) -> dict:
    keep = []
    for e in state.evidence:
        if e.key.startswith("complaint.mention."):
            continue
        if e.key == "coach.observation":
            continue                                  # geen losse observatie-dump
        if _is_complaint_group(e) and e.status in (RESOLVED, HISTORICAL):
            continue                                  # planning kijkt naar actief/recurring
        # planning-relevante intake-kennis: profielvoorkeuren/ervaring, blessure-
        # HISTORIE (verleden, geen actuele klacht) en coach-planning-context.
        planning_intake = (
            e.domain == "profile"
            or e.key == "health.injury_history"
            or e.key in ("coach.memory", "coach.intake_note")
        )
        if e.domain in ("load", "training_response", "goal", "zones", "recovery") \
                or _is_complaint_group(e) or planning_intake:
            keep.append(e)
    return {
        "task": "schema", "athlete_key": state.athlete_key, "naam": state.naam,
        "overall": state.overall,
        "source_gaps": _task_gaps(state, {"fs.training_log", "fs.zones", "intake"}),
        "evidence": _dump(keep),
    }


# ── FEEDBACK — session/workout-relevant ──────────────────────────────────────
def for_feedback(state, workout_key: str = "") -> dict:
    keep = []
    for e in state.evidence:
        if e.key.startswith("complaint.mention."):
            continue
        if _is_complaint_group(e):
            # alleen actueel/recent/recurring — oude losse klacht is niet relevant
            if e.status in (ACTIVE, RECENT, RECURRING):
                keep.append(e)
            continue
        if e.key.startswith("training.distance_deviation."):
            if not workout_key or e.workout_key == workout_key:
                keep.append(e)
            continue
        if e.key in ("training.compliance", "recovery.rpe_trend", "recovery.feeling_trend",
                     "zones.personal", "load.trend", "load.well_tolerated",
                     "load.possible_relation", "zones.structural_over",
                     # longitudinale hardloopbelasting — zodat Feedback niet vraagt
                     # naar km/frequentie die het zelf betrouwbaar weet (run-only)
                     "load.km_per_week", "load.runs_per_week", "load.interruption"):
            keep.append(e)
    return {
        "task": "feedback", "athlete_key": state.athlete_key, "naam": state.naam,
        "workout_key": workout_key,
        "overall": state.overall,
        "source_gaps": _task_gaps(state, {"fs.training_log", "coach_notes", "fs.zones"}),
        "evidence": _dump(keep),
    }


# ── HOME — alleen actionable prioriteit ──────────────────────────────────────
def for_home(state) -> dict:
    keep = []
    for e in state.evidence:
        if e.status == CONFLICT:
            keep.append(e)
            continue
        actionable = (
            (_is_complaint_group(e) and e.status in (ACTIVE, RECURRING)) or
            (e.key == "load.signal" and e.value == "hoog") or
            (e.key == "load.possible_relation") or
            (e.key == "zones.structural_over" and e.value == "ZONE_REVIEW_CANDIDATE")
        )
        # alleen MEDIUM/HIGH; LOW-strength hoort niet op Home (locked besluit 2)
        if actionable and e.strength in (HIGH, MEDIUM):
            keep.append(e)
    return {
        "task": "home", "athlete_key": state.athlete_key, "naam": state.naam,
        "overall": state.overall,
        # taak-relevante bronuitval mag Home halen als het betrouwbaarheid raakt
        "source_gaps": _task_gaps(state, {"fs.training_log", "belasting", "coach_notes"}),
        "evidence": _dump(keep),
    }


# ── DOSSIER — rijkste projectie (alle historie behouden) ─────────────────────
def for_dossier(state) -> dict:
    return {
        "task": "dossier", "athlete_key": state.athlete_key, "naam": state.naam,
        "overall": state.overall, "conflicts": list(state.conflicts),
        "source_gaps": list(state.source_gaps),
        "sources": [s.to_dict() for s in state.sources],
        "evidence": _dump(state.evidence),          # incl. resolved/historical/mentions
    }


# ── TEAMPULS — alleen privacy-safe aggregaat (stub) ──────────────────────────
def for_teampuls(state) -> dict:
    counts = {}
    for e in state.evidence:
        counts[e.domain] = counts.get(e.domain, 0) + 1
    return {
        "task": "teampuls", "athlete_key": state.athlete_key,
        "overall": state.overall, "domain_counts": counts,
        "note": "stub — alleen aggregaat, geen individuele private tekst",
    }
