"""Feedback Coachability Reset — athlete-first, data-second (T1..T12).

Deterministische coachability-verbeteringen (geen nieuwe safety-laag): CopyQuality-opschoning,
CoachingIntent, klacht-recency, km-lap-guard, partial-sync-autoriteit, atleet-first sessie-overzicht.

    python3 -m pytest tests/test_feedback_coachability.py -q
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
import feedback_copy as fc

SYS = ai_feedback.SYSTEM_PROMPT
HR = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
      enumerate([(110, 130), (130, 145), (145, 169), (169, 179), (179, 200)], 1)]


# ══ T1 — data-first is verboden in de stijlregels (athlete-first, data-second) ══
def test_t1_prompt_athlete_first_data_budget():
    assert "ATHLETE-FIRST, DATA-SECOND" in SYS
    assert "DATA-BUDGET" in SYS and "MAXIMAAL 1 of 2" in SYS
    assert "GEEN DEFENSIEVE ZINNEN" in SYS


# ══ T2 — vage/technische HR-blocktaal is verboden en wordt opgeschoond ══════════
def test_t2_system_language_stripped():
    txt = ("Mooi gelopen vandaag. De blokkoppeling was niet strak te achterhalen. "
           "Het dominante beeld laat zien dat de lapdata rustig was.")
    out = fc.clean_draft(txt)
    assert "Mooi gelopen vandaag." in out
    assert "blokkoppeling" not in out.lower() and "dominante beeld" not in out.lower()
    assert "lapdata" not in out.lower()


def test_t2_prompt_bans_technical_language():
    assert "GEEN INTERNE/TECHNISCHE TAAL" in SYS and "blokkoppeling" in SYS


# ══ T3 — dubbele klacht-zin → maximaal één per onderwerp ════════════════════════
def test_t3_duplicate_complaint_deduped():
    txt = ("Hou even in de gaten hoe je knie hierop reageert. "
           "Hou ook even in de gaten hoe je knie hierop reageert. Sterke training verder.")
    out = fc.clean_draft(txt)
    assert out.lower().count("knie") == 1
    assert "Sterke training verder." in out


# ══ T4 — stale complaint (alleen historisch actief) → geen klacht-zin ══════════
def _decide(monkeypatch, *, builder, laps, comments, diag=None):
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder)
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {"zone_type": "hartslag", "zones_text": "z", "zones": HR})
    w = {"workout_type": "run", "workout_key": "W", "athlete_key": "AK", "post_notes": "",
         "athlete_comments": comments,
         "details": {"has_structured_workout": True, "description": "rustige duurloop",
                     "Activities": [{"hr_avg": 138, "pace_display": "5:00", "Laps": laps}]}}
    if diag:
        w["_brein_diag"] = diag
    return fa.build_decision(w)


def _hr(z):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 6, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": z}]}


def _lhr(hr, dur):
    return {"hr_avg": hr, "duration": dur, "amount": 1}


def test_t4_stale_complaint_not_included(monkeypatch):
    # knie staat historisch actief (complaint_areas) maar NIET recent (geen complaint_new), atleet
    # noemt hem niet → geen klacht-zin.
    d = _decide(monkeypatch, builder=[_hr(2)], laps=[_lhr(138, 3000)],
                comments=["lekker gelopen, voelde goed"],
                diag={"complaint_areas": ["knie"], "complaint_new": []})
    assert not any(a["id"].startswith("complaint_") for a in d["atoms"])


# ══ T5 — huidige klacht (atleet noemt hem nu) → één natuurlijke klacht-zin ══════
def test_t5_current_complaint_included(monkeypatch):
    d = _decide(monkeypatch, builder=[_hr(2)], laps=[_lhr(138, 3000)],
                comments=["ging goed maar mijn knie voelde wat gevoelig"],
                diag={"complaint_areas": ["knie"], "complaint_new": ["knie"]})
    ids = [a["id"] for a in d["atoms"]]
    assert "complaint_knie" in ids
    assert sum(1 for i in ids if i.startswith("complaint_")) == 1   # geen dubbele


# ══ T6 — 800m blokken via km-laps → geen per-blok zone-conclusie ════════════════
def test_t6_km_laps_not_used_for_subkm_blocks(monkeypatch):
    # geplande 800m werkblokken, uitgevoerd als ~1km auto-laps → mismatch → geen block_sequence
    builder = [{"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 0.8,
                "distUnit": "km", "target": [{"targetType": "hr zone", "zone": 4}]} for _ in range(5)]
    laps = [{"amount": 1.0, "hr_avg": v, "duration": 240} for v in (150, 168, 150, 168, 168)]
    d = _decide(monkeypatch, builder=builder, laps=laps, comments=["lekker gelopen"])
    assert not any(a["id"] == "block_sequence" for a in d["atoms"])
    assert "werkblokken uit op" not in d["text"]


def test_t6_km_lap_mismatch_helper():
    import feedback_facts as ff
    blocks = fs_client._planned_blocks([{"intensity": "ACTIVE", "durationType": "DISTANCE",
                                         "durationDist": 0.8, "distUnit": "km", "target": []}])
    assert ff.km_lap_mismatch(blocks, [{"amount": 1.0}, {"amount": 1.0}]) is True
    # 800m blokken met 800m laps → geen mismatch
    assert ff.km_lap_mismatch(blocks, [{"amount": 0.8}, {"amount": 0.8}]) is False


# ══ T7 — positieve simpele sessie → concise, geen analyse-overkill ══════════════
def test_t7_positive_simple_concise(monkeypatch):
    d = _decide(monkeypatch, builder=[_hr(2)], laps=[_lhr(138, 3000)], comments=["lekker gelopen"])
    assert d["status"] == fa.AUTO_SAFE
    # AUTO_SAFE-tekst is kort (één compliance-atoom), geen lap/zone-opsomming
    assert d["text"].count(".") <= 2 and "lap" not in d["text"].lower()


# ══ T8 — partial sync → nooit 'je liep maar 1 km', geen afstandsoordeel ═════════
def test_t8_partial_sync_no_distance_claim(monkeypatch):
    # activiteit registreert 20 km gepland, detail-laps slechts ~1 km → partial sync → REVIEW
    laps = [{"amount": 0.5, "hr_avg": 140, "duration": 150}, {"amount": 0.5, "hr_avg": 140, "duration": 150}]
    w = {"workout_type": "run", "workout_key": "W", "athlete_key": "AK", "post_notes": "",
         "athlete_comments": ["heerlijke lange duurloop gedaan"],
         "details": {"has_structured_workout": True, "description": "lange duurloop",
                     "Activities": [{"amount": 1.0, "planned_amount": 20, "hr_avg": 140,
                                     "pace_display": "5:00", "Laps": laps}]}}
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: [])
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {"zone_type": "hartslag", "zones_text": "z", "zones": HR})
    d = fa.build_decision(w)
    assert d["status"] == fa.REVIEW_REQUIRED and "partial_sync" in d["reasons"]


def test_t8_partial_sync_helper():
    assert fa.partial_sync({"amount": 1.0, "planned_amount": 20,
                            "Laps": [{"amount": 0.5}, {"amount": 0.5}]}) is True
    assert fa.partial_sync({"amount": 10.0, "planned_amount": 10,
                            "Laps": [{"amount": 1.0} for _ in range(10)]}) is False


# ══ T9 — forward-planning wording: geen dubbelzinnig 'aanhouden' ════════════════
def test_t9_forward_planning_wording():
    assert "onderscheid tussen" in SYS.lower() or "LATEN STAAN" in SYS
    assert "aanhouden" in SYS and "dubbelzinnige woord" in SYS


# ══ T10 — review copy quality: concise, no dup, no system terms, no disclaimer ══
def test_t10_review_copy_cleanup():
    draft = ("Fijn dat het goed voelde. Dat kan ik niet uit de data halen. "
             "De blokkoppeling was niet betrouwbaar. Fijn dat het goed voelde. "
             "Mooie gecontroleerde training.")
    out = fc.clean_draft(draft)
    assert out.lower().count("fijn dat het goed voelde") == 1    # dedupe
    assert "kan ik niet uit de data" not in out.lower()          # disclaimer weg
    assert "blokkoppeling" not in out.lower()                    # systeemtaal weg
    assert "Mooie gecontroleerde training." in out


# ══ T11 — session summary athlete-first: één atleet-container, sessies eronder ══
def test_t11_athlete_first_grouping():
    items = [
        {"athlete_key": "A", "athlete_name": "Rick R", "datum": "2026-09-05", "workout_name": "Duurloop", "feedback_text": "x", "groep_label": "G1"},
        {"athlete_key": "A", "athlete_name": "Rick R", "datum": "2026-09-04", "workout_name": "Interval", "feedback_text": "y", "groep_label": "G2"},
        {"athlete_key": "A", "athlete_name": "Rick R", "datum": "2026-09-02", "workout_name": "Duurloop", "feedback_text": "z", "groep_label": "G1"},
        {"athlete_key": "B", "athlete_name": "Sophie S", "datum": "2026-09-05", "workout_name": "Herstel", "feedback_text": "q", "groep_label": "G1"},
    ]
    groups = feedback_core.athlete_first_groups(items)
    assert len(groups) == 2                                       # geen dubbele top-level atleten
    rick = next(g for g in groups if g["athlete_key"] == "A")
    assert len(rick["sessions"]) == 3
    assert [s["datum"] for s in rick["sessions"]] == ["2026-09-05", "2026-09-04", "2026-09-02"]  # chronologisch


# ══ T12 — summary priority: aandacht/vraag/review vóór simpele auto_safe ════════
def test_t12_summary_priority():
    items = [
        {"athlete_key": "A", "athlete_name": "A", "datum": "2026-09-05", "status": "AUTO_SAFE", "feedback_text": "x", "workout_name": "w"},
        {"athlete_key": "B", "athlete_name": "B", "datum": "2026-09-05", "status": "REVIEW_REQUIRED", "feedback_text": "x", "workout_name": "w"},
        {"athlete_key": "C", "athlete_name": "C", "datum": "2026-09-05", "attention": True, "feedback_text": "x", "workout_name": "w"},
        {"athlete_key": "D", "athlete_name": "D", "datum": "2026-09-05", "question": True, "feedback_text": "x", "workout_name": "w"},
    ]
    order = [g["athlete_key"] for g in feedback_core.athlete_first_groups(items)]
    assert order == ["C", "D", "B", "A"]                          # aandacht → vraag → review → auto_safe


# ══ CoachingIntent classifier ══════════════════════════════════════════════════
def test_coaching_intent():
    assert fc.classify_intent("hoe hard ging ik eigenlijk?")["primary"] == fc.ANSWER
    assert fc.classify_intent("lekker gelopen, voelde soepel")["primary"] == fc.ACKNOWLEDGE
    assert fc.classify_intent("mijn knie doet pijn, moet ik de fysio bellen?")["primary"] == fc.ANSWER
    assert fc.classify_intent("")["data_needed"] is True         # geen bericht → data mag leiden
    assert fc.classify_intent("lekker gelopen")["max_data_points"] == 0
