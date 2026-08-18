"""Fase 1 canonical-state — Schema config-prefill uit ÉÉN keten (Q1).

Endstate: source/intake → typed evidence → AthleteState → for_schema/planning_defaults →
config_prefill. GEEN parallel raw-intake-leespad voor planningvelden in v2.

Borgt:
  • `adapter.planning_defaults` levert de planning-velden via de ECHTE chain (assemble →
    for_schema), niet een losse raw-intake-passthrough;
  • freshness/live-vs-last-known-good/conflict worden CENTRAAL in Masterbrein opgelost:
    live intake → verse waarde; intake-bron uit → last-known-good uit de snapshot;
  • `config_prefill` in v2 gebruikt UITSLUITEND die projectie (geen `_nieuwste_intake`
    voor deze velden); in legacy blijft het raw-pad ongewijzigd;
  • unknown blijft unknown; de coach kan elk veld overschrijven.

    python3 -m pytest tests/test_schema_prefill_canonical.py -q
"""
import os
import sys
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import schema_core
import athlete_context
from brain import adapter as brain_adapter
from brain import snapshot as brain_snapshot
from brain import state as brain_state
from brain.models import SourceHealth

TODAY = date(2026, 8, 18)


# ── 1. planning_defaults draait via de canonieke chain (assemble → for_schema) ─
class TestPlanningDefaultsChain:
    def _live_intake(self, monkeypatch, ik):
        monkeypatch.setattr(intake_store, "load_intakes", lambda: {"AK": dict(ik)})
        monkeypatch.setattr(intake_store, "load_laatste_intakes", lambda: {})

    def test_live_intake_via_for_schema(self, monkeypatch):
        self._live_intake(monkeypatch, {
            "trainingsdagen": "di/do", "doel": "10 km PR", "huidig_volume": "30 km",
            "tijd_per_training": "60 min", "race_prioriteit": "A", "tussenraces": "geen",
            "athlete_name": "Lisa"})
        monkeypatch.setattr(brain_snapshot, "load_snapshot", lambda k: None)
        out = brain_adapter.planning_defaults("AK", TODAY)
        assert out == {"trainingsdagen": "di/do", "doel": "10 km PR", "huidig_volume": "30 km",
                       "tijd_per_training": "60 min", "race_prioriteit": "A", "tussenraces": "geen"}

    def test_intake_bron_uit_valt_terug_op_last_known_good(self, monkeypatch):
        # centrale freshness-resolutie: intake-read faalt → assemble carriet LKG uit snapshot
        prev = brain_state.assemble("AK", "Lisa",
                                    {"intake": {"trainingsdagen": "wo/vr", "doel": "5 km"},
                                     "intake_ts": "2026-08-01"},
                                    [SourceHealth(source="intake", available=True)], TODAY)
        def _boom():
            raise RuntimeError("GitHub down")
        monkeypatch.setattr(intake_store, "load_intakes", _boom)
        monkeypatch.setattr(brain_snapshot, "load_snapshot", lambda k: prev)
        out = brain_adapter.planning_defaults("AK", TODAY)
        assert out.get("trainingsdagen") == "wo/vr" and out.get("doel") == "5 km"

    def test_lege_intake_geen_snapshot_is_leeg(self, monkeypatch):
        self._live_intake(monkeypatch, {})
        monkeypatch.setattr(brain_snapshot, "load_snapshot", lambda k: None)
        assert brain_adapter.planning_defaults("AK", TODAY) == {}

    def test_alleen_bekende_velden(self, monkeypatch):
        self._live_intake(monkeypatch, {"trainingsdagen": "ma/wo", "athlete_name": "Lisa"})
        monkeypatch.setattr(brain_snapshot, "load_snapshot", lambda k: None)
        out = brain_adapter.planning_defaults("AK", TODAY)
        assert out == {"trainingsdagen": "ma/wo"}         # unknown blijft unknown


# ── 2. config_prefill: v2 = uitsluitend Masterbrein; legacy = raw (geen mix) ──
@pytest.fixture
def prefill_env(monkeypatch):
    import fs_client
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda k: {}, raising=False)
    yield monkeypatch


def _set_intake(monkeypatch, base):
    base = {**{"naam": "Lisa", "athlete_name": "Lisa Jansen"}, **base}
    monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: dict(base))


def _v2(monkeypatch, brein):
    monkeypatch.setattr(athlete_context, "schema_brain_mode", lambda: "v2")
    monkeypatch.setattr(brain_adapter, "planning_defaults", lambda k: dict(brein))


class TestConfigPrefillSingleSource:
    def test_v2_gebruikt_uitsluitend_masterbrein(self, prefill_env):
        """Raw intake heeft 'ma/wo', Masterbrein 'di/do' → v2 toont Masterbrein (geen
        tweede planning-truth; raw wordt voor deze velden NIET geraadpleegd)."""
        mp = prefill_env
        _set_intake(mp, {"trainingsdagen": "ma/wo", "doel": "halve marathon"})
        _v2(mp, {"trainingsdagen": "di/do", "doel": "10 km PR"})
        cfg = schema_core.config_prefill("AK")["config"]
        assert cfg["trainingsdagen"] == "di/do"           # Masterbrein = enige bron
        assert cfg["doel"] == "10 km PR"

    def test_v2_leeg_masterbrein_is_leeg_veld(self, prefill_env):
        """Kent Masterbrein een planningveld niet, dan blijft het veld leeg — er wordt
        NIET stiekem teruggevallen op raw intake (geen parallelle truth)."""
        mp = prefill_env
        _set_intake(mp, {"trainingsdagen": "ma/wo"})       # raw kent 't nog
        _v2(mp, {})                                        # Masterbrein niet
        cfg = schema_core.config_prefill("AK")["config"]
        assert cfg["trainingsdagen"] == ""                 # unknown blijft unknown

    def test_legacy_gebruikt_raw_pad(self, prefill_env):
        mp = prefill_env
        _set_intake(mp, {"trainingsdagen": "za/zo"})
        mp.setattr(athlete_context, "schema_brain_mode", lambda: "legacy")
        # planning_defaults mag in legacy NIET geraadpleegd worden:
        def _forbidden(k):
            raise AssertionError("planning_defaults mag niet in legacy draaien")
        mp.setattr(brain_adapter, "planning_defaults", _forbidden)
        cfg = schema_core.config_prefill("AK")["config"]
        assert cfg["trainingsdagen"] == "za/zo"            # bewezen raw-pad ongewijzigd

    def test_alle_planning_velden_uit_masterbrein(self, prefill_env):
        mp = prefill_env
        _set_intake(mp, {})
        _v2(mp, {"trainingsdagen": "di/do", "doel": "5k", "huidig_volume": "25 km",
                 "tijd_per_training": "60 min", "race_prioriteit": "A", "tussenraces": "geen"})
        cfg = schema_core.config_prefill("AK")["config"]
        assert (cfg["trainingsdagen"], cfg["doel"], cfg["huidig_volume"],
                cfg["tijd_per_training"], cfg["race_prioriteit"], cfg["tussenraces"]) == \
               ("di/do", "5k", "25 km", "60 min", "A", "geen")

    def test_coach_override_blijft_behouden(self, prefill_env):
        """Prefill = enkel beginwaarde; een coach-bewerkte config wint bij het assembleren
        van de plan-intake (`_intake_from_config`)."""
        mp = prefill_env
        _set_intake(mp, {"trainingsdagen": "di/do"})
        cfg = {"trainingsdagen": "ma/wo/vr", "athlete_name": "Lisa Jansen",
               "startdatum": "2026-09-01", "weken": "8"}
        intake = schema_core._intake_from_config("AK", cfg)
        assert intake["trainingsdagen"] == "ma/wo/vr"      # coach-keuze wint
