"""Feedback Context Relevance Simplification v6.

Productbesluit na gate 2/4: Feedback wordt EENVOUDIGER. Datums bepalen de RELEVANTIE (max ±3
kalenderdagen), maar worden niet meer athlete-facing naverteld:
- geen standaard gisteren/eergisteren/morgen/overmorgen/N dagen geleden → verwijs naar de sessie
  via de BETEKENIS (de intervaltraining, de komende lange duurloop); irrelevante context weglaten;
- een tijdswoord uit een OUD atleetbericht ('morgen') niet letterlijk kopiëren;
- de LLM telt zelf GEEN blokken; alleen deterministisch vooraf berekende volgorde/telling als feit.

Bewijst het bron-contract (geen downstream rewriter); AI-output is niet-deterministisch en wordt
NIET getest. Geen nieuwe FinalSurge-fetch, geen store/cache.

    python3 -m pytest tests/test_feedback_context_relevance_v6.py -q
"""
import os
import re
import sys
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client
import feedback_core
import feedback_obligations as ob

SYS = ai_feedback.SYSTEM_PROMPT
_REL_DAY = re.compile(r"\b(gisteren|eergisteren|morgen|overmorgen)\b")

HR_ZONES = [{"num": 1, "naam": "z", "low": 110, "high": 130}, {"num": 2, "naam": "z", "low": 130, "high": 145},
            {"num": 3, "naam": "z", "low": 145, "high": 160}, {"num": 4, "naam": "z", "low": 169, "high": 179},
            {"num": 5, "naam": "z", "low": 179, "high": 200}]


# ══ system-prompt contracten ════════════════════════════════════════════════════
def test_prompt_no_calendar_narration_rule():
    assert "GEEN KALENDER NAVERTELLEN" in SYS
    assert "via de BETEKENIS" in SYS
    assert "STANDAARD GEEN relatieve dag-woorden" in SYS


def test_prompt_no_self_block_counting_rule():
    assert "TEL OF CLASSIFICEER ZELF GEEN BLOKKEN" in SYS
    assert "WERKBLOK-TELLING" in SYS or "BLOKVOLGORDE" in SYS


def test_prompt_stale_athlete_timeword_rule():
    assert "historische tekst" in SYS and "kopieer het NIET" in SYS.replace("KOPIEER", "kopieer")


# ══ V6 — bounded ±3-day window ══════════════════════════════════════════════════
def test_window_constants_are_three():
    assert feedback_core._NEAR_FUTURE_DAYS == 3
    assert feedback_core._PRIOR_DAYS == 3


def _prior_rows(cur, prior):
    rows = [{"workout_key": "CUR", "workout_date": cur, "workout_type": "run", "name": "Herstelloop",
             "Activities": [{"amount": 6, "amount_type": "km"}]}]
    for d, nm, km in prior:
        rows.append({"workout_key": "P" + d, "workout_date": d, "workout_type": "run", "name": nm,
                     "Activities": ([{"amount": km, "amount_type": "km"}] if km else [])})
    return rows


# ══ V6-G2 — nearby prior session referred to by meaning, no date narration ══════
def test_v6g2_prior_by_meaning(monkeypatch):
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: date(2026, 9, 4))  # vrijdag
    rows = _prior_rows("2026-09-04", [("2026-09-01", "Intervaltraining", 9)])          # dinsdag (3d)
    block = feedback_core._prior_session_block(
        {"athlete_key": "AK", "workout_key": "CUR", "workout_date": "2026-09-04"}, rows)
    assert "de Intervaltraining (eerder gedaan" in block          # betekenis-gebaseerd
    assert not _REL_DAY.search(block.split("intern:")[0])         # geen relatief dag-woord in labelregel
    assert "via de BETEKENIS" in block


def test_v6g4_irrelevant_out_of_window(monkeypatch):
    # nabije sessie 4 dagen terug = buiten venster → geen prior-blok (geen forced reference)
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: date(2026, 9, 4))
    rows = _prior_rows("2026-09-04", [("2026-08-31", "Rustige duurloop", 8)])
    assert feedback_core._prior_session_block(
        {"athlete_key": "AK", "workout_key": "CUR", "workout_date": "2026-09-04"}, rows) == ""


# ══ V6-G3 — upcoming long run by meaning ════════════════════════════════════════
def test_v6g3_upcoming_by_meaning(monkeypatch):
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: date(2026, 9, 4))
    up = [{"workout_key": "F1", "workout_date": "2026-09-06", "name": "Lange duurloop",
           "planned_amount": 20, "planned_amount_type": "km", "is_race": False, "Activities": []}]
    monkeypatch.setattr(fs_client, "get_workouts_deduped", lambda ak, s, e: up)
    block = feedback_core._near_future_block(
        {"athlete_key": "AK", "workout_key": "WK", "workout_date": "2026-09-04"})
    assert "de Lange duurloop (komt eraan" in block
    assert not _REL_DAY.search(block.split("intern:")[0])         # geen 'overmorgen' als label


# ══ V6-G1 — stale athlete-message 'morgen' not instructed to be copied ══════════
def test_v6g1_stale_morgen_not_copied():
    res = ob.build(modality="hartslag", shares={}, athlete_text="Top! kan er morgen niet bij zijn")
    pb = res["prompt_block"]
    assert "BERICHT-VERPLICHTINGEN" in pb
    assert "KOPIEER het tijdswoord" in pb and "niet" in pb.lower()
    assert "Jammer dat je er niet bij kunt zijn" in pb


# ══ V6-G5 — Jordi-like: deterministic block sequence/count, no model arithmetic ══
@pytest.fixture
def fs(monkeypatch):
    store = {"zones": {"zone_type": "hartslag", "zones_text": "Z1..", "zones": HR_ZONES},
             "steps": [{"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1,
                        "distUnit": "km", "target": [{"targetType": "hr zone", "zone": 4}]} for _ in range(5)]}
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: store["zones"])
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: store["steps"])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)
    return store


def test_v6g5_jordi_sequence_and_count(fs):
    laps = [{"amount": 1, "hr_avg": v} for v in (167, 171, 160, 169, 172)]
    wd = {"athlete_name": "J", "athlete_first_name": "J", "workout_name": "Cruise intervals",
          "post_notes": "", "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
          "workout_date": "2026-09-04",
          "details": {"has_structured_workout": True, "description": "5x1km",
                      "Activities": [{"hr_avg": 168, "pace_display": "4:10", "Laps": laps}]},
          "athlete_comments": []}
    ctx = ai_feedback._build_workout_context(wd)[0]
    assert "WERKBLOK-EVIDENCE" in ctx
    assert "Blokvolgorde" in ctx and "3 in Z4" in ctx            # volgorde + telling als feit
    assert "tel of classificeer zelf NIETS" in ctx              # model mag zelf niet tellen


def test_block_sequence_unit():
    blocks = [{"index": i, "type": "ACTIVE", "target_zone": 4, "metric": "hr", "observed_hr": v}
              for i, v in enumerate((155, 171, 155, 169, 172), 1)]           # Z3,Z4,Z3,Z4,Z4
    line = ob.block_zone_counts(blocks, HR_ZONES, is_pace=False, zone_type="hartslag")
    assert "Blokvolgorde op hartslag: Z3, Z4, Z3, Z4, Z4" in line
    assert "3 in Z4, 2 in Z3" in line or "2 in Z3, 3 in Z4" in line
    assert "%" not in line


# ══ V6-G6 — Sophie continuous divergence preserved, no percentages/stale day ════
def test_v6g6_divergence_preserved():
    res = ob.build(modality="hartslag", shares={"Z1": 55, "Z2": 45},
                   athlete_text="kan er morgen niet bij zijn",
                   divergence={"above": "tempo", "easy": "hartslag"})
    pb = res["prompt_block"]
    assert "HARTSLAG/TEMPO-VERSCHIL" in pb and "je zat er gewoon goed in" in pb
    assert "KOPIEER het tijdswoord" in pb                       # stale 'morgen' niet kopiëren
    assert not re.search(r"Z[1-5]\s*\d+\s*%", pb)               # geen percentages
