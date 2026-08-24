"""Class 1 — Feedback-actie → Home freshness ZONDER geforceerde sweep (ex-PF-3 latency).

Onder PF-3 zette een post/skip `_revalidate` op de Home-snapshot, wat de client dwong tot een
volledige `_bereken`-sweep (~20-25s) alleen om de feedbacktegel te corrigeren. Class 1
ontkoppelt dat: de tegel wordt op ELKE Home-read canoniek uit de gedeelde open-set afgeleid
(`_apply_feedback_overlay` → `feedback_core.canonical_open_actions`). Deze suite bewijst:
  1. `invalidate_feedback` is een veilige no-op: muteert nooit een teller, zet geen
     `_revalidate`, forceert geen sweep;
  2. de fast-read corrigeert de tegel canoniek (FRESH) zonder `_bereken`;
  3. een koude/UNKNOWN open-set toont NOOIT de bevroren integer (stale), maar op een
     refresh-read blijft de zojuist verse `_bereken`-telling staan;
  4. `posted_today`-semantiek volgt de sweep.

    python3 -m pytest tests/test_home_feedback_freshness.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import home_core
import feedback_core as FC


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


def _fresh(wachten, gepost=0):
    """Stub voor de canonieke open-set (FRESH)."""
    tot = wachten + gepost
    return {"status": FC.OPEN_FRESH, "wachten": wachten, "gepost": gepost,
            "pct": int(gepost / tot * 100) if tot else 100,
            "open_ids": [f"W{i}" for i in range(wachten)]}


def _unknown():
    return {"status": FC.OPEN_UNKNOWN, "wachten": None, "gepost": None,
            "pct": None, "open_ids": None}


@pytest.fixture
def home(monkeypatch):
    durable = {"snap": {}}
    monkeypatch.setattr(home_core.intake_store, "load_home_snapshot", lambda: durable["snap"])
    monkeypatch.setattr(home_core.intake_store, "save_home_snapshot",
                        lambda d: (durable.__setitem__("snap", d) or (True, "")))
    monkeypatch.setattr(home_core.intake_store, "load_home_handled", lambda: {})
    monkeypatch.setattr(home_core, "_heeft_token", lambda: True)
    # Deze suite stuurt de open-set expliciet via een stub op de canonieke reconciler.
    monkeypatch.setattr(FC, "canonical_open_actions", lambda: _unknown())
    home_core._MEM = {}
    yield {"durable": durable, "monkeypatch": monkeypatch}
    home_core._MEM = {}


class TestInvalidateIsVeiligeNoop:
    def test_zet_geen_revalidate_en_muteert_geen_teller(self, home):
        home_core._MEM = _snap(wachten=22, gepost=0)
        home_core.invalidate_feedback()
        assert "_revalidate" not in home_core._MEM               # geen geforceerde sweep-vlag
        assert home_core._MEM["feedback"] == {"wachten": 22, "gepost": 0, "pct": 0}  # ONgemuteerd

    def test_dubbele_retried_request_geen_dubbeltelling(self, home):
        home_core._MEM = _snap(wachten=22, gepost=3)
        for _ in range(5):
            home_core.invalidate_feedback()
        assert home_core._MEM["feedback"]["wachten"] == 22       # geen enkele decrement
        assert home_core._MEM["feedback"]["gepost"] == 3

    def test_geen_snapshot_is_veilig(self, home):
        home_core._MEM = {}
        home_core.invalidate_feedback()
        assert not home_core._valid(home_core._MEM)              # niets verzonnen


class TestFastReadCorrigeertZonderSweep:
    def test_fast_read_fresh_zonder_bereken(self, home, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(home_core, "_bereken", lambda: calls.__setitem__("n", calls["n"] + 1) or {})
        home_core._MEM = _snap(wachten=22, gepost=0)             # bevroren 22
        monkeypatch.setattr(FC, "canonical_open_actions", lambda: _fresh(4, 18))
        out = home_core.cockpit(refresh=False)
        assert out["feedback"]["wachten"] == 4 and out["feedback"]["gepost"] == 18
        assert out["feedback"]["stale"] is False
        assert calls["n"] == 0                                    # GEEN sweep voor de teller

    def test_koude_unknown_toont_geen_bevroren_integer(self, home):
        home_core._MEM = _snap(wachten=22, gepost=0)             # bevroren 22
        # canonical_open_actions is by-default UNKNOWN in de fixture
        out = home_core.cockpit(refresh=False)
        assert out["feedback"]["stale"] is True
        assert out["feedback"]["wachten"] is None                # geen valse precisie, geen 22


class TestRefreshHoudtVerseSweepwaarde:
    def test_refresh_unknown_behoudt_verse_bereken_telling(self, home, monkeypatch):
        # Op een refresh is de zojuist door _bereken berekende telling legitiem actueel →
        # allow_stale=False laat die staan (geen valse 'bijwerken…').
        home_core._MEM = _snap(wachten=22, gepost=0)
        monkeypatch.setattr(home_core, "_bereken", lambda: _snap(wachten=4, gepost=18))
        out = home_core.cockpit(refresh=True)
        assert out["feedback"]["wachten"] == 4 and out["feedback"]["gepost"] == 18
        assert out["feedback"].get("stale") is not True          # verse sweep, niet stale
        assert "_revalidate" not in out

    def test_refresh_fresh_neemt_open_set_over(self, home, monkeypatch):
        home_core._MEM = _snap(wachten=22, gepost=0)
        monkeypatch.setattr(home_core, "_bereken", lambda: _snap(wachten=9, gepost=0))
        monkeypatch.setattr(FC, "canonical_open_actions", lambda: _fresh(2, 20))
        out = home_core.cockpit(refresh=True)
        assert out["feedback"]["wachten"] == 2 and out["feedback"]["gepost"] == 20   # open-set leidend

    def test_posted_today_is_sweep_semantiek(self, home, monkeypatch):
        home_core._MEM = _snap(wachten=22, gepost=0)
        monkeypatch.setattr(home_core, "_bereken", lambda: _snap(wachten=0, gepost=22))
        out = home_core.cockpit(refresh=True)
        assert out["feedback"]["gepost"] == 22 and out["feedback"]["pct"] == 100
