"""Masterbrein partial-context resilience (foutklasse A, 17 aug 2026).

Borgt dat een onverwachte exception in ÉÉN build-stage binnen `state.assemble`
(en dus `adapter.build_state`/`build_context`) NIET de hele centrale atleetcontext
wist: onafhankelijke evidence/intakefacts blijven behouden (partial truth), alleen
de getroffen slice degradeert, de fout wordt gelogd + als diagnostic vastgelegd,
er komt geen vals STABLE/GOOD, en zowel Schema als Dossier tonen de partial context.

    python3 -m pytest tests/test_brain_resilience.py -q
"""
import io
import os
import sys
from contextlib import redirect_stderr
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import brain.state as S
import brain.derive as D
import brain.snapshot as SNAP
import brain.sources as SRC
import brain.adapter as A
from brain.models import SourceHealth

TODAY = date(2026, 8, 17)


def _health(tl=True):
    return [SourceHealth(source="fs.training_log", available=tl, error="" if tl else "geen sessie"),
            SourceHealth(source="fs.zones", available=True), SourceHealth(source="intake", available=True)]


def _raw(klacht=""):
    ik = {"athlete_name": "Testatleet", "naam": "Test", "doel": "10 EM < 70 min",
          "huidige_klachten": klacht, "huidig_volume": "30 km/week", "loopervaring": "3 jaar",
          "referentie_prestatie": "5k 24:30", "blessurehistorie": "kuit 2023",
          "trainingsdagen": "di/do/za", "slaap": "7-8u", "coach_notitie": "rustig", "updated_at": TODAY.isoformat()}
    return {"intake": ik, "intake_ts": TODAY.isoformat(), "notes": [], "profiel": "", "on_hold": None,
            "garmin": "", "belasting": None,
            "training_log": [{"date": TODAY.isoformat(), "actual_km": 10, "completed": True,
                              "workout_key": "w1", "is_race": False}], "labels": [], "zones": {}}


def _boom(*a, **k):
    raise RuntimeError("stage boom")


def _keys(st):
    return {e.key for e in st.evidence}


# ── 1+2+3+4+9: one sub-builder exception → partial state ─────────────────────
class TestStageIsolation:
    def test_1_partial_state_not_total_loss(self, monkeypatch):
        monkeypatch.setattr(D, "all", _boom)
        st = S.assemble("K", "T", _raw(), _health(True), today=TODAY)
        assert st is not None and st.evidence                     # partial, niet leeg

    def test_2_independent_intake_facts_remain(self, monkeypatch):
        monkeypatch.setattr(D, "all", _boom)
        k = _keys(S.assemble("K", "T", _raw(), _health(True), today=TODAY))
        for key in ("goal.doel", "health.injury_history", "profile.experience",
                    "training_response.available_days", "recovery.slaap"):
            assert key in k                                       # onafhankelijke intakefacts blijven

    def test_3_diagnostic_visible(self, monkeypatch):
        monkeypatch.setattr(D, "all", _boom)
        st = S.assemble("K", "T", _raw(), _health(True), today=TODAY)
        be = getattr(st, "build_errors", [])
        assert any(e["stage"] == "derive" for e in be)           # getroffen stage zichtbaar

    def test_4_other_domains_intact(self, monkeypatch):
        # klacht-stage intact terwijl derive faalt → gezondheid/complaint blijft
        monkeypatch.setattr(D, "all", _boom)
        st = S.assemble("K", "T", _raw("pijn in de knie"), _health(True), today=TODAY)
        assert any(e.key.startswith("complaint.") and not e.key.startswith("complaint.mention.")
                   for e in st.evidence)

    def test_9_no_false_stable_when_core_stage_fails(self, monkeypatch):
        monkeypatch.setattr(D, "all", _boom)                     # derive = kern voor 'load stabiel'
        st = S.assemble("K", "T", _raw(), _health(True), today=TODAY)
        assert st.overall == "INSUFFICIENT_DATA"                 # nooit vals STABLE/GOOD

    def test_intake_stage_isolated_from_base(self, monkeypatch):
        import brain.intake_evidence as IE
        monkeypatch.setattr(IE, "intake_evidence", _boom)
        k = _keys(S.assemble("K", "T", _raw(), _health(True), today=TODAY))
        assert "goal.doel" in k and "recovery.slaap" in k        # base overleeft
        assert "profile.experience" not in k                     # alleen intake-only weg


# ── 5: echte source-gap ONgewijzigd ──────────────────────────────────────────
class TestSourceGapUnchanged:
    def test_5_source_gap_same_as_before(self):
        raw = _raw(); raw["training_log"] = []                    # echte gap → geen log-data
        st = S.assemble("K", "T", raw, _health(tl=False), today=TODAY)  # fs.training_log gap
        assert "fs.training_log" in st.source_gaps
        assert getattr(st, "build_errors", []) == []             # gap ≠ build-fout
        assert "goal.doel" in _keys(st)                          # intakefacts blijven
        assert st.overall == "INSUFFICIENT_DATA"                 # geen echte load → onzeker


# ── 6: logging/diagnostic aangeroepen ────────────────────────────────────────
class TestLogging:
    def test_6_traceback_logged(self, monkeypatch):
        monkeypatch.setattr(D, "all", _boom)
        buf = io.StringIO()
        with redirect_stderr(buf):
            S.assemble("K", "T", _raw(), _health(True), today=TODAY)
        out = buf.getvalue()
        assert "stage 'derive' faalde" in out and "Traceback" in out


# ── 7+8: Schema én Dossier tonen partial context ─────────────────────────────
@pytest.fixture
def _v2_env(monkeypatch):
    import athlete_context as AC
    monkeypatch.setattr(AC, "schema_brain_mode", lambda: "v2")
    monkeypatch.setattr(SNAP, "load_snapshot", lambda k: None)
    monkeypatch.setattr(SNAP, "save_snapshot", lambda s: None)
    monkeypatch.setattr(SRC, "gather", lambda k, today=None: (_raw("pijn in de knie"), _health(True)))
    monkeypatch.setattr(D, "all", _boom)                         # forceer één gefaalde stage


class TestConsumersPartial:
    def test_7_schema_bekende_context_partial(self, _v2_env):
        import schema_core
        r = schema_core.bekende_context("K")
        gevuld = [s for s in r["secties"] if not s.get("onbekend")]
        assert gevuld                                            # partial context zichtbaar
        assert r.get("build_errors")                             # diagnostic meegegeven
        # geen totale 'bronfout'-sectie
        assert not any(s.get("source_error") for s in r["secties"])
        # (Dossier-cockpit partial-truth wordt getest in tests/test_dossier_cockpit.py,
        #  zodat deze gedeelde-brain-suite geen Dossier-afhankelijkheid heeft.)


# ── normaalpad: geen fout → geen diagnostic ──────────────────────────────────
def test_happy_path_no_errors():
    st = S.assemble("K", "T", _raw(), _health(True), today=TODAY)
    assert getattr(st, "build_errors", []) == []
    assert st.overall in ("STABLE", "GOOD")
    ctx = A.to_legacy_context(st, _raw(), today=TODAY)
    assert ctx.get("_build_errors") == []
