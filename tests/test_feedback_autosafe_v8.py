"""Feedback Auto-Safe Builder v8 — MetricAuthority + deterministic atoms + AUTO_SAFE/REVIEW_REQUIRED.

Kern: het GEPLANDE plan bepaalt de compliance-metriek (MetricAuthority). Een secundaire metriek mag
een correct uitgevoerde primaire training niet als afwijkend kwalificeren (Sophie-fix). AUTO_SAFE
bestaat UITSLUITEND uit geregistreerde atoom-teksten (geen LLM-feiten); onzeker → REVIEW_REQUIRED.

Deze suite bevat unit-tests (authority + atomen) én echte productie-pad-tests via
`feedback_core.genereer` (mock alleen LLM + FS).

    python3 -m pytest tests/test_feedback_autosafe_v8.py -q
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
import feedback_atoms as fa
import metric_authority as MA

HR = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
      enumerate([(110, 130), (130, 145), (145, 169), (169, 179), (179, 200)], 1)]
PACE = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
        enumerate([(352, 720), (314, 352), (285, 314), (260, 285), (200, 260)], 1)]
REC = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
       enumerate([(128, 142), (142, 160), (160, 175)], 1)]


def _hr(z):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": z}]}


def _pace(z):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km",
            "target": [{"targetType": "pace zone", "zone": z}]}


def _rest():
    return {"intensity": "REST", "durationType": "DISTANCE", "durationDist": 0.4, "distUnit": "km", "target": []}


# ══ MetricAuthority ═════════════════════════════════════════════════════════════
def test_authority_hr():
    a = MA.derive(fs_client._planned_blocks([_hr(2)]), "", "run")
    assert a["primary"] == MA.HR and a["hr_target_zones"] == [2] and a["confidence"] == "HIGH"


def test_authority_pace():
    a = MA.derive(fs_client._planned_blocks([_pace(2)]), "", "run")
    assert a["primary"] == MA.PACE and a["pace_target_zones"] == [2]


def test_authority_dual():
    a = MA.derive(fs_client._planned_blocks([_hr(1), _pace(2)]), "", "run")
    assert a["primary"] == MA.DUAL


def test_authority_unknown_and_rpe():
    assert MA.derive([], "", "run")["primary"] == MA.UNKNOWN
    assert MA.derive([], "lekker op gevoel lopen", "run")["primary"] == MA.RPE
    assert MA.derive([], "hartslag onder 140 houden", "run")["primary"] == MA.HR
    assert not MA.carries_compliance_judgment(MA.derive([], "", "run"))


# ══ atom decision helper (mockt FS) ════════════════════════════════════════════
def _decision(monkeypatch, *, zones, builder, laps, comments, hr_avg=138, pace="4:50",
              hsw=True, diag=None, effort=None):
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder)
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: zones)
    w = {"workout_type": "run", "workout_key": "W", "athlete_key": "AK", "post_notes": "",
         "athlete_comments": comments,
         "details": {"has_structured_workout": hsw, "description": "herstel na cruise intervals",
                     "Activities": [{"hr_avg": hr_avg, "pace_display": pace, "Laps": laps}]}}
    if diag:
        w["_brein_diag"] = diag
    if effort is not None:
        w["effort"] = effort
    return fa.build_decision(w)


# ══ H/A. Sophie — HR-guided plan, HR compliant, pace faster → AUTO_SAFE, no divergence ══
def test_sophie_hr_authority_ignores_pace(monkeypatch):
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(6)] \
        + [{"amount": 1, "hr_avg": 140, "pace_display": "4:50"} for _ in range(4)]
    zones = {"zone_type": "hartslag", "zones_text": "z", "zones": HR,
             "secondary_zone_type": "tempo", "secondary_zones": PACE}
    d = _decision(monkeypatch, zones=zones, builder=[_hr(2)], laps=laps,
                  comments=["ik dacht Z1-Z2, kan er morgen niet bij zijn"], hr_avg=138)
    assert d["status"] == fa.AUTO_SAFE
    assert d["authority"]["primary"] == MA.HR
    ids = [a["id"] for a in d["atoms"]]
    assert "hr_compliant" in ids and "attendance" in ids
    assert "divergence" not in " ".join(ids)                 # geen tempo-divergentie-atom
    assert "tempo" not in d["text"].lower() and "boven" not in d["text"].lower()  # geen pace-kritiek
    assert "rustige bereik" in d["text"]


# ══ Douwe — false Z1 recovery claim corrected, no path can say Z1 ═══════════════
def test_douwe_correction_no_z1_confirmation(monkeypatch):
    d = _decision(monkeypatch, zones={"zone_type": "hartslag", "zones_text": "z", "zones": REC},
                  builder=[_rest() for _ in range(4)],
                  laps=[{"amount": 0.4, "hr_avg": v} for v in (148, 151, 153, 155)],
                  comments=["elk rustblok gelukt om weer in Z1 te komen"],
                  diag={"complaint_areas": ["scheen"]})
    assert d["status"] == fa.AUTO_SAFE
    ids = [a["id"] for a in d["atoms"]]
    assert "recovery_blocks_z2_not_z1" in ids and "complaint_scheen" in ids
    assert "niet in Z1" in d["text"]
    # geen enkel atoom kan bevestigen dat het herstel WEL naar Z1 ging (alleen de 'niet in Z1'-correctie)
    assert all("in z1" not in a["text"].lower() or "niet in z1" in a["text"].lower() for a in d["atoms"])


# ══ Jordi — exact block atom only with authoritative metric + coupling ══════════
def test_jordi_block_atom_when_matched(monkeypatch):
    d = _decision(monkeypatch, zones={"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                  builder=[_hr(4) for _ in range(5)],
                  laps=[{"amount": 1, "hr_avg": v} for v in (167, 171, 160, 169, 172)],
                  comments=["maagkramp in blok 3"], hr_avg=168)
    assert d["status"] == fa.AUTO_SAFE and d["authority"]["primary"] == MA.HR
    assert d["text"] == "Op hartslag kwamen je werkblokken uit op Z3, Z4, Z3, Z4 en Z4."


def test_jordi_ambiguous_coupling_no_block_prose(monkeypatch):
    # 3 laps vs 5 blokken → AMBIGUOUS → geen blok-atoom, geen verzonnen prose → REVIEW_REQUIRED
    d = _decision(monkeypatch, zones={"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                  builder=[_hr(4) for _ in range(5)],
                  laps=[{"amount": 1, "hr_avg": v} for v in (167, 171, 160)], comments=[])
    assert d["status"] == fa.REVIEW_REQUIRED
    assert "werkblokken uit op" not in d["text"]


# ══ Matthijs — direct recovery-zone answer when compliant ══════════════════════
def test_matthijs_direct_answer(monkeypatch):
    d = _decision(monkeypatch, zones={"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                  builder=[_hr(1)], laps=[{"amount": 1, "hr_avg": 125} for _ in range(5)],
                  comments=["welke zone is goed voor zo'n herstelloop? Z1?"], hr_avg=125)
    assert d["status"] == fa.AUTO_SAFE
    assert "op Z1 sturen" in d["text"]


# ══ Metric authority tests A–D (end of build) ══════════════════════════════════
def test_A_hr_plan_pace_faster_no_review_from_pace(monkeypatch):
    # HR compliant + pace in snellere zone → geen pace-divergentie, geen review louter door pace
    laps = [{"amount": 1, "hr_avg": 135, "pace_display": "4:40"} for _ in range(8)]
    zones = {"zone_type": "hartslag", "zones_text": "z", "zones": HR,
             "secondary_zone_type": "tempo", "secondary_zones": PACE}
    d = _decision(monkeypatch, zones=zones, builder=[_hr(2)], laps=laps, comments=[], hr_avg=135)
    assert d["status"] == fa.AUTO_SAFE and "hr_compliant" in [a["id"] for a in d["atoms"]]


def test_B_pace_plan_hr_outside_no_hr_failure(monkeypatch):
    # pace-plan, pace compliant, HR buiten een generieke zone maar geen HR-cap → pace-compliance staat
    laps = [{"amount": 1, "hr_avg": 200, "pace_display": "4:35"} for _ in range(6)]
    zones = {"zone_type": "tempo", "zones_text": "z", "zones": PACE}
    d = _decision(monkeypatch, zones=zones, builder=[_pace(4)], laps=laps, comments=[], pace="4:35")
    assert d["authority"]["primary"] == MA.PACE
    assert "pace_compliant" in [a["id"] for a in d["atoms"]] and d["status"] == fa.AUTO_SAFE


def test_D_unknown_authority_review(monkeypatch):
    d = _decision(monkeypatch, zones={"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                  builder=[], laps=[{"amount": 1, "hr_avg": 140} for _ in range(4)], comments=[], hsw=False)
    assert d["authority"]["primary"] == MA.UNKNOWN and d["status"] == fa.REVIEW_REQUIRED


# ══ E/F. AUTO_SAFE contains only registered atoms; unregistered prose rejected ══
def test_auto_safe_is_atoms_only(monkeypatch):
    d = _decision(monkeypatch, zones={"zone_type": "hartslag", "zones_text": "z", "zones": REC},
                  builder=[_rest() for _ in range(4)],
                  laps=[{"amount": 0.4, "hr_avg": v} for v in (148, 151, 153, 155)],
                  comments=["elk rustblok gelukt om weer in Z1 te komen"])
    assert fa._final_is_atoms_only(d["text"], d["atoms"]) is True
    # een niet-geregistreerde feitelijke zin toevoegen → niet meer atoms-only
    assert fa._final_is_atoms_only(d["text"] + " Je tempo was te hoog.", d["atoms"]) is False


# ══ K/L. running + internal vocabulary safe by construction ═════════════════════
def test_atoms_running_and_internal_safe():
    import feedback_facts as ff
    texts = [ff.divergence_sentence({"above": "tempo", "easy": "hartslag"}),
             "Op hartslag bleef je binnen het rustige bereik dat voor deze training bedoeld was.",
             "Je herstelblokken bleven op hartslag in Z2, niet in Z1 zoals je dacht.",
             "Hou ook even in de gaten hoe je scheen hierop reageert.",
             "Jammer dat je er niet bij kunt zijn.",
             "Voor dit soort hersteltrainingen zou ik op Z1 sturen."]
    for t in texts:
        assert not re.search(r"\brit\b|\britje\b|fietsrit", t.lower())
        for bad in ("blokmatch", "matched", "possible", "provenance", "pipeline", "readiness"):
            assert bad not in t.lower()


# ══ N. end-to-end via genereer: AUTO_SAFE text = persisted text + status ════════
def _run_genereer(monkeypatch, w, zones, builder, llm_out):
    feedback_core._cache.clear()
    feedback_core._cache[w["workout_key"]] = w
    monkeypatch.setattr(feedback_core, "_brein_context", lambda w: "")
    monkeypatch.setattr(feedback_core, "_timeline_rows", lambda w: [])
    monkeypatch.setattr(feedback_core, "_refresh_thread", lambda w: None)
    monkeypatch.setattr(feedback_core, "_session_context", lambda w: "")
    monkeypatch.setattr(feedback_core, "_ensure_details", lambda wid: None)
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder)
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: zones)
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)
    monkeypatch.setattr(ai_feedback, "_generate_text", lambda **kw: llm_out)
    txt = feedback_core.genereer(w["workout_key"])
    return txt, feedback_core.last_generation_status(w["workout_key"])


def test_end_to_end_sophie_auto_safe(monkeypatch):
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(6)] \
        + [{"amount": 1, "hr_avg": 140, "pace_display": "4:50"} for _ in range(4)]
    w = {"athlete_name": "Sophie X", "athlete_first_name": "Sophie", "workout_name": "Herstelloop",
         "post_notes": "", "workout_key": "S", "athlete_key": "AK", "workout_type": "run",
         "workout_date": "2026-09-05",
         "details": {"has_structured_workout": True, "description": "herstel na cruise intervals",
                     "Activities": [{"hr_avg": 138, "pace_display": "4:50", "Laps": laps}]},
         "athlete_comments": ["ik dacht Z1-Z2, kan er morgen niet bij zijn"], "thread": []}
    zones = {"zone_type": "hartslag", "zones_text": "z", "zones": HR,
             "secondary_zone_type": "tempo", "secondary_zones": PACE}
    txt, status = _run_genereer(monkeypatch, w, zones, [_hr(2)], "LLM zou hier iets verzinnen")
    assert status == "AUTO_SAFE"
    assert "rustige bereik" in txt and "Jammer dat je er niet bij kunt zijn." in txt
    assert txt != "LLM zou hier iets verzinnen"              # LLM-prose niet gebruikt in AUTO_SAFE


def test_end_to_end_review_required_uses_llm(monkeypatch):
    # onbekende authority + geen deterministische content → REVIEW_REQUIRED (LLM-draft)
    w = {"athlete_name": "Rob X", "athlete_first_name": "Rob", "workout_name": "Duurloop",
         "post_notes": "", "workout_key": "R", "athlete_key": "AK", "workout_type": "run",
         "workout_date": "2026-09-05",
         "details": {"has_structured_workout": False, "description": "rustige duurloop",
                     "Activities": [{"hr_avg": 145, "pace_display": "5:00",
                                     "Laps": [{"amount": 1, "hr_avg": 145} for _ in range(5)]}]},
         "athlete_comments": [], "thread": []}
    txt, status = _run_genereer(monkeypatch, w, {"zone_type": "hartslag", "zones_text": "z", "zones": HR},
                                [], "Sterke duurloop Rob, lekker constant.")
    assert status == "REVIEW_REQUIRED" and "Sterke duurloop" in txt


def test_review_required_not_auto_sendable_default():
    assert feedback_core.last_generation_status("nonexistent") == "REVIEW_REQUIRED"
