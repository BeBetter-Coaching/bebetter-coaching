"""Feedback Session Coherence & Signal Relevance v2 — deterministic contracts + golden G9..G16.

Bewijst de bron-verbeteringen (geen downstream rewriter):
- P0 same-day sessie-coherentie (`feedback_core._session_context`): split/herstart samen begrijpen,
  géén valse merge van losse sessies (run+kracht, AM/PM losse runs);
- P0 sibling-awareness: de comment van een zusters-registratie wordt meegegeven;
- P1 actieve signalen sturen de tekst (`adapter.feedback_context` load.signal + directive);
- P1 deterministische relatieve datumlabels (`_relative_day_label` / `_near_future_block`);
- P1 exacte blokgrootte-labels (`_format_block_assessment`);
- P2 categorisch gevoel als woord (geen '4/5').

Golden G9..G16 = geanonimiseerde/synthetische fixtures (geen echte namen/comments).

    python3 -m pytest tests/test_feedback_session_coherence_v2.py -q
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
from brain.models import ACTIVE

SYS = ai_feedback.SYSTEM_PROMPT


# ── helpers ─────────────────────────────────────────────────────────────────
def _case(wk, ak="AK", day="2026-09-04", sport="run", km=None, planned=None, comments=None):
    acts = [{"amount": km, "amount_type": "km", "planned_amount": planned, "planned_amount_type": "km"}]
    return {"workout_key": wk, "athlete_key": ak, "workout_date": day, "workout_type": sport,
            "athlete_comments": comments or [], "post_notes": "", "details": {"Activities": acts}}


@pytest.fixture(autouse=True)
def _clean_cache():
    feedback_core._cache.clear()
    yield
    feedback_core._cache.clear()


# ══ G9 — split/restarted run: same session, no 'stopped early', sibling comment ══
def test_g9_split_restart_same_session():
    a = _case("A", km=0.85, planned=6)
    b = _case("B", km=5.51, planned=None, comments=["De verbinding viel weg dus ik ben opnieuw begonnen en heb de rest gewoon afgemaakt."])
    feedback_core._cache["A"] = a
    feedback_core._cache["B"] = b
    out = feedback_core._session_context(a)                    # genereer op het 0,85 km-fragment
    assert "ZELFDE-DAG SESSIE-CONTEXT" in out
    assert "0.85 km" in out and "5.51 km" in out
    assert "Samen ~6.4 km" in out and "gepland ~6 km" in out
    assert "'vroeg gestopt'" in out                            # instrueert NIET als vroeg-gestopt te lezen
    assert "verbinding viel weg" in out.lower()                # sibling-comment meegegeven (niet opnieuw vragen)


# ══ G10 — same-day AM easy + PM intervals: two full runs, do NOT aggregate ═══════
def test_g10_separate_runs_not_merged():
    am = _case("AM", km=6.0, planned=6.0)
    pm = _case("PM", km=8.0, planned=8.0)
    feedback_core._cache["AM"] = am
    feedback_core._cache["PM"] = pm
    assert feedback_core._session_context(am) == ""            # geen fragment/plan-match/comment → SEPARATE


# ══ G11 — run + strength same day: different sport, never merged ═════════════════
def test_g11_run_plus_strength_not_merged():
    run = _case("R", km=0.9, planned=6, sport="run")
    strength = _case("S", km=None, planned=None, sport="strength")
    feedback_core._cache["R"] = run
    feedback_core._cache["S"] = strength
    assert feedback_core._session_context(run) == ""           # kracht is geen loop-registratie → geen merge


def test_session_needs_two_factors_not_one():
    # Alleen een fragment (geen plan-match, geen comment) is ONVOLDOENDE → geen merge.
    a = _case("A", km=0.9, planned=None)
    b = _case("B", km=9.0, planned=None)                       # 0.9/9 = fragment, maar geen 2e factor
    feedback_core._cache["A"] = a
    feedback_core._cache["B"] = b
    assert feedback_core._session_context(a) == ""


# ══ G12/G13 — active signal must be able to steer the text ═══════════════════════
def _feedback_ctx(evidence, monkeypatch, overall="STABLE"):
    from brain import projections as _proj
    monkeypatch.setattr(_proj, "for_feedback", lambda st, wk="": {"evidence": evidence, "source_gaps": []})

    class _St:
        conflicts = []
        source_gaps = []
    _St.overall = overall
    return adapter.feedback_context(_St(), "WK", today=date(2026, 9, 4))


def test_g12_elevated_load_signal_reaches_and_steers(monkeypatch):
    ev = [{"key": "load.signal", "value": "hoog", "status": ACTIVE},
          {"key": "load.km_per_week", "value": 42, "status": ACTIVE}]
    out = _feedback_ctx(ev, monkeypatch)
    pb = out["prompt_block"]
    assert "Actueel belastingssignaal" in pb                   # het load-signaal bereikt nu de prompt
    assert "ACTUEEL signaal" in pb and "reactie MEE" in pb      # directive: signaal moet de tekst sturen
    assert "voorwaardelijk advies" in pb and "medisch terughoudend" in pb.lower()


def test_g13_active_complaint_directive_neutral(monkeypatch):
    ev = [{"key": "complaint.knie", "value": "knie", "status": ACTIVE, "detail": {"area": "knie"}}]
    out = _feedback_ctx(ev, monkeypatch)
    pb = out["prompt_block"]
    assert "ACTUEEL signaal" in pb
    assert "geen diagnose" in pb and "geen oorzaak" in pb      # medische terughoudendheid


# ══ G14 — deterministic relative date labels ═════════════════════════════════════
def test_g14_relative_day_labels():
    fri = date(2026, 9, 4)                                     # generatiedatum vrijdag
    assert feedback_core._relative_day_label(date(2026, 9, 5), fri) == "morgen"      # zaterdag
    assert feedback_core._relative_day_label(date(2026, 9, 6), fri) == "overmorgen"  # zondag ≠ morgen
    assert feedback_core._relative_day_label(date(2026, 9, 8), fri) == "dinsdag"     # binnen week → weekdag
    assert feedback_core._relative_day_label(date(2026, 9, 4), fri) == "vandaag"


def test_g14_near_future_uses_relative_label(monkeypatch):
    gen = date(2026, 9, 4)
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: gen)
    up = [{"workout_key": "F1", "workout_date": "2026-09-05", "name": "Duurloop",
           "planned_amount": 8, "planned_amount_type": "km", "is_race": False, "Activities": []}]
    monkeypatch.setattr(fs_client, "get_workouts_deduped", lambda ak, s, e: up)
    block = feedback_core._near_future_block({"athlete_key": "AK", "workout_key": "WK", "workout_date": "2026-09-04"})
    assert "morgen (" in block                                 # relatief label vooraan
    assert "LETTERLIJK over" in block                          # regel: niet zelf uitrekenen


# ══ G15 — mixed block lengths: exact size labels, no invented 'longer' ═══════════
def test_g15_block_size_labels():
    blocks = [
        {"index": 1, "type": "WARMUP", "dur": "1 km", "target_zone": None, "metric": "hr", "status": "NOT_EVALUATED"},
        {"index": 2, "type": "ACTIVE", "dur": "400 m", "target_zone": 4, "metric": "hr", "observed_hr": 168, "status": "ON_TARGET"},
        {"index": 3, "type": "ACTIVE", "dur": "200 m", "target_zone": 5, "metric": "hr", "observed_hr": 178, "status": "ON_TARGET"},
        {"index": 4, "type": "ACTIVE", "dur": "600 m", "target_zone": 4, "metric": "hr", "observed_hr": 170, "status": "ON_TARGET"},
    ]
    txt = ai_feedback._format_block_assessment({"confidence": "MATCHED", "blocks": blocks}, "X")
    assert "van 400 m" in txt and "van 200 m" in txt and "van 600 m" in txt
    assert "EXACTE blokgroottes" in txt and "600m-blok" in txt  # instrueert exacte referenties


# ══ G16 — categorical feel wording (no unexplained 4/5) ══════════════════════════
def test_g16_categorical_feel_word_not_number():
    # felt=4 → "Slecht"; de prompt moet het WOORD 'slecht' aandragen, niet '4/5'.
    parts = []
    felt, effort = 4, 7
    # reproduceer de exacte prompt-frase via _build_workout_context met een mock fs
    import types
    monmyp = None
    wd = {"athlete_name": "X Y", "athlete_first_name": "X", "workout_name": "Training",
          "post_notes": "", "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
          "workout_date": "2026-09-04", "felt": felt, "effort": effort,
          "details": {"has_structured_workout": False, "description": "duurloop",
                      "Activities": [{"hr_avg": 150, "pace_display": "5:30", "Laps": []}]},
          "athlete_comments": []}
    # zonder zones/builder is dit prima; get_athlete_zones/get_workout_builder mogen leeg zijn
    import fs_client as _fs
    _orig_z, _orig_b, _orig_f = _fs.get_athlete_zones, _fs.get_workout_builder, _fs.get_fastest_activity_on_day
    _fs.get_athlete_zones = lambda ak: {}
    _fs.get_workout_builder = lambda wk, ak: []
    _fs.get_fastest_activity_on_day = lambda ak, d: None
    try:
        ctx, _ = ai_feedback._build_workout_context(wd)
    finally:
        _fs.get_athlete_zones, _fs.get_workout_builder, _fs.get_fastest_activity_on_day = _orig_z, _orig_b, _orig_f
    assert "Gevoel dat de atleet zelf aangaf: slecht" in ctx   # leidt met het WOORD
    # de oude verwarrende koppeling 'Slecht (4/5 — schaal …)' bestaat niet meer
    assert "Slecht (4/5 — schaal 1=Geweldig" not in ctx
    assert "verwoord dit als woord" in ctx


# ══ P2 — sync/missing-execution guardrail present ════════════════════════════════
def test_sync_guardrail_in_prompt():
    assert "ONTBREKENDE UITVOERING / SYNC" in SYS
    assert "niet-geverifieerde platform" in SYS
