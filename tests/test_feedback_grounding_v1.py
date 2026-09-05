"""Feedback Grounding & Masterbrein Correctness v1 — deterministic context/prompt contracts.

Bewijst de bron-verbeteringen (geen downstream fixer): de PROMPT-veiligheidsregels (coach-agency,
medisch, geruststelling, zone-kwantificeerders) en de DETERMINISTISCHE context-payload die de AI
krijgt (zoneverdeling, near-future planning, context-readiness marker, onverwacht-extra, geen ruwe
machinewaarden). AI-output is niet-deterministisch en wordt hier NIET exact getest; we borgen de
context/prompt-CONTRACT + de deterministische helpers met de echte functies + gemockte fetches.

Golden archetypes (G1..G8) = geanonimiseerde/synthetische reproducties van de 8 audit-cases; geen
echte namen of comments.

    python3 -m pytest tests/test_feedback_grounding_v1.py -q
"""
import os
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client
import feedback_core
from brain import adapter

SYS = ai_feedback.SYSTEM_PROMPT

HR_ZONES = {
    "zone_type": "hartslag",
    "zones_text": "Z1 110-130\nZ2 130-145\nZ3 145-160\nZ4 160-175\nZ5 175-190",
    "zones": [{"num": 1, "naam": "Herstel", "low": 110, "high": 130},
              {"num": 2, "naam": "Easy", "low": 130, "high": 145},
              {"num": 3, "naam": "Tempo", "low": 145, "high": 160},
              {"num": 4, "naam": "Interval", "low": 160, "high": 175},
              {"num": 5, "naam": "Snelheid", "low": 175, "high": 190}],
}


def _active(zone=4, km=1):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": km, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": zone}]}


def _steps_interval():
    return ([{"intensity": "WARMUP", "durationType": "DISTANCE", "durationDist": 2, "distUnit": "km", "target": []}]
            + [_active() for _ in range(5)]
            + [{"intensity": "COOLDOWN", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km", "target": []}])


def _wd(hr_avg=150, laps=None, structured=True, description="", planned_amount=None,
        comments=None, notes="", near_future="", brein=""):
    acts = [{"hr_avg": hr_avg, "pace_display": "5:00", "Laps": laps or [], "planned_amount": planned_amount}]
    return {"athlete_name": "Atleet X", "athlete_first_name": "X", "workout_name": "Training",
            "post_notes": notes, "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
            "workout_date": "2026-08-20",
            "details": {"has_structured_workout": structured, "description": description,
                        "Activities": acts},
            "athlete_comments": comments or [],
            "near_future_block": near_future, "brein_context": brein}


@pytest.fixture
def fs(monkeypatch):
    store = {"zones": HR_ZONES, "steps": _steps_interval()}
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: store["zones"])
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: store["steps"])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)
    return store


def _ctx(wd):
    return ai_feedback._build_workout_context(wd)[0]


# ══ PROMPT SAFETY RULES (source contract) ═══════════════════════════════════════
def test_prompt_coach_agency_rule():
    assert "COACH-AGENCY" in SYS
    assert "Zeg NOOIT toe dat je het omzet" in SYS
    assert "een training of wedstrijd toevoegt, verplaatst of schrapt" in SYS


def test_prompt_medical_attribution_rule():
    assert "MEDISCH & MEDICATIE" in SYS
    assert "fijn dat jij merkt dat" in SYS
    assert 'NOOIT als vaststaand feit of werking ("de medicatie werkt"' in SYS


def test_prompt_reassurance_rule():
    assert "GERUSTSTELLING PAST BIJ DE SIGNALEN" in SYS
    assert '"geen alarm"' in SYS and "niet vals gerust" in SYS


def test_prompt_quantifier_zone_rule():
    assert "GEEN ONGEGRONDE HOEVEELHEIDSCLAIMS" in SYS
    assert "ZONEVERDELING" in SYS and "per lap, geen\n   sessieverdeling" in SYS


# ══ P1 — deterministic whole-session zone distribution ══════════════════════════
def test_zone_distribution_deterministic():
    laps = [{"amount": 1, "hr_avg": 138} for _ in range(8)] + [{"amount": 1, "hr_avg": 168} for _ in range(2)]
    out = ai_feedback._zone_distribution(laps, HR_ZONES["zones"], is_pace=False)
    assert "ZONEVERDELING" in out
    assert "Z2 80%" in out and "Z4 20%" in out
    # de instructie dwingt af dat kwantiteitsclaims op DEZE verdeling rusten
    assert "meeste/grootste deel" in out


def test_zone_distribution_needs_two_laps():
    assert ai_feedback._zone_distribution([{"amount": 1, "hr_avg": 140}], HR_ZONES["zones"], is_pace=False) == ""
    assert ai_feedback._zone_distribution([], HR_ZONES["zones"], is_pace=False) == ""


def test_zone_distribution_in_context(fs):
    # v4: de exacte ZONEVERDELING (percentages) gaat NIET meer athlete-facing mee; de verdeling
    # blijft intern bewijs voor kwalitatieve duiding + blok/lap-aantallen.
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(7)] \
        + [{"amount": 1, "hr_avg": 168, "pace_display": "4:10"} for _ in range(3)]
    ctx = _ctx(_wd(hr_avg=145, laps=laps, structured=True))
    assert "ZONEVERDELING" not in ctx                         # geen percentage-verdeling athlete-facing
    assert "80%" not in ctx and "20%" not in ctx              # geen zone-percentages


# ══ P1 — bounded near-future planning ═══════════════════════════════════════════
def test_near_future_block(monkeypatch):
    today = date.today()
    up = [
        {"workout_key": "F1", "workout_date": (today + timedelta(days=1)).isoformat(),
         "name": "Duurloop", "planned_amount": 10, "planned_amount_type": "km", "is_race": False, "Activities": []},
        {"workout_key": "F2", "workout_date": (today + timedelta(days=2)).isoformat(),
         "name": "5 km Oss", "is_race": True,
         "Activities": [{"planned_amount": 5, "planned_amount_type": "km"}]},
    ]
    monkeypatch.setattr(fs_client, "get_workouts_deduped", lambda ak, s, e: up)
    block = feedback_core._near_future_block({"athlete_key": "AK", "workout_key": "WK",
                                              "workout_date": today.isoformat()})
    assert "RELEVANTE KOMENDE TRAINING" in block
    assert "Duurloop" in block and "10 km" in block
    assert "5 km Oss" in block and "[WEDSTRIJD]" in block          # G3/G4: race conflict zichtbaar
    assert "via de BETEKENIS" in block and "NIET met 'morgen'" in block   # v6: geen relatief dag-woord
    assert "Zeg NOOIT toe dat je het schema aanpast" in block      # coach-agency herhaald bij near-future


def test_near_future_block_empty_when_none(monkeypatch):
    monkeypatch.setattr(fs_client, "get_workouts_deduped", lambda ak, s, e: [])
    assert feedback_core._near_future_block({"athlete_key": "AK", "workout_date": date.today().isoformat()}) == ""


def test_near_future_reaches_context(fs):
    ctx = _ctx(_wd(near_future="━━━ KOMENDE GEPLANDE TRAININGEN ━━━\n- wo 3/9: 5 km Oss [WEDSTRIJD]"))
    assert "KOMENDE GEPLANDE TRAININGEN" in ctx and "[WEDSTRIJD]" in ctx


# ══ P1 — unplanned / extra workout awareness ════════════════════════════════════
def test_unplanned_marker_present(fs):
    fs["steps"] = []                                              # geen builder
    ctx = _ctx(_wd(structured=False, description="", planned_amount=None, laps=[{"amount": 1, "hr_avg": 140}]))
    assert "NIET vooraf gepland" in ctx


def test_planned_workout_no_unplanned_marker(fs):
    ctx = _ctx(_wd(structured=True, laps=[{"amount": 1, "hr_avg": 140}]))
    assert "NIET vooraf gepland" not in ctx


# ══ P0 — context readiness (never UNKNOWN → 'geen bijzonderheden') ═══════════════
def test_context_block_read_failure_marks_unknown(monkeypatch):
    import athlete_read
    def _boom(*a, **k):
        raise RuntimeError("read down")
    monkeypatch.setattr(athlete_read, "get_state", _boom)
    out = adapter.feedback_context_block("AK", "WK")
    assert out["readiness"] == "UNKNOWN"
    assert out["prompt_block"] and "ONVOLLEDIG" in out["prompt_block"]


def test_feedback_context_partial_marks_unknown(monkeypatch):
    from brain import projections as _proj
    monkeypatch.setattr(_proj, "for_feedback", lambda st, wk="": {"evidence": [], "source_gaps": ["fs.zones"]})

    class _St:
        overall = "INSUFFICIENT_DATA"
        conflicts = []
        source_gaps = ["fs.zones"]
    out = adapter.feedback_context(_St(), "WK", today=date(2026, 9, 4))
    assert out["readiness"] == "PARTIAL"
    assert "ONVOLLEDIG" in out["prompt_block"]
    assert "geen ongegronde geruststelling" in out["prompt_block"].lower() or "geen aannames" in out["prompt_block"].lower()


def test_feedback_context_ready_empty_is_silent(monkeypatch):
    from brain import projections as _proj
    monkeypatch.setattr(_proj, "for_feedback", lambda st, wk="": {"evidence": [], "source_gaps": []})

    class _St:
        overall = "GOOD"
        conflicts = []
        source_gaps = []
    out = adapter.feedback_context(_St(), "WK", today=date(2026, 9, 4))
    assert out["readiness"] == "READY"
    assert out["prompt_block"] == ""                              # READY + oprecht leeg → geen valse marker


# ══ GOLDEN ARCHETYPES (deterministic context contract) ══════════════════════════
def test_g5_structured_interval_block_and_distribution(fs):
    # G5: gestructureerde 5-blok interval — BLOK-ANALYSE aanwezig, gemiddelde is géén sessiebrede
    # goedkeuring (PF-4). v4: geen ZONEVERDELING-percentages; wél kwalitatieve duiding.
    fs["steps"] = _steps_interval()
    laps = [{"amount": 1, "hr_avg": 128} for _ in range(2)] + [{"amount": 1, "hr_avg": 168} for _ in range(5)] \
        + [{"amount": 1, "hr_avg": 120}]
    ctx = _ctx(_wd(hr_avg=150, laps=laps, structured=True))
    assert "BLOK-ANALYSE" in ctx
    assert "ZONEVERDELING" not in ctx                         # geen percentage-verdeling athlete-facing
    assert "bewijst NIET of de geplande werkblokken hun target haalden" in ctx


def test_g7_fartlek_distribution_prevents_overclaim(fs):
    # G7: fartlek met meerdere zones — v4 krijgt de AI een KWALITATIEVE duiding i.p.v. percentages.
    fs["steps"] = []
    laps = [{"amount": 1, "hr_avg": 138} for _ in range(3)] + [{"amount": 1, "hr_avg": 150} for _ in range(3)] \
        + [{"amount": 1, "hr_avg": 168} for _ in range(4)]
    ctx = _ctx(_wd(hr_avg=150, laps=laps, structured=False, description="fartlek"))
    assert "ZONEVERDELING" not in ctx                         # geen percentages
    assert "verspreid over meerdere zones" in ctx             # kwalitatieve duiding i.p.v. gok/percentage


def test_context_has_no_raw_boolean(fs):
    # Geen enkele ruwe machinewaarde ('= True'/'= False') in de samengestelde context.
    ctx = _ctx(_wd(hr_avg=150, laps=[{"amount": 1, "hr_avg": 150} for _ in range(4)], structured=True))
    assert "= True" not in ctx and "= False" not in ctx
    assert ": True" not in ctx and ": False" not in ctx
