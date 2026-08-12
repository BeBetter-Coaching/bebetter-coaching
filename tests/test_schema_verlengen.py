"""Tests voor Schema Verlengen — slimme herijking i.p.v. herhaalde intake.

Dekt de Verlengen-toevoegingen bovenop de bewezen Nieuw-flow:
  - mode parametriseren: mode=verlengen activeert de bewezen VERVOLGBLOK-directive
  - vorig blok betrouwbaar identificeren (toekomstig / net afgelopen / weken geleden)
  - startdatum-semantiek (laatste zondag→maandag, woensdag→donderdag, afgelopen→ná einde)
  - herijking: live zones vervangen oude; actueel volume = feit; gewenste frequentie
    NIET stil wijzigen (coach-check); onderbreking/klacht = aandacht
  - readiness: klaar / controle / geblokkeerd; weinig data of onderbreking blokkeert NIET
  - mini-update: alleen vragen die niet al uit de context bekend zijn
  - overlap: verlengen mag alleen ná het bestaande blok toevoegen (blokkerend)
  - regressie: Nieuw blijft mode=nieuw (geen VERVOLGBLOK, geen overlap-check)

Draaien met:  python3 -m pytest tests/ -q
"""

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import schema_core
import schema_builder as SB
import athlete_context as AC


def _iso(d):
    return d.isoformat()


# ── MODE: mode=verlengen activeert de bewezen VERVOLGBLOK-directive ───────────
class TestModeDirective:
    def test_intake_from_config_neemt_mode_over(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {"mode": "verlengen", "doel": "10km"})
        assert intake["mode"] == "verlengen"

    def test_onbekende_mode_valt_terug_op_nieuw(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {"mode": "hackerz"})
        assert intake["mode"] == "nieuw"

    def test_verlengen_geeft_vervolgblok_directive(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {"mode": "verlengen",
                                                       "trainingsdagen": "di/do"})
        harde, _ = SB._harde_eisen_secties(intake)
        assert "VERVOLGBLOK" in harde

    def test_nieuw_geeft_geen_vervolgblok_directive(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {"mode": "nieuw",
                                                       "trainingsdagen": "di/do"})
        harde, _ = SB._harde_eisen_secties(intake)
        assert "VERVOLGBLOK" not in harde

    def test_context_config_mode_reflecteert_config(self):
        assert schema_core.context_config({"mode": "verlengen"})["mode"] == "verlengen"
        assert schema_core.context_config({})["mode"] == "nieuw"


# ── STARTDATUM-SEMANTIEK (pure) ──────────────────────────────────────────────
class TestStart:
    def test_laatste_zondag_geeft_maandag(self):
        # 2026-08-16 = zondag → start maandag 2026-08-17
        assert schema_core._verleng_start({"laatste_datum": "2026-08-16"}) == "2026-08-17"

    def test_laatste_woensdag_geeft_donderdag(self):
        # 2026-08-19 = woensdag → start donderdag 2026-08-20 (korte eerste week toegestaan)
        assert schema_core._verleng_start({"laatste_datum": "2026-08-19"}) == "2026-08-20"

    def test_geen_laatste_valt_terug_op_default_maandag(self):
        s = schema_core._verleng_start({"laatste_datum": ""})
        assert date.fromisoformat(s).weekday() == 0        # eerstvolgende maandag


# ── VORIG BLOK betrouwbaar identificeren ─────────────────────────────────────
class TestVorigBlok:
    def _mock(self, monkeypatch, planned, intake=None):
        monkeypatch.setattr(schema_core, "_planned_window", lambda k: planned)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: intake or {})

    def _rijen(self, datums):
        return [{"key": f"k{i}", "date": d, "name": "training"} for i, d in enumerate(datums)]

    def test_toekomstig_blok_loopt_nog(self, monkeypatch):
        today = date.today()
        datums = [_iso(today + timedelta(days=n)) for n in (2, 4, 7, 9, 11)]
        self._mock(monkeypatch, self._rijen(datums))
        vb = schema_core.vorig_blok("A")
        assert vb["loopt_nog"] is True
        assert vb["laatste_datum"] == datums[-1]
        assert vb["betrouwbaar"] is True

    def test_blok_eindigde_gisteren(self, monkeypatch):
        today = date.today()
        datums = [_iso(today - timedelta(days=n)) for n in (14, 10, 6, 3, 1)]
        self._mock(monkeypatch, self._rijen(sorted(datums)))
        vb = schema_core.vorig_blok("A")
        assert vb["loopt_nog"] is False
        assert vb["afgelopen_dagen"] == 1

    def test_blok_weken_geleden_nog_betrouwbaar(self, monkeypatch):
        today = date.today()
        datums = sorted(_iso(today - timedelta(days=n)) for n in (40, 37, 34, 31, 28))
        self._mock(monkeypatch, self._rijen(datums))
        vb = schema_core.vorig_blok("A")
        assert vb["afgelopen_dagen"] >= 20
        assert vb["betrouwbaar"] is True
        assert vb["bron"] == "finalsurge"

    def test_geen_planning_maar_intake_is_betrouwbaar_zonder_overlaprisico(self, monkeypatch):
        self._mock(monkeypatch, [], intake={"doel": "10km", "startdatum": "2026-01-01"})
        vb = schema_core.vorig_blok("A")
        assert vb["laatste_datum"] == ""          # niets om mee te overlappen
        assert vb["betrouwbaar"] is True
        assert vb["bron"] == "intake"

    def test_frequentie_afgeleid_uit_planning(self, monkeypatch):
        # 8 trainingen over 2 weken ≈ 4/week
        base = date(2026, 8, 3)
        datums = sorted(_iso(base + timedelta(days=d)) for d in (0, 2, 4, 6, 7, 9, 11, 13))
        self._mock(monkeypatch, self._rijen(datums))
        vb = schema_core.vorig_blok("A")
        assert vb["frequentie"] == 4.0


# ── HERIJKING: feiten actualiseren, coachbesluiten niet stil wijzigen ─────────
class TestHerijking:
    def _ctx(self, **over):
        base = {"naam": "Test", "training": {}, "health": {}, "feedback": {}}
        base.update(over)
        return base

    def _run(self, monkeypatch, config, ctx, intake=None):
        monkeypatch.setattr(AC, "build_athlete_context", lambda key, naam="", today=None: ctx)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: intake or {})
        return schema_core._herijking("A", config, {})

    def test_live_zones_vervangen_oude_als_veranderd(self, monkeypatch):
        cfg = {"zones": "NIEUWE zones bpm", "trainingsdagen": "di/do"}
        items, _ = self._run(monkeypatch, cfg, self._ctx(), intake={"zones": "oude zones"})
        z = next(i for i in items if i["sleutel"] == "zones")
        assert z["status"] == "veranderd" and z["zekerheid"] == "hoog"

    def test_actueel_volume_wordt_feit_in_config(self, monkeypatch):
        cfg = {"trainingsdagen": "di/do", "huidig_volume": "40 km/week"}
        items, _ = self._run(monkeypatch, cfg, self._ctx(training={"km_per_week": 51}),
                             intake={"huidig_volume": "40 km/week"})
        assert "51" in cfg["huidig_volume"]             # feit geactualiseerd
        v = next(i for i in items if i["sleutel"] == "volume")
        assert v["status"] == "veranderd"

    def test_hogere_uitvoeringsfrequentie_wijzigt_trainingsdagen_niet(self, monkeypatch):
        cfg = {"trainingsdagen": "di/do/za"}             # gewenst 3
        items, _ = self._run(monkeypatch, cfg, self._ctx(training={"runs_per_week": 5}))
        f = next(i for i in items if i["sleutel"] == "frequentie")
        assert f["status"] == "controleren"             # coach-check, geen auto-wijziging
        assert cfg["trainingsdagen"] == "di/do/za"       # ongewijzigd

    def test_onderbreking_is_kritiek_aandachtspunt(self, monkeypatch):
        cfg = {"trainingsdagen": "di/do"}
        items, _ = self._run(monkeypatch, cfg,
                             self._ctx(training={"onderbreking": "3 weken niet getraind"}))
        o = next(i for i in items if i["sleutel"] == "onderbreking")
        assert o["status"] == "aandacht" and o["kritiek"] is True

    def test_actuele_klacht_is_kritiek(self, monkeypatch):
        cfg = {"trainingsdagen": "di/do"}
        ctx = self._ctx(health={"actuele_klachten": [
            {"tekst": "achilles gevoelig", "bron": "coach-notitie", "datum": "2026-08-05"}]})
        items, _ = self._run(monkeypatch, cfg, ctx)
        k = [i for i in items if i["sleutel"] == "klacht"]
        assert k and k[0]["kritiek"] is True


# ── READINESS: rijk model, blokkeer alleen op harde voorwaarde ───────────────
class TestReadiness:
    def test_volledig_bekend_is_klaar(self):
        cfg = {"athlete_key": "A", "doel": "10km", "zones": "z", "trainingsdagen": "di/do"}
        items = [{"status": "geldig", "kritiek": False}]
        assert schema_core._verleng_readiness(cfg, {}, items)["status"] == "klaar"

    def test_ontbrekend_doel_blokkeert(self):
        cfg = {"athlete_key": "A", "doel": "", "zones": "z"}
        assert schema_core._verleng_readiness(cfg, {}, [])["status"] == "geblokkeerd"

    def test_controleren_of_kritiek_geeft_controle(self):
        cfg = {"athlete_key": "A", "doel": "10km", "zones": "z"}
        items = [{"status": "controleren", "kritiek": False},
                 {"status": "aandacht", "kritiek": True}]
        rd = schema_core._verleng_readiness(cfg, {}, items)
        assert rd["status"] == "controle" and rd["kritiek"] == 1 and rd["controle"] == 1

    def test_weinig_data_of_onderbreking_blokkeert_niet(self):
        cfg = {"athlete_key": "A", "doel": "10km", "zones": "z"}
        items = [{"status": "aandacht", "kritiek": True, "sleutel": "onderbreking"}]
        assert schema_core._verleng_readiness(cfg, {}, items)["status"] != "geblokkeerd"


# ── MINI-UPDATE: alleen vragen die niet al bekend zijn ───────────────────────
class TestMiniUpdate:
    def test_geen_trainingsdagenvraag_als_bekend(self):
        vragen = schema_core._verleng_vragen("A", {"trainingsdagen": "di/do"},
                                             {"recovery": {"slaap": "goed"}})
        sleutels = {v["sleutel"] for v in vragen}
        assert "trainingsdagen" not in sleutels
        assert "werk_slaap" not in sleutels           # recovery bekend → niet vragen

    def test_vraagt_trainingsdagen_als_onbekend(self):
        vragen = schema_core._verleng_vragen("A", {"trainingsdagen": ""}, {})
        assert any(v["sleutel"] == "trainingsdagen" for v in vragen)


# ── OVERLAP: verlengen voegt alleen ná het bestaande blok toe ────────────────
class TestOverlap:
    def _rows(self, datums):
        return [{"id": f"r{i}", "date": d, "name": "Duurloop", "activity_type": "Run",
                 "included": True} for i, d in enumerate(datums)]

    def test_row_op_of_voor_laatste_is_blokkerend(self):
        cfg = {"mode": "verlengen", "_verleng_laatste": "2026-08-16"}
        rows = self._rows(["2026-08-15", "2026-08-18"])
        errs = schema_core._overlap_errors("A", cfg, schema_core._included(rows))
        assert errs and "Overlap" in errs[0]

    def test_alleen_na_laatste_geen_fout(self):
        cfg = {"mode": "verlengen", "_verleng_laatste": "2026-08-16"}
        rows = self._rows(["2026-08-17", "2026-08-20"])
        assert schema_core._overlap_errors("A", cfg, schema_core._included(rows)) == []

    def test_nieuw_mode_doet_geen_overlapcheck(self):
        cfg = {"mode": "nieuw", "_verleng_laatste": "2026-08-16"}
        rows = self._rows(["2026-08-15"])
        assert schema_core._overlap_errors("A", cfg, schema_core._included(rows)) == []

    def test_publish_preview_meldt_overlap_als_error(self, monkeypatch):
        cfg = {"mode": "verlengen", "_verleng_laatste": "2026-08-16"}
        rows = self._rows(["2026-08-10"])
        res = schema_core.publish_preview("A", cfg, rows)
        assert res["valid"] is False and any("Overlap" in e for e in res["errors"])


# ── VERLENG_PREFILL end-to-end (deps gemockt) ────────────────────────────────
class TestVerlengPrefill:
    def _wire(self, monkeypatch, planned, base_config, ctx, intake=None):
        monkeypatch.setattr(schema_core, "config_prefill",
                            lambda k: {"config": dict(base_config), "context": {}, "afspraken": []})
        monkeypatch.setattr(schema_core, "_planned_window", lambda k: planned)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: intake or {})
        monkeypatch.setattr(AC, "build_athlete_context", lambda key, naam="", today=None: ctx)

    def test_prefill_zet_mode_en_start_na_laatste(self, monkeypatch):
        planned = [{"key": "k", "date": "2026-08-16", "name": "t"}] * 4
        base = {"athlete_key": "A", "doel": "10km", "zones": "z", "trainingsdagen": "di/do", "weken": "8"}
        self._wire(monkeypatch, planned, base, {"naam": "T", "training": {}, "health": {}, "feedback": {}})
        res = schema_core.verleng_prefill("A")
        assert res["config"]["mode"] == "verlengen"
        assert res["config"]["startdatum"] == "2026-08-17"     # ná laatste zondag
        assert res["config"]["_verleng_laatste"] == "2026-08-16"
        assert res["readiness"]["status"] in ("klaar", "controle")
        assert "vorig_blok" in res and "herijking" in res
