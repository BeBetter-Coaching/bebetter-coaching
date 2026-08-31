"""Feedback P0 — laatst-geldige-queue (LKG) startup-repair.

Contract voor de LKG-fix (branch fix/feedback-p0-lkg):

  1. startup-prewarm met geldige durable snapshot → `_QUEUE_MEM` warm, non-fataal;
  2. GitHub-load faalt → geldige lokale mirror wordt gebruikt (bron local_mirror);
  3. GitHub-load slaagt → lokale mirror wordt bijgewerkt (verse LKG);
  4. GitHub-persist slaagt → lokale mirror wordt bijgewerkt;
  5. ongeldige mirror wordt niet gebruikt (→ none);
  6. een geldige LKG wordt NOOIT door leeg vervangen bij een remote-fout;
  7. warme non-refresh read serveert direct de items (bron mem);
  8. eerste item auto-open op de directe LKG gebruikt de SERVER-volgorde (frontend);
  9. single-flight queue-refresh blijft intact.

Feedback-only: de resilience zit in intake_store.load/save_feedback_queue + de mirror
`.feedback_queue.json`, niet in de generieke `_load_json`/`_save_json`.

    python3 -m pytest tests/test_feedback_p0_lkg.py -q
"""
import base64
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import feedback_core as FC

_APP_JS = os.path.join(_ROOT, "pwa", "static", "app.js")


def _snap(items=1, wid="W1"):
    its = [{"id": f"{wid}{i}", "datum": "2026-08-31", "categorie": "reactie",
            "groep": "comfort", "naam": "Lisa", "athlete_ts": ""} for i in range(items)]
    return {"fs": True, "items": its, "_volle": {}, "gepost": 0,
            "berekend": "2026-08-31T08:00:00", "datum": "2026-08-31"}


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            return {}
        enc = base64.b64encode(json.dumps(self._payload).encode("utf-8")).decode("ascii")
        return {"content": enc}


@pytest.fixture
def fq(tmp_path, monkeypatch):
    """Isoleer de Feedback-mirror op een tmp-pad + schone bron-state."""
    monkeypatch.setattr(intake_store, "_FEEDBACK_QUEUE_LOCAL", str(tmp_path / ".fq.json"),
                        raising=False)
    intake_store._LAST_FQ_SOURCE = "none"
    FC._QUEUE_MEM = {}
    FC._cache.clear()
    FC._QREFRESHING = False
    yield tmp_path
    FC._QUEUE_MEM = {}
    FC._cache.clear()
    FC._QREFRESHING = False


def _mirror_path():
    return intake_store._FEEDBACK_QUEUE_LOCAL


# ── intake_store resilience ──────────────────────────────────────────────────
class TestLkgResilience:
    def test_3_github_load_slaagt_ververst_mirror(self, fq, monkeypatch):
        monkeypatch.setattr(intake_store, "_gh_token", lambda: "TOK")
        monkeypatch.setattr(intake_store.requests, "get", lambda *a, **k: _Resp(200, _snap(2)))
        d = intake_store.load_feedback_queue()
        assert intake_store.last_feedback_queue_source() == "github"
        assert len(d["items"]) == 2
        # mirror geschreven met exact deze snapshot
        assert os.path.exists(_mirror_path())
        with open(_mirror_path()) as f:
            assert len(json.load(f)["items"]) == 2

    def test_2_github_faalt_gebruikt_geldige_mirror(self, fq, monkeypatch):
        with open(_mirror_path(), "w") as f:
            json.dump(_snap(3), f)
        monkeypatch.setattr(intake_store, "_gh_token", lambda: "TOK")

        def boom(*a, **k):
            raise TimeoutError("gh timeout")
        monkeypatch.setattr(intake_store.requests, "get", boom)
        d = intake_store.load_feedback_queue()
        assert intake_store.last_feedback_queue_source() == "local_mirror"
        assert len(d["items"]) == 3

    def test_4_persist_slaagt_ververst_mirror(self, fq, monkeypatch):
        monkeypatch.setattr(intake_store, "_save_json", lambda *a, **k: (True, ""))
        ok, err = intake_store.save_feedback_queue(_snap(4))
        assert ok and not err
        with open(_mirror_path()) as f:
            assert len(json.load(f)["items"]) == 4

    def test_5_ongeldige_mirror_niet_gebruikt(self, fq, monkeypatch):
        with open(_mirror_path(), "w") as f:
            f.write('{"fs": true, "items": "NOTALIST"}')       # structureel ongeldig
        monkeypatch.setattr(intake_store, "_gh_token", lambda: "TOK")
        monkeypatch.setattr(intake_store.requests, "get", lambda *a, **k: _Resp(404))
        d = intake_store.load_feedback_queue()
        assert d == {}
        assert intake_store.last_feedback_queue_source() == "none"

    def test_6_geldige_lkg_nooit_naar_leeg_bij_remote_fout(self, fq, monkeypatch):
        with open(_mirror_path(), "w") as f:
            json.dump(_snap(5), f)
        monkeypatch.setattr(intake_store, "_gh_token", lambda: "TOK")
        monkeypatch.setattr(intake_store.requests, "get", lambda *a, **k: _Resp(500))  # remote-fout
        d = intake_store.load_feedback_queue()
        assert len(d["items"]) == 5                             # NIET leeg
        assert intake_store.last_feedback_queue_source() == "local_mirror"


# ── prewarm + warm read ──────────────────────────────────────────────────────
class TestPrewarmAndWarm:
    def test_1_prewarm_met_geldige_durable(self, fq, monkeypatch):
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _snap(6))
        monkeypatch.setattr(intake_store, "last_feedback_queue_source", lambda: "github")
        info = FC.prewarm_queue()
        assert info["ok"] is True and info["items"] == 6
        assert FC._queue_valid(FC._QUEUE_MEM)                   # _QUEUE_MEM is nu warm

    def test_1b_prewarm_non_fataal_bij_read_fout(self, fq, monkeypatch):
        def boom():
            raise RuntimeError("durable stuk")
        monkeypatch.setattr(intake_store, "load_feedback_queue", boom)
        info = FC.prewarm_queue()                               # mag NIET raisen
        assert info["ok"] is False

    def test_7_warm_nonrefresh_serveert_direct_items(self, fq, monkeypatch):
        monkeypatch.setattr(FC.FS, "get_token", lambda: "TOK", raising=False)
        FC._QUEUE_MEM = _snap(3)
        r = FC.queue(refresh=False)
        assert r.get("cached") is True
        assert len(r["items"]) == 3
        assert (r.get("diag") or {}).get("bron") == "mem"

    def test_9_single_flight_geen_tweede_sweep(self, fq, monkeypatch):
        monkeypatch.setattr(FC.FS, "get_token", lambda: "TOK", raising=False)
        called = {"n": 0}
        monkeypatch.setattr(FC.FS, "get_workouts_needing_feedback",
                            lambda *a, **k: (called.__setitem__("n", called["n"] + 1) or ([], {})),
                            raising=False)
        FC._QUEUE_MEM = _snap(2)
        FC._QREFRESHING = True
        r = FC.queue(refresh=True)
        assert r.get("verversen_bezig") is True and called["n"] == 0


# ── frontend bron-contract ───────────────────────────────────────────────────
def _fn_body(src, header):
    i = src.index(header); b = src.index("{", i)
    depth, j = 0, b
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[b:j + 1]
        j += 1
    raise AssertionError("geen body voor " + header)


class TestFrontendAutoOpen:
    def test_8_warm_lkg_auto_opent_eerste_item_serverorde(self):
        with open(_APP_JS, encoding="utf-8") as f:
            src = f.read()
        enter = _fn_body(src, "async function fbEnter(")
        assert "auto_first_warm" in enter
        assert "fbOpen(FB.items[0].id" in enter          # eerste item = server-volgorde
        assert ".sort(" not in enter                     # geen client-resort in het openpad
