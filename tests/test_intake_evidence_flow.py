"""Intake → Masterbrein → Schema: canonieke kennis-flow (Linde-case, 17 aug 2026).

Borgt dat RIJKE intake één keer als typed evidence in AthleteState landt, dat
`for_schema` daar de planning-subset van levert, dat de Schema-workbench + het
'Bekende atleetcontext'-panel die context ontvangen, dat alleen bronondersteunde
informatie verschijnt (unknown blijft unknown, geen AI-inventie) en dat de nieuwe
intake-evidence NIET naar Feedback/Home lekt en de source-health-gate niet omzeilt.

    python3 -m pytest tests/test_intake_evidence_flow.py -q
"""
import os
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

from brain import state as S, projections as P, adapter as A
from brain import intake_evidence as IE
from brain.models import (ATHLETE_REPORTED, AI_INTERPRETATION, HISTORICAL, INSUFFICIENT_DATA,
                          SourceHealth)
import athlete_context as AC

KEY = "LINDE-UUID-123"
TODAY = date(2026, 8, 17)

RICH = {
    "athlete_name": "Linde Voorbeeld", "naam": "Linde", "doel": "10 EM onder 70 min",
    "wedstrijddatum_tekst": "20 sep halve marathon", "huidig_volume": "30 km/week",
    "trainingsdagen": "di/do/za", "tijd_per_training": "60 min",
    "loopervaring": "3 jaar consistent", "referentie_prestatie": "5k in 24:30",
    "langste_afstand": "16 km", "eerdere_schemas": "ja, vorig jaar",
    "wat_werkte": "rustige opbouw", "wat_niet_werkte": "te veel intervallen",
    "kwaliteitservaring": "beperkt", "blessurehistorie": "kuitblessure 2023",
    "huidige_klachten": "", "leuk": "lange duurlopen", "niet_leuk": "baantraining",
    "slaap": "7-8 uur", "werkdruk": "gemiddeld", "herstelcapaciteit": "redelijk",
    "race_prioriteit": "A-race", "tussenraces": "5k testrace",
    "coach_notitie": "rustig opbouwen, blessuregevoelig",
    "updated_at": TODAY.isoformat(),
}


def _raw(ik, ik_ts=None):
    return {"intake": ik, "intake_ts": ik_ts or ik.get("updated_at", ""),
            "notes": [], "profiel": "", "on_hold": None, "garmin": "",
            "belasting": None, "training_log": [], "labels": [], "zones": {}}


def _health_fs_down():
    h = [SourceHealth(source=s, available=False, error="geen FinalSurge-sessie")
         for s in ("fs.training_log", "fs.labels", "fs.zones")]
    h.append(SourceHealth(source="intake", available=True))
    return h


def _state(ik, ik_ts=None, training_log=None):
    raw = _raw(ik, ik_ts)
    if training_log is not None:
        raw["training_log"] = training_log
    return S.assemble(KEY, ik.get("athlete_name", KEY), raw, _health_fs_down(), today=TODAY), raw


# ── 1+2: rijke intake → canoniek getypeerd als evidence ──────────────────────
class TestIntakeTyping:
    def test_alle_kennis_wordt_evidence_op_user_key(self):
        st, _ = _state(RICH)
        by_key = {e.key: e for e in st.evidence}
        for k in ("profile.experience", "profile.preference_likes", "profile.preference_dislikes",
                  "training_response.available_days", "training_response.time_per_session",
                  "training_response.schema_history", "training_response.responds_well",
                  "training_response.responds_poorly", "training_response.quality_experience",
                  "load.volume_intake", "load.reference_performance", "load.longest_recent",
                  "health.injury_history", "goal.race_priority", "goal.intermediate_races",
                  "coach.intake_note"):
            assert k in by_key, f"ontbreekt: {k}"
            assert by_key[k].athlete_key == KEY

    def test_truth_types_zijn_reported_nooit_ai(self):
        st, _ = _state(RICH)
        for e in st.evidence:
            assert e.truth_type != AI_INTERPRETATION
        assert {e.key: e.truth_type for e in st.evidence}["profile.experience"] == ATHLETE_REPORTED
        assert {e.key: e.truth_type for e in st.evidence}["coach.intake_note"] == "COACH_REPORTED"

    def test_blessurehistorie_is_historisch_geen_actuele_klacht(self):
        st, _ = _state(RICH)
        inj = next(e for e in st.evidence if e.key == "health.injury_history")
        assert inj.status == HISTORICAL
        # geen actuele klacht verzonnen uit een historie-melding
        assert not any(e.key.startswith("complaint.") and not e.key.startswith("complaint.mention.")
                       and e.status in ("ACTIVE", "RECENT", "RECURRING") for e in st.evidence)

    def test_waarden_zijn_verbatim_geen_inventie(self):
        st, _ = _state(RICH)
        bk = {e.key: e.value for e in st.evidence}
        assert bk["load.volume_intake"] == "30 km/week"
        assert bk["profile.experience"] == "3 jaar consistent"
        assert bk["load.reference_performance"] == "5k in 24:30"


# ── 4: for_schema planning-subset ────────────────────────────────────────────
class TestSchemaProjection:
    def test_for_schema_bevat_planning_kennis(self):
        st, _ = _state(RICH)
        keys = {e["key"] for e in P.for_schema(st)["evidence"]}
        for k in ("profile.experience", "load.volume_intake", "load.reference_performance",
                  "health.injury_history", "training_response.responds_well",
                  "goal.race_priority", "coach.intake_note"):
            assert k in keys

    def test_for_schema_laat_ruis_weg(self):
        st, _ = _state(RICH)
        keys = {e["key"] for e in P.for_schema(st)["evidence"]}
        assert not any(k.startswith("complaint.mention.") for k in keys)
        assert "coach.observation" not in keys


# ── 5+6: workbench-context + panel niet leeg ─────────────────────────────────
class TestSchemaContextAndPanel:
    def test_to_legacy_context_gevuld(self):
        st, raw = _state(RICH)
        ctx = A.to_legacy_context(st, raw, today=TODAY)
        assert ctx["profile"].get("loopervaring") == "3 jaar consistent"
        assert ctx["training"].get("huidig_volume_intake") == "30 km/week"
        assert ctx["training"].get("referentie_prestatie") == "5k in 24:30"
        assert ctx["health"].get("blessurehistorie") == "kuitblessure 2023"
        assert ctx["goals"].get("race_prioriteit") == "A-race"
        assert ctx["coach"].get("coach_notitie_intake") == "rustig opbouwen, blessuregevoelig"

    def test_ui_sections_niet_leeg(self):
        st, raw = _state(RICH)
        ctx = A.to_legacy_context(st, raw, today=TODAY)
        secties = AC.ui_sections(ctx)
        gevuld = [s for s in secties if not s["onbekend"]]
        assert len(gevuld) >= 4                                # profile/training/health/goals
        assert secties                                         # nooit lege lijst → nooit 'Nog niets bekend'

    def test_ai_prompt_bevat_kennis(self):
        st, raw = _state(RICH)
        ctx = A.to_legacy_context(st, raw, today=TODAY)
        tekst = AC.to_prompt_text(AC.schema_projection(ctx))
        assert "3 jaar consistent" in tekst
        assert "kuitblessure 2023" in tekst


# ── 7+8: alleen bronondersteund; unknown blijft unknown ──────────────────────
class TestUnknownStaysUnknown:
    def test_lege_velden_geven_geen_evidence(self):
        mager = {"athlete_name": "Mager", "naam": "Mager", "doel": "fitter worden",
                 "updated_at": TODAY.isoformat()}
        st, _ = _state(mager)
        keys = {e.key for e in st.evidence}
        assert "profile.experience" not in keys
        assert "load.volume_intake" not in keys
        assert "health.injury_history" not in keys
        # wat wél gemeld is, is er
        assert "goal.doel" in keys

    def test_geen_intake_geen_intake_evidence(self):
        assert IE.intake_evidence({"intake": {}, "intake_ts": ""}, KEY, TODAY) == []


# ── 9: intake overschrijft geen sterkere actuele bron ────────────────────────
class TestSourceAuthority:
    def test_intake_volume_omzeilt_source_health_gate_niet(self):
        # FS-log down + rijke intake (incl. huidig_volume) → NOOIT GOOD/STABLE:
        # zelf-gemelde intake-belasting telt niet als echte belastbaarheid.
        st, _ = _state(RICH)
        assert st.overall == INSUFFICIENT_DATA

    def test_oude_intake_volume_is_stale(self):
        oud = dict(RICH, updated_at=(TODAY - timedelta(days=400)).isoformat())
        st, _ = _state(oud, ik_ts=(TODAY - timedelta(days=400)).isoformat())
        vol = next(e for e in st.evidence if e.key == "load.volume_intake")
        assert vol.status == "STALE"


# ── 12: geen lek naar Feedback/Home ──────────────────────────────────────────
class TestNoLeak:
    def test_nieuwe_intake_evidence_niet_in_feedback(self):
        st, _ = _state(RICH)
        ffk = {e["key"] for e in P.for_feedback(st)["evidence"]}
        for k in ("profile.experience", "load.volume_intake", "load.reference_performance",
                  "health.injury_history", "training_response.responds_well",
                  "goal.race_priority", "coach.intake_note"):
            assert k not in ffk

    def test_nieuwe_intake_evidence_niet_in_home(self):
        st, _ = _state(RICH)
        hk = {e["key"] for e in P.for_home(st)["evidence"]}
        for k in ("profile.experience", "load.volume_intake", "health.injury_history",
                  "coach.intake_note"):
            assert k not in hk
