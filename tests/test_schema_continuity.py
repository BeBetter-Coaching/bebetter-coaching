"""Schema athlete-context + route-continuïteit (coherentie-fout Linde, 17 aug 2026).

Borgt dat Schema-roster én Schema-workbench dezelfde canonieke intake-waarheid
via `user_key` lezen, dat een gekoppelde intake overal zichtbaar is, dat er geen
naam-/`nieuw:`-fallback voor een gekoppelde athlete bestaat, en dat een schema-
draft weet wanneer zijn intake wijzigde (stamp) + de workbench deep-linkbaar is.

    python3 -m pytest tests/test_schema_continuity.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import schema_core


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    monkeypatch.setattr(intake_store, "_INTAKES_LOCAL", str(tmp_path / "intakes.json"), raising=False)
    monkeypatch.setattr(intake_store, "_LAATSTE_INTAKE_LOCAL", str(tmp_path / "laatste.json"), raising=False)
    return intake_store


KEY = "LINDE-UUID-123"
_LINKED = {"athlete_name": "Linde Voorbeeld", "doel": "10 EM onder 70 min",
           "trainingsdagen": "di/do/za", "huidig_volume": "30 km/week",
           "gekoppeld_op": "2026-08-17", "updated_at": "2026-08-17"}


class TestCanonicalIntakeEndToEnd:
    def test_gekoppelde_intake_in_prefill(self, store):
        store.save_intakes({KEY: dict(_LINKED)})
        cfg = schema_core.config_prefill(KEY)["config"]
        assert cfg["doel"] == "10 EM onder 70 min"
        assert cfg["trainingsdagen"] == "di/do/za"
        assert cfg["huidig_volume"] == "30 km/week"

    def test_roster_en_prefill_zelfde_waarheid(self, store):
        store.save_intakes({KEY: dict(_LINKED)})
        # roster-pad = zelfde nieuwste_intake op user_key als de prefill
        ik = store.nieuwste_intake(store.load_intakes().get(KEY), store.load_laatste_intakes().get(KEY))
        cfg = schema_core.config_prefill(KEY)["config"]
        assert ik.get("doel") == cfg["doel"]                 # één bron, geen divergentie

    def test_geen_naam_of_nieuw_fallback_voor_gekoppelde_key(self, store):
        # Intake staat onder 'nieuw:linde' (nog niet gekoppeld); Schema op de FS-key
        # mag die NIET via naam oppikken — alleen de canonieke user_key telt.
        store.save_intakes({"nieuw:linde_voorbeeld": dict(_LINKED)})
        cfg = schema_core.config_prefill(KEY)["config"]
        assert cfg["doel"] == "" and cfg["trainingsdagen"] == ""

    def test_geen_intake_geeft_lege_config_en_lege_stamp(self, store):
        store.save_intakes({})
        resp = schema_core.config_prefill(KEY)
        assert resp["config"]["doel"] == ""
        assert resp["intake_stamp"] == ""


class TestIntakeStamp:
    def test_stamp_in_prefill_response(self, store):
        store.save_intakes({KEY: dict(_LINKED)})
        resp = schema_core.config_prefill(KEY)
        assert resp["intake_stamp"] == schema_core._intake_stamp(_LINKED)
        assert resp["intake_stamp"]                          # niet leeg voor een gekoppelde intake

    def test_stamp_verandert_bij_gewijzigde_intake(self, store):
        s1 = schema_core._intake_stamp(_LINKED)
        s2 = schema_core._intake_stamp({**_LINKED, "doel": "marathon"})
        s3 = schema_core._intake_stamp(dict(_LINKED))        # identiek → stabiel
        assert s1 != s2                                      # wijziging → nieuwe stamp (draft wordt stale)
        assert s1 == s3
        assert schema_core._intake_stamp(None) == ""

    def test_koppelen_verandert_stamp(self, store):
        # Vóór koppelen (geen intake op de key) vs ná koppelen → andere stamp,
        # zodat een pre-link config-draft zichzelf als stale herkent.
        voor = schema_core._intake_stamp(store.load_intakes().get(KEY))
        store.save_intakes({KEY: dict(_LINKED)})
        na = schema_core._intake_stamp(store.load_intakes().get(KEY))
        assert voor == "" and na and voor != na


class TestFrontendCoherentieGuards:
    _APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

    def test_workbench_invalideert_stale_config_draft(self):
        fn = self._APP[self._APP.index("function schemaWerk"):self._APP.index("function schemaWerk") + 1400]
        assert "configStale" in fn
        assert "intake_stamp" in fn                          # vergelijkt draft-stamp met a.intake_stamp
        assert 'draft.stage === "config"' in fn

    def test_schema_deeplink_hergebruikt_routing(self):
        assert 'pushRoute("schema"' in self._APP             # workbench zet route
        assert "openSchemaAthlete" in self._APP
        assert "schemaOpenPending" in self._APP              # heropenen zodra roster geladen is
        # applyRoute (bestaande primitive) opent de schema-athlete uit de URL
        ar = self._APP[self._APP.index("function applyRoute"):self._APP.index("function applyRoute") + 600]
        assert 'view === "schema"' in ar and "openSchemaAthlete(ident)" in ar

    def test_config_draft_draagt_stamp(self):
        assert "intake_stamp: r.intake_stamp" in self._APP   # verse config-draft onthoudt zijn intake-versie
