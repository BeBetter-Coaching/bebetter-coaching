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

    def test_grote_discrepantie_herlabelt_sleuteldagen_en_stelt_sessies_voor(self, monkeypatch):
        # 8×/week uitgevoerd maar 3 (sleutel)dagen geconfigureerd → trainingsdagen droegen
        # KWALITEITSDAGEN, niet alle sessies. Voorstel sessies/week; dagen niet stil gelijk zetten.
        cfg = {"trainingsdagen": "di/do/za"}             # 3 sleuteldagen
        items, _ = self._run(monkeypatch, cfg, self._ctx(training={"runs_per_week": 8}))
        f = next(i for i in items if i["sleutel"] == "frequentie")
        assert f["status"] == "controleren"             # coach-check, geen stille lock
        assert cfg["sleuteldagen"] == "di/do/za"         # kwaliteitsdagen bewaard
        assert cfg["sessies_per_week"] == "8"            # voorstel = feitelijke uitvoering
        assert cfg["trainingsdagen"] == ""               # beschikbare dagen = coach-check (niet gokken)

    def test_milde_afwijking_wist_trainingsdagen_niet(self, monkeypatch):
        cfg = {"trainingsdagen": "di/do/za"}             # 3
        items, _ = self._run(monkeypatch, cfg, self._ctx(training={"runs_per_week": 4}))
        assert cfg["trainingsdagen"] == "di/do/za"       # diff 1 → alleen een note, geen herlabel
        assert not cfg.get("sessies_per_week")

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


# ── PUNT 2 — TRAINING ≠ DOELRACE ─────────────────────────────────────────────
class TestDoelrace:
    def _mock(self, monkeypatch, planned, intake):
        monkeypatch.setattr(schema_core, "_planned_window", lambda k: planned)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: intake)

    def _rijen(self, datums):
        return [{"key": f"k{i}", "date": d, "name": "training"} for i, d in enumerate(datums)]

    def test_workout_op_wedstrijddatum_is_doelrace_geen_training(self, monkeypatch):
        # laatste 'workout' valt op de bekende wedstrijddatum → doelrace, niet laatste training
        datums = ["2026-08-01", "2026-08-05", "2026-08-08", "2026-08-22"]
        self._mock(monkeypatch, self._rijen(datums),
                   {"wedstrijddatum": "2026-08-22", "race_prioriteit": "10km A-race", "doel": "sub-40"})
        vb = schema_core.vorig_blok("A")
        assert vb["doelrace"] and vb["doelrace"]["datum"] == "2026-08-22"
        assert vb["blok_einde"] == "2026-08-08"          # laatste échte training vóór de race
        # vervolgstart valt ná de doelrace, niet ná de laatste training
        assert schema_core._verleng_start(vb) == "2026-08-23"

    def test_geen_wedstrijddatum_geen_doelrace(self, monkeypatch):
        datums = ["2026-08-01", "2026-08-05", "2026-08-08"]
        self._mock(monkeypatch, self._rijen(datums), {"doel": "opbouw"})
        vb = schema_core.vorig_blok("A")
        assert vb["doelrace"] is None
        assert vb["blok_einde"] == "2026-08-08"

    def test_doelrace_rolt_oud_hoofddoel_niet_door(self, monkeypatch):
        cfg = {"doel": "sub-40 10km", "trainingsdagen": "di/do"}
        monkeypatch.setattr(AC, "build_athlete_context",
                            lambda key, naam="", today=None: {"naam": "T", "training": {}, "health": {}, "feedback": {}})
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        vb = {"doelrace": {"datum": "2026-08-22", "naam": "10km A-race"}}
        items, _ = schema_core._herijking("A", cfg, vb)
        assert cfg["doel"] == ""                          # geen roll-over → coach kiest nieuw hoofddoel
        d = next(i for i in items if i["sleutel"] == "doel")
        assert "hoofddoel" in d["label"].lower()

    def test_leeg_doel_na_doelrace_blokkeert_readiness(self):
        cfg = {"athlete_key": "A", "doel": "", "zones": "z"}
        assert schema_core._verleng_readiness(cfg, {}, [])["status"] == "geblokkeerd"


# ── PUNT 3 — SESSIES/WEEK-DIRECTIVE + PLAN-COMPLETENESS ──────────────────────
class TestSessiesEnCompleteness:
    def test_sessies_per_week_geeft_harde_eis(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {
            "mode": "verlengen", "trainingsdagen": "", "sessies_per_week": "8",
            "sleuteldagen": "di/do/zo", "dubbele_dagen": "di/do"})
        harde, _ = SB._harde_eisen_secties(intake)
        assert "SESSIES PER WEEK" in harde and "8" in harde
        assert "di/do" in harde                            # dubbele dagen genoemd

    def test_geen_sessies_per_week_geen_sessie_eis(self, monkeypatch):
        # Nieuw/bestaande flow: zonder sessies_per_week GEEN sessie-hardregel (byte-gedrag ongewijzigd)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {"trainingsdagen": "di/do"})
        harde, _ = SB._harde_eisen_secties(intake)
        assert "SESSIES PER WEEK" not in harde

    def _weken(self, counts):
        return [{"week_index": i + 1, "rows": [{"id": f"r{i}{j}"} for j in range(c)]}
                for i, c in enumerate(counts)]

    def test_completeness_blokkeert_te_weinig_sessies(self):
        ok, melding = schema_core.plan_completeness(self._weken([3, 3, 3, 2]), "7")
        assert ok is False and "week 1" in melding and "3 van de gewenste 7" in melding

    def test_completeness_laatste_week_mag_taperen(self):
        ok, _ = schema_core.plan_completeness(self._weken([7, 7, 7, 3]), "7")
        assert ok is True                                 # alleen de laatste week is korter

    def test_completeness_uit_zonder_sessies_per_week(self):
        ok, _ = schema_core.plan_completeness(self._weken([1, 1, 1]), "")
        assert ok is True                                 # geen eis → nooit blokkeren

    def test_completeness_bereik_gebruikt_ondergrens(self):
        ok, _ = schema_core.plan_completeness(self._weken([7, 7, 7, 3]), "7-9")
        assert ok is True                                 # "7-9" → ondergrens 7

    # ── Kalenderbewuste completeness (frequency-guard, één invariant) ─────────
    def _weken_kal(self, counts, eerste_maandag):
        """Weken mét week_start (maandag) zodat de volle-vs-partiële-weeklogica werkt."""
        from datetime import date, timedelta
        mon0 = date.fromisoformat(eerste_maandag)
        return [{"week_index": i + 1,
                 "week_start": (mon0 + timedelta(weeks=i)).isoformat(),
                 "rows": [{"id": f"r{i}{j}"} for j in range(c)]}
                for i, c in enumerate(counts)]

    def test_case1_live_race_za_start_zo(self):
        # LIVE CASE: race za 15-8 → vervolgstart zo 16-8 (weekmaandag 10-8); week 1 = 1 zondagtraining.
        # Partiële eerste week → verwacht = 1, GEEN "1 van 8" en GEEN "1 van 2".
        cfg = {"startdatum": "2026-08-16", "sessies_per_week": "8", "dubbele_dagen": "zo"}
        ok, melding = schema_core.plan_completeness(self._weken_kal([1, 8, 8, 3], "2026-08-10"), "8", cfg)
        assert ok is True, melding

    def test_case2_volle_week_te_weinig_faalt(self):
        # start maandag → week 1 is vol; 3 van 8 → FAIL
        cfg = {"startdatum": "2026-08-17", "sessies_per_week": "8"}
        ok, melding = schema_core.plan_completeness(self._weken_kal([3, 8], "2026-08-17"), "8", cfg)
        assert ok is False and "3 van de gewenste 8" in melding

    def test_case3_volle_week_compleet_pass(self):
        cfg = {"startdatum": "2026-08-17", "sessies_per_week": "8"}
        assert schema_core.plan_completeness(self._weken_kal([8, 8, 3], "2026-08-17"), "8", cfg)[0] is True

    def test_case4_volle_week_met_dubbels_pass(self):
        # 9/week (2 dubbele dagen) → 9 rows in een volle week → PASS
        cfg = {"startdatum": "2026-08-17", "sessies_per_week": "9", "dubbele_dagen": "di do"}
        assert schema_core.plan_completeness(self._weken_kal([9, 9, 3], "2026-08-17"), "9", cfg)[0] is True

    def test_case5_volle_week_dubbelmogelijk_maar_te_weinig_faalt(self):
        # dubbele_dagen verlaagt de eis NIET: volle 9-week met 7 rows mist 2 sessies → FAIL
        cfg = {"startdatum": "2026-08-17", "sessies_per_week": "9", "dubbele_dagen": "di do"}
        ok, melding = schema_core.plan_completeness(self._weken_kal([7, 9, 3], "2026-08-17"), "9", cfg)
        assert ok is False and "7 van de gewenste 9" in melding

    def test_case6_partiele_week_start_donderdag_geen_zelfbedacht_minimum(self):
        # start do 20-8 (weekmaandag 17-8): aangesneden week → geen minimum, ook al is 8/week de norm
        cfg = {"startdatum": "2026-08-20", "sessies_per_week": "8"}
        assert schema_core.plan_completeness(self._weken_kal([2, 8, 3], "2026-08-17"), "8", cfg)[0] is True

    def test_case7_partiele_week_dubbele_dag_niet_automatisch_verplicht(self):
        # start zo; dubbele_dagen bevat zondag; plan heeft 1 zondagtraining → NIET automatisch 2 eisen
        cfg = {"startdatum": "2026-08-16", "sessies_per_week": "8",
               "trainingsdagen": "za zo", "dubbele_dagen": "zo"}
        ok, melding = schema_core.plan_completeness(self._weken_kal([1, 8, 3], "2026-08-10"), "8", cfg)
        assert ok is True, melding

    def test_case8_partiele_week_twee_sessies_een_dag_pass(self):
        # plan zet bewust 2 sessies op zondag in de aangesneden week → guard accepteert beide
        cfg = {"startdatum": "2026-08-16", "sessies_per_week": "8", "dubbele_dagen": "zo"}
        assert schema_core.plan_completeness(self._weken_kal([2, 8, 3], "2026-08-10"), "8", cfg)[0] is True

    def test_case9_geen_bovengrens_integriteit_via_csv_prompt(self):
        # 'CSV verzint extra' is niet betrouwbaar uit de vrije-tekst-plan af te leiden en
        # wordt geborgd door de harde CSV-prompt (build_csv_prompt), niet door deze guard.
        # De frequency-guard kent dus geen bovengrens: meer rows dan spw blokkeert niet.
        cfg = {"startdatum": "2026-08-17", "sessies_per_week": "8"}
        assert schema_core.plan_completeness(self._weken_kal([10, 8, 3], "2026-08-17"), "8", cfg)[0] is True

    def test_case10_laatste_taperweek_pass(self):
        cfg = {"startdatum": "2026-08-17", "sessies_per_week": "8"}
        assert schema_core.plan_completeness(self._weken_kal([8, 8, 8, 2], "2026-08-17"), "8", cfg)[0] is True
