"""Tests voor de Schema-workbench (Slice 1) — pure logica, geen netwerk.

Dekt de PWA-toevoegingen bovenop de bewezen kern:
  - canonieke rows -> maandag-weekgroepering (identiek aan Streamlit-weeklogica)
  - km-totalen, trainingsvolgorde, stabiele row-identiteit
  - non-run row zonder run-velden blijft correct
  - context() leest de bestaande intake (geen nieuwe waarheid)
  - guards: geen FinalSurge-write in de Slice-1 flow; Home/Feedback ongemoeid

Draaien met:  python3 -m pytest tests/ -q
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import schema_core


# Maandag 2026-08-10 is de maandag van de startweek.
def _rijen():
    return [
        {"date": "2026-08-13", "activity_type": "Strength", "name": "Kracht",
         "planned_km": None, "planned_min": 45, "description": "core"},
        {"date": "2026-08-11", "activity_type": "Run", "name": "Duurloop",
         "planned_km": 10, "planned_min": None, "description": "Z2"},
        {"date": "2026-08-18", "activity_type": "Run", "name": "Interval",
         "planned_km": 8, "planned_min": None, "description": "Z4"},
    ]


class TestWeekgroepering:
    def test_maandag_week_index(self):
        weken = schema_core.groepeer_weken(_rijen(), "2026-08-10")
        assert [w["week_index"] for w in weken] == [1, 2]

    def test_km_totaal_per_week(self):
        weken = schema_core.groepeer_weken(_rijen(), "2026-08-10")
        assert weken[0]["total_km"] == 10   # duurloop 10 + kracht None
        assert weken[1]["total_km"] == 8

    def test_volgorde_binnen_week_op_datum(self):
        weken = schema_core.groepeer_weken(_rijen(), "2026-08-10")
        namen = [r["name"] for r in weken[0]["rows"]]
        assert namen == ["Duurloop", "Kracht"]   # 11 aug vóór 13 aug

    def test_stabiele_row_ids(self):
        rijen = _rijen()
        schema_core.groepeer_weken(rijen, "2026-08-10")
        assert [r["id"] for r in rijen] == ["r0", "r1", "r2"]

    def test_startdatum_niet_op_maandag(self):
        # Start dinsdag 2026-08-11 → maandag van startweek = 2026-08-10, dus zelfde weken
        weken = schema_core.groepeer_weken(_rijen(), "2026-08-11")
        assert [w["week_index"] for w in weken] == [1, 2]

    def test_datumrange_label(self):
        weken = schema_core.groepeer_weken(_rijen(), "2026-08-10")
        assert weken[0]["label"] == "Week 1"
        assert weken[0]["datumrange"] == "10/8 – 16/8"

    def test_geen_startdatum_valt_terug_zonder_crash(self):
        weken = schema_core.groepeer_weken(_rijen(), "")
        assert weken                       # ISO-week fallback, geen exception
        assert all("rows" in w for w in weken)


class TestNonRun:
    def test_strength_zonder_km_blijft_none(self):
        rijen = _rijen()
        schema_core.groepeer_weken(rijen, "2026-08-10")
        strength = next(r for r in rijen if r["activity_type"] == "Strength")
        assert strength["planned_km"] is None
        assert strength["planned_min"] == 45


class TestContext:
    def test_context_leest_intake(self, monkeypatch):
        monkeypatch.setattr(schema_core.intake_store, "load_laatste_intakes", lambda: {
            "ATL1": {"athlete_name": "Lisa Jansen", "naam": "Lisa", "doel": "10km sub 50",
                     "weken": "8", "trainingsdagen": "di/do", "startdatum": "2026-08-10",
                     "zone_type": "hartslag", "mode": "nieuw"},
        })
        ctx = schema_core.context("ATL1")
        assert ctx["naam"] == "Lisa Jansen"
        assert ctx["doel"] == "10km sub 50"
        assert ctx["trainingsdagen"] == "di/do"
        assert ctx["zone_bron"] == "hartslag"   # afgeleid van zone_type
        assert ctx["mode"] == "nieuw"

    def test_context_onbekende_atleet_is_leeg_maar_veilig(self, monkeypatch):
        monkeypatch.setattr(schema_core.intake_store, "load_laatste_intakes", lambda: {})
        ctx = schema_core.context("NOPE")
        assert ctx["zone_bron"] == "tempo"       # default, geen crash


class TestSliceGuards:
    """Slice 1 mag NIET naar FinalSurge schrijven en Home/Feedback niet raken."""

    def _app_js(self):
        with open(os.path.join(_ROOT, "pwa", "static", "app.js"), encoding="utf-8") as f:
            return f.read()

    def test_geen_push_in_slice1_flow(self):
        # De push-route mag in de backend blijven bestaan, maar de nieuwe
        # workbench-flow doet er GEEN aanroep naar (geen actieve write).
        js = self._app_js()
        assert 'jpost("/api/schema/push"' not in js
        assert "/api/schema/push" not in js.replace(
            "bestaande /api/schema/push-route blijft", "")  # alleen de comment-vermelding mag

    def test_feedback_regressieguard(self):
        js = self._app_js()
        # Bewezen Feedback-hooks blijven aanwezig (niet per ongeluk verwijderd).
        assert "fbDraftGet" in js and "fb-focus-col" in js

    def test_home_regressieguard(self):
        assert "renderHome" in self._app_js()

    def test_slice2_geen_write_cta(self):
        js = self._app_js()
        # Slice 2 introduceert geen push/write-CTA; nog steeds geen push-aanroep.
        assert 'jpost("/api/schema/push"' not in js
        assert "sbBuildSchema" in js and "sbChatSend" in js   # nieuwe flow aanwezig


# ── Slice 2: config-assemblage + AI plan-sparfase (AI gemonkeypatcht) ─────────
class TestSlice2Config:
    def test_intake_from_config_overschrijft_basis(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake",
                            lambda k: {"doel": "oud doel", "zones": "Zbase", "trainingsdagen": "ma/wo"})
        cfg = {"doel": "10km sub 50", "startdatum": "2026-08-10", "weken": "8",
               "trainingsdagen": "di/do", "zone_type": "tempo", "zones": "Znieuw"}
        intake = schema_core._intake_from_config("ATL1", cfg)
        assert intake["doel"] == "10km sub 50"          # config wint van basis
        assert intake["trainingsdagen"] == "di/do"
        assert intake["zones"] == "Znieuw"
        assert intake["mode"] == "nieuw"
        assert intake["weken"] == "8" and intake["schema_einddatum"] == "2026-10-04"
        assert intake["athlete_key"] == "ATL1"

    def test_context_blob_wordt_uploaded_summary(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        intake = schema_core._intake_from_config("A", {"_context": "TRAININGSLOG…"})
        assert intake["uploaded_summary"] == "TRAININGSLOG…"

    def test_genereer_plan_config_gebruikt_assembled_intake(self, monkeypatch):
        import schema_builder as SB
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        captured = {}
        monkeypatch.setattr(SB, "generate_plan", lambda intake: captured.update(intake) or "PLAN X")
        # _context gezet → geen zware actuele-context-fetch (geen netwerk)
        cfg = {"doel": "10km", "startdatum": "2026-08-10", "weken": "6",
               "trainingsdagen": "di/do", "zone_type": "tempo", "zones": "Z", "_context": "ctx"}
        res = schema_core.genereer_plan_config("ATL1", cfg)
        assert res["plan"] == "PLAN X"
        assert captured["mode"] == "nieuw" and captured["doel"] == "10km"
        assert captured["uploaded_summary"] == "ctx"
        assert res["context"]["doel"] == "10km"


class TestSlice2Chat:
    def _base(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})

    def test_gewone_reactie_laat_plan_ongemoeid(self, monkeypatch):
        import schema_builder as SB
        self._base(monkeypatch)
        monkeypatch.setattr(SB, "chat_about_plan", lambda plan, intake, hist: "Goede vraag, dat kan.")
        res = schema_core.chat_plan("A", {"doel": "10km"}, "HUIDIG PLAN", [{"role": "user", "content": "vraag"}])
        assert res["plan_updated"] is False and res["plan"] == ""
        assert res["reply"] == "Goede vraag, dat kan."

    def test_plan_update_wordt_atomair_geparsed(self, monkeypatch):
        import schema_builder as SB
        self._base(monkeypatch)
        monkeypatch.setattr(SB, "chat_about_plan",
                            lambda plan, intake, hist: "Ik maak week 4 rustiger.\n===PLAN UPDATE===\nWEEK 1..8 volledig\n===EINDE PLAN===")
        res = schema_core.chat_plan("A", {"doel": "10km"}, "OUD", [])
        assert res["plan_updated"] is True and not res["truncated"]
        assert "WEEK 1..8" in res["plan"] and res["reply"] == "Ik maak week 4 rustiger."

    def test_chat_krijgt_actuele_plan_en_intake(self, monkeypatch):
        import schema_builder as SB
        self._base(monkeypatch)
        seen = {}
        def _stub(plan, intake, hist):
            seen["plan"] = plan; seen["doel"] = intake.get("doel"); seen["hist"] = len(hist)
            return "ok"
        monkeypatch.setattr(SB, "chat_about_plan", _stub)
        schema_core.chat_plan("A", {"doel": "5km"}, "ACTUEEL PLAN", [{"role": "user", "content": "x"}])
        assert seen["plan"] == "ACTUEEL PLAN" and seen["doel"] == "5km" and seen["hist"] == 1

    def test_leeg_plan_weigert(self, monkeypatch):
        self._base(monkeypatch)
        import pytest
        with pytest.raises(ValueError):
            schema_core.chat_plan("A", {}, "   ", [])


class TestSlice2Roster:
    """Acceptance-fix: selector toont de VOLLE coachbare roster; intake = prefill,
    geen toelatingsvoorwaarde."""

    def _roster(self, monkeypatch, roster, intakes=None, module_intakes=None):
        import types
        import fs_client as FS
        fake = types.SimpleNamespace(roster=lambda: roster)      # config_prefill gebruikt fs_core.roster
        monkeypatch.setitem(sys.modules, "fs_core", fake)
        # coachbare_atleten gebruikt de centrale get_athletes_by_group (gegroepeerd)
        groepen = {}
        for a in roster:
            groepen.setdefault(a.get("groep") or "Overig", []).append(
                {"name": a.get("naam"), "user_key": a.get("user_key"), "first_name": a.get("voornaam")})
        monkeypatch.setattr(FS, "get_athletes_by_group", lambda: groepen)
        monkeypatch.setattr(schema_core.intake_store, "load_laatste_intakes", lambda: intakes or {})
        monkeypatch.setattr(schema_core.intake_store, "load_intakes", lambda: module_intakes or {})

    def test_atleet_met_en_zonder_intake_beide_in_selector(self, monkeypatch):
        self._roster(monkeypatch, [
            {"user_key": "A", "naam": "Anna Appel", "voornaam": "Anna", "groep": "Gevorderd"},
            {"user_key": "B", "naam": "Bram Bakker", "voornaam": "Bram", "groep": "Beginners"},
        ], intakes={"A": {"doel": "10km", "weken": "8", "trainingsdagen": "di/do"}})
        out = schema_core.coachbare_atleten()
        keys = {a["key"]: a for a in out}
        assert "A" in keys and "B" in keys            # ZONDER intake (B) staat er óók in
        assert keys["A"]["heeft_intake"] is True and keys["A"]["doel"] == "10km"
        assert keys["B"]["heeft_intake"] is False and keys["B"]["doel"] == ""

    def test_config_prefill_met_intake(self, monkeypatch):
        self._roster(monkeypatch, [{"user_key": "A", "naam": "Anna Appel", "voornaam": "Anna"}],
                     intakes={"A": {"athlete_name": "Anna Appel", "naam": "Anna", "doel": "10km sub 50",
                                    "trainingsdagen": "di/do", "zone_type": "tempo", "zones": "Z1..Z5",
                                    "startdatum": "2026-09-07", "weken": "8"}})
        monkeypatch.setattr(schema_core, "_nieuwste_intake", schema_core._nieuwste_intake)  # echte merge
        # get_athlete_zones niet nodig (val terug op opgeslagen zones); FS-import faalt stil
        res = schema_core.config_prefill("A")
        c = res["config"]
        assert c["naam"] == "Anna" and c["doel"] == "10km sub 50"
        assert c["trainingsdagen"] == "di/do" and c["zones"] == "Z1..Z5"

    def test_config_prefill_zonder_intake_defaults_en_identity(self, monkeypatch):
        self._roster(monkeypatch, [{"user_key": "B", "naam": "Bram Bakker", "voornaam": "Bram"}])
        res = schema_core.config_prefill("B")
        c = res["config"]
        assert c["athlete_name"] == "Bram Bakker" and c["naam"] == "Bram"   # identity uit roster
        assert c["doel"] == "" and c["trainingsdagen"] == ""                # geen gegokte waarden
        assert c["weken"] and c["startdatum"]                              # veilige defaults
        assert res["context"]["mode"] == "nieuw"


class TestMasterbreinContext:
    """Schema-chat gebruikt de gedeelde athlete_context (masterbrein)."""

    def test_plan_gen_voedt_context_en_traceability(self, monkeypatch):
        import schema_builder as SB
        import athlete_context as AC
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})
        fake_ctx = {"naam": "Anna", "health": {"actuele_klachten": [
            {"tekst": "achilles", "bron": "coach-notitie", "datum": "2026-08-08", "status": "recent"}]}}
        monkeypatch.setattr(AC, "build_athlete_context", lambda key, naam="", today=None: fake_ctx)
        captured = {}
        monkeypatch.setattr(SB, "generate_plan", lambda intake: captured.update(intake) or "PLAN")
        res = schema_core.genereer_plan_config("A", {"doel": "10km", "startdatum": "2026-08-10",
                                                     "weken": "8", "trainingsdagen": "di/do"})
        assert "achilles" in captured.get("uploaded_summary", "").lower()   # context vóór AI
        assert res["context_used"]["active_complaints"] == 1                # traceability

    def test_bekende_context_endpoint_shape(self, monkeypatch):
        import athlete_context as AC
        monkeypatch.setattr(AC, "build_athlete_context",
                            lambda key, naam="", today=None: {"naam": "X", "health": {}})
        out = schema_core.bekende_context("A")
        assert "secties" in out and "used" in out and isinstance(out["secties"], list)


# ── Slice 3: veilige publicatie (validatie, dup-check, partial-failure, retry) ─
def _rows():
    return [
        {"id": "r0", "included": True, "edited": True, "date": "2026-09-01", "activity_type": "Run",
         "name": "Duurloop", "planned_km": 10, "planned_min": None, "description": "Z2"},
        {"id": "r1", "included": False, "date": "2026-09-02", "activity_type": "Run",
         "name": "Interval", "planned_km": 8, "planned_min": None, "description": "Z4"},
        {"id": "r2", "included": True, "date": "2026-09-03", "activity_type": "Strength",
         "name": "Kracht", "planned_km": None, "planned_min": 45, "description": "core"},
    ]


class TestPublishValidatie:
    def test_geldige_rows(self):
        assert schema_core.validate_rows("ATL", _rows()) == []

    def test_lege_selectie_blokkeert(self):
        rows = [{"id": "a", "included": False, "date": "2026-09-01", "name": "x", "activity_type": "Run"}]
        assert any("geselecteerd" in e for e in schema_core.validate_rows("ATL", rows))

    def test_ontbrekende_naam_en_datum_blokkeren(self):
        rows = [{"id": "a", "included": True, "date": "fout", "name": "", "activity_type": "Run"}]
        errs = schema_core.validate_rows("ATL", rows)
        assert any("datum" in e.lower() for e in errs) and any("naam" in e.lower() for e in errs)

    def test_negatieve_waarde_blokkeert(self):
        rows = [{"id": "a", "included": True, "date": "2026-09-01", "name": "x", "activity_type": "Run", "planned_km": -5}]
        assert any("negatieve" in e.lower() for e in schema_core.validate_rows("ATL", rows))

    def test_geen_atleet_blokkeert(self):
        assert any("atleet" in e.lower() for e in schema_core.validate_rows("", _rows()))


class TestPublishPreview:
    def _fs(self, monkeypatch, bestaand):
        import fs_client as FS
        monkeypatch.setattr(FS, "get_planned_workouts_from", lambda k, d: bestaand)

    def test_excluded_nooit_in_payload_en_dupclassificatie(self, monkeypatch):
        self._fs(monkeypatch, [{"date": "2026-09-01", "name": "Duurloop", "key": "w1"},
                               {"date": "2026-09-03", "name": "Iets anders", "key": "w2"}])
        pv = schema_core.publish_preview("ATL", {"zone_type": "tempo"}, _rows())
        ids = {i["id"]: i["status"] for i in pv["items"]}
        assert "r1" not in ids                                   # excluded nooit meegestuurd
        assert ids["r0"] == "mogelijk_duplicaat"                 # zelfde datum + naam
        assert ids["r2"] == "bestaande_op_datum"                 # zelfde datum, andere naam
        assert pv["counts"]["included"] == 2 and pv["counts"]["excluded"] == 1
        assert pv["counts"]["edited"] == 1 and pv["counts"]["conflicts"] == 2

    def test_vrije_datum_is_nieuw(self, monkeypatch):
        self._fs(monkeypatch, [])
        pv = schema_core.publish_preview("ATL", {"zone_type": "tempo"}, _rows())
        assert all(i["status"] == "nieuw" for i in pv["items"]) and pv["counts"]["conflicts"] == 0

    def test_invalid_preview_geen_write_mogelijk(self, monkeypatch):
        self._fs(monkeypatch, [])
        rows = [{"id": "a", "included": True, "date": "2026-09-01", "name": "", "activity_type": "Run"}]
        pv = schema_core.publish_preview("ATL", {}, rows)
        assert pv["valid"] is False and pv["errors"]


class TestPublishWrite:
    def setup_method(self):
        schema_core._WRITE_RECEIPTS.clear()

    def _patch_import(self, monkeypatch, faildict=None, builderfail=None):
        import schema_builder as SB
        self.calls = []
        faildict = faildict or {}
        builderfail = builderfail or set()
        def fake(athlete_key, workouts, zone_type, fill_builder, op_tijd):
            w = workouts[0]; self.calls.append(w["name"])
            if w["name"] in faildict:
                return (0, [f'{w["date"]} {w["name"]}: {faildict[w["name"]]}'], [])
            if w["name"] in builderfail:
                return (1, [], [f'{w["date"]} {w["name"]} (builder): boom'])
            return (1, [], [])
        monkeypatch.setattr(SB, "import_to_finalsurge", fake)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: {})

    def test_volledig_succes(self, monkeypatch):
        self._patch_import(monkeypatch)
        res = schema_core.publish("ATL", {"zone_type": "tempo"}, _rows(), "w1")
        assert res["state"] == "success" and res["counts"]["success"] == 2
        assert "Interval" not in self.calls                     # excluded nooit geschreven

    def test_partial_failure(self, monkeypatch):
        self._patch_import(monkeypatch, faildict={"Kracht": "500"})
        res = schema_core.publish("ATL", {"zone_type": "tempo"}, _rows(), "w2")
        assert res["state"] == "partial_failure"
        assert res["counts"]["success"] == 1 and res["counts"]["failed"] == 1

    def test_retry_alleen_mislukte(self, monkeypatch):
        self._patch_import(monkeypatch, faildict={"Kracht": "500"})
        schema_core.publish("ATL", {"zone_type": "tempo"}, _rows(), "w3")
        self.calls.clear()
        schema_core.publish("ATL", {"zone_type": "tempo"}, _rows(), "w3")   # zelfde write_id
        assert self.calls == ["Kracht"]                         # Duurloop (succes) nooit opnieuw

    def test_builder_failure_apart_en_niet_dubbel_aanmaken(self, monkeypatch):
        self._patch_import(monkeypatch, builderfail={"Duurloop"})
        res = schema_core.publish("ATL", {"zone_type": "tempo"}, _rows(), "w4")
        by = {r["id"]: r["status"] for r in res["results"]}
        assert by["r0"] == "builder_failed" and res["counts"]["builder_failed"] == 1
        assert res["state"] == "success"                        # workout is aangemaakt → geen 'failed'
        self.calls.clear()
        schema_core.publish("ATL", {"zone_type": "tempo"}, _rows(), "w4")
        assert "Duurloop" not in self.calls                     # nooit opnieuw aanmaken

    def test_lege_selectie_weigert_write(self, monkeypatch):
        self._patch_import(monkeypatch)
        import pytest
        rows = [{"id": "a", "included": False, "date": "2026-09-01", "name": "x", "activity_type": "Run"}]
        with pytest.raises(ValueError):
            schema_core.publish("ATL", {}, rows, "w5")


class TestSlice3Guards:
    def _app_js(self):
        with open(os.path.join(_ROOT, "pwa", "static", "app.js"), encoding="utf-8") as f:
            return f.read()

    def test_geen_confirm_als_enige_beveiliging(self):
        # De publish-flow gebruikt een expliciete preview + CTA, geen browser confirm().
        js = self._app_js()
        assert "sbPublishPreview" in js and "publish/preview" in js
        assert "Publiceer " in js                                # expliciete CTA met aantal

    def test_write_alleen_via_publish_endpoint(self):
        js = self._app_js()
        assert 'jpost("/api/schema/publish"' in js               # nieuwe write
        assert 'jpost("/api/schema/push"' not in js              # geen legacy write-CTA

    def test_generatietekst_geen_vaste_belofte(self):
        assert "20–40s" not in self._app_js()
