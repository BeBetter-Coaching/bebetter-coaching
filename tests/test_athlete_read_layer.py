"""Canonical Athlete Read Layer v1 — Gate 1 service tests (real functions, injected gather).

Bewijst de goedgekeurde read-regels op de echte `pwa/athlete_read.py`:
- fresh mem hit (geen tweede build);
- stale mem → direct terug + precies één background rebuild per user_key;
- N cold concurrent reads → precies één foreground build (single-flight);
- invalidate → volgende read bouwt opnieuw;
- geen fake raw uit de snapshot (LKG → raw=None, raw_available=false);
- degraded gather behoudt bruikbare raw (raw_available=true);
- echte exception in build_state + snapshot → LKG-state, raw=None;
- generation-id stabiel bij alleen een built_at-verandering; inhoudswijziging → andere id.

    python3 -m pytest tests/test_athlete_read_layer.py -q
"""
import os
import sys
import threading
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import pytest

import athlete_read as AR
from brain import snapshot as _snapshot
from brain import state as _state
from brain.models import SourceHealth

TODAY = date(2026, 9, 1)


# ── synthetische raw/health (geen FinalSurge/IO) ─────────────────────────────
def _health(*, training_log=True):
    h = []
    for src, ok in (("intake", True), ("coach_notes", True), ("coach_memory", True),
                    ("on_hold", True), ("garmin", True), ("belasting", True),
                    ("fs.training_log", training_log), ("fs.labels", True), ("fs.zones", training_log)):
        h.append(SourceHealth(source=src, available=ok,
                              last_success=(TODAY.isoformat() if ok else ""),
                              error=("" if ok else "geen bron")))
    return h


def _raw(doel="10km sub 50", training_log=True):
    return {"intake": {"doel": doel, "trainingsdagen": "di/do", "athlete_name": "Tester"},
            "intake_ts": (TODAY - timedelta(days=30)).isoformat(), "notes": [], "profiel": "",
            "on_hold": None, "garmin": "", "belasting": None, "training_log": [], "labels": [],
            "zones": {}}


def _counting_gather(raw, health, counter, delay=0.0):
    def _g(user_key, today=None):
        counter["n"] += 1
        if delay:
            import time as _t
            _t.sleep(delay)
        return raw, health
    return _g


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Isoleer elke test: lege in-process staat, geen snapshot-IO, synchrone bg-uitvoerder."""
    AR.reset()
    # geen echte GitHub/local snapshot-IO tijdens build_state
    monkeypatch.setattr(_snapshot, "load_snapshot", lambda uk: None, raising=True)
    monkeypatch.setattr(_snapshot, "save_snapshot", lambda st: (True, ""), raising=True)
    # background rebuild synchroon → deterministisch
    monkeypatch.setattr(AR, "_run_bg", lambda fn: fn(), raising=True)
    yield
    AR.reset()


def _mk_state(doel="10km sub 50", built_at="2026-09-01T10:00:00"):
    st = _state.assemble("u1", "Tester", _raw(doel), _health(), TODAY, prev=None)
    st.built_at = built_at
    return st


# ── 1. fresh mem hit ─────────────────────────────────────────────────────────
def test_fresh_mem_hit_no_second_build():
    c = {"n": 0}
    g = _counting_gather(_raw(), _health(), c)
    r1 = AR.get_state("u1", TODAY, gather_fn=g)
    r2 = AR.get_state("u1", TODAY, gather_fn=g)
    assert c["n"] == 1, "tweede read binnen TTL mag NIET opnieuw bouwen"
    assert r1.freshness["from"] == "fresh"
    assert r2.freshness["from"] == "mem" and r2.freshness["stale"] is False
    assert r1.state_generation_id == r2.state_generation_id


# ── 2. stale mem → direct terug + precies één background rebuild ──────────────
def test_stale_mem_serves_direct_plus_one_bg(monkeypatch):
    c = {"n": 0}
    g = _counting_gather(_raw(), _health(), c)
    AR.get_state("u1", TODAY, gather_fn=g)            # vult mem (n=1)
    monkeypatch.setattr(AR, "_STATE_TTL_SEC", -1, raising=True)   # alles is nu stale
    r = AR.get_state("u1", TODAY, gather_fn=g)        # stale serve + sync bg rebuild
    assert r.freshness["from"] == "mem" and r.freshness["stale"] is True, "stale serve moet direct"
    assert c["n"] == 2, "precies één background rebuild"


def test_bg_rebuild_capped_at_one_per_key(monkeypatch):
    c = {"n": 0}
    g = _counting_gather(_raw(), _health(), c)
    AR.get_state("u1", TODAY, gather_fn=g)            # n=1
    captured = []
    monkeypatch.setattr(AR, "_run_bg", lambda fn: captured.append(fn), raising=True)  # NIET uitvoeren
    monkeypatch.setattr(AR, "_STATE_TTL_SEC", -1, raising=True)
    AR.get_state("u1", TODAY, gather_fn=g)            # schedule bg #1 (inflight blijft staan)
    AR.get_state("u1", TODAY, gather_fn=g)            # inflight aanwezig → géén 2e schedule
    assert len(captured) == 1, "max één background rebuild per user_key zolang er één in flight is"


# ── 3. N cold concurrent reads → precies één foreground build ────────────────
def test_concurrent_cold_reads_single_build():
    c = {"n": 0}
    g = _counting_gather(_raw(), _health(), c, delay=0.05)   # bouw duurt even → threads verzamelen
    results = []
    barrier = threading.Barrier(8)

    def _worker():
        barrier.wait()
        results.append(AR.get_state("u1", TODAY, gather_fn=g))

    ts = [threading.Thread(target=_worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert c["n"] == 1, "8 gelijktijdige cold reads → precies één foreground build"
    gens = {r.state_generation_id for r in results}
    assert len(results) == 8 and len(gens) == 1, "alle callers delen dezelfde generatie"


# ── 4. invalidate → volgende read bouwt opnieuw ──────────────────────────────
def test_invalidate_forces_rebuild():
    c = {"n": 0}
    g = _counting_gather(_raw(), _health(), c)
    AR.get_state("u1", TODAY, gather_fn=g)
    AR.invalidate("u1")
    AR.get_state("u1", TODAY, gather_fn=g)
    assert c["n"] == 2, "na invalidate moet de volgende read opnieuw bouwen"


def test_refresh_forces_rebuild():
    c = {"n": 0}
    g = _counting_gather(_raw(), _health(), c)
    AR.get_state("u1", TODAY, gather_fn=g)
    AR.get_state("u1", TODAY, refresh=True, gather_fn=g)
    assert c["n"] == 2, "refresh=True forceert een rebuild"


# ── 5/7. geen fake raw uit snapshot; echte exception + snapshot → raw=None ────
def test_no_fake_raw_lkg_on_build_exception(monkeypatch):
    lkg = _mk_state()
    monkeypatch.setattr(AR._snapshot, "load_snapshot", lambda uk: lkg, raising=True)

    def _boom(user_key, today=None):
        raise RuntimeError("gather kapot")

    r = AR.get_state("u1", TODAY, gather_fn=_boom)
    assert r.freshness["from"] == "lkg"
    assert r.state is lkg, "LKG-state uit de snapshot geserveerd"
    assert r.raw is None, "raw mag NOOIT uit de snapshot gereconstrueerd worden"
    assert r.freshness["raw_available"] is False
    assert r.freshness["stale"] is True and r.freshness["degraded"] is True


def test_lkg_absent_yields_none_state(monkeypatch):
    monkeypatch.setattr(AR._snapshot, "load_snapshot", lambda uk: None, raising=True)

    def _boom(user_key, today=None):
        raise RuntimeError("gather kapot")

    r = AR.get_state("u1", TODAY, gather_fn=_boom)
    assert r.state is None and r.raw is None and r.freshness["raw_available"] is False


# ── 6. degraded gather behoudt bruikbare raw ─────────────────────────────────
def test_degraded_gather_keeps_raw():
    c = {"n": 0}
    g = _counting_gather(_raw(training_log=False), _health(training_log=False), c)
    r = AR.get_state("u1", TODAY, gather_fn=g)
    assert r.freshness["from"] == "fresh"
    assert r.raw is not None and r.freshness["raw_available"] is True, "degraded ≠ geen raw"
    assert r.freshness["degraded"] is True, "een uitgevallen bron markeert degraded"


# ── 8/9. generation-id: stabiel bij alleen built_at; anders bij inhoud ───────
def test_generation_id_excludes_built_at():
    a = _mk_state(doel="10km sub 50", built_at="2026-09-01T10:00:00")
    b = _mk_state(doel="10km sub 50", built_at="2026-09-01T23:59:59")
    assert AR._generation_id(a) == AR._generation_id(b), "alleen built_at-verschil ⇒ zelfde gen-id"


def test_generation_id_changes_on_content():
    a = _mk_state(doel="10km sub 50")
    b = _mk_state(doel="marathon sub 3:30")
    assert AR._generation_id(a) != AR._generation_id(b), "inhoudelijk andere state ⇒ andere gen-id"


def test_generation_id_stable_repeat():
    a = _mk_state(doel="10km sub 50")
    assert AR._generation_id(a) == AR._generation_id(a) and len(AR._generation_id(a)) == 16
