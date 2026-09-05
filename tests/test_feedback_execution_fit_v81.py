"""Feedback Practical Coaching Tolerance v8.1 — ExecutionFit buckets.

Vervangt binaire compliance door een deterministische ExecutionFit (ON_TARGET / MOSTLY_ON_TARGET /
MIXED / CLEARLY_ABOVE) op de PRIMAIRE metriek uit MetricAuthority. Normale afwijking naar één
aangrenzende zone wordt PROPORTIONEEL beschreven, niet bestraft. Absolute taal ('netjes binnen',
'volledig binnen', 'precies volgens plan') alleen bij ON_TARGET (de Rick-fix). Geen percentages.

    python3 -m pytest tests/test_feedback_execution_fit_v81.py -q
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import fs_client
import feedback_atoms as fa
import metric_authority as MA

HR = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
      enumerate([(110, 130), (130, 145), (145, 169), (169, 179), (179, 200)], 1)]
PACE = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
        enumerate([(352, 720), (314, 352), (285, 314), (260, 285), (200, 260)], 1)]
_ZONE_PCT = re.compile(r"Z[1-5]\s*\d+\s*%|\d+\s*%")


def _hr(z):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 6, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": z}]}


def _pacetgt(z):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 6, "distUnit": "km",
            "target": [{"targetType": "pace zone", "zone": z}]}


def _lhr(hr, dur):
    return {"hr_avg": hr, "duration": dur, "amount": 1}


def _lpace(pace, dur):
    return {"pace_display": pace, "duration": dur, "amount": 1}


def _fit_hr(laps, upper=2):
    return fa.execution_fit(laps, HR, is_pace=False, target_upper=upper)


def _decide(monkeypatch, *, builder, laps, zones, comments=None, hsw=True):
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder)
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: zones)
    w = {"workout_type": "run", "workout_key": "W", "athlete_key": "AK", "post_notes": "",
         "athlete_comments": comments or [],
         "details": {"has_structured_workout": hsw, "description": "rustige duurloop",
                     "Activities": [{"hr_avg": 140, "pace_display": "5:00", "Laps": laps}]}}
    return fa.build_decision(w)


HRZ = {"zone_type": "hartslag", "zones_text": "z", "zones": HR}
PACEZ = {"zone_type": "tempo", "zones_text": "z", "zones": PACE}


# ══ T1 Sophie — all in target → ON_TARGET, positive atom, pace ignored ══════════
def test_t1_sophie_on_target(monkeypatch):
    d = _decide(monkeypatch, builder=[_hr(2)], zones={**HRZ, "secondary_zone_type": "tempo", "secondary_zones": PACE},
                laps=[_lhr(125, 335), _lhr(138, 2666)])
    assert d["status"] == fa.AUTO_SAFE and d["execution_fit"]["category"] == fa.ON_TARGET
    assert "netjes binnen het rustige bereik" in d["text"]
    assert "tempo" not in d["text"].lower()                   # pace niet gebruikt voor compliance


# ══ T2 Rick — ~84% in target, remainder adjacent Z3 → MOSTLY, geen absolute claim ══
def test_t2_rick_mostly_on_target(monkeypatch):
    # Z1 335s, Z2 2533s, Z3 553s → 83.8% in/onder target, alleen aangrenzend
    laps = [_lhr(125, 335), _lhr(138, 2533), _lhr(155, 553)]
    assert _fit_hr(laps)["category"] == fa.MOSTLY_ON_TARGET
    d = _decide(monkeypatch, builder=[_hr(2)], zones=HRZ, laps=laps, comments=["pittige dag gehad"])
    assert d["status"] == fa.AUTO_SAFE
    assert "grootste deel" in d["text"] and "liep de intensiteit wat op" in d["text"]
    assert "netjes binnen" not in d["text"]                   # geen absolute stellige claim
    assert not _ZONE_PCT.search(d["text"])                    # geen percentages
    assert "fout" not in d["text"].lower() and "te hard" not in d["text"].lower()


# ══ T3 tiny excursion (45s above) → ON_TARGET (ruis niet overdrijven) ═══════════
def test_t3_tiny_excursion_on_target():
    assert _fit_hr([_lhr(138, 3000), _lhr(155, 45)])["category"] == fa.ON_TARGET


# ══ T4 meaningful but not disastrous → MIXED (neutraal, geen hard fail) ═════════
def test_t4_mixed(monkeypatch):
    laps = [_lhr(138, 2000), _lhr(155, 1100)]                 # ~65% in target
    assert _fit_hr(laps)["category"] == fa.MIXED
    d = _decide(monkeypatch, builder=[_hr(2)], zones=HRZ, laps=laps)
    assert d["status"] == fa.AUTO_SAFE and "grotendeels rustig" in d["text"]
    assert "netjes binnen" not in d["text"]


# ══ T5 clearly above (sustained 2+ zones above) → CLEARLY_ABOVE ═════════════════
def test_t5_clearly_above(monkeypatch):
    laps = [_lhr(138, 1500), _lhr(172, 1500)]                 # helft in Z4 (2 zones boven target Z2)
    assert _fit_hr(laps)["category"] == fa.CLEARLY_ABOVE
    d = _decide(monkeypatch, builder=[_hr(2)], zones=HRZ, laps=laps)
    assert d["status"] == fa.AUTO_SAFE and "duidelijk deel" in d["text"] and "hoger" in d["text"]
    assert "fout" not in d["text"].lower()                    # neutraal, geen berisping


# ══ T6 pace-primary — zelfde tolerantie op tempo, HR overrulet niet ═════════════
def test_t6_pace_primary(monkeypatch):
    # tempo plan Z2 (314-352s); laps grotendeels Z2, wat Z3 (sneller); HR hoog maar irrelevant
    laps = [_lpace("5:30", 2600), _lpace("5:05", 500)]        # 5:30=330 Z2, 5:05=305 Z3
    d = _decide(monkeypatch, builder=[_pacetgt(2)], zones=PACEZ, laps=laps)
    assert d["authority"]["primary"] == MA.PACE
    assert d["status"] == fa.AUTO_SAFE and "tempo" in d["text"].lower()
    assert "op hartslag" not in d["text"].lower()             # HR niet als compliance-oordeel


# ══ T7 dual — beide tellen alleen omdat het plan beide voorschrijft ═════════════
def test_t7_dual_authority():
    a = MA.derive(fs_client._planned_blocks([_hr(2), _pacetgt(2)]), "", "run")
    assert a["primary"] == MA.DUAL and a["hr_target_zones"] and a["pace_target_zones"]


# ══ T8 absolute-language guard — 'netjes binnen' onmogelijk bij boven-target ════
def test_t8_absolute_language_only_on_target(monkeypatch):
    # forceer een niet-ON_TARGET fit; controleer dat geen absolute 'netjes binnen' in de output zit
    for laps in ([_lhr(138, 2533), _lhr(155, 553), _lhr(125, 335)],  # MOSTLY
                 [_lhr(138, 1500), _lhr(172, 1500)]):                # CLEARLY_ABOVE
        d = _decide(monkeypatch, builder=[_hr(2)], zones=HRZ, laps=laps)
        assert not fa._ABSOLUTE_RE.search(d["text"])


# ══ T9 atoms-only — AUTO_SAFE-tekst is exact de geregistreerde atomen ═══════════
def test_t9_atoms_only(monkeypatch):
    d = _decide(monkeypatch, builder=[_hr(2)], zones=HRZ, laps=[_lhr(138, 2533), _lhr(155, 553), _lhr(125, 335)])
    assert d["status"] == fa.AUTO_SAFE and fa._final_is_atoms_only(d["text"], d["atoms"])


# ══ T10 safety locks — geen rit/%/stale dag/interne taal in ExecutionFit-atomen ══
def test_t10_safety_locks():
    for (metric, easy), variants in fa._FIT_TEXT.items():
        for cat, txt in variants.items():
            assert not re.search(r"\brit\b|\britje\b|fietsrit", txt.lower())
            assert not _ZONE_PCT.search(txt)
            assert not re.search(r"\b(gisteren|morgen|overmorgen|eergisteren)\b", txt.lower())
            for bad in ("blokmatch", "matched", "possible", "provenance", "pipeline", "readiness"):
                assert bad not in txt.lower()


# ══ constants zijn simpele, testbare drempels (niet overfit) ════════════════════
def test_thresholds_are_simple_constants():
    assert fa._NOISE_SECONDS == 90
    assert fa._MOSTLY_MIN_SHARE == 0.80
    assert fa._MIXED_MIN_SHARE == 0.50
