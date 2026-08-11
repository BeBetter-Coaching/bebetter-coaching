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
