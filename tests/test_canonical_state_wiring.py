"""Fase 1 canonical-state — bewijs dat de invalidatie-seam ÉCHT bedraad is (Q2).

Integratie (geen source-grep): een bevestigde post/skip roept de Home-invalidatie-seam
precies één keer aan; een gefaalde skip roept 'm niet aan. Plus front-endgaranties die
alleen in een echte browser draaien (server-invalidatie triggert de refresh; de
feedbacktegel convergeert naar de canonieke sweep).

    python3 -m pytest tests/test_canonical_state_wiring.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import feedback_core as FC


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    monkeypatch.setattr(intake_store, "_SKIPPED_LOCAL", str(tmp_path / "skipped.json"),
                        raising=False)
    FC._cache.clear()
    calls = []
    monkeypatch.setattr(FC, "_home_invalidate_feedback", lambda: calls.append(1))
    yield calls
    FC._cache.clear()


def _seed(wk):
    FC._cache[wk] = {"workout_key": wk, "athlete_key": "AK", "athlete_name": "Test",
                     "workout_date": "2026-08-12", "post_notes": "", "felt": "",
                     "effort": "", "thread": []}


class TestSeamBedraad:
    def test_skip_roept_invalidatie_precies_eenmaal(self, env):
        _seed("W1")
        FC.overslaan("W1")
        assert env == [1]                                 # één invalidatie (geen delta)

    def test_skip_faalt_geen_invalidatie(self, env, monkeypatch):
        _seed("W1")
        monkeypatch.setattr(intake_store, "save_skipped", lambda sk: (False, "boom"))
        with pytest.raises(RuntimeError):
            FC.overslaan("W1")
        assert env == []                                  # geen seam op verloren skip

    def test_post_roept_invalidatie_precies_eenmaal(self, env, monkeypatch):
        import fs_client
        _seed("W1")
        monkeypatch.setattr(fs_client, "post_comment", lambda **kw: True, raising=False)
        monkeypatch.setattr(fs_client, "get_athletes", lambda: [], raising=False)
        assert FC.plaats("W1", "netjes gelopen") is True
        assert env == [1]


class TestClientInvalidatie:
    """Client: server-invalidatie triggert de refresh; de tegel convergeert; homeFbDelta
    is enkel transiënt (gereset op een autoritatieve read), geen tweede waarheid."""

    def _src(self):
        return open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

    def test_tegel_uit_canonieke_fastread_geen_geforceerde_sweep(self):
        # Class 1: de tegel corrigeert op de FAST-READ (overlay → open-set); cockpitStale
        # forceert GEEN sweep meer op een feedback-post/skip (`_revalidate` retired).
        src = self._src()
        assert "s._revalidate" not in src                 # geen geforceerde sweep-seam meer
        assert "renderFeedbackStrip(s.feedback, true)" in src  # tegel uit de fast-read

    def test_tegel_convergeert_op_achtergrondrefresh(self):
        src = self._src()
        assert "renderFeedbackStrip(fresh.feedback" in src  # ook in diff-modus naar sweep

    def test_delta_is_transient_reset_op_fresh(self):
        src = self._src()
        assert "if (fresh) homeFbDelta" in src             # optimisme verrekend bij fresh read

    def test_terugkeer_naar_home_herleest_stats(self):
        """Navigation-freshness seam: bij terugkeer naar een al-opgebouwde Home (in-app nav,
        geen browserrefresh) her-leest renderHome de snapshot en rendert de tegel DIRECT uit
        de canonieke fast-read (Class 1), zonder de trage Home-sweep te forceren. cockpitVersen
        blijft enkel voor prioriteit-staleness."""
        src = self._src()
        assert "renderFeedbackStrip(s.feedback, true)" in src
        assert "if (s.feedback && s.feedback.stale) feedbackQueueWarm()" in src

    def test_nieuw_badge_diff_is_autoritatief_niet_dom(self):
        # Class 1 (punt 6): "N nieuw" diff tegen de laatst toegepaste autoritatieve set
        # (lastPrioSig), niet tegen de toevallige DOM-state.
        src = self._src()
        assert "lastPrioSig" in src
        assert "$$(\"#home-prio .prio-item\").forEach(el => huidig" not in src   # geen DOM-diff meer
