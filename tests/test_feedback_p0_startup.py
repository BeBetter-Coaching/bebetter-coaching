"""Feedback P0 — koude-startup mag de UI nooit blokkeren + FinalSurge tail-latency-cap.

Regressiecontract voor de P0-fix (branch fix/feedback-p0-startup):

BACKEND (feedback_core.queue / fs_client-constanten)
  1. non-refresh read zonder snapshot → `pending` ZONDER FinalSurge-sweep
     (zo kan de frontend direct een bruikbare shell renderen i.p.v. wachten);
  2. de read (`refresh=False`) veegt NOOIT; alleen `refresh=True` bouwt de queue
     (SWR: de sweep is een aparte achtergrond-call);
  3. warme/cached read = identiek + server-sortering (datum-first) onaangeroerd;
  4. single-flight: een tweede refresh terwijl er één loopt geeft de cache terug
     (`verversen_bezig`) ZONDER een tweede sweep;
  5. fs_client-constanten volgens het nieuwe contract: _TIMEOUT=(5,12),
     _MAX_WORKERS=16, HTTP-pool pool_connections>=16 & pool_maxsize>=16.

FRONTEND (pwa/static/app.js — geen JS-runner in deze repo, dus bron-contract)
  6. de pending-tak rendert een niet-blokkerende 3-zone wacht-shell
     (`fbRenderColdWaiting` raakt queue-info, #fb-focus én #fb-ctx-col);
  7. `fbEnter` start `fbRefresh()` op de ACHTERGROND (geen `await` binnen fbEnter);
  8. zodra de koude sweep terug is: eerste item volgens server-sortering
     auto-openen (`auto_first_cold`, desktop-gated).

    python3 -m pytest tests/test_feedback_p0_startup.py -q
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import fs_client
import feedback_core as FC

_APP_JS = os.path.join(_ROOT, "pwa", "static", "app.js")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Token aanwezig, lokale lege skip-store, schone process-state."""
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "", raising=False)
    monkeypatch.setattr(intake_store, "_SKIPPED_LOCAL", str(tmp_path / "skipped.json"),
                        raising=False)
    monkeypatch.setattr(FC.FS, "get_token", lambda: "TOKEN", raising=False)
    FC._cache.clear()
    FC._QUEUE_MEM = {}
    FC._QREFRESHING = False
    yield
    FC._cache.clear()
    FC._QUEUE_MEM = {}
    FC._QREFRESHING = False


def _snap(items, volle=None):
    return {"fs": True, "items": items, "_volle": volle or {},
            "gepost": 0, "berekend": "2026-08-31T08:00:00", "datum": "2026-08-31"}


def _item(wid, datum, categorie="reactie", groep="comfort", naam="Lisa", ts=""):
    return {"id": wid, "athlete_key": "A", "naam": naam, "voornaam": naam,
            "datum": datum, "workout": "Duurloop", "categorie": categorie,
            "groep": groep, "groep_label": "Comfort", "athlete_ts": ts}


def _spy_sweep(monkeypatch):
    """Vervang de FinalSurge-sweep door een teller; retourneert (calls, stats-getter)."""
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return [], {"roster_ms": 1, "workouts_fanout_ms": 1, "comments_ms": 0,
                    "athlete_count": 0, "candidate_count": 0, "comment_fetch_count": 0,
                    "posted_today": 0}

    monkeypatch.setattr(FC.FS, "get_workouts_needing_feedback", fake, raising=False)
    return calls


# ── BACKEND ──────────────────────────────────────────────────────────────────
class TestColdReadNeverSweeps:
    def test_1_pending_zonder_snapshot_veegt_niet(self, env, monkeypatch):
        """Koud (geen mem/durable) → pending, en de dure sweep wordt NIET aangeroepen."""
        calls = _spy_sweep(monkeypatch)
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: {})
        r = FC.queue(refresh=False)
        assert r.get("pending") is True
        assert r.get("items") == []
        assert calls["n"] == 0, "non-refresh read mag de FinalSurge-sweep nooit triggeren"

    def test_2_read_veegt_nooit_alleen_refresh(self, env, monkeypatch):
        """Met een geldige snapshot: read=cache (0 sweeps); refresh=True = 1 sweep."""
        calls = _spy_sweep(monkeypatch)
        FC._QUEUE_MEM = _snap([_item("W1", "2026-08-12")], {"W1": {"workout_key": "W1"}})
        r = FC.queue(refresh=False)
        assert r.get("cached") is True and calls["n"] == 0
        monkeypatch.setattr(FC, "_queue_persist", lambda snap: (True, ""))
        FC.queue(refresh=True)
        assert calls["n"] == 1, "alleen refresh=True mag vegen"


class TestWarmFlowIdentical:
    def test_3_server_sortering_datum_first_onaangeroerd(self, env):
        """Warme cached read behoudt de server-sortering (oudste datum eerst)."""
        FC._QUEUE_MEM = _snap([_item("Wnew", "2026-08-12"), _item("Wold", "2026-08-10")])
        r = FC.queue(refresh=False)
        assert r.get("cached") is True
        assert [i["id"] for i in r["items"]] == ["Wold", "Wnew"]


class TestSingleFlight:
    def test_4_tweede_refresh_geeft_cache_zonder_tweede_sweep(self, env, monkeypatch):
        calls = _spy_sweep(monkeypatch)
        FC._QUEUE_MEM = _snap([_item("W1", "2026-08-12")])
        FC._QREFRESHING = True                            # simuleer: er loopt al een sweep
        r = FC.queue(refresh=True)
        assert r.get("verversen_bezig") is True
        assert r.get("cached") is True
        assert calls["n"] == 0, "single-flight mag geen tweede sweep starten"


class TestFsClientConstants:
    def test_5_timeout_en_workers_contract(self):
        assert fs_client._TIMEOUT == (5, 12)
        assert fs_client._MAX_WORKERS == 16

    def test_5b_http_pool_coherent(self):
        ad = fs_client._session.get_adapter("https://beta.finalsurge.com")
        assert ad._pool_connections >= 16
        assert ad._pool_maxsize >= 16


# ── FRONTEND (bron-contract op app.js) ───────────────────────────────────────
def _app_js():
    with open(_APP_JS, encoding="utf-8") as f:
        return f.read()


def _fn_body(src, header):
    """Haal de body van een functie op via brace-matching vanaf `header`."""
    i = src.index(header)
    b = src.index("{", i)
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


class TestFrontendNonBlocking:
    def test_6_pending_rendert_nietblokkerende_3zone_shell(self):
        src = _app_js()
        enter = _fn_body(src, "async function fbEnter(")
        # pending-tak roept de niet-blokkerende cold-waiting renderer aan (geen hard laadscherm)
        assert "fbRenderColdWaiting()" in enter
        cold = _fn_body(src, "function fbRenderColdWaiting(")
        assert "#fb-focus" in cold, "case-zone moet een neutrale wacht-staat krijgen"
        assert "#fb-ctx-col" in cold, "context-zone moet zichtbaar/gezet worden"
        assert "fbRenderLoading" in cold, "queue-zone toont een wacht-skeleton"

    def test_7_refresh_draait_op_achtergrond(self):
        enter = _fn_body(_app_js(), "async function fbEnter(")
        assert re.search(r"(?<!await )\bfbRefresh\(\)", enter), "fbEnter start fbRefresh()"
        assert "await fbRefresh" not in enter, "fbEnter mag NIET op de sweep blokkeren"

    def test_8_koude_sweep_auto_opent_eerste_item(self):
        refresh = _fn_body(_app_js(), "async function fbRefresh(")
        assert "auto_first_cold" in refresh
        assert "fbOpen(fresh[0].id" in refresh
        # server-sortering: geen client-resort van `fresh` vóór de selectie
        assert ".sort(" not in refresh
