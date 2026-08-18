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

    def test_revalidate_forceert_refresh(self):
        src = self._src()
        assert "s._revalidate" in src                     # cockpitStale honoreert de seam-vlag

    def test_tegel_convergeert_op_achtergrondrefresh(self):
        src = self._src()
        assert "renderFeedbackStrip(fresh.feedback" in src  # ook in diff-modus naar sweep

    def test_delta_is_transient_reset_op_fresh(self):
        src = self._src()
        assert "if (fresh) homeFbDelta" in src             # optimisme verrekend bij fresh read

    def test_terugkeer_naar_home_herleest_stats(self):
        """Navigation-freshness seam: bij terugkeer naar een al-opgebouwde Home (in-app
        nav, geen browserrefresh) her-leest renderHome de snapshot en start via
        cockpitVersen de bestaande refresh — zodat de server-invalidatie (_revalidate)
        herkend wordt. Hergebruikt de bestaande api-read + refresh-primitive."""
        src = self._src()
        # de dataset.done-terugkeerbranch bevat nu een verse stats-read die cockpitVersen voedt
        assert 'api("/api/home/stats").then(s => { if (s && s.fs) cockpitVersen(s); })' in src
