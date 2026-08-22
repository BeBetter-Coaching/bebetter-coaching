"""Fase 1 canonical-state — Feedback-actie → Home freshness via SNAPSHOT-INVALIDATIE (Q2).

`home_core.invalidate_feedback` is een reconciliation-seam, GEEN tweede teller-truth: het
markeert de Home-snapshot als 'moet revalideren' (`_revalidate`) en muteert NOOIT de
feedback-tellingen. Die komen uitsluitend uit de canonieke `_bereken`-sweep. Deze suite
bewijst de zes gevraagde eigenschappen:
  1. dubbele/retried request → geen dubbeltelling (vlag idempotent, teller onaangeraakt);
  2. failed post/skip → geen delta (seam muteert nooit een teller);
  3. concurrent snapshot-refresh + invalidate → uiteindelijk correcte telling;
  4. koude reload → correct (vlag + telling overleven, sweep reconcilieert);
  5. volgende `_bereken`-sweep convergeert naar exact de sweep-telling (geen residue);
  6. `posted_today`-semantiek = de canonieke sweep.

    python3 -m pytest tests/test_home_feedback_freshness.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import home_core


def _snap(wachten=22, gepost=0, **extra):
    tot = wachten + gepost
    s = {
        "fs": True, "atleten": 30, "groepen": 3,
        "team": {"actie": 0, "aandacht": 0, "rustig": 30},
        "feedback": {"wachten": wachten, "gepost": gepost,
                     "pct": int(gepost / tot * 100) if tot else 100},
        "prioriteit": [], "prioriteit_totaal": 0,
        "berekend": "2026-08-18T09:00:00", "datum": "2026-08-18",
    }
    s.update(extra)
    return s


@pytest.fixture
def home(monkeypatch):
    durable = {"snap": {}}
    monkeypatch.setattr(home_core.intake_store, "load_home_snapshot", lambda: durable["snap"])
    monkeypatch.setattr(home_core.intake_store, "save_home_snapshot",
                        lambda d: (durable.__setitem__("snap", d) or (True, "")))
    monkeypatch.setattr(home_core.intake_store, "load_home_handled", lambda: {})
    monkeypatch.setattr(home_core, "_heeft_token", lambda: True)
    # PF-3: deze suite toetst de invalidate/_bereken-contracten, NIET de feedback-overlay.
    # Isoleer daarom de gedeelde Feedback-queue → geen queue → overlay is een no-op, dus de
    # feedbacktelling volgt hier zuiver de snapshot/_bereken-waarde (bestaande semantiek).
    import feedback_core as _fc
    monkeypatch.setattr(_fc, "feedback_open_truth", lambda: None)
    home_core._MEM = {}
    yield durable
    home_core._MEM = {}


class TestInvalidateIsGeenTeller:
    def test_zet_revalidate_vlag_zonder_teller_te_muteren(self, home):
        home_core._MEM = _snap(wachten=22, gepost=0)
        home_core.invalidate_feedback()
        assert home_core._MEM["_revalidate"] is True
        assert home_core._MEM["feedback"] == {"wachten": 22, "gepost": 0, "pct": 0}  # ONgemuteerd

    def test_1_dubbele_retried_request_geen_dubbeltelling(self, home):
        home_core._MEM = _snap(wachten=22, gepost=3)
        for _ in range(5):                                # 5× retry van dezelfde actie
            home_core.invalidate_feedback()
        assert home_core._MEM["feedback"]["wachten"] == 22   # geen enkele decrement
        assert home_core._MEM["feedback"]["gepost"] == 3

    def test_2_seam_muteert_nooit_een_teller(self, home):
        # ongeacht hoe vaak/aangeroepen: de tellingen blijven exact de snapshotwaarde
        home_core._MEM = _snap(wachten=10, gepost=7)
        vóór = dict(home_core._MEM["feedback"])
        home_core.invalidate_feedback()
        assert home_core._MEM["feedback"] == vóór

    def test_geen_snapshot_is_noop(self, home):
        home_core._MEM = {}
        home_core.invalidate_feedback()
        assert not home_core._valid(home_core._MEM)       # niets verzonnen

    def test_persisteert_vlag_durable(self, home):
        home_core._MEM = _snap(wachten=5)
        home_core.invalidate_feedback()
        assert home["snap"].get("_revalidate") is True    # overleeft restart/reload


class TestConvergentieNaarCanoniekeSweep:
    def _mock_bereken(self, monkeypatch, fresh):
        monkeypatch.setattr(home_core, "_bereken", lambda: fresh)

    def test_5_volgende_bereken_convergeert_exact(self, home, monkeypatch):
        # stale snapshot + invalidate; daarna de echte sweep → exact de sweep-telling
        home_core._MEM = _snap(wachten=22, gepost=0)
        home_core.invalidate_feedback()
        self._mock_bereken(monkeypatch, _snap(wachten=4, gepost=18))
        out = home_core.cockpit(refresh=True)
        assert out["feedback"] == {"wachten": 4, "gepost": 18, "pct": 81}
        assert "_revalidate" not in out                   # vlag geschoond door de sweep

    def test_6_posted_today_is_sweep_semantiek(self, home, monkeypatch):
        # gepost komt uitsluitend uit de sweep (posted_today), niet uit een seam-teller
        home_core._MEM = _snap(wachten=22, gepost=0)
        home_core.invalidate_feedback()
        self._mock_bereken(monkeypatch, _snap(wachten=0, gepost=22))
        out = home_core.cockpit(refresh=True)
        assert out["feedback"]["gepost"] == 22 and out["feedback"]["pct"] == 100

    def test_3_concurrent_refresh_dan_invalidate_telling_correct(self, home, monkeypatch):
        # refresh schrijft verse telling; een daarná binnenkomende invalidate mag die
        # NIET corrumperen — hij herflagt hooguit (→ één extra onschadelijke refresh).
        home_core._MEM = _snap(wachten=22, gepost=0)
        self._mock_bereken(monkeypatch, _snap(wachten=4, gepost=18))
        home_core.cockpit(refresh=True)                   # verse sweep persisteert
        home_core.invalidate_feedback()                   # concurrent/late invalidate
        assert home_core._MEM["feedback"] == {"wachten": 4, "gepost": 18, "pct": 81}  # intact
        assert home_core._MEM.get("_revalidate") is True  # hooguit één extra refresh

    def test_4_koude_reload_telling_intact_en_reconcilieert(self, home, monkeypatch):
        home_core._MEM = _snap(wachten=9, gepost=1)
        home_core.invalidate_feedback()
        home_core._MEM = {}                               # koude start: leeg proces-geheugen
        koud = home_core.cockpit(refresh=False)           # leest durable
        assert koud["feedback"] == {"wachten": 9, "gepost": 1, "pct": 10}  # niet gecorrumpeerd
        assert koud.get("_revalidate") is True            # client zal reval-refresh triggeren
        # de reval-refresh levert de canonieke telling
        self._mock_bereken(monkeypatch, _snap(wachten=8, gepost=2))
        vers = home_core.cockpit(refresh=True)
        assert vers["feedback"] == {"wachten": 8, "gepost": 2, "pct": 20}
