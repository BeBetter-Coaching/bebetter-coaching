"""Feedback 'Overslaan' — cross-app consistentie PWA ↔ Streamlit (punt A).

De skip-status is één gedeelde bron (skipped.json, gekeyd op workout_key). Deze
tests borgen:
  • PWA `overslaan` schrijft onder workout_key naar de gedeelde store;
  • een verse lezer (zoals Streamlit ná de korte cache-TTL) ziet de skip meteen →
    dezelfde workout is dan óók in Streamlit afgehandeld;
  • andere workouts blijven onaangeraakt; zonder workout_key geen skip.
Plus twee guard-tests tegen het terugvallen van de fix (Streamlit-TTL + PWA
keepalive-flush), want die twee lagen zijn buiten een echte browser/Streamlit-
sessie niet puur uit te voeren.

    python3 -m pytest tests/test_feedback_skip_consistency.py -q
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
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    monkeypatch.setattr(intake_store, "_SKIPPED_LOCAL", str(tmp_path / "skipped.json"),
                        raising=False)
    FC._cache.clear()
    yield intake_store
    FC._cache.clear()


def _seed(wk, **over):
    w = {"workout_key": wk, "athlete_name": "Test", "workout_date": "2026-08-12",
         "post_notes": "", "felt": "", "effort": "", "thread": []}
    w.update(over)
    FC._cache[wk] = w
    return w


class TestSkipGedeeldeBron:
    def test_pwa_skip_schrijft_onder_workout_key(self, store):
        _seed("W1")
        assert FC.overslaan("W1") is True
        sk = store.load_skipped()
        assert "W1" in sk                                 # gekeyd op workout_key
        assert isinstance(sk["W1"], dict)                 # snapshot, geen kale string

    def test_verse_lezer_ziet_skip_meteen(self, store):
        # 'Streamlit' = een onafhankelijke, verse lezer van dezelfde store.
        _seed("W1"); _seed("W2")
        FC.overslaan("W1")
        # PWA-filter (leest elke keer vers)
        overgebleven = FC._filter_skipped([FC._cache["W1"], FC._cache["W2"]])
        assert [w["workout_key"] for w in overgebleven] == ["W2"]
        # verse store-lezing bevat de skip → een verse Streamlit-sessie ziet 'm ook
        assert "W1" in store.load_skipped()

    def test_andere_workouts_onaangeraakt(self, store):
        _seed("W1"); _seed("W2")
        FC.overslaan("W1")
        assert "W2" not in store.load_skipped()

    def test_zonder_workout_key_geen_skip(self, store):
        _seed("W3", workout_key="")
        with pytest.raises(ValueError):
            FC.overslaan("W3")
        assert store.load_skipped() == {}


class TestGuardsTegenRegressie:
    """Borg de twee lagen die alleen in een echte sessie/browser draaien."""

    def test_streamlit_skip_cache_heeft_ttl(self):
        src = open(os.path.join(_ROOT, "main.py")).read()
        assert "_SKIPPED_TTL_S" in src                    # bounded staleness i.p.v. sessie-cache-voor-altijd
        assert "_skipped_cache_ts" in src                 # herlaadt na verval
        # de TTL wordt in _load_skipped gebruikt (herladen bij verval)
        blok = src[src.index("def _load_skipped"):src.index("def _save_skipped")]
        assert "_SKIPPED_TTL_S" in blok and "_skipped_cache_ts" in blok

    def test_pwa_skip_flush_bij_verlaten(self):
        src = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
        assert "fbFlushPendingSkip" in src                # skip niet verloren bij sluiten binnen 5s
        assert "pagehide" in src and "visibilitychange" in src
        assert "keepalive" in src                         # POST overleeft de unload
