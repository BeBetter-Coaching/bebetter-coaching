"""Canonical Athlete Read Layer v1 — één gedeelde, in-process AthleteState-read.

Doel (goedgekeurd ontwerp `BeBetter-Canonical-Athlete-Read-Layer-v1-DESIGN-REV.md`): Dossier,
Workspace-deep, Feedback-cockpit-context, Feedback-AI-context en "Waarom?" bouwen niet elk
opnieuw een zware AthleteState op. Deze laag is een **compositie/lees-laag**, GEEN nieuwe
waarheid:

  * ze herberekent niets — `brain.adapter.build_state()` blijft de enige builder;
  * ze bezit GEEN nieuwe durable store — `brain.snapshot` (`brain_snapshot.json`) blijft de
    state-LKG; er is GEEN durable raw-cache;
  * `state_generation_id` is een inhoud-afgeleide signatuur over de canonieke AthleteState-
    kennis (evidence/overall/conflicts/source_gaps), berekend op leesmoment.

Contract (samengevat):
  VERSE MEM  → direct terug (from=mem, stale=false), geen build.
  STALE MEM  → direct terug (from=mem, stale=true) + max één background rebuild per user_key.
  GEEN MEM   → één single-flight FOREGROUND build; concurrente callers delen die build.
  raw        → uitsluitend uit een live gather/build; NOOIT gereconstrueerd uit de snapshot.
               pure LKG-fallback → raw=None, raw_available=false.

In-process, single-worker residual identiek aan coach_read/Feedback single-flight; het
`state_generation_id` + LKG maken divergentie zichtbaar en zelfhelend.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import date

from brain import adapter as _adapter
from brain import snapshot as _snapshot
from brain.models import SCHEMA_VERSION

# Freshness-venster: gelijk aan de bestaande conventie (feedback_core._OPEN_TTL_SEC, client
# cockpitStale ~15 min). Hergebruikt geen nieuwe store/timestamp.
_STATE_TTL_SEC = 15 * 60


class AthleteRead:
    """In-memory read-projectie (geen persistentie). `raw` is None bij een pure LKG-fallback."""
    __slots__ = ("state", "raw", "state_generation_id", "schema_version",
                 "source_health", "freshness")

    def __init__(self, state, raw, state_generation_id, schema_version, source_health, freshness):
        self.state = state
        self.raw = raw
        self.state_generation_id = state_generation_id
        self.schema_version = schema_version
        self.source_health = source_health
        self.freshness = freshness

    def as_dict(self) -> dict:
        return {
            "state_generation_id": self.state_generation_id,
            "schema_version": self.schema_version,
            "freshness": dict(self.freshness),
        }


class _Entry:
    __slots__ = ("state", "raw", "gen", "schema_version", "source_health",
                 "degraded", "built_at", "created_wall", "created_mono")

    def __init__(self, state, raw, gen, schema_version, source_health, degraded, built_at):
        self.state = state
        self.raw = raw
        self.gen = gen
        self.schema_version = schema_version
        self.source_health = source_health
        self.degraded = degraded
        self.built_at = built_at
        self.created_wall = time.time()
        self.created_mono = time.monotonic()


# ── in-process state ─────────────────────────────────────────────────────────
_MEM: dict = {}                        # user_key -> _Entry (hot read)
_LOCK = threading.Lock()               # guards _MEM + _INFLIGHT
_INFLIGHT: dict = {}                   # user_key -> threading.Event (fg OF bg build in flight)


def _run_bg(fn) -> None:
    """Achtergrond-uitvoerder (seam voor tests: monkeypatch naar `lambda fn: fn()` = synchroon)."""
    threading.Thread(target=fn, daemon=True).start()


# ── generation-id: content-derived over de canonieke AthleteState-kennis ─────
def _generation_id(state) -> str:
    """Inhoud-afgeleide identiteit. Hasht schema_version/athlete_key/overall + de deterministisch
    gesorteerde evidence/conflicts/source_gaps. Sluit `built_at` (wall-clock) en `sources`
    (vluchtige error-tekst/availability — semantisch al in source_gaps/overall) expliciet uit,
    zodat gelijke kennis dezelfde id geeft en een nieuwe buildtijd of transiënte bronfout geen
    false generation-change veroorzaakt."""
    if state is None:
        return ""
    d = state.to_dict()
    ev = sorted((d.get("evidence") or []), key=lambda e: str(e.get("id", "")))
    payload = {
        "schema_version": d.get("schema_version"),
        "athlete_key": d.get("athlete_key"),
        "overall": d.get("overall"),
        "evidence": ev,
        "conflicts": sorted(d.get("conflicts") or []),
        "source_gaps": sorted(d.get("source_gaps") or []),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _any_unavailable(state) -> bool:
    try:
        return any(not getattr(s, "available", True) for s in (getattr(state, "sources", []) or []))
    except Exception:
        return False


# ── serving ──────────────────────────────────────────────────────────────────
def _serve(ent: _Entry, frm: str, stale: bool) -> AthleteRead:
    age = int(time.time() - ent.created_wall)
    return AthleteRead(
        state=ent.state, raw=ent.raw, state_generation_id=ent.gen,
        schema_version=ent.schema_version, source_health=ent.source_health,
        freshness={"from": frm, "stale": stale, "age_sec": age,
                   "degraded": ent.degraded, "raw_available": ent.raw is not None},
    )


def _lkg_read(user_key: str) -> AthleteRead:
    """Pure LKG-fallback: alleen de snapshot-state (GEEN raw). raw=None, raw_available=false."""
    try:
        state = _snapshot.load_snapshot(user_key)
    except Exception:
        state = None
    sh = list(getattr(state, "sources", []) or []) if state is not None else []
    return AthleteRead(
        state=state, raw=None, state_generation_id=_generation_id(state),
        schema_version=getattr(state, "schema_version", SCHEMA_VERSION), source_health=sh,
        freshness={"from": "lkg", "stale": True, "age_sec": None,
                   "degraded": True, "raw_available": False},
    )


def _do_build(user_key: str, today, gather_fn) -> AthleteRead:
    """Bouw (build_state) + cache in _MEM. Bij een échte exception vóór (state,raw): LKG (raw=None).
    Aanroeper houdt de single-flight-leiderschap voor `user_key`."""
    try:
        state, raw = _adapter.build_state(user_key, today, gather_fn=gather_fn)
    except Exception:
        return _lkg_read(user_key)
    degraded = bool(getattr(state, "source_gaps", None)) or _any_unavailable(state)
    ent = _Entry(state=state, raw=raw, gen=_generation_id(state),
                 schema_version=getattr(state, "schema_version", SCHEMA_VERSION),
                 source_health=list(getattr(state, "sources", []) or []),
                 degraded=degraded, built_at=getattr(state, "built_at", ""))
    with _LOCK:
        _MEM[user_key] = ent
    return _serve(ent, "fresh", False)


def _foreground(user_key: str, today, gather_fn) -> AthleteRead:
    """Single-flight foreground build: precies één build per user_key; concurrente callers
    delen die in-flight build en krijgen daarna de verse mem (of LKG als de build faalde)."""
    while True:
        with _LOCK:
            ev = _INFLIGHT.get(user_key)
            leader = ev is None
            if leader:
                ev = threading.Event()
                _INFLIGHT[user_key] = ev
        if leader:
            try:
                return _do_build(user_key, today, gather_fn)
            finally:
                with _LOCK:
                    _INFLIGHT.pop(user_key, None)
                ev.set()
        # niet-leider: wacht op de leider, serveer daarna verse mem of LKG
        ev.wait(30)
        with _LOCK:
            ent = _MEM.get(user_key)
        if ent is not None:
            return _serve(ent, "mem", False)
        return _lkg_read(user_key)


def _schedule_bg(user_key: str, today, gather_fn) -> None:
    """Max één background rebuild per user_key (deelt de single-flight-gate met de foreground)."""
    with _LOCK:
        if user_key in _INFLIGHT:
            return
        ev = threading.Event()
        _INFLIGHT[user_key] = ev

    def _work():
        try:
            _do_build(user_key, today, gather_fn)
        except Exception:
            pass
        finally:
            with _LOCK:
                _INFLIGHT.pop(user_key, None)
            ev.set()

    _run_bg(_work)


# ── public API ───────────────────────────────────────────────────────────────
def get_state(user_key: str, today: date | None = None, refresh: bool = False,
              gather_fn=None) -> AthleteRead:
    """Canonieke AthleteState-read. Zie de module-docstring voor de harde SWR-/raw-regels.
    `gather_fn` is passthrough naar `build_state()` (test/outage-injectie)."""
    if not user_key:
        return AthleteRead(state=None, raw=None, state_generation_id="",
                           schema_version=SCHEMA_VERSION, source_health=[],
                           freshness={"from": "lkg", "stale": True, "age_sec": None,
                                      "degraded": True, "raw_available": False})
    if not refresh:
        with _LOCK:
            ent = _MEM.get(user_key)
        if ent is not None:
            age_mono = time.monotonic() - ent.created_mono
            if age_mono <= _STATE_TTL_SEC:
                return _serve(ent, "mem", False)                    # VERSE MEM
            _schedule_bg(user_key, today, gather_fn)                # STALE MEM → bg rebuild
            return _serve(ent, "mem", True)
    return _foreground(user_key, today, gather_fn)                  # GEEN MEM / refresh


def peek_generation(user_key: str) -> str | None:
    """Huidige generation-id uit de hot cache zonder rebuild (voor 'Waarom?'-coherentie)."""
    with _LOCK:
        ent = _MEM.get(user_key)
    return ent.gen if ent is not None else None


def invalidate(user_key: str) -> None:
    """Evict de hot cache voor één atleet (na een write die een gather-input muteert)."""
    if not user_key:
        return
    with _LOCK:
        _MEM.pop(user_key, None)


def reset() -> None:
    """Testhulp: leeg de in-process staat volledig."""
    with _LOCK:
        _MEM.clear()
        _INFLIGHT.clear()
