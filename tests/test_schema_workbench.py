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
