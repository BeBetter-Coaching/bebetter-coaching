"""Deterministic Coaching Facts + Guarded Composer v7.

Architectuur: deterministische coach-feiten → LLM schrijft eromheen → fail-closed validator vóór
acceptatie. Plus de harde productregel: een hardloopactiviteit mag NOOIT als 'rit'/'ritje'/
'fietsrit' worden omschreven (foutieve sporttaal), afgedwongen door de eindvalidator.

AI-output is niet-deterministisch en wordt NIET getest; we borgen de fact-pack-constructie, de
validator en de fail-closed gate. Geen nieuwe fetch/store.

    python3 -m pytest tests/test_feedback_deterministic_facts_v7.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client
import feedback_core
import feedback_facts as ff

SYS = ai_feedback.SYSTEM_PROMPT

# contigue HR-zones (geen gaten) → schone blok-classificatie
HR_ZONES = [{"num": 1, "naam": "Herstel", "low": 110, "high": 130},
            {"num": 2, "naam": "Easy", "low": 130, "high": 145},
            {"num": 3, "naam": "Tempo", "low": 145, "high": 169},
            {"num": 4, "naam": "Interval", "low": 169, "high": 179},
            {"num": 5, "naam": "Snel", "low": 179, "high": 200}]
REC_ZONES = [{"num": 1, "naam": "Herstel", "low": 128, "high": 142},
             {"num": 2, "naam": "Easy", "low": 142, "high": 160},
             {"num": 3, "naam": "Tempo", "low": 160, "high": 175}]


# ══ sport-language contract + prompt ════════════════════════════════════════════
def test_sport_profile():
    assert ff.sport_profile("run")["is_running"] is True
    assert ff.sport_profile("bike")["is_running"] is False
    assert ff.sport_profile("strength")["canonical_type"] == "strength"


def test_system_prompt_running_language_rule():
    assert "SPORTTAAL HARDLOPEN" in SYS
    assert '"rit"' in SYS and '"fietsrit"' in SYS
    assert "de hele training" in SYS


# ══ V7-G9 — running language guard: 'de hele rit' rejected ═════════════════════
def test_v7g9_running_de_hele_rit_rejected():
    res = ff.validate_draft("Sterke training. Over de hele rit bleef je hartslag mooi rustig.",
                            is_running=True)
    assert res["ok"] is False and res["kind"] == "sport"
    assert ff.block_message(res["kind"]) == "Concept geblokkeerd — onjuiste sporttaal."


def test_rit_variants_rejected_for_run():
    for bad in ["de hele rit", "tijdens de rit", "een lekker ritje", "je rit was sterk"]:
        assert ff.validate_draft(f"Goed gedaan. {bad}.", is_running=True)["ok"] is False


# ══ V7-G10 — running language positive cases accepted ══════════════════════════
def test_v7g10_running_positive_phrases_accepted():
    for good in ["Tijdens de hele training bleef je hartslag rustig.",
                 "Mooie sessie vandaag.", "Tijdens je loop zat je lekker in je tempo.",
                 "De duurloop zag er sterk uit."]:
        assert ff.validate_draft(good, is_running=True)["ok"] is True


def test_ritme_not_falsely_blocked():
    # 'ritme' bevat 'rit' als substring maar is geen wielrenwoord → niet blokkeren
    assert ff.validate_draft("Je hield een mooi constant ritme aan.", is_running=True)["ok"] is True


# ══ V7-G11 — do not over-block legitimate cycling cross-training ═══════════════
def test_v7g11_legit_bike_context_not_blocked():
    # atleet noemt zelf een aparte fietsrit → 'fietsrit' in coachtekst mag als kruistraining
    res = ff.validate_draft("Mooie training. Fijn dat je fietsritje er als aanvulling was.",
                            is_running=True, athlete_message="deed er ook een fietsritje bij")
    assert res["ok"] is True


def test_fietsrit_for_run_without_context_rejected():
    # geen fiets-context in atleetbericht → 'fietsrit' beschrijft de run = fout
    res = ff.validate_draft("Sterke fietsrit vandaag.", is_running=True, athlete_message="lekker gelopen")
    assert res["ok"] is False and res["kind"] == "sport"


def test_non_run_rit_allowed():
    assert ff.validate_draft("Mooie rit op de fiets vandaag.", is_running=False)["ok"] is True


# ══ V7-G1/G2 — mandatory fact verbatim + alteration ════════════════════════════
FACT = "Op hartslag bleef het rustig, maar qua tempo zat er ook een stuk boven je rustige bereik in."


def test_v7g1_mandatory_fact_present_accepted():
    draft = f"Lekkere training. {FACT} Hou het zo rustig."
    res = ff.validate_draft(draft, is_running=True, mandatory=[{"id": "divergence", "sentence": FACT}])
    assert res["ok"] is True


def test_v7g2_mandatory_fact_altered_rejected():
    # model rondt/wijzigt de zin → ontbreekt verbatim → fail-closed
    altered = "Lekkere training. Op hartslag was het rustig en je tempo zat prima. Top."
    res = ff.validate_draft(altered, is_running=True, mandatory=[{"id": "divergence", "sentence": FACT}])
    assert res["ok"] is False and res["kind"] == "content"
    assert "missing_fact" in res["detail"]


def test_mandatory_fact_whitespace_tolerant():
    draft = f"Goed.\n{FACT}\n\nMooi."
    assert ff.validate_draft(draft, is_running=True, mandatory=[{"id": "d", "sentence": FACT}])["ok"] is True


# ══ V7-G3 — internal language rejected ═════════════════════════════════════════
def test_v7g3_internal_language_rejected():
    for bad in ["De blokmatch is niet betrouwbaar.", "De koppeling is MATCHED.",
                "Het signaal komt uit brein_context.", "De context laadt nog."]:
        assert ff.validate_draft(bad, is_running=True)["ok"] is False


# ══ zone percentage rejected, losse 100% toegestaan ════════════════════════════
def test_zone_percentage_rejected():
    assert ff.validate_draft("56% in Z3 gezeten.", is_running=True)["ok"] is False
    assert ff.validate_draft("Op hartslag zat 40% in zone 2.", is_running=True)["ok"] is False


def test_plain_percentage_allowed():
    assert ff.validate_draft("Je bent weer 100% hersteld, mooi.", is_running=True)["ok"] is True


# ══ stale relative-day rejected ════════════════════════════════════════════════
def test_stale_relative_day_rejected():
    assert ff.validate_draft("Jammer dat je er morgen niet bij bent.", is_running=True)["ok"] is False
    assert ff.validate_draft("Prima herstel na gisteren.", is_running=True)["ok"] is False


# ══ V7-G4 — Jordi deterministic block sequence ═════════════════════════════════
def test_v7g4_block_sequence_fact():
    blocks = [{"index": i, "type": "ACTIVE", "observed_hr": v}
              for i, v in enumerate((167, 171, 160, 169, 172), 1)]
    s = ff.block_sequence_sentence(blocks, HR_ZONES, is_pace=False, zone_type="hartslag")
    assert s == "Op hartslag kwamen je werkblokken uit op Z3, Z4, Z3, Z4 en Z4."


def test_block_sequence_none_when_out_of_zone():
    # één blok in een zone-gat → geen feit (model bespreekt geen per-blok verloop)
    z = [{"num": 3, "naam": "T", "low": 145, "high": 160}, {"num": 4, "naam": "I", "low": 169, "high": 179}]
    blocks = [{"index": 1, "type": "ACTIVE", "observed_hr": 165}]  # 165 valt in het gat 160-169
    assert ff.block_sequence_sentence(blocks + blocks, z, is_pace=False, zone_type="hartslag") is None


# ══ V7-G5 — Douwe false Z1 recovery claim corrected ════════════════════════════
def test_v7g5_recovery_contradiction():
    blocks = [{"index": i, "type": "REST", "observed_hr": v} for i, v in enumerate((148, 151, 153, 155), 1)]
    s = ff.recovery_claim_contradiction(blocks, REC_ZONES, "elk rustblok gelukt om weer in Z1 te komen")
    assert s == "Je herstelblokken bleven op hartslag in Z2, niet in Z1 zoals je dacht."


def test_recovery_no_contradiction_when_reached_z1():
    blocks = [{"index": 1, "type": "REST", "observed_hr": 135}]  # 135 = Z1 (128-142)
    assert ff.recovery_claim_contradiction(blocks, REC_ZONES, "rustblok weer in Z1") is None


def test_recovery_no_claim_no_fact():
    blocks = [{"index": 1, "type": "REST", "observed_hr": 150}]
    assert ff.recovery_claim_contradiction(blocks, REC_ZONES, "lekker gelopen") is None


# ══ V7-G7 — complaint obligation mandatory line ════════════════════════════════
def test_v7g7_complaint_sentence():
    assert ff.complaint_sentence(["scheenbeen"]) == "Hou ook even in de gaten hoe je scheen hierop reageert."
    assert ff.complaint_sentence([]) is None


# ══ V7-G6 — Sophie divergence mandatory fact ═══════════════════════════════════
def test_v7g6_divergence_sentence():
    assert ff.divergence_sentence({"above": "tempo", "easy": "hartslag"}) == FACT


# ══ V7-G8 — clean case: empty fact pack, no boilerplate ════════════════════════
def test_v7g8_clean_pack_empty():
    pack = ff.build_fact_pack(workout_type="run")
    assert pack["mandatory"] == []
    assert ff.fact_prompt_section(pack) == ""


def test_fact_prompt_section_lists_sentences():
    pack = ff.build_fact_pack(workout_type="run", divergence={"above": "tempo", "easy": "hartslag"})
    sec = ff.fact_prompt_section(pack)
    assert "VERPLICHTE ZINNEN" in sec and FACT in sec and "LETTERLIJK" in sec


# ══ fail-closed gate via feedback_core._validate_or_block ══════════════════════
def test_validate_or_block_raises_on_rit():
    w = {"workout_type": "run", "_fact_pack": {"sport": {"is_running": True}, "mandatory": []},
         "post_notes": "", "athlete_comments": []}
    with pytest.raises(ValueError) as e:
        feedback_core._validate_or_block(w, "Over de hele rit ging het lekker.", feedback_core.INITIAL_ANALYSIS)
    assert "onjuiste sporttaal" in str(e.value)


def test_validate_or_block_raises_on_missing_fact():
    w = {"workout_type": "run", "post_notes": "", "athlete_comments": [],
         "_fact_pack": {"sport": {"is_running": True}, "mandatory": [{"id": "d", "sentence": FACT}]}}
    with pytest.raises(ValueError) as e:
        feedback_core._validate_or_block(w, "Mooie training, lekker rustig gebleven.",
                                         feedback_core.INITIAL_ANALYSIS)
    assert "inhoudelijke controle niet gehaald" in str(e.value)


def test_validate_or_block_passes_clean():
    w = {"workout_type": "run", "post_notes": "", "athlete_comments": [],
         "_fact_pack": {"sport": {"is_running": True}, "mandatory": []}}
    feedback_core._validate_or_block(w, "Sterke training vandaag, mooi constant tempo.",
                                     feedback_core.INITIAL_ANALYSIS)   # geen exception


def test_validate_or_block_reply_skips_mandatory():
    # vervolgreactie hoeft de verplichte feiten niet te herhalen (alleen sport/vocab-guards)
    w = {"workout_type": "run", "post_notes": "", "athlete_comments": [],
         "_fact_pack": {"sport": {"is_running": True}, "mandatory": [{"id": "d", "sentence": FACT}]}}
    feedback_core._validate_or_block(w, "Ja precies, goed dat je het zo aanvoelt.",
                                     feedback_core.FOLLOW_UP_REPLY)    # geen exception


# ══ integratie: divergence-fact verschijnt in de context ═══════════════════════
@pytest.fixture
def fs_both(monkeypatch):
    PACE = [{"num": 1, "naam": "z", "low": 352, "high": 720}, {"num": 2, "naam": "z", "low": 314, "high": 352},
            {"num": 3, "naam": "z", "low": 285, "high": 314}, {"num": 4, "naam": "z", "low": 260, "high": 285},
            {"num": 5, "naam": "z", "low": 200, "high": 260}]
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {
        "zone_type": "hartslag", "zones_text": "Z1..", "zones": HR_ZONES,
        "secondary_zone_type": "tempo", "secondary_zones": PACE})
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: [])
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None)


def test_integration_divergence_fact_in_context(fs_both):
    laps = [{"amount": 1, "hr_avg": 138, "pace_display": "5:30"} for _ in range(6)] \
        + [{"amount": 1, "hr_avg": 140, "pace_display": "4:50"} for _ in range(4)]
    wd = {"athlete_name": "S", "athlete_first_name": "S", "workout_name": "Herstelloop",
          "post_notes": "", "workout_key": "WK", "athlete_key": "AK", "workout_type": "run",
          "workout_date": "2026-09-04",
          "details": {"has_structured_workout": False, "description": "herstel na cruise intervals",
                      "Activities": [{"hr_avg": 138, "pace_display": "5:00", "Laps": laps}]},
          "athlete_comments": []}
    ctx = ai_feedback._build_workout_context(wd)[0]
    assert "VERPLICHTE ZINNEN" in ctx and FACT in ctx
    assert wd["_fact_pack"]["mandatory"][0]["id"] == "divergence"
