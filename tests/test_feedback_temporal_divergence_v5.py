"""Feedback Temporal Anchoring + Continuous Divergence Guard v5.

Na v4 (3/4 PASS) blijft Sophie hangen op twee smalle structurele fouten:
1. temporele verwijzing naar een VORIGE sessie: model verzon 'na gisteren' terwijl de relevante
   sessie (cruise intervals) op dinsdag lag → deterministisch VORIGE-TRAINING-anker + guard;
2. continue easy/recovery: één geruststellende modaliteit (HR binnen Z1-Z2) drukte de andere
   relevante modaliteit (tempo boven Z2) weg → divergentie-guard, geen blanket 'goed uitgevoerd'.

Bewijst het bron-contract (geen downstream rewriter); AI-output is niet-deterministisch en wordt
NIET getest. Geen nieuwe FinalSurge-fan-out (gedeelde read), geen store/cache.

    python3 -m pytest tests/test_feedback_temporal_divergence_v5.py -q
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
import feedback_obligations as ob

_ZONE_PCT = __import__("re").compile(r"Z[1-5]\s*\d+\s*%")

HR_ZONES = [{"num": 1, "naam": "Herstel", "low": 110, "high": 130},
            {"num": 2, "naam": "Easy", "low": 130, "high": 145},
            {"num": 3, "naam": "Tempo", "low": 145, "high": 160},
            {"num": 4, "naam": "Interval", "low": 160, "high": 175},
            {"num": 5, "naam": "Snelheid", "low": 175, "high": 200}]
# Tempozones in seconden/km (sneller = lagere seconden).
PACE_ZONES = [{"num": 1, "naam": "Herstel", "low": 352, "high": 720},   # 5:52-12:00
              {"num": 2, "naam": "Duur", "low": 314, "high": 352},      # 5:14-5:52
              {"num": 3, "naam": "Tempo", "low": 285, "high": 314},     # 4:45-5:14
              {"num": 4, "naam": "Drempel", "low": 260, "high": 285},   # 4:20-4:45
              {"num": 5, "naam": "Snelheid", "low": 200, "high": 260}]


# ══ V5-G1/G2 — deterministic prior-session temporal anchoring ═══════════════════
def test_relative_past_label():
    fri = date(2026, 9, 4)                                    # vrijdag
    assert feedback_core._relative_past_label(date(2026, 9, 3), fri) == "gisteren"      # do
    assert feedback_core._relative_past_label(date(2026, 9, 2), fri) == "eergisteren"   # wo
    assert feedback_core._relative_past_label(date(2026, 9, 1), fri) == "dinsdag"       # di (binnen week)
    assert feedback_core._relative_past_label(date(2026, 8, 24), fri) == "11 dagen geleden"


def _prior_pool(current_date, prior):
    """prior = list van (date_iso, name, executed_km)."""
    rows = [{"workout_key": "CUR", "workout_date": current_date, "workout_type": "run",
             "name": "Herstelloop", "Activities": [{"amount": 6, "amount_type": "km"}]}]
    for d, nm, km in prior:
        rows.append({"workout_key": "P" + d, "workout_date": d, "workout_type": "run", "name": nm,
                     "Activities": ([{"amount": km, "amount_type": "km"}] if km else [])})
    return rows


def test_v5g1_prior_tuesday_no_yesterday(monkeypatch):
    # Generatie vrijdag; vorige UITGEVOERDE training dinsdag (cruise intervals); donderdag leeg.
    gen = date(2026, 9, 4)
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: gen)
    rows = _prior_pool("2026-09-04", [("2026-09-01", "Cruise intervals", 10)])
    w = {"athlete_key": "AK", "workout_key": "CUR", "workout_date": "2026-09-04"}
    block = feedback_core._prior_session_block(w, rows)
    assert "RELEVANTE VORIGE TRAINING" in block
    # v6: verwijs via de BETEKENIS; exacte weekdag alleen intern, geen athlete-facing relatief dag-woord
    assert "de Cruise intervals (eerder gedaan" in block
    assert "intern: di 1/9" in block                          # dinsdag alleen als interne disambiguatie
    assert "de dag ervoor" not in block.split("intern:")[0]   # geen relatief dag-woord in de labelregel


def test_v5g2_prior_by_meaning_no_relative_day(monkeypatch):
    gen = date(2026, 9, 4)                                    # vrijdag
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: gen)
    rows = _prior_pool("2026-09-04", [("2026-09-03", "Intervallen", 8)])   # donderdag (binnen 3d)
    w = {"athlete_key": "AK", "workout_key": "CUR", "workout_date": "2026-09-04"}
    block = feedback_core._prior_session_block(w, rows)
    # v6: verwijs via betekenis, geen athlete-facing 'gisteren'; weekdag alleen intern
    assert "de Intervallen (eerder gedaan" in block
    assert "intern: do 3/9" in block
    assert "gisteren" not in block.split("intern:")[0]        # geen relatief dag-woord in de labelregel


def test_prior_out_of_window_omitted(monkeypatch):
    gen = date(2026, 9, 4)
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: gen)
    # enige prior ligt 4 dagen terug (buiten het ±3-venster) → geen prior-blok
    rows = _prior_pool("2026-09-04", [("2026-08-31", "Cruise intervals", 10)])
    w = {"athlete_key": "AK", "workout_key": "CUR", "workout_date": "2026-09-04"}
    assert feedback_core._prior_session_block(w, rows) == ""


def test_prior_skips_non_executed(monkeypatch):
    gen = date(2026, 9, 4)
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: gen)
    # donderdag alleen GEPLAND (geen uitvoering) → sla over, val terug op dinsdag (uitgevoerd, binnen 3d)
    rows = _prior_pool("2026-09-04", [("2026-09-03", "Geplande rust", 0),
                                      ("2026-09-01", "Cruise intervals", 10)])
    w = {"athlete_key": "AK", "workout_key": "CUR", "workout_date": "2026-09-04"}
    block = feedback_core._prior_session_block(w, rows)
    assert "de Cruise intervals (eerder gedaan" in block and "intern: di 1/9" in block


def test_prompt_forbids_invented_prior_day():
    # de datum-context verbiedt een zelf-verzonnen dag-relatie met een eerdere training
    wd = {"athlete_name": "X Y", "athlete_first_name": "X", "workout_name": "Herstelloop",
          "post_notes": "", "workout_key": "WK", "athlete_key": "", "workout_type": "run",
          "workout_date": date.today().isoformat(),
          "details": {"has_structured_workout": False, "description": "herstel na cruise intervals",
                      "Activities": [{"hr_avg": 140, "pace_display": "5:40", "Laps": []}]},
          "athlete_comments": []}
    ctx = ai_feedback._build_workout_context(wd)[0]
    assert "Verzin ZELF NOOIT een dag-relatie met een EERDERE training" in ctx


# ══ V5-G3 — continuous recovery HR/pace divergence guard ════════════════════════
def test_v5g3_divergence_guard_fires():
    res = ob.build(modality="hartslag", shares={"Z1": 55, "Z2": 45}, athlete_text="",
                   divergence={"above": "tempo", "easy": "hartslag"})
    pb = res["prompt_block"]
    assert "HARTSLAG/TEMPO-VERSCHIL" in pb
    assert "op hartslag" in pb and "op tempo" in pb
    assert "je zat er gewoon goed in" in pb                   # verboden blanket-conclusie benoemd
    assert not _ZONE_PCT.search(pb)


def test_above_easy_helper():
    assert ob.above_easy({"Z1": 60, "Z2": 20, "Z3": 20}) is True   # Z3 boven Z2, materieel
    assert ob.above_easy({"Z1": 57, "Z2": 43}) is False            # alles binnen Z1-Z2
    assert ob.above_easy({"Z2": 92, "Z3": 8}) is False             # Z3 niet materieel (<10)


@pytest.fixture
def fs_both(monkeypatch):
    # Sophie-achtig: HF-zonetabel primair + tempo-zonetabel secundair (uit dezelfde ZoneList).
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {
        "zone_type": "hartslag", "zones_text": "Z1..", "zones": HR_ZONES,
        "secondary_zone_type": "tempo", "secondary_zones": PACE_ZONES})
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: [])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)


def _wd_recovery(laps, comments=None, name="Herstelloop", desc="herstel na cruise intervals"):
    return {"athlete_name": "Atleet S", "athlete_first_name": "S", "workout_name": name,
            "post_notes": "", "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
            "workout_date": "2026-09-04",
            "details": {"has_structured_workout": False, "description": desc,
                        "Activities": [{"hr_avg": 138, "pace_display": "5:00", "Laps": laps}]},
            "athlete_comments": comments or []}


def test_v5g3_integration_sophie_divergence(fs_both):
    # HF binnen Z1-Z2 (138 = Z2), tempo materieel boven Z2 (4:50=290s → Z3, 5:30=330s → Z2).
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(6)] \
        + [{"amount": 1, "hr_avg": 140, "pace_display": "4:50"} for _ in range(4)]
    # v8: divergentie vuurt ALLEEN bij een expliciet DUAAL plan (pace-target ÉN HR-target).
    dual = _wd_recovery(laps, desc="rustig lopen op tempo rond 4:30 en hartslag onder 150")
    ctx = ai_feedback._build_workout_context(dual)[0]
    assert "HARTSLAG/TEMPO-VERSCHIL" in ctx
    assert "je zat er gewoon goed in" in ctx                  # verbod aanwezig
    assert not _ZONE_PCT.search(ctx)
    # v8 Sophie-fix: HR-gestuurd plan (geen pace-metric) → GEEN divergentie ondanks snellere tempozone
    hr_only = _wd_recovery(laps, desc="rustige hersteltraining op hartslag zone 1 tot 2")
    assert "HARTSLAG/TEMPO-VERSCHIL" not in ai_feedback._build_workout_context(hr_only)[0]


# ══ V5-G4 — structured session: no forced generic divergence ════════════════════
def test_v5g4_structured_no_divergence_prose(fs_both, monkeypatch):
    # gestructureerd (>=2 blokken) → divergentie-guard vuurt NIET (block-evidence leidend)
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: [
        {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km",
         "target": [{"targetType": "hr zone", "zone": 4}]} for _ in range(5)])
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(6)] \
        + [{"amount": 1, "hr_avg": 140, "pace_display": "4:50"} for _ in range(4)]
    wd = _wd_recovery(laps, name="Intervaltraining", desc="5x1km")
    wd["details"]["has_structured_workout"] = True
    ctx = ai_feedback._build_workout_context(wd)[0]
    assert "HARTSLAG/TEMPO-VERSCHIL" not in ctx


def test_no_divergence_when_both_easy(fs_both):
    # beide modaliteiten binnen easy → geen divergentie
    laps = [{"amount": 1, "hr_avg": 135, "pace_display": "6:00"} for _ in range(10)]  # HF Z2, tempo Z1
    ctx = ai_feedback._build_workout_context(_wd_recovery(laps))[0]
    assert "HARTSLAG/TEMPO-VERSCHIL" not in ctx


# ══ V5-G5 — availability message stays green ════════════════════════════════════
def test_v5g5_availability_message():
    res = ob.build(modality="hartslag", shares={}, athlete_text="kan er morgen niet bij zijn")
    assert "BERICHT-VERPLICHTINGEN" in res["prompt_block"]
    assert "GEEN plezier of succes" in res["prompt_block"]
