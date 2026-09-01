"""Feedback P0 — true hot-read + LKG-preserving refresh (build-contract §Tests backend).

Bewijst de harde invarianten van de terminating-startup/hot-read-fix:

  1. HOT read = 0 externe I/O: met een geldig `_QUEUE_MEM` (+ gehydrateerde skip-mirror)
     maakt `queue(refresh=False)` GEEN GitHub- of FinalSurge-call. Alle externe seams
     zijn gemonkeypatcht om te GOOIEN als ze toch geraakt worden.
  2. Skip reconcilieert direct in het geheugen: ná `overslaan()` sluit de volgende
     non-refresh read het item uit ZONDER `load_skipped()` (GitHub) te lezen.
  3. Durable-restore + in-memory skip: prewarm herstelt queue + skip-state; de eerste
     non-refresh read is daarna extern-I/O-vrij.
  4. Achtergrond-refresh-fout behoudt de LKG: bij een FinalSurge-sweepfout blijft de
     publieke queue de oude geldige items houden en markeert `verouderd`.

    python3 -m pytest tests/test_feedback_p0_hotread.py -q
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


def _wk(wid):
    return {"workout_key": wid, "athlete_key": "A", "athlete_name": "Lisa",
            "workout_name": "Duurloop", "workout_date": "2026-08-12", "workout_type": "run",
            "post_notes": "", "felt": "", "effort": "", "thread": []}


def _snap(ids):
    volle = {i: _wk(i) for i in ids}
    items = [FC._queue_item(i, volle[i]) for i in ids]
    return {"fs": True, "items": items, "gepost": 0, "berekend": date.today().isoformat(),
            "datum": date.today().isoformat(), "_volle": volle}


def _boom(*a, **k):
    raise AssertionError("externe I/O geraakt op de hot read")


@pytest.fixture
def hot(monkeypatch):
    monkeypatch.setattr(FC, "heeft_token", lambda: True)
    monkeypatch.setattr(FC, "_home_invalidate_feedback", lambda: None)
    FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    yield monkeypatch
    FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None


class TestHotReadZeroIO:
    def test_1_geldig_mem_geen_externe_call(self, hot):
        FC._QUEUE_MEM = _snap(["W1", "W2"])
        FC._SKIP_MEM = {}                                 # gehydrateerd (zoals na prewarm)
        # ELKE externe seam gooit als 'ie geraakt wordt:
        hot.setattr(intake_store, "load_skipped", _boom)
        hot.setattr(intake_store, "load_feedback_queue", _boom)
        hot.setattr(FC.FS, "get_workouts_needing_feedback", _boom, raising=False)
        hot.setattr(FC.FS, "get_athletes", _boom, raising=False)
        hot.setattr(FC.FS, "get_workouts_deduped", _boom, raising=False)
        r = FC.queue(refresh=False)                       # mag NIETS extern raken
        assert r["cached"] is True and r["diag"]["bron"] == "mem"
        assert [i["id"] for i in r["items"]] == ["W1", "W2"]

    def test_2_skip_reconcilieert_in_memory_zonder_githubread(self, hot, tmp_path):
        # overslaan gebruikt de lokale (token-loze) store; dat is het write-pad.
        hot.setattr(intake_store, "_gh_token", lambda: "")
        hot.setattr(intake_store, "_SKIPPED_LOCAL", str(tmp_path / "skipped.json"), raising=False)
        FC._QUEUE_MEM = _snap(["W1", "W2"])
        FC._SKIP_MEM = {}
        FC._cache["W1"] = _wk("W1"); FC._cache["W2"] = _wk("W2")
        assert FC.overslaan("W1") is True                 # write-pad: store + mirror bijgewerkt
        hot.setattr(intake_store, "load_skipped", _boom)  # hot read mag dit NIET aanroepen
        r = FC.queue(refresh=False)
        assert [i["id"] for i in r["items"]] == ["W2"]    # W1 direct weg (in-memory skip)

    def test_3_prewarm_restore_dan_hot_read_io_vrij(self, hot):
        # koud proces: durable + skip komen één keer binnen via prewarm (hydratatie).
        hot.setattr(intake_store, "load_feedback_queue", lambda: _snap(["W1", "W2"]))
        hot.setattr(intake_store, "load_skipped", lambda: {"W1": {"athlete_ts": ""}})
        hot.setattr(intake_store, "last_feedback_queue_source", lambda: "github", raising=False)
        info = FC.prewarm_queue()
        assert info["ok"] is True
        # nu ALLE externe reads laten gooien → de eerste non-refresh read blijft I/O-vrij
        hot.setattr(intake_store, "load_feedback_queue", _boom)
        hot.setattr(intake_store, "load_skipped", _boom)
        r = FC.queue(refresh=False)
        assert [i["id"] for i in r["items"]] == ["W2"]    # W1 gefilterd via de gehydrateerde skip
        assert r["diag"]["bron"] == "mem"


class TestRefreshFailurePreservesLKG:
    def test_4_sweepfout_behoudt_oude_items_en_markeert(self, hot):
        FC._QUEUE_MEM = _snap(["A", "B"])                 # geldige oude LKG
        def sweep_boom(*a, **k):
            raise RuntimeError("FinalSurge down")
        hot.setattr(FC.FS, "get_workouts_needing_feedback", sweep_boom, raising=False)
        r = FC.queue(refresh=True)
        assert [i["id"] for i in r["items"]] == ["A", "B"]  # LKG behouden (nooit geblankt)
        assert r.get("verouderd") is True                   # refresh-falen gemarkeerd
