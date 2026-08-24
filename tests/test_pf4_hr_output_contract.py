"""PF-4 — HR output-contract bij intervaltrainingen (Class C / Finding 2).

Bij een gestructureerde interval-/blokkentraining mag het whole-workout HR-gemiddelde
NOOIT op zichzelf bewijzen dat de geplande werkblokken hun target haalden — zeker niet
als de block-mapping AMBIGUOUS/UNAVAILABLE is. Het gemiddelde blijft een FEIT, maar geen
sessiebrede target-verificatie. Dit is een PROMPT/OUTPUT-CONTRACT-fix in de assembled
context (ai_feedback._build_workout_context); de deterministische classifier + block-
assessment (FC-2) blijven ONGEWIJZIGD en worden hier met de ECHTE functies aangeroepen.

    python3 -m pytest tests/test_pf4_hr_output_contract.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client


# ── HR-zonetabel: gemiddelde 150 → Z3 (145-160); harde laps 168 → Z4 (160-175) ──
HR_ZONES = {
    "zone_type": "hartslag",
    "zones_text": "Z1 (Herstel): 110-130 bpm\nZ2 (Easy): 130-145 bpm\nZ3 (Tempo): 145-160 bpm\n"
                  "Z4 (Interval): 160-175 bpm\nZ5 (Snelheid): 175-190 bpm",
    "zones": [{"num": 1, "naam": "Herstel", "low": 110, "high": 130},
              {"num": 2, "naam": "Easy", "low": 130, "high": 145},
              {"num": 3, "naam": "Tempo", "low": 145, "high": 160},
              {"num": 4, "naam": "Interval", "low": 160, "high": 175},
              {"num": 5, "naam": "Snelheid", "low": 175, "high": 190}],
}
PACE_ZONES = {
    "zone_type": "tempo",
    "zones_text": "Z2 (Easy): 5:30-6:00 min/km\nZ3 (Tempo): 4:40-5:00 min/km\nZ4: 4:10-4:30 min/km",
    "zones": [{"num": 2, "naam": "Easy", "low": 360, "high": 330},
              {"num": 3, "naam": "Tempo", "low": 300, "high": 280},
              {"num": 4, "naam": "Interval", "low": 270, "high": 250}],
}


def _active(zone=4, km=1):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": km, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": zone}]}


def _steps_interval():                       # warmup + 5×ACTIVE Z4 + cooldown = 7 blokken
    return ([{"intensity": "WARMUP", "durationType": "DISTANCE", "durationDist": 2, "distUnit": "km", "target": []}]
            + [_active() for _ in range(5)]
            + [{"intensity": "COOLDOWN", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km", "target": []}])


def _active_pace(zone=4, km=1):              # Class 2: pace-target werkblok
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": km, "distUnit": "km",
            "target": [{"targetType": "pace zone", "zone": zone}]}


def _steps_interval_pace():                  # warmup + 5×ACTIVE pace-Z4 + cooldown = 7 blokken
    return ([{"intensity": "WARMUP", "durationType": "DISTANCE", "durationDist": 2, "distUnit": "km", "target": []}]
            + [_active_pace() for _ in range(5)]
            + [{"intensity": "COOLDOWN", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km", "target": []}])


def _steps_matched():                        # 3×ACTIVE Z4 1km (matcht 3 laps 1-op-1)
    return [_active() for _ in range(3)]


def _laps(n, hr=150, amount=1.0):
    return [{"amount": amount, "hr_avg": hr, "pace_display": "5:00"} for _ in range(n)]


def _wd(hr_avg, laps, structured=True, pace_display="5:00", ztype="hartslag"):
    return {"athlete_name": "Lisa T", "athlete_first_name": "Lisa", "workout_name": "Training",
            "post_notes": "", "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
            "workout_date": "2026-08-20",
            "details": {"has_structured_workout": structured,
                        "Activities": [{"hr_avg": hr_avg, "pace_display": pace_display, "Laps": laps}]},
            "athlete_comments": []}


@pytest.fixture
def fs(monkeypatch):
    """Echte assess_workout_blocks/_planned_blocks/classify (FC-2), gemockte fetches."""
    store = {"zones": HR_ZONES, "steps": _steps_interval()}
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: store["zones"])
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: store["steps"])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)
    return store


PROT = "bewijst NIET of de geplande werkblokken hun target haalden"     # kernguard
NO_VERDICT = "NOOIT dat de training 'correct uitgevoerd'"
UNCERTAIN = "NIET vast te stellen"
MATCHED_LEAD = "BLOK-ANALYSE hieronder als leidende beoordeling"
CONTINU = "continue inspanning"


def _ctx(wd):
    context, _ = ai_feedback._build_workout_context(wd)
    return context


# ════════════════════════════════════════════════════════════════════════════
# 1,2,5,6 — structured + AMBIGUOUS/UNAVAILABLE: geen sessiebrede goedkeuring
# ════════════════════════════════════════════════════════════════════════════
def test_1_structured_ambiguous_geen_correct_uitgevoerd(fs):
    fs["steps"] = _steps_interval()                       # 7 planned
    ctx = _ctx(_wd(150, _laps(12)))                       # 12 laps → count mismatch → AMBIGUOUS
    assert PROT in ctx and NO_VERDICT in ctx and UNCERTAIN in ctx
    assert CONTINU not in ctx                             # niet als continue training geframed


def test_2_structured_unavailable_geen_correct_uitgevoerd(fs):
    fs["steps"] = _steps_interval()
    ctx = _ctx(_wd(150, []))                              # geen laps → UNAVAILABLE, maar wél structured
    assert PROT in ctx and NO_VERDICT in ctx and UNCERTAIN in ctx
    assert CONTINU not in ctx


def test_5_in_zone_gemiddelde_geen_target_goedkeuring(fs):
    # gemiddelde valt IN Z3 (150), maar dat mag de werkblokken (Z4) niet goedkeuren.
    fs["steps"] = _steps_interval()
    ctx = _ctx(_wd(150, _laps(12, hr=168)))
    assert "BINNEN de persoonlijke zone" in ctx           # whole-workout HR blijft feit (Z3 membership)
    assert NO_VERDICT in ctx                              # maar geen sessiebrede goedkeuring


def test_6_out_of_zone_gemiddelde_geen_harder_advies(fs):
    # gemiddelde onder Z4 → mag NIET automatisch 'harder' adviseren bij AMBIGUOUS.
    fs["steps"] = _steps_interval()
    ctx = _ctx(_wd(138, _laps(12, hr=168)))               # 138 → Z2
    assert "evenmin dat er 'te hard' of 'te zacht' is gelopen" in ctx
    assert UNCERTAIN in ctx


# ════════════════════════════════════════════════════════════════════════════
# 3 — structured + MATCHED: per-blok leidend, geen gemiddelde-verdict
# ════════════════════════════════════════════════════════════════════════════
def test_3_structured_matched_perblok_leidend(fs):
    fs["steps"] = _steps_matched()                        # 3 planned
    ctx = _ctx(_wd(150, _laps(3, hr=168)))                # 3 laps 1km → MATCHED
    assert PROT in ctx and NO_VERDICT in ctx              # gemiddelde is geen sessiebrede goedkeuring
    assert MATCHED_LEAD in ctx                            # per-blok BLOK-ANALYSE leidt
    assert UNCERTAIN not in ctx                           # MATCHED → geen 'niet koppelbaar'-tekst
    assert CONTINU not in ctx


# ════════════════════════════════════════════════════════════════════════════
# 4,7 — whole-workout HR blijft feit; continue training houdt bestaand contract
# ════════════════════════════════════════════════════════════════════════════
def test_4_whole_workout_hr_blijft_observatie(fs):
    fs["steps"] = _steps_interval()
    ctx = _ctx(_wd(150, _laps(12)))
    assert "BEREKENDE POSITIE" in ctx                     # het gemiddelde blijft als feit aanwezig
    assert "150 bpm" in ctx


def test_7_continue_training_behoudt_gemiddelde_contract(fs):
    ctx = _ctx(_wd(150, _laps(1), structured=False))      # geen structured plan → continu
    assert CONTINU in ctx
    assert "correct uitgevoerd" in ctx                    # bestaand contract blijft
    assert PROT not in ctx                                # geen interval-guard op een continue run


def test_7b_enkel_blok_is_geen_interval(fs):
    fs["steps"] = [_active()]                             # 1 gepland blok → NIET structured
    ctx = _ctx(_wd(150, _laps(1)))
    assert CONTINU in ctx and PROT not in ctx             # easy/steady run niet 'onzeker' gemaakt


# ════════════════════════════════════════════════════════════════════════════
# 8,9 — pace-target geen HR-verdict; missing HR → geen zone-regel
# ════════════════════════════════════════════════════════════════════════════
def test_8_pace_target_interval_zelfde_guard_geen_hr_oordeel(fs):
    # Class 2: een ECHTE pace-target interval bij een tempo-atleet (planned metric == zonetabel).
    fs["zones"] = PACE_ZONES
    fs["steps"] = _steps_interval_pace()
    ctx = _ctx(_wd(150, _laps(12), pace_display="5:00"))  # tempo-atleet, pace-interval, AMBIGUOUS
    assert PROT in ctx and UNCERTAIN in ctx               # PF-4 structuur-guard blijft firen
    # planned metric = tempo → tempo is PRIMAIR; geen HR-zoneoordeel
    assert "PRIMAIR via tempo" in ctx
    assert "bpm = Zone" not in ctx and "bpm — BINNEN" not in ctx


def test_9_missing_hr_geen_zone_regel(fs):
    fs["steps"] = _steps_interval()
    ctx = _ctx(_wd(None, _laps(12)))                      # geen hr_avg
    assert "BEREKENDE POSITIE" not in ctx                 # geen whole-workout zone-regel → geen OORDEEL
    assert NO_VERDICT not in ctx


# ════════════════════════════════════════════════════════════════════════════
# 10,11,12 — beide generators krijgen de guard; dispatch ongewijzigd
# ════════════════════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, t): self.content = [type("X", (), {"text": t})()]


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_feedback, "create_message", lambda **kw: calls.append(kw) or _Resp("ok"))
    return calls


def test_10_generate_feedback_krijgt_guard(fs, monkeypatch):
    calls = _capture(monkeypatch)
    ai_feedback.generate_feedback(_wd(150, _laps(12)))
    prompt = calls[-1]["messages"][0]["content"]
    assert PROT in prompt and NO_VERDICT in prompt


def test_11_generate_reply_zelfde_truth_boundary(fs, monkeypatch):
    calls = _capture(monkeypatch)
    thread = [{"van": "coach", "tekst": "hoe ging het?"},
              {"van": "atleet", "tekst": "zwaar maar oké"}]
    ai_feedback.generate_reply(_wd(150, _laps(12)), thread)
    achtergrond = calls[-1]["messages"][0]["content"]     # de context zit in het achtergrondbericht
    assert PROT in achtergrond and NO_VERDICT in achtergrond
    assert len(calls[-1]["messages"]) >= 3                # reply blijft multi-turn (dispatch intact)


def test_12_conversation_dispatch_unchanged():
    import feedback_core as FC
    assert FC.feedback_mode([]) == FC.INITIAL_ANALYSIS
    assert FC.feedback_mode([{"van": "coach", "tekst": "q"},
                             {"van": "atleet", "tekst": "a"}]) == FC.FOLLOW_UP_REPLY


# ════════════════════════════════════════════════════════════════════════════
# FC-2 untouched — assessment blijft exact de deterministische waarheid
# ════════════════════════════════════════════════════════════════════════════
def test_fc2_assessment_untouched_ambiguous_en_matched():
    amb = fs_client.assess_workout_blocks(_steps_interval(), _laps(12), HR_ZONES["zones"], "hartslag")
    assert amb["confidence"] == "AMBIGUOUS"               # 7 planned ≠ 12 laps
    matched = fs_client.assess_workout_blocks(_steps_matched(), _laps(3, hr=168), HR_ZONES["zones"], "hartslag")
    assert matched["confidence"] == "MATCHED"             # 3==3 + structureel compatibel
    unavail = fs_client.assess_workout_blocks(_steps_interval(), [], HR_ZONES["zones"], "hartslag")
    assert unavail["confidence"] == "UNAVAILABLE"


def test_clean_text_ongewijzigd():
    # PF-4 lost NIETS op met output-cleanup: _clean_text raakt geen quotes/verdicts.
    assert ai_feedback._clean_text('"correct uitgevoerd"') == '"correct uitgevoerd"'
    assert ai_feedback._clean_text("goed — sterk") == "goed, sterk"
