"""Reproduceerbare in-process memory-benchmark die de echte productieflow nabootst.

    python3 tests/memory_bench.py [--athletes 24] [--cycles 3] [--json out.json]

WAAROM: Render herstartte de productie-instance na overschrijding van ~512 MB; memory
liep tijdens actief coachgebruik op van ~123 MB naar ~514 MB terwijl CPU laag bleef.
Codelezen alleen bewijst niets — dit script draait de ECHTE modules (feedback_core,
athlete_read, dossier_cockpit, coach_read, feedback_week, home_core) tegen SYNTHETISCHE,
read-only fixtures en meet wat er ná GC blijft leven.

GEEN netwerk, GEEN FinalSurge-writes, GEEN LLM-calls: fs_client / intake_store / ai_client
worden volledig gestubd. Er wordt niets gepersisteerd.

Gemeten per stage: tracemalloc (Python-heap, ná gc.collect()), gc-objecttellingen,
cardinaliteit van elke procesglobale cache, en de RSS-highwatermark van het proces.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import sys
import tracemalloc
from datetime import date, datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "pwa")):
    if p not in sys.path:
        sys.path.insert(0, p)

TODAY = date.today()


# ══════════════════════════════════════════════════════════════════════════════
# Synthetische fixtures — vorm identiek aan productie, inhoud verzonnen.
# ══════════════════════════════════════════════════════════════════════════════
def _laps(n: int) -> list:
    """Lap-rijen zoals FinalSurge ze in workout-details levert."""
    return [{
        "lap": i + 1, "distance": 1000.0 + i, "duration": 300.0 + i,
        "avg_hr": 140 + (i % 30), "max_hr": 150 + (i % 30), "avg_pace": 300 + i,
        "elevation_gain": 4.0, "avg_cadence": 172, "calories": 62,
        "start_time": f"2026-09-0{(i % 9) + 1}T09:{i % 60:02d}:00",
        "note": "",
    } for i in range(n)]


def _workout_details(seed: int) -> dict:
    """Volledige detail-payload (Activities + laps) — wat `_ensure_details` ophaalt."""
    return {
        "workout_key": f"w{seed}",
        "Activities": [{
            "activity_key": f"a{seed}", "activity_type_name": "Run",
            "distance": 12000.0, "duration": 3600.0, "avg_hr": 148, "max_hr": 172,
            "elevation_gain": 120.0, "calories": 780, "avg_cadence": 174,
            "laps": _laps(48),
        }],
        "laps": _laps(48),
    }


def _thread(n: int) -> list:
    return [{"van": "atleet" if i % 2 == 0 else "coach",
             "wie": "Atleet" if i % 2 == 0 else "Jip",
             "tekst": "Ging prima, benen voelden fris maar de laatste twee blokken waren zwaar. " * 2,
             "ts": f"2026-09-0{(i % 9) + 1}T10:00:00"} for i in range(n)]


def _workout(ak: str, naam: str, seed: int, light: bool = True) -> dict:
    """Queue-workout zoals get_workouts_needing_feedback(include_details=False) hem geeft."""
    return {
        "athlete_name": naam, "athlete_first_name": naam.split()[0], "athlete_key": ak,
        "athlete_group": "Comfort", "athlete_groups": ["Comfort"],
        "workout_key": f"w{seed}",
        "workout_name": "Duurloop met blokken",
        "workout_date": (TODAY - timedelta(days=seed % 7)).isoformat(),
        "workout_type": "run",
        "post_notes": "Voelde goed, laatste blok zwaar. " * 3,
        "felt": "2", "effort": "6",
        "athlete_comments": ["Scheen was even gevoelig maar zakte weg."],
        "thread": _thread(4),
        "details": {} if light else _workout_details(seed),
        "data_only": False, "planned_no_notes": False,
    }


def _training_log_entry(i: int) -> dict:
    d = TODAY - timedelta(days=i)
    return {
        "date": d.isoformat(), "name": "Duurloop", "description": "60 min rustig",
        "activity_type": "Run", "activity_type_name": "Run",
        "planned_distance": 12000.0, "actual_distance": 12100.0,
        "planned_duration": 3600.0, "actual_duration": 3620.0,
        "completed": True, "felt": 2, "effort": 6,
        "post_workout_notes": "Prima gelopen, benen wat zwaar in het laatste kwartier.",
        "avg_hr": 147, "max_hr": 171, "calories": 760, "elevation_gain": 95.0,
        "Activities": [{"activity_key": f"tl{i}", "duration": 3620.0, "distance": 12100.0,
                        "avg_hr": 147, "laps": _laps(12)}],
    }


def _athletes(n: int) -> list:
    return [{"user_key": f"u{i:03d}", "name": f"Atleet {i:03d} Testerman",
             "first_name": f"Atleet{i:03d}", "group": "Comfort",
             "all_groups": ["Comfort"], "coach_athlete_key": f"ca{i:03d}"} for i in range(n)]


# ══════════════════════════════════════════════════════════════════════════════
# Stubs — geen netwerk, geen writes.
# ══════════════════════════════════════════════════════════════════════════════
def install_stubs(n_athletes: int):
    import fs_client as FS
    import intake_store as IS

    roster = _athletes(n_athletes)
    by_key = {a["user_key"]: a for a in roster}

    FS.get_token = lambda: "stub-token"
    FS.get_coach_key = lambda: "coach-1"
    FS.get_athletes = lambda *a, **k: [dict(x) for x in roster]
    FS.get_athletes_by_group = lambda *a, **k: {"Comfort": [dict(x) for x in roster]}
    FS.reset_roster_cache = lambda: None
    FS.group_is_excluded = lambda g, ex: str(g or "").lower() in {str(x).lower() for x in (ex or ())}
    FS.is_executed_workout = lambda w: True
    FS.classify_workout_type = lambda w: "run"

    # Elke sweep levert VERSE dict-objecten (zoals een echte HTTP-fetch): identiteit
    # verschilt per refresh, inhoud is gelijkwaardig.
    # `DAG` bootst het verstrijken van de tijd na: het 7-daagse venster schuift op, dus
    # elke 'dag' komen er NIEUWE workout_keys binnen en vallen oude uit de queue. Precies
    # wat er in productie gebeurt terwijl het proces blijft draaien.
    state = {"dag": 0}

    def _needing(days_back=7, **kw):
        out = []
        for i, a in enumerate(roster):
            for d in range(2):                      # ~2 openstaande trainingen per atleet
                out.append(_workout(a["user_key"], a["name"], (state["dag"] * 1000) + i * 10 + d))
        stats = {"posted_today": 0, "roster_ms": 1, "workouts_fanout_ms": 1, "comments_ms": 1,
                 "athlete_count": len(roster), "candidate_count": len(out), "comment_fetch_count": 0}
        return (out, stats) if kw.get("return_stats") else out
    FS.get_workouts_needing_feedback = _needing

    FS.get_workout_details = lambda wk, ak=None, *a, **k: _workout_details(abs(hash(wk)) % 1000)
    FS.get_comments = lambda wk, uk=None, *a, **k: []
    FS.get_workout_comments = lambda *a, **k: []
    FS.get_workout_thread = lambda *a, **k: _thread(4)
    FS.build_thread = lambda cs, pn, fn, ck: _thread(4)
    FS.get_training_log = lambda uk, months=4, *a, **k: [_training_log_entry(i) for i in range(120)]
    FS.get_calendar_labels = lambda uk, s, e, *a, **k: [
        {"date": (TODAY + timedelta(days=i - 7)).isoformat(), "name": "Duurloop",
         "description": "60 min rustig in Z2 met 3x8 min blok"} for i in range(97)]
    FS.get_athlete_zones = lambda uk, *a, **k: {
        "zone_type": "hartslag",
        "zones": [{"zone": z, "low": 100 + z * 12, "high": 111 + z * 12} for z in range(1, 6)]}
    FS.get_workouts_deduped = lambda uk, s, e, *a, **k: [
        {"workout_date": (TODAY - timedelta(days=i)).isoformat(), "name": "Duurloop",
         "Activities": [{"duration": 3600.0, "distance": 12000.0, "laps": _laps(12)}]}
        for i in range((e - s).days + 1)]
    FS.get_workout_builder = lambda wk, ak=None, *a, **k: [
        {"metric": "hartslag", "type": "ACTIVE", "duration": 1200, "zone_low": 2, "zone_high": 2,
         "description": "20 min in Z2"}]
    FS.get_fastest_activity_on_day = lambda *a, **k: None
    FS.get_upcoming_races = lambda days_ahead=42, *a, **k: []
    FS.get_compliance_alerts = lambda *a, **k: []
    FS.get_schema_end_dates = lambda *a, **k: []
    FS.get_last_activity_dates = lambda *a, **k: {}
    FS.post_comment = lambda *a, **k: (_ for _ in ()).throw(AssertionError("WRITE in benchmark"))

    # intake_store: puur in-memory, geen GitHub, geen disk-writes.
    notes = {a["user_key"]: [{"datum": (TODAY - timedelta(days=i)).isoformat(),
                              "tekst": "Coachnotitie over opbouw en gevoel. " * 4}
                             for i in range(6)] for a in roster}
    belasting_stand = {"datum": TODAY.isoformat(), "afgehandeld": {}, "resultaten": [
        {"user_key": a["user_key"], "naam": a["name"], "ernst": "let_op", "group": "Comfort",
         "signalen": ["Volume +18% laatste 7 dagen"],
         "metrics": {"km_recent": 48.0, "km_basis_week": 40.0, "runs_recent": []}}
        for a in roster]}
    store = {
        "intakes": {a["user_key"]: {"athlete_name": a["name"], "doel": "10 km onder 45 min",
                                    "antwoorden": {f"v{i}": "antwoordtekst " * 12 for i in range(25)}}
                    for a in roster},
        "laatste_intakes": {}, "notes": notes, "profielen": {}, "on_hold": {},
        "admin_clients": {}, "belasting": belasting_stand, "home_handled": {},
        "feedback_queue": {}, "skipped": {}, "weekbriefing": {}, "intake_inbox": {},
    }
    IS.load_intakes = lambda: store["intakes"]
    IS.load_laatste_intakes = lambda: store["laatste_intakes"]
    IS.load_notes = lambda: store["notes"]
    IS.load_profielen = lambda: store["profielen"]
    IS.load_on_hold = lambda: store["on_hold"]
    IS.load_admin_clients = lambda: store["admin_clients"]
    IS.load_belasting = lambda: store["belasting"]
    IS.load_home_handled = lambda: store["home_handled"]
    IS.load_feedback_queue = lambda: store["feedback_queue"]
    IS.save_feedback_queue = lambda snap: store.__setitem__("feedback_queue", snap) or (True, "")
    IS.load_skipped = lambda: store["skipped"]
    IS.save_skipped = lambda s: (True, "")
    IS.load_weekbriefing = lambda: store["weekbriefing"]
    IS.save_weekbriefing = lambda d: (True, "")
    IS.load_intake_inbox = lambda: store["intake_inbox"]
    IS.garmin_context_text = lambda uk: ""
    store["_dag"] = state
    for _n in ("save_intakes", "save_notes", "save_profielen", "save_on_hold",
               "save_belasting", "save_home_handled"):
        if hasattr(IS, _n):
            setattr(IS, _n, lambda *a, **k: (True, ""))

    # brain.snapshot: geen disk/GitHub-persistentie tijdens de benchmark.
    try:
        from brain import snapshot as SNAP
        SNAP.load_snapshot = lambda uk: None
        SNAP.save_snapshot = lambda st: None
    except Exception:
        pass

    return roster, by_key, store


# ══════════════════════════════════════════════════════════════════════════════
# Meten
# ══════════════════════════════════════════════════════════════════════════════
_RSS_DIV = 1024 * 1024 if sys.platform == "darwin" else 1024      # macOS: bytes, Linux: KiB


def rss_peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / _RSS_DIV


def cache_sizes() -> dict:
    """Cardinaliteit van elke procesglobale cache die een request kan overleven."""
    out = {}

    def _n(mod, attr, key=None):
        try:
            m = __import__(mod)
            v = getattr(m, attr)
            out[key or f"{mod}.{attr}"] = len(v)
        except Exception:
            out[key or f"{mod}.{attr}"] = None

    _n("feedback_core", "_cache", "feedback_core._cache")
    _n("feedback_core", "_GEN_STATUS", "feedback_core._GEN_STATUS")
    _n("races_core", "_cache", "races_core._cache")
    _n("athlete_read", "_MEM", "athlete_read._MEM")
    _n("athlete_read", "_INFLIGHT", "athlete_read._INFLIGHT")
    _n("schema_core", "_WRITE_RECEIPTS", "schema_core._WRITE_RECEIPTS")
    try:
        import feedback_core as FC
        out["feedback_core._QUEUE_MEM.items"] = len((FC._QUEUE_MEM or {}).get("items") or [])
        out["feedback_core._QUEUE_MEM._volle"] = len((FC._QUEUE_MEM or {}).get("_volle") or {})
        out["feedback_core._cache.with_details"] = sum(
            1 for w in FC._cache.values() if isinstance(w, dict) and w.get("details"))
    except Exception:
        pass
    try:
        import home_core as HC
        out["home_core._MEM"] = len(HC._MEM or {})
    except Exception:
        pass
    return out


def measure(label: str) -> dict:
    gc.collect()
    gc.collect()
    cur, peak = tracemalloc.get_traced_memory()
    counts = {}
    for o in gc.get_objects():
        t = type(o).__name__
        counts[t] = counts.get(t, 0) + 1
    return {
        "stage": label,
        "heap_mb": round(cur / 1048576, 1),
        "heap_peak_mb": round(peak / 1048576, 1),
        "rss_peak_mb": round(rss_peak_mb(), 1),
        "gc_objects": len(gc.get_objects()),
        "dicts": counts.get("dict", 0), "lists": counts.get("list", 0),
        "caches": cache_sizes(),
    }


def top_sites(n: int = 12) -> list:
    snap = tracemalloc.take_snapshot().filter_traces((
        tracemalloc.Filter(False, tracemalloc.__file__),
        tracemalloc.Filter(False, __file__),
    ))
    out = []
    for st in snap.statistics("traceback")[:n]:
        fr = st.traceback[0]
        out.append({"mb": round(st.size / 1048576, 2), "count": st.count,
                    "where": f"{os.path.relpath(fr.filename, _ROOT)}:{fr.lineno}"})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# De productieflow
# ══════════════════════════════════════════════════════════════════════════════
def coach_day(n_athletes: int, cycles: int, verbose: bool = True) -> dict:
    """Bootst een coachdag na: prewarm, refreshes, per-atleet cockpit/week/feedback-detail.
    Elke cyclus = een 'dag' verder, dus het 7-daagse queue-venster schuift op (nieuwe wids)."""
    roster, by_key, store = install_stubs(n_athletes)

    import athlete_read as AR
    import coach_read as CR                                       # noqa: F401
    import dossier_cockpit as DC
    import feedback_core as FC
    import feedback_week as FW
    import home_core as HC

    stages = []

    def snap(label):
        m = measure(label)
        stages.append(m)
        if verbose:
            c = m["caches"]
            print(f"  {label:<32} heap={m['heap_mb']:>6.1f}MB  objs={m['gc_objects']:>8}  "
                  f"fb_cache={str(c.get('feedback_core._cache')):>5}  "
                  f"details={str(c.get('feedback_core._cache.with_details')):>4}  "
                  f"state_mem={str(c.get('athlete_read._MEM')):>4}")
        return m

    snap("1 cold start")
    FC.prewarm_queue()
    snap("2 queue prewarm")
    FC.queue(refresh=True)
    base = snap("3 queue refresh #1")

    alle = list(by_key)
    for cyc in range(cycles):
        store["_dag"]["dag"] = cyc + 1                            # tijd schuift op → nieuwe wids
        # De coach bekijkt per cyclus een andere helft van de roster.
        helft = alle[: len(alle) // 2] if cyc % 2 == 0 else alle[len(alle) // 2:]
        for uk in helft:
            try:
                DC.cockpit(uk)                                    # cockpit / deep read (AthleteState)
            except Exception:
                pass
            try:
                FW.week_for_athlete(uk, TODAY)                    # feedback/week
            except Exception:
                pass
        snap(f"4.{cyc} cockpit+week x{len(helft)}")

        wids = [it["id"] for it in (FC.queue().get("items") or [])][: 2 * len(helft)]
        for wid in wids:
            try:
                FC.detail(wid)                                    # detail → _ensure_details (laps!)
            except Exception:
                pass
        snap(f"5.{cyc} feedback detail x{len(wids)}")

        FC.queue(refresh=True)
        snap(f"6.{cyc} queue refresh")
        try:
            HC.cockpit(refresh=True)
        except Exception:
            pass
        snap(f"7.{cyc} home refresh")

    gc.collect()
    eind = snap("8 na volledige GC")

    # ── De beslissende test: is dit retentie (caches) of een echte leak? ──────
    # Legen we ALLEEN de procesglobale caches, dan moet de heap terugvallen naar
    # ongeveer de basislijn. Doet hij dat → UNBOUNDED_CACHE. Doet hij dat niet →
    # er houdt iets anders de payloads vast (LEAK_CONFIRMED).
    FC._cache.clear()
    FC._QUEUE_MEM = {}
    FC._GEN_STATUS.clear()
    AR.reset()
    HC._MEM.clear()
    na_clear = snap("9 na cache-clear")

    vast = round(na_clear["heap_mb"] - base["heap_mb"], 1)
    return {
        "stages": stages, "top_sites": top_sites(),
        "athletes": n_athletes, "cycles": cycles,
        "baseline_mb": base["heap_mb"], "eind_mb": eind["heap_mb"],
        "na_clear_mb": na_clear["heap_mb"],
        "groei_mb": round(eind["heap_mb"] - base["heap_mb"], 1),
        "vrijgegeven_mb": round(eind["heap_mb"] - na_clear["heap_mb"], 1),
        "resterend_mb": vast,
    }


def per_entry_cost(n_athletes: int, verbose: bool = True) -> dict:
    """Meet wat ÉÉN bezochte atleet en ÉÉN geopende training permanent kosten.
    Daarmee is de productie-cardinaliteit (roster-omvang, dagen×trainingen) te extrapoleren."""
    roster, by_key, store = install_stubs(n_athletes)
    import athlete_read as AR
    import dossier_cockpit as DC
    import feedback_core as FC

    gc.collect(); gc.collect()
    a0 = tracemalloc.get_traced_memory()[0]
    for uk in list(by_key):
        try:
            DC.cockpit(uk)
        except Exception:
            pass
    gc.collect(); gc.collect()
    a1 = tracemalloc.get_traced_memory()[0]
    per_athlete = (a1 - a0) / max(1, len(AR._MEM))

    FC.queue(refresh=True)
    gc.collect(); gc.collect()
    b0 = tracemalloc.get_traced_memory()[0]
    wids = [it["id"] for it in (FC.queue().get("items") or [])]
    for wid in wids:
        try:
            FC.detail(wid)
        except Exception:
            pass
    gc.collect(); gc.collect()
    b1 = tracemalloc.get_traced_memory()[0]
    met_details = sum(1 for w in FC._cache.values() if isinstance(w, dict) and w.get("details"))
    per_workout = (b1 - b0) / max(1, met_details)

    res = {
        "athlete_read._MEM entries": len(AR._MEM),
        "kb_per_athlete_state": round(per_athlete / 1024, 1),
        "feedback_core._cache entries": len(FC._cache),
        "workouts_met_details": met_details,
        "kb_per_geopende_training": round(per_workout / 1024, 1),
    }
    if verbose:
        print("\n== Kosten per permanent gecachete entry ==")
        for k, v in res.items():
            print(f"  {k:<34} {v}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--athletes", type=int, default=24)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--json", default="")
    ap.add_argument("--per-entry", action="store_true", help="alleen de per-entry-kostenmeting")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    tracemalloc.start(8)
    if a.per_entry:
        per_entry_cost(a.athletes)
        return

    print(f"== BeBetter memory benchmark — {a.athletes} atleten, {a.cycles} cycli "
          f"({datetime.now().isoformat(timespec='seconds')}) ==")
    res = coach_day(a.athletes, a.cycles, verbose=not a.quiet)
    last = res["stages"][-1]

    print(f"\nbasislijn (na 1e refresh) : {res['baseline_mb']:.1f} MB")
    print(f"na alle cycli + GC        : {res['eind_mb']:.1f} MB  (groei +{res['groei_mb']:.1f} MB)")
    print(f"na cache-clear            : {res['na_clear_mb']:.1f} MB  "
          f"(vrijgegeven {res['vrijgegeven_mb']:.1f} MB, resterend +{res['resterend_mb']:.1f} MB)")
    print(f"RSS highwatermark         : {last['rss_peak_mb']:.1f} MB")
    print("\ncache-cardinaliteit aan het eind van de cycli:")
    for k, v in res["stages"][-2]["caches"].items():
        print(f"  {k:<38} {v}")
    print("\ntop allocatiesites (retained, ná GC):")
    for s in res["top_sites"]:
        print(f"  {s['mb']:>7.2f} MB  {s['count']:>7}x  {s['where']}")

    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f, indent=2)
        print(f"\nJSON → {a.json}")


if __name__ == "__main__":
    main()
