"""Schema Capability v1 — intake-prefill, periode (weken↔einddatum), km/min, config.

Must-have milestone: maak Schema bouwen functioneel volwassen zonder de canonical
schema-/write-logica te herontwerpen. Kernpunten:

  P0 — intake→config prefill werkt écht door na koppelen (root cause: `link_intake`
       behield de oude orphan-`updated_at`, waardoor een stale bouwer-snapshot in
       laatste_intakes de gekoppelde intake overschaduwde in `nieuwste_intake` →
       doel/trainingsdagen bleven leeg). Fix: koppelen stempelt `updated_at` = vandaag.
  P1 — rijkere config-UI (einddatum, wedstrijddatum, tijd/sessie, sessies_per_week),
       canonieke weken↔einddatum via de bestaande `_bereken_periode` (geen tweede
       date-engine), en km/min-keuze via het bestaande `op_tijd`.

De optionele FinalSurge-write/delete-capabilities (Bijsturen, pace↔HR, Builder
bijvullen) zijn bewust NO-GO in deze milestone (aparte Schema Maintenance v1).

    python3 -m pytest tests/test_schema_capability_v1.py -q
"""
import os
import sys
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_API = open(os.path.join(_ROOT, "pwa", "api.py")).read()


def _fn(name):
    i = _APP.index(f"function {name}(")
    depth, started = 0, False
    for j in range(i, len(_APP)):
        c = _APP[j]
        if c == "{":
            depth += 1; started = True
        elif c == "}":
            depth -= 1
            if started and depth == 0:
                return _APP[i:j + 1]
    raise AssertionError(f"function {name} niet gebalanceerd")


import intake_store   # noqa: E402
import intake_core    # noqa: E402
import schema_core    # noqa: E402
from brain import adapter as brain_adapter   # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    for attr, naam in [
        ("_INTAKES_LOCAL", "intakes.json"),
        ("_INTAKE_ARCHIEF_LOCAL", "intakes_archief.json"),
        ("_LAATSTE_INTAKE_LOCAL", "laatste_intakes.json"),
    ]:
        monkeypatch.setattr(intake_store, attr, str(tmp_path / naam), raising=False)
    return intake_store


# ══ P0 — intake-prefill werkt door na koppelen ═════════════════════════════
class TestPrefillDoorwerking:
    def test_1_koppelen_stempelt_updated_at_vandaag(self, store):
        # De orphan draagt een OUDE datum; na koppelen moet de gekoppelde intake als
        # 'vandaag' gelden (anders schaduwt een stale snapshot hem).
        store.save_intakes({"nieuw:Dominique Slooff": {
            "athlete_name": "Dominique Slooff", "doel": "HM sub 1:45",
            "trainingsdagen": "di/do/za", "updated_at": "2026-01-10"}})
        ok, err, _ = intake_core.link_intake("nieuw:Dominique Slooff", "uk-dom")
        assert ok, err
        rec = store.load_intakes()["uk-dom"]
        assert rec["updated_at"] == date.today().isoformat()
        assert rec.get("_intake_datum") == "2026-01-10"   # originele datum bewaard (transparantie)

    def test_2_gekoppelde_intake_wint_van_stale_snapshot(self, store):
        # Reproductie van de live-bug + fix: een oudere/lege bouwer-snapshot mag de
        # verse gekoppelde intake NIET meer overschaduwen in nieuwste_intake.
        store.save_intakes({"nieuw:Dom": {
            "athlete_name": "Dominique Slooff", "doel": "HM sub 1:45",
            "trainingsdagen": "di/do/za", "updated_at": "2026-01-10"}})
        # stale snapshot dated later than the orphan's OLD date
        store.save_laatste_intake("uk-dom", {"athlete_name": "Dominique Slooff",
                                             "_opgeslagen": "2026-02-01T09:00:00"})
        intake_core.link_intake("nieuw:Dom", "uk-dom")
        win = store.nieuwste_intake(store.load_intakes().get("uk-dom"),
                                    store.load_laatste_intakes().get("uk-dom"))
        assert win.get("doel") == "HM sub 1:45"           # gekoppelde intake wint
        assert win.get("trainingsdagen") == "di/do/za"

    def test_3_planning_defaults_surfacet_velden_na_koppelen(self, store):
        store.save_intakes({"nieuw:Dom": {
            "athlete_name": "Dominique Slooff", "doel": "HM sub 1:45",
            "trainingsdagen": "di/do/za", "huidig_volume": "30 km/week",
            "tijd_per_training": "60 min", "race_prioriteit": "A-race",
            "updated_at": "2026-01-10"}})
        store.save_laatste_intake("uk-dom", {"athlete_name": "Dominique Slooff",
                                             "_opgeslagen": "2026-02-01T09:00:00"})
        intake_core.link_intake("nieuw:Dom", "uk-dom")
        pd = brain_adapter.planning_defaults("uk-dom")
        assert pd.get("doel") == "HM sub 1:45"
        assert pd.get("trainingsdagen") == "di/do/za"
        assert pd.get("huidig_volume") == "30 km/week"
        assert pd.get("tijd_per_training") == "60 min"


# ══ P1 — periode (weken ↔ einddatum), canoniek ═════════════════════════════
class TestPeriode:
    def test_4_start_plus_weken_geeft_einddatum(self):
        wk, eind = schema_core._bereken_periode("2026-09-07", "12", "")
        assert wk == 12 and eind == "2026-11-29"

    def test_5_start_plus_einddatum_geeft_weken(self):
        wk, eind = schema_core._bereken_periode("2026-09-07", "", "2026-11-29")
        assert wk == 12 and eind == "2026-11-29"

    def test_6_round_trip_geen_off_by_one(self):
        wk1, eind1 = schema_core._bereken_periode("2026-09-07", "12", "")
        wk2, _ = schema_core._bereken_periode("2026-09-07", "", eind1)
        assert wk1 == wk2 == 12

    def test_7_maandag_uitlijning_dinsdag_start(self):
        # Dinsdag-start telt maandag-uitgelijnd → zelfde einddatum als maandag-start.
        wk_ma, eind_ma = schema_core._bereken_periode("2026-09-07", "12", "")
        wk_di, eind_di = schema_core._bereken_periode("2026-09-08", "12", "")
        assert eind_ma == eind_di and wk_ma == wk_di

    def test_8_endpoint_bestaat_en_gebruikt_canonical(self):
        assert '@app.get("/api/schema/periode")' in _API
        assert "_bereken_periode(start" in _API

    def test_9_wedstrijddatum_mag_na_einddatum(self):
        # Geen automatische gelijktrekking: een hoofddoel-race mag ná het schema-einde.
        _, einddatum = schema_core._bereken_periode("2026-09-07", "12", "")
        wedstrijd = "2026-12-20"
        assert wedstrijd > einddatum   # coherent, geen fout


# ══ P1 — config bevat de rijkere planningvelden ════════════════════════════
class TestConfigPrefill:
    def test_10_config_bevat_sessies_per_week(self, store, monkeypatch):
        store.save_intakes({"uk-x": {"athlete_name": "X", "doel": "5k",
                                     "sessies_per_week": "4", "updated_at": date.today().isoformat()}})
        monkeypatch.setattr(schema_core, "_schema_brain_v2", lambda: False)   # legacy pad = raw intake
        monkeypatch.setattr(schema_core, "_resolve_zones", lambda *a, **k: ("", "tempo", "UNAVAILABLE", ""))
        cfg = schema_core.config_prefill("uk-x")["config"]
        assert cfg["sessies_per_week"] == "4"
        assert "schema_einddatum" in cfg and "wedstrijddatum" in cfg and "op_tijd" in cfg


# ══ P1 — frontend: rijkere config-UI + km/min + periode-binding ════════════
class TestConfigUI:
    def test_11_nieuwe_velden_in_config_form(self):
        body = _fn("sbRenderConfig")
        for el in ('id="cfg-eind"', 'id="cfg-race-datum"', 'id="cfg-sessies"',
                   'id="cfg-tijd"', 'id="cfg-uitvoer"'):
            assert el in body, f"config-UI mist {el}"

    def test_12_sync_bindt_nieuwe_velden(self):
        body = _fn("sbSyncConfig")
        assert "cfg-eind" in body and "cfg-race-datum" in body
        assert "cfg-sessies" in body and "cfg-tijd" in body
        # einddatum wordt NIET meer stil leeggeklaard (was: c.schema_einddatum = "")
        assert 'c.schema_einddatum = "";' not in body

    def test_13_km_min_toggle_zet_op_tijd(self):
        body = _fn("sbRenderConfig")
        assert 'data-v="afstand"' in body and 'data-v="tijd"' in body
        assert "config.op_tijd = (b.dataset.v === \"tijd\")" in body

    def test_14_periode_via_canonieke_server_geen_frontend_engine(self):
        body = _fn("sbRecalcPeriode")
        assert "/api/schema/periode" in body
        assert 'leading === "eind"' in body        # laatst-bewerkte veld leidt
        # geen client-side datum-rekenwerk (geen Date-arithmetic in de recalc)
        assert "setDate(" not in body and "getTime()" not in body

    def test_15_periode_bidirectioneel_bedraad(self):
        body = _fn("sbRenderConfig")
        assert 'sbRecalcPeriode("weken")' in body   # weken/start leidt
        assert 'sbRecalcPeriode("eind")' in body    # einddatum leidt


# ══ Nieuw/Verlengen ongemoeid (regressie) ══════════════════════════════════
class TestModiIntact:
    def test_16_nieuw_en_verlengen_modebar(self):
        assert 'sbModeBar("nieuw")' in _APP
        assert "sbStartVerleng" in _APP and "sbRenderHerijking" in _APP

    def test_17_bijsturen_niet_half_gebouwd(self):
        # NO-GO deze milestone: geen halve destructieve write/delete-flow ingeslopen.
        assert "delete_workout" not in _APP
        assert "convert_schema_zones" not in _APP
