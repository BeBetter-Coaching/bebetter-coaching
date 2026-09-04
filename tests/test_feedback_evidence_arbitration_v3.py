"""Feedback Evidence Arbitration & Message Coverage v3 — deterministic obligations layer.

Bewijst de bron-verbeteringen (geen downstream rewriter) voor de Comfort-gate 2/4:
- P0 zone-evidence arbitration: exacte %, modaliteit gelabeld, geen materiële zone weggelaten;
- P0 atleet-claim-verificatie: 'ik dacht Z1-Z2' niet blind bevestigd;
- P0 bericht-verplichtingen: kan-niet-komen/pijn/vraag niet genegeerd;
- P0/P1 signaal-verplichting: actieve klacht/verhoogde belasting stuurt de tekst (veilig);
- P1 modaliteit-labels + geen afronding.

Golden G17..G22 = geanonimiseerde/synthetische fixtures (geen echte namen/comments). De
AI-output is niet-deterministisch en wordt hier NIET getest; we borgen het deterministische
VERPLICHTINGEN-contract (feedback_obligations) + de integratie in _build_workout_context.

    python3 -m pytest tests/test_feedback_evidence_arbitration_v3.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client
import feedback_obligations as ob


# ── pure zone_shares ─────────────────────────────────────────────────────────
HR_ZONES = [
    {"num": 1, "naam": "Herstel", "low": 110, "high": 130},
    {"num": 2, "naam": "Easy", "low": 130, "high": 145},
    {"num": 3, "naam": "Tempo", "low": 145, "high": 160},
    {"num": 4, "naam": "Interval", "low": 160, "high": 175},
    {"num": 5, "naam": "Snelheid", "low": 175, "high": 190}]

# Tempozones in seconden/km (sneller = lagere seconden).
PACE_ZONES = [
    {"num": 1, "naam": "Herstel", "low": 352, "high": 720},   # 5:52–12:00
    {"num": 2, "naam": "Duur", "low": 314, "high": 352},      # 5:14–5:52
    {"num": 3, "naam": "Tempo", "low": 285, "high": 314},     # 4:45–5:14
    {"num": 4, "naam": "Drempel", "low": 260, "high": 285},   # 4:20–4:45
    {"num": 5, "naam": "Snelheid", "low": 200, "high": 260}]  # <4:20


def test_zone_shares_distance_weighted():
    laps = [{"amount": 1, "hr_avg": 138} for _ in range(8)] + [{"amount": 1, "hr_avg": 168} for _ in range(2)]
    shares, any_dist, used = ob.zone_shares(laps, HR_ZONES, is_pace=False)
    assert shares == {"Z2": 80, "Z4": 20}
    assert any_dist and used == 10


def test_zone_shares_needs_two_laps():
    assert ob.zone_shares([{"amount": 1, "hr_avg": 140}], HR_ZONES, is_pace=False)[0] == {}
    assert ob.zone_shares([], HR_ZONES, is_pace=False)[0] == {}


def test_zone_distribution_delegates_and_matches():
    # De zoneverdeling-tekst deelt nu één bron met de obligations-laag (geen divergentie).
    laps = [{"amount": 1, "hr_avg": 138} for _ in range(8)] + [{"amount": 1, "hr_avg": 168} for _ in range(2)]
    out = ai_feedback._zone_distribution(laps, HR_ZONES, is_pace=False)
    assert "ZONEVERDELING" in out and "Z2 80%" in out and "Z4 20%" in out


# ══ G17 — easy/recovery run met weggelaten hogere zone (Sophie) ═════════════════
def test_g17_easy_run_omitted_higher_zone():
    res = ob.build(modality="tempo", shares={"Z1": 74, "Z2": 13, "Z3": 13},
                   athlete_text="ik dacht Z1, nu zie ik Z1-Z2, maakt vast niet uit")
    pb = res["prompt_block"]
    assert "EVIDENCE-CONTRACT" in pb
    assert "op tempo" in pb                                   # modaliteit gelabeld
    assert "Z3 13%" in pb                                     # de gelijk-grote hogere zone NIET weggelaten
    assert "materiële" in pb.lower() or "materiele" in pb.lower()
    # claim-verificatie: niet blind bevestigen
    assert "Status: PARTIALLY_SUPPORTED" in pb or "Status: CONTRADICTED" in pb
    assert "'Klopt'" in pb and "Precies" in pb               # verboden instemmingswoorden benoemd


def test_g17_completeness_rule_wording():
    res = ob.build(modality="tempo", shares={"Z1": 74, "Z2": 13, "Z3": 13}, athlete_text="")
    pb = res["prompt_block"]
    assert "klein stukje" in pb                               # verbiedt '13% = klein stukje' terwijl Z3 verdwijnt
    assert "Rond NIET af" in pb


# ══ G18 — dual-modality: exacte %, modaliteit gelabeld, geen afronding (Douwe) ══
def test_g18_no_rounding_modality_labeled():
    res = ob.build(modality="hartslag", shares={"Z1": 11, "Z2": 33, "Z3": 56},
                   planned_target_zones={3}, athlete_text="")
    pb = res["prompt_block"]
    assert "op hartslag" in pb
    assert "Z2 33%" in pb and "Z3 56%" in pb                  # exacte getallen
    assert "33% is 33%, niet 40%" in pb                       # expliciet tegen de 33→40 afronding
    assert "de helft" in pb.lower()                           # verbiedt vage 'helft' voor 56%
    # geen atleet-claim → geen claim-sectie
    assert "ATLEET-CLAIM" not in pb


def test_g18_above_target_surfaced():
    # target Z3, materieel aandeel in Z4 → mag niet als 'precies volgens plan' worden bevestigd.
    res = ob.build(modality="tempo", shares={"Z1": 20, "Z3": 27, "Z4": 53},
                   planned_target_zones={3}, athlete_text="")
    pb = res["prompt_block"]
    assert "BOVEN het geplande target" in pb and "Z4" in pb


# ══ G19 — actieve klacht + threshold-werk → veilige check-in ════════════════════
def test_g19_active_complaint_steers_safely():
    res = ob.build(modality="hartslag", shares={}, complaint_areas=["scheenbeen"],
                   load_elevated=True, intensity_high=True, has_upcoming=False, athlete_text="")
    pb = res["prompt_block"]
    assert "SIGNAAL-VERPLICHTING" in pb
    assert "scheenbeen" in pb
    assert "check-in" in pb
    assert "geen diagnose" in pb and "geen behandeladvies" in pb


def test_g19_complaint_without_intensity_is_quiet():
    # actieve klacht maar geen zware uitvoering/geen zware sessie op komst → geen harde verplichting
    # (de gelockte achtergrond-directive dekt de zachte vermelding al; geen dubbel-injectie/ruis).
    res = ob.build(modality="hartslag", shares={}, complaint_areas=["knie"],
                   load_elevated=False, intensity_high=False, has_upcoming=False, athlete_text="")
    assert "SIGNAAL-VERPLICHTING" not in res["prompt_block"]


# ══ G20 — beschikbaarheidsbericht: niet wensen alsof ze aanwezig is ═════════════
def test_g20_availability_obligation():
    res = ob.build(modality="hartslag", shares={},
                   athlete_text="Lekkere training! Alleen kan ik er morgen helaas niet bij zijn.")
    pb = res["prompt_block"]
    assert "BERICHT-VERPLICHTINGEN" in pb
    assert "KOMENDE sessie niet te kunnen doen" in pb
    assert "GEEN plezier of succes" in pb


# ══ G21 — atleet-feitclaim weerlegd door verdeling ══════════════════════════════
def test_g21_athlete_claim_contradicted():
    res = ob.build(modality="hartslag", shares={"Z2": 30, "Z3": 45, "Z4": 25},
                   athlete_text="volgens mij ging alles in Z2")
    pb = res["prompt_block"]
    assert "ATLEET-CLAIM" in pb
    assert "Status: CONTRADICTED" in pb                       # 'alles' + dominante Z3 niet geclaimd
    assert "NIET met 'Klopt'" in pb


def test_supported_claim_no_section():
    # atleet had gelijk (dekt alle materiële zones, geen totaliteitsfout) → geen claim-ruis
    res = ob.build(modality="hartslag", shares={"Z1": 88, "Z2": 12}, athlete_text="ging in Z1 en Z2")
    assert "ATLEET-CLAIM" not in res["prompt_block"]


# ══ G22 — schone case → leeg blok (kort en coachend) ════════════════════════════
def test_g22_clean_case_empty_block():
    res = ob.build(modality="hartslag", shares={"Z1": 95, "Z2": 5},
                   athlete_text="lekker gelopen, voelde goed")
    assert res["prompt_block"] == ""
    assert res["sections"] == []


def test_single_material_zone_no_zone_section():
    # één dominante zone → geen arbitrage nodig (geen omissie/verwarring mogelijk)
    res = ob.build(modality="tempo", shares={"Z1": 92, "Z2": 8}, athlete_text="")
    assert "ZONE-EVIDENCE" not in res["prompt_block"]


# ── claim-parsing units ──────────────────────────────────────────────────────
def test_claimed_zones_parsing():
    assert ob._claimed_zones("ik dacht Z1-Z2") == {1, 2}
    assert ob._claimed_zones("alles in zone 2") == {2}
    assert ob._claimed_zones("Z3 en Z4 gedaan") == {3, 4}
    assert ob._claimed_zones("geen zone genoemd") == set()


def test_schedule_request_obligation():
    res = ob.build(shares={}, athlete_text="Kun je mijn training van donderdag verzetten?")
    pb = res["prompt_block"]
    assert "BERICHT-VERPLICHTINGEN" in pb and "coach-agency" in pb


# ══ integratie via _build_workout_context ═══════════════════════════════════════
def _wd_pace(laps, comments=None, notes=""):
    return {"athlete_name": "Atleet S", "athlete_first_name": "S", "workout_name": "Duurloop",
            "post_notes": notes, "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
            "workout_date": "2026-09-04",
            "details": {"has_structured_workout": False, "description": "rustige duurloop",
                        "Activities": [{"hr_avg": 140, "pace_display": "5:40", "Laps": laps}]},
            "athlete_comments": comments or []}


@pytest.fixture
def fs_pace(monkeypatch):
    monkeypatch.setattr(fs_client, "get_athlete_zones",
                        lambda ak: {"zone_type": "tempo", "zones_text": "Z1..", "zones": PACE_ZONES})
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: [])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)


def test_g17_integration_pace_run(fs_pace):
    # 6× Z1 (6:00), 2× Z2 (5:30), 2× Z3 (5:00) → Z1 60/Z2 20/Z3 20, allemaal materieel.
    laps = ([{"amount": 1, "pace_display": "6:00"} for _ in range(6)]
            + [{"amount": 1, "pace_display": "5:30"} for _ in range(2)]
            + [{"amount": 1, "pace_display": "5:00"} for _ in range(2)])
    ctx = ai_feedback._build_workout_context(_wd_pace(laps, comments=["ik dacht dat alles Z1-Z2 was"]))[0]
    assert "EVIDENCE-CONTRACT" in ctx
    assert "op tempo" in ctx
    assert "Z3 20%" in ctx                                    # hogere zone niet weggelaten
    assert "ATLEET-CLAIM" in ctx                              # claim wordt geverifieerd
    assert "ZONEVERDELING" in ctx                             # bestaande verdeling nog intact


def test_g22_integration_clean_run(fs_pace):
    # alles Z1 → geen arbitrage → geen evidence-contract, wél gewoon context.
    laps = [{"amount": 1, "pace_display": "6:10"} for _ in range(10)]
    ctx = ai_feedback._build_workout_context(_wd_pace(laps, notes="lekker gelopen"))[0]
    assert "EVIDENCE-CONTRACT" not in ctx


def test_integration_signal_from_brein_diag(fs_pace):
    # actieve klacht + verhoogde belasting uit _brein_diag + hoge RPE → signaalverplichting.
    laps = [{"amount": 1, "pace_display": "4:30"} for _ in range(6)]   # Z4 (drempel), zwaar
    wd = _wd_pace(laps, notes="pittig")
    wd["effort"] = 8
    wd["_brein_diag"] = {"complaint_areas": ["scheenbeen"], "load_active": True}
    ctx = ai_feedback._build_workout_context(wd)[0]
    assert "SIGNAAL-VERPLICHTING" in ctx and "scheenbeen" in ctx
