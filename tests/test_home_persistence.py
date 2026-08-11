"""Regressietests voor de Home-persistentiebug (acceptance 11 aug 2026):
een afgehandeld signaal (Gezien/Later) moet ook na refresh/cold read verborgen
blijven. De oorzaak was dat het leespad de duurzame home_handled-store niet
opnieuw toepaste op een (verouderde) snapshot. `_apply_handled_overlay` doet dat nu.

Draaien met:  python3 -m pytest tests/ -q
"""

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import home_core


def _snapshot():
    """Een 'koude' snapshot zoals uit de durable store: nog NIET gedempt.
    Twee atleten: A met compliance (actie), B met schema-aandacht."""
    return {
        "fs": True, "atleten": 5, "groepen": 2,
        "team": {"actie": 1, "aandacht": 1, "rustig": 3},
        "prioriteit": [
            {"user_key": "A", "naam": "Anna", "voornaam": "Anna", "tier": "actie",
             "n_signalen": 1, "reden": "3 van 5 trainingen gemist",
             "signalen": [{"soort": "compliance", "tier": "actie", "reden": "3 van 5 gemist",
                           "kort": "3 gemist", "fingerprint": "c3", "severity": 3, "detail": {}, "context": []}]},
            {"user_key": "B", "naam": "Bram", "voornaam": "Bram", "tier": "aandacht",
             "n_signalen": 1, "reden": "schema loopt af over 3 dagen",
             "signalen": [{"soort": "schema", "tier": "aandacht", "reden": "schema nog 3d",
                           "kort": "schema nog 3d", "fingerprint": "s:a", "severity": 1, "detail": {}, "context": []}]},
        ],
        "prioriteit_totaal": 2,
    }


def _handled_rec(status, severity, tot):
    return {"status": status, "severity": severity, "tot": tot,
            "handled_at": date.today().isoformat()}


class TestHandledOverlay:
    def _patch(self, monkeypatch, store):
        monkeypatch.setattr(home_core.intake_store, "load_home_handled", lambda: store)

    def test_gezien_blijft_verborgen_na_cold_read(self, monkeypatch):
        # Anna's compliance is 'gezien' met venster tot morgen → moet weg uit de lijst.
        morgen = (date.today() + timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 3, morgen)})
        out = home_core._apply_handled_overlay(_snapshot())
        keys = [i["user_key"] for i in out["prioriteit"]]
        assert "A" not in keys and "B" in keys
        assert out["prioriteit_totaal"] == 1

    def test_team_telling_herberekend(self, monkeypatch):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 3, morgen)})
        out = home_core._apply_handled_overlay(_snapshot())
        assert out["team"]["actie"] == 0        # Anna's actie gedempt
        assert out["team"]["aandacht"] == 1     # Bram blijft
        assert out["team"]["rustig"] == 4       # 5 - 0 - 1

    def test_alles_afgehandeld_leegt_de_lijst(self, monkeypatch):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {
            "A|compliance": _handled_rec("gezien", 3, morgen),
            "B|schema": _handled_rec("later", 1, morgen),
        })
        out = home_core._apply_handled_overlay(_snapshot())
        assert out["prioriteit"] == []
        assert out["team"] == {"actie": 0, "aandacht": 0, "rustig": 5}

    def test_verlopen_venster_komt_terug(self, monkeypatch):
        gisteren = (date.today() - timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 3, gisteren)})
        out = home_core._apply_handled_overlay(_snapshot())
        assert "A" in [i["user_key"] for i in out["prioriteit"]]   # venster voorbij → weer zichtbaar

    def test_escalatie_toont_opnieuw(self, monkeypatch):
        # Gezien bij severity 2, maar het signaal is nu severity 3 (erger) → tonen.
        morgen = (date.today() + timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 2, morgen)})
        out = home_core._apply_handled_overlay(_snapshot())
        assert "A" in [i["user_key"] for i in out["prioriteit"]]

    def test_lege_store_laat_snapshot_ongemoeid(self, monkeypatch):
        self._patch(monkeypatch, {})
        snap = _snapshot()
        out = home_core._apply_handled_overlay(snap)
        assert out is snap                        # geen handled → identiek object terug

    def test_pending_snapshot_ongemoeid(self, monkeypatch):
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 3, "2999-01-01")})
        pending = {"fs": True, "prioriteit": None, "pending": True}
        assert home_core._apply_handled_overlay(pending) is pending

    def test_idempotent_op_al_gedempte_snapshot(self, monkeypatch):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 3, morgen)})
        once = home_core._apply_handled_overlay(_snapshot())
        twice = home_core._apply_handled_overlay(once)
        assert [i["user_key"] for i in once["prioriteit"]] == [i["user_key"] for i in twice["prioriteit"]]
