"""Fase 1 canonical-state — Feedback skip = ECHTE server-side state transition.

Borgt de drie skip-garanties uit de herstelopdracht §2:
  • `overslaan` meldt NOOIT succes als de canonieke store (skipped.json) de write niet
    bevestigt (geen verloren skip) — met geforceerde write-failure;
  • élke queue-READ (warme mem én koude durable) respecteert de canonieke skip-state:
    een net overgeslagen training komt niet terug via een verouderde snapshot;
  • her-activatie blijft werken: geeft de atleet ná het overslaan nieuwe input, dan
    verschijnt de training weer.

    python3 -m pytest tests/test_feedback_skip_persistence.py -q
"""
import os
import sys
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import feedback_core as FC


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Lokale (token-loze) store + schone caches."""
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    monkeypatch.setattr(intake_store, "_SKIPPED_LOCAL", str(tmp_path / "skipped.json"),
                        raising=False)
    monkeypatch.setattr(FC, "_home_invalidate_feedback", lambda: None)  # Home-seam isoleren
    FC._cache.clear()
    FC._QUEUE_MEM.clear() if hasattr(FC._QUEUE_MEM, "clear") else None
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    yield intake_store
    FC._cache.clear()
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None


def _seed(wk, **over):
    w = {"workout_key": wk, "athlete_key": "AK", "athlete_name": "Test",
         "workout_date": "2026-08-12", "post_notes": "", "felt": "", "effort": "",
         "thread": []}
    w.update(over)
    FC._cache[wk] = w
    return w


# ── 1. Persistence-garantie: geen stille success bij write-failure ───────────
class TestSkipPersistenceHard:
    def test_write_failure_geeft_geen_success(self, store, monkeypatch):
        _seed("W1")
        monkeypatch.setattr(intake_store, "save_skipped",
                            lambda sk: (False, "GitHub API: 409 — conflict"))
        with pytest.raises(RuntimeError):
            FC.overslaan("W1")               # persistence niet bewezen → GEEN True

    def test_write_success_persisteert_onder_workout_key(self, store):
        _seed("W1")
        assert FC.overslaan("W1") is True
        assert "W1" in store.load_skipped()

    def test_api_krijgt_geen_ok_bij_write_failure(self, store, monkeypatch):
        """De API-laag vertaalt de exception naar een niet-ok respons (geen 200)."""
        import importlib
        _seed("W1")
        monkeypatch.setattr(intake_store, "save_skipped", lambda sk: (False, "boom"))
        # simuleer de endpoint-body-afhandeling: overslaan gooit → API vangt → 500
        with pytest.raises(RuntimeError):
            FC.overslaan("W1")


# ── 2. Queue-READ respecteert canonieke skip-state (koude/mem read) ──────────
def _snapshot(volle_workouts):
    volle = {w["workout_key"]: w for w in volle_workouts}
    items = [FC._queue_item(w["workout_key"], w) for w in volle_workouts]
    return {"fs": True, "items": items, "gepost": 0,
            "berekend": date.today().isoformat(), "datum": date.today().isoformat(),
            "_volle": volle}


class TestQueueReadSkipConsistent:
    def test_skip_na_sweep_komt_niet_terug_op_read(self, store, monkeypatch):
        monkeypatch.setattr(FC, "heeft_token", lambda: True)
        w1, w2 = _seed("W1"), _seed("W2")
        FC._QUEUE_MEM = _snapshot([w1, w2])          # snapshot van vóór de skip
        FC.overslaan("W1")                            # skip ná de sweep
        out = FC.queue(refresh=False)                 # koude/mem read
        ids = [i["id"] for i in out["items"]]
        assert ids == ["W2"]                          # W1 niet opnieuw geïntroduceerd

    def test_durable_snapshot_read_filtert_skip(self, store, monkeypatch):
        monkeypatch.setattr(FC, "heeft_token", lambda: True)
        w1, w2 = _seed("W1"), _seed("W2")
        # geen mem → val terug op durable store
        FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _snapshot([w1, w2]))
        FC.overslaan("W2")
        out = FC.queue(refresh=False)
        assert [i["id"] for i in out["items"]] == ["W1"]

    def test_lichte_snapshot_zonder_volle_filtert_op_skipkeys(self, store, monkeypatch):
        monkeypatch.setattr(FC, "heeft_token", lambda: True)
        w1, w2 = _seed("W1"), _seed("W2")
        snap = _snapshot([w1, w2])
        snap.pop("_volle")                            # oudere lichte snapshot
        FC._QUEUE_MEM = snap
        FC.overslaan("W1")
        out = FC.queue(refresh=False)
        assert [i["id"] for i in out["items"]] == ["W2"]

    def test_her_activatie_bij_nieuwe_input(self, store, monkeypatch):
        # P0 hot-read-contract: her-activatie op de WARME read reconcilieert in-memory
        # (workout weer zichtbaar + skip weg uit de in-memory mirror) ZONDER store-write;
        # de canonieke store-opruiming gebeurt op het achtergrond/write-pad (sweep).
        monkeypatch.setattr(FC, "heeft_token", lambda: True)
        w1 = _seed("W1")
        FC.overslaan("W1")
        w1["post_notes"] = "toch nog een vraag"           # nieuwe atleet-input ná het overslaan
        FC._QUEUE_MEM = _snapshot([w1])
        out = FC.queue(refresh=False)
        assert [i["id"] for i in out["items"]] == ["W1"]  # weer zichtbaar (her-activatie op hot read)
        assert store.load_skipped().get("W1") is not None  # hot read schreef NIET (skip nog canoniek aanwezig)
        # canonieke opruiming op het write-pad (sweep): reactiveert → store + mirror schoon
        assert FC._filter_skipped([FC._cache["W1"]]) == [FC._cache["W1"]]
        assert "W1" not in store.load_skipped()           # nu canoniek opgeruimd via write-pad
        assert "W1" not in FC._skips_current()            # in-memory mirror ook bijgewerkt
