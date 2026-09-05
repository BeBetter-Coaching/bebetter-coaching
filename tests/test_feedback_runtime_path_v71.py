"""Feedback runtime-path tests v7.1 — application-owned factual spine + final-text validation.

Deze tests draaien de ECHTE productie-generatiepad `feedback_core.genereer(wid)` end-to-end en
mocken ALLEEN de LLM-output en de FinalSurge-reads. Ze bewijzen dat de tekst die persistent/
verstuurbaar wordt exact de tekst is die de validator zag, dat verplichte feiten NIET kunnen
ontbreken (app voegt ze in), en dat tegenstrijdige vrije tekst fail-closed wordt geblokkeerd.

    python3 -m pytest tests/test_feedback_runtime_path_v71.py -q
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
import feedback_core

HR = [{"num": 1, "naam": "Herstel", "low": 110, "high": 130}, {"num": 2, "naam": "Easy", "low": 130, "high": 145},
      {"num": 3, "naam": "Tempo", "low": 145, "high": 169}, {"num": 4, "naam": "Interval", "low": 169, "high": 179},
      {"num": 5, "naam": "Snel", "low": 179, "high": 200}]
PACE = [{"num": 1, "naam": "z", "low": 352, "high": 720}, {"num": 2, "naam": "z", "low": 314, "high": 352},
        {"num": 3, "naam": "z", "low": 285, "high": 314}, {"num": 4, "naam": "z", "low": 260, "high": 285},
        {"num": 5, "naam": "z", "low": 200, "high": 260}]
REC = [{"num": 1, "naam": "Herstel", "low": 128, "high": 142}, {"num": 2, "naam": "Easy", "low": 142, "high": 160},
       {"num": 3, "naam": "Tempo", "low": 160, "high": 175}]
SEQ = "Op hartslag kwamen je werkblokken uit op Z3, Z4, Z3, Z4 en Z4."
DIV = "Op hartslag bleef het rustig, maar qua tempo zat er ook een stuk boven je rustige bereik in."
CORR = "Je herstelblokken bleven op hartslag in Z2, niet in Z1 zoals je dacht."


def _active():
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": 4}]}


def _rest():
    return {"intensity": "REST", "durationType": "DISTANCE", "durationDist": 0.4, "distUnit": "km", "target": []}


def _run_genereer(monkeypatch, w, zones, builder, llm_out):
    """Draai het echte genereer-pad; mock alleen LLM + FS. Geeft (result, text)."""
    feedback_core._cache.clear()
    feedback_core._cache[w["workout_key"]] = w
    monkeypatch.setattr(feedback_core, "_brein_context", lambda w: "")
    monkeypatch.setattr(feedback_core, "_timeline_rows", lambda w: [])
    monkeypatch.setattr(feedback_core, "_refresh_thread", lambda w: None)
    monkeypatch.setattr(feedback_core, "_session_context", lambda w: "")
    monkeypatch.setattr(feedback_core, "_ensure_details", lambda wid: None)
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: zones)
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder)
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)
    monkeypatch.setattr(ai_feedback, "_generate_text", lambda **kw: llm_out)
    try:
        return "SENDABLE", feedback_core.genereer(w["workout_key"])
    except ValueError as e:
        return "BLOCKED", str(e)


def _wd(wk, name, desc, laps, comments, structured):
    return {"athlete_name": f"{name} X", "athlete_first_name": name, "workout_name": name,
            "post_notes": "", "workout_key": wk, "athlete_key": "AK", "workout_type": "run",
            "workout_date": "2026-09-05",
            "details": {"has_structured_workout": structured, "description": desc,
                        "Activities": [{"hr_avg": 150, "pace_display": "4:40", "Laps": laps}]},
            "athlete_comments": comments, "thread": []}


# ══ 1. Jordi-like: deterministische sequence komt in het persistente concept ═════
def test_jordi_sequence_present_even_when_llm_omits(monkeypatch):
    w = _wd("J", "Jordi", "5x1km", [{"amount": 1, "hr_avg": v} for v in (167, 171, 160, 169, 172)],
            ["maagkramp in blok 3"], True)
    res, txt = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                             [_active() for _ in range(5)],
                             "Sterke training Jordi. Jammer van die maagkramp, hou het in de gaten.")
    assert res == "SENDABLE"
    assert SEQ in txt                                        # app voegde het blokfeit in (LLM liet het weg)


def test_jordi_no_sequence_when_coupling_insufficient(monkeypatch):
    # 3 laps vs 5 geplande blokken → AMBIGUOUS → geen blokfeit; geen verzonnen claim
    w = _wd("J2", "Jordi", "5x1km", [{"amount": 1, "hr_avg": v} for v in (167, 171, 160)], [], True)
    res, txt = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                             [_active() for _ in range(5)], "Sterke training, mooi constant.")
    assert res == "SENDABLE"
    assert "werkblokken uit op Z" not in txt                 # geen per-blok claim bij onvoldoende koppeling


# ══ 2. Sophie-like: divergentie aanwezig, blanket reassurance onmogelijk ═════════
def test_sophie_hr_guided_auto_safe_no_pace_criticism(monkeypatch):
    # v8: HR-gestuurd plan + HR compliant → AUTO_SAFE deterministisch (LLM genegeerd), geen pace-kritiek
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(6)] \
        + [{"amount": 1, "hr_avg": 140, "pace_display": "4:50"} for _ in range(4)]
    w = _wd("S", "Sophie", "herstel na cruise intervals", laps, ["kan er morgen niet bij zijn"], True)
    w["details"]["Activities"][0]["hr_avg"] = 138           # gemiddelde HR binnen Z2 (compliant)
    zones = {"zone_type": "hartslag", "zones_text": "z", "zones": HR,
             "secondary_zone_type": "tempo", "secondary_zones": PACE}
    res, txt = _run_genereer(monkeypatch, w, zones, [{"intensity": "ACTIVE", "durationType": "DISTANCE",
                             "durationDist": 6, "distUnit": "km", "target": [{"targetType": "hr zone", "zone": 2}]}],
                             "LLM zou hier iets verzinnen")
    assert res == "SENDABLE"
    assert "rustige bereik" in txt and DIV not in txt        # geen divergentie-atom
    assert txt != "LLM zou hier iets verzinnen"              # LLM niet gebruikt in AUTO_SAFE


# ══ 3. Douwe-like: AUTO_SAFE correctie, geen enkel pad kan Z1 bevestigen ═════════
def test_douwe_auto_safe_correction_no_z1(monkeypatch):
    w = _wd("D", "Douwe", "herstelblokken", [{"amount": 0.4, "hr_avg": v} for v in (148, 151, 153, 155)],
            ["elk rustblok gelukt om weer in Z1 te komen"], True)
    # zelfs met een tegenstrijdige LLM-output wordt die NIET gebruikt: AUTO_SAFE komt uit atomen
    res, txt = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": REC},
                             [_rest() for _ in range(4)],
                             f"Goed bezig Douwe. {CORR} Fijn dat je rustblokken steeds terugkwamen naar Z1.")
    assert res == "SENDABLE"
    assert CORR in txt
    assert "terugkwamen naar z1" not in txt.lower()          # geen Z1-bevestiging in het concept


# ══ 4. rejected final text is never sendable ═══════════════════════════════════
def test_rejected_rit_never_sendable(monkeypatch):
    w = _wd("R", "Rob", "duurloop", [{"amount": 1, "hr_avg": 140}], [], False)
    res, txt = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                             [], "Sterke training. Over de hele rit bleef je hartslag mooi rustig.")
    assert res == "BLOCKED" and "onjuiste sporttaal" in txt


def test_clean_case_sendable_no_boilerplate(monkeypatch):
    w = _wd("C", "Matthijs", "duurloop", [{"amount": 1, "hr_avg": 140} for _ in range(5)], [], False)
    res, txt = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                             [], "Sterke duurloop Matthijs, lekker constant gelopen. Mooi bezig.")
    assert res == "SENDABLE"
    assert txt.startswith("Sterke duurloop")                # schone case: geen ingevoegde feit-ruggengraat


# ══ 5. no generation route bypasses final validation ═══════════════════════════
def test_single_generation_route_validates():
    src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
    # generate_feedback/generate_reply worden alleen in genereer aangeroepen
    assert src.count("ai_feedback.generate_feedback(") == 1
    assert src.count("ai_feedback.generate_reply(") == 1
    # en genereer roept altijd _validate_or_block aan vóór return
    gen = src[src.index("def genereer("):src.index("def _validate_or_block(")]
    assert "_validate_or_block(w, tekst, mode)" in gen and gen.rindex("return tekst") > gen.index("_validate_or_block")
    api = open(os.path.join(_ROOT, "pwa", "api.py")).read()
    assert api.count("feedback.genereer(") == 1             # één generatie-endpoint


def test_validator_sees_exact_persisted_text(monkeypatch):
    # bewijs: de tekst die genereer teruggeeft is precies wat de validator zag
    seen = {}
    orig = feedback_core._validate_or_block

    def spy(w, tekst, mode):
        seen["text"] = tekst
        return orig(w, tekst, mode)
    monkeypatch.setattr(feedback_core, "_validate_or_block", spy)
    w = _wd("E", "Eva", "duurloop", [{"amount": 1, "hr_avg": 140} for _ in range(4)], [], False)
    res, txt = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                             [], "Mooie duurloop Eva, lekker gelopen.")
    assert res == "SENDABLE" and seen["text"] == txt
