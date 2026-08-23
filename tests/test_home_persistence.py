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

    def test_severity_bump_binnen_tier_blijft_verborgen(self, monkeypatch):
        # Class 1 (inversie): een louter NUMERIEKE severity-bump binnen dezelfde tier
        # (compliance: 'n gemist' loopt op, tier blijft 'actie', bv. na een weekend) mag een
        # afgehandelde atleet NIET terugbrengen. Anders keert na elke sweep vrijwel iedereen
        # terug. Record heeft geen 'tier' (of gelijke tier) → venster telt → verborgen.
        morgen = (date.today() + timedelta(days=1)).isoformat()
        self._patch(monkeypatch, {"A|compliance": _handled_rec("gezien", 2, morgen)})
        out = home_core._apply_handled_overlay(_snapshot())
        assert "A" not in [i["user_key"] for i in out["prioriteit"]]   # blijft gedempt

    def test_echte_tier_escalatie_toont_opnieuw(self, monkeypatch):
        # Alleen een KWALITATIEF zwaarder signaal (tier aandacht → actie) doorbreekt het
        # venster. Bram's schema is afgehandeld op tier 'aandacht'; het huidige signaal is nu
        # 'actie' (schema verlopen) → terecht opnieuw tonen.
        morgen = (date.today() + timedelta(days=1)).isoformat()
        rec = {"status": "gezien", "severity": 1, "tier": "aandacht", "tot": morgen,
               "handled_at": date.today().isoformat()}
        snap = _snapshot()
        snap["prioriteit"][1]["signalen"][0]["tier"] = "actie"     # Bram's schema geëscaleerd
        self._patch(monkeypatch, {"B|schema": rec})
        out = home_core._apply_handled_overlay(snap)
        assert "B" in [i["user_key"] for i in out["prioriteit"]]   # echte escalatie → terug

    def test_gelijke_tier_binnen_venster_blijft_verborgen(self, monkeypatch):
        # Record MÉT tier, huidige tier gelijk → geen escalatie → venster telt → verborgen.
        morgen = (date.today() + timedelta(days=1)).isoformat()
        rec = {"status": "gezien", "severity": 3, "tier": "actie", "tot": morgen,
               "handled_at": date.today().isoformat()}
        self._patch(monkeypatch, {"A|compliance": rec})
        out = home_core._apply_handled_overlay(_snapshot())
        assert "A" not in [i["user_key"] for i in out["prioriteit"]]

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
