"""Feedback Athlete-Facing Zone Simplification + Hard Signal Obligation v4.

Productbesluit na re-gate 1/4: GEEN zonepercentages meer in athlete-facing feedback (het model
nam ze aantoonbaar onbetrouwbaar over: 23→27, 57→71, 56→50). De exacte verdeling blijft INTERN
bewijs voor een KWALITATIEVE duiding + exacte blok/lap-AANTALLEN. Actieve klacht bij relevante
belasting → deterministische neutrale check-in.

Bewijst het bron-contract (geen downstream rewriter); AI-output is niet-deterministisch en wordt
NIET getest — we borgen dat de athlete-facing context/instructies geen zonepercentages bevatten,
dat blok-aantallen wél zijn toegestaan, en dat de verplichtingen deterministisch vuren.

    python3 -m pytest tests/test_feedback_zone_simplification_v4.py -q
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client
import feedback_obligations as ob

SYS = ai_feedback.SYSTEM_PROMPT

HR_ZONES = {
    "zone_type": "hartslag", "zones_text": "Z1..",
    "zones": [{"num": 1, "naam": "Herstel", "low": 110, "high": 130},
              {"num": 2, "naam": "Easy", "low": 130, "high": 145},
              {"num": 3, "naam": "Tempo", "low": 145, "high": 160},
              {"num": 4, "naam": "Interval", "low": 169, "high": 179},
              {"num": 5, "naam": "Snelheid", "low": 179, "high": 200}]}

_ZONE_PCT = re.compile(r"Z[1-5]\s*\d+\s*%")


def _active(zone=4, km=1):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": km, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": zone}]}


def _steps_5x():
    return [_active() for _ in range(5)]


@pytest.fixture
def fs(monkeypatch):
    store = {"zones": HR_ZONES, "steps": _steps_5x()}
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: store["zones"])
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: store["steps"])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)
    return store


def _wd(hr_avg=150, laps=None, structured=True, comments=None, notes="", diag=None, effort=None):
    wd = {"athlete_name": "Atleet X", "athlete_first_name": "X", "workout_name": "Training",
          "post_notes": notes, "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
          "workout_date": "2026-09-04",
          "details": {"has_structured_workout": structured, "description": "",
                      "Activities": [{"hr_avg": hr_avg, "pace_display": "5:00", "Laps": laps or []}]},
          "athlete_comments": comments or []}
    if diag is not None:
        wd["_brein_diag"] = diag
    if effort is not None:
        wd["effort"] = effort
    return wd


def _ctx(wd):
    return ai_feedback._build_workout_context(wd)[0]


# ══ P0 — hard ban athlete-facing zone percentages ═══════════════════════════════
def test_system_prompt_bans_zone_percentages():
    assert "GEEN ZONEPERCENTAGES" in SYS
    assert '"56% in Z3"' in SYS and "distributie-breuk" in SYS
    assert "AANTALLEN werkblokken/laps" in SYS              # counts expliciet toegestaan


def test_context_has_no_zone_percentage(fs):
    laps = [{"amount": 1, "hr_avg": 138} for _ in range(7)] + [{"amount": 1, "hr_avg": 172} for _ in range(3)]
    ctx = _ctx(_wd(hr_avg=148, laps=laps, structured=True))
    assert not _ZONE_PCT.search(ctx)                        # geen 'Z2 70%'
    assert "ZONEVERDELING" not in ctx


def test_no_distribution_prose_in_obligations():
    res = ob.build(modality="hartslag", shares={"Z2": 33, "Z3": 56}, planned_target_zones={3},
                   is_structured=True, athlete_text="")
    assert not _ZONE_PCT.search(res["prompt_block"])


# ══ internal evidence retained ══════════════════════════════════════════════════
def test_internal_zone_shares_still_exact():
    laps = [{"amount": 1, "hr_avg": 138} for _ in range(7)] + [{"amount": 1, "hr_avg": 172} for _ in range(3)]
    shares, _, used = ob.zone_shares(laps, HR_ZONES["zones"], is_pace=False)
    assert shares == {"Z2": 70, "Z4": 30} and used == 10     # exact intern beschikbaar (Masterbrein/QA)


# ══ R2 Jordi — block-count evidence (counts allowed) ════════════════════════════
def test_r2_jordi_block_counts(fs):
    # werkblok-HR 167/171/160/169/172 vs Z4 169-179 → 3 in Z4 (171,169,172).
    laps = [{"amount": 1, "hr_avg": v} for v in (167, 171, 160, 169, 172)]
    ctx = _ctx(_wd(hr_avg=168, laps=laps, structured=True))
    assert "WERKBLOK-TELLING" in ctx
    assert "3 in Z4" in ctx                                  # betrouwbare AANTALLEN i.p.v. percentage
    assert not _ZONE_PCT.search(ctx)


def test_block_zone_counts_unit():
    blocks = [{"index": i, "type": "ACTIVE", "target_zone": 4, "metric": "hr", "observed_hr": v}
              for i, v in enumerate((167, 171, 160, 169, 172), 1)]
    line = ob.block_zone_counts(blocks, HR_ZONES["zones"], is_pace=False, zone_type="hartslag")
    assert "van de 5 werkblokken" in line and "3 in Z4" in line
    assert "%" not in line


# ══ R4 Douwe — active shin complaint triggers neutral check-in ══════════════════
def test_r4_douwe_complaint_checkin(fs):
    laps = [{"amount": 1, "hr_avg": 172} for _ in range(5)]  # zwaar (Z4)
    wd = _wd(hr_avg=172, laps=laps, structured=True, notes="pittig",
             diag={"complaint_areas": ["scheen"], "load_active": True}, effort=8)
    ctx = _ctx(wd)
    assert "SIGNAAL-VERPLICHTING" in ctx
    assert "scheen" in ctx and "check-in" in ctx
    assert "geen diagnose" in ctx


def test_r4_complaint_checkin_example_present():
    res = ob.build(modality="hartslag", shares={}, complaint_areas=["scheen"],
                   intensity_high=True, athlete_text="")
    pb = res["prompt_block"]
    assert "hou even in de gaten hoe je scheen" in pb or "hoe reageert je scheen" in pb


def test_complaint_stale_without_intensity_quiet():
    res = ob.build(modality="hartslag", shares={}, complaint_areas=["knie"],
                   intensity_high=False, has_upcoming=False, athlete_text="")
    assert "SIGNAAL-VERPLICHTING" not in res["prompt_block"]


# ══ R3 Sophie — claim correction (no %) + message obligation stays green ════════
def test_r3_sophie_claim_and_message():
    res = ob.build(modality="tempo", shares={"Z1": 60, "Z2": 20, "Z3": 20},
                   athlete_text="ik dacht Z1-Z2, kan er helaas morgen niet bij zijn")
    pb = res["prompt_block"]
    assert "ATLEET-CLAIM" in pb and "NIET met 'Klopt'" in pb
    assert "BERICHT-VERPLICHTINGEN" in pb and "GEEN plezier of succes" in pb
    assert not _ZONE_PCT.search(pb)


# ══ R1 Matthijs — clean, at Z2 ceiling, no arbitration noise ════════════════════
def test_r1_matthijs_clean_no_block():
    # binnen zone, één dominante zone, geen claim/klacht/bericht → leeg blok (kort/coachend).
    res = ob.build(modality="tempo", shares={"Z2": 96, "Z1": 4}, athlete_text="lekker gelopen")
    assert res["prompt_block"] == ""


# ══ HR/pace divergence not silently reassured (structured) ══════════════════════
def test_structured_divergence_guard():
    res = ob.build(modality="hartslag", shares={"Z2": 40, "Z3": 60}, planned_target_zones={3},
                   is_structured=True, athlete_text="")
    assert "kies dan niet stil de geruststellende kant" in res["prompt_block"]
