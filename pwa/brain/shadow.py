"""Masterbrein v2 — shadow-run / compare (Fase A).

Draait v2 NAAST v1 voor één atleet en rapporteert compact (geen gevoelige vrije
teksten in de standaard-output; alleen keys, counts, statussen, timings). Wordt
NIET in production UI aangeroepen — alleen expliciet vanuit dev/tests.

Gebruik:
    python3 -c "import sys; sys.path.insert(0,'pwa'); import brain.shadow as s; \
                import json; print(json.dumps(s.compare('USER_KEY'), indent=2, default=str))"
"""
from __future__ import annotations

from datetime import date
from time import perf_counter

from . import projections
from . import sources as _sources
from . import state as _state


def compare(user_key: str, today: date | None = None) -> dict:
    today = today or date.today()
    t0 = perf_counter()

    # v1
    v1 = {}
    try:
        import athlete_context as AC
        c1 = perf_counter()
        ctx = AC.build_athlete_context(user_key, today=today)
        v1 = {"used": AC.used_summary(ctx), "ms": int((perf_counter() - c1) * 1000)}
    except Exception as e:
        v1 = {"error": str(e)[:120]}

    # v2 — gemeten per fase
    tg = perf_counter()
    raw, health = _sources.gather(user_key, today)
    gather_ms = int((perf_counter() - tg) * 1000)
    ta = perf_counter()
    st = _state.assemble(user_key, "", raw, health, today)
    assemble_ms = int((perf_counter() - ta) * 1000)

    per_truth, per_domain, per_status = {}, {}, {}
    for e in st.evidence:
        per_truth[e.truth_type] = per_truth.get(e.truth_type, 0) + 1
        per_domain[e.domain] = per_domain.get(e.domain, 0) + 1
        per_status[e.status] = per_status.get(e.status, 0) + 1

    patterns = [{"key": e.key, "value": e.value, "strength": e.strength, "status": e.status}
                for e in st.evidence if e.domain == "training_response" or e.key.startswith("zones.structural")]
    complaints = [{"key": e.key, "status": e.status, "strength": e.strength,
                   "count": e.detail.get("count"), "last_seen_days": e.detail.get("last_seen_days")}
                  for e in st.evidence if e.key.startswith("complaint.")
                  and not e.key.startswith("complaint.mention.")]
    conflicts = [{"key": e.key, "detail": e.detail} for e in st.evidence if e.status == "CONFLICT"]

    return {
        "athlete_key": user_key,
        "source_health": [s.to_dict() for s in st.sources],
        "overall": st.overall,
        "evidence_counts": {"total": len(st.evidence), "by_truth": per_truth,
                            "by_domain": per_domain, "by_status": per_status},
        "patterns": patterns,
        "current_health": complaints,
        "conflicts": conflicts,
        "schema_projection_size": len(projections.for_schema(st)["evidence"]),
        "home_projection_size": len(projections.for_home(st)["evidence"]),
        "timings_ms": {"gather": gather_ms, "assemble": assemble_ms,
                       "total": int((perf_counter() - t0) * 1000)},
        "v1": v1,
    }


def run(user_keys: list, today: date | None = None) -> list:
    return [compare(k, today) for k in user_keys]


# ── Semantische V1↔V2 vergelijking (deterministisch, geen AI) ────────────────
_EXPECTED_CORRECTION = "EXPECTED_CORRECTION"
_EXPECTED_ENRICHMENT = "EXPECTED_ENRICHMENT"
_FORMAT_ONLY = "FORMAT_ONLY"
_UNEXPECTED = "UNEXPECTED_SEMANTIC_CHANGE"
_SOURCE_HEALTH = "SOURCE_HEALTH_DIFFERENCE"


def _num(v):
    """Trek een getal uit '35.2' of '35.2 (laatst bekend...)' of 35.2."""
    if isinstance(v, (int, float)):
        return float(v)
    try:
        import re
        m = re.search(r"-?\d+(?:[.,]\d+)?", str(v or ""))
        return float(m.group(0).replace(",", ".")) if m else None
    except Exception:
        return None


def _classify_running(v1_km, v2_km, v1_runs, v2_runs, all_km, gaps, n_nonrun=0) -> str:
    """Deterministische classificatie van het V1↔V2 running-load-verschil.

    Sportmix kan zowel km/week (fiets met afstand) ALS runs/week (elke non-run
    completed entry telde in v1 als 'run', ook zonder afstand) raken. Een
    neerwaartse correctie die verklaard wordt door aanwezige non-run sessies is
    dus EXPECTED, niet verdacht."""
    if "fs.training_log" in (gaps or []):
        return _SOURCE_HEALTH
    a1, a2 = _num(v1_km), _num(v2_km)
    r1, r2 = _num(v1_runs), _num(v2_runs)

    def _same(x, y):
        return (x is None and y is None) or (x is not None and y is not None and abs(x - y) < 0.15)

    def _lower(v1, v2):
        return v1 is not None and v2 is not None and v2 < v1 - 0.15

    km_same, runs_same = _same(a1, a2), _same(r1, r2)
    km_lower, runs_lower = _lower(a1, a2), _lower(r1, r2)
    has_nonrun = bool(n_nonrun and n_nonrun > 0)

    # Sportmix-correctie: er zíjn non-run sessies én de enige beweging is naar
    # beneden (nooit omhoog) op km en/of runs → precies de bekende v1-bug.
    if has_nonrun and (km_lower or runs_lower) \
            and (a2 is None or a1 is None or a2 <= a1 + 0.15) \
            and (r2 is None or r1 is None or r2 <= r1 + 0.15):
        return _EXPECTED_CORRECTION
    if a1 is None and a2 is not None:
        return _EXPECTED_ENRICHMENT
    if km_same and runs_same:
        return _FORMAT_ONLY
    return _UNEXPECTED


def semantic_compare(user_key: str, naam: str = "", today: date | None = None,
                     v1_ctx: dict | None = None) -> dict:
    """Deterministische, compacte V1↔V2 vergelijking voor dev/shadow-diagnostiek.

    Toont GEEN gevoelige vrije tekst (alleen getallen, keys, statussen,
    classificaties). Verwacht: cross-trainers corrigeren, pure runners blijven
    gelijk in running load."""
    today = today or date.today()
    from . import adapter as _adapter
    import athlete_context as AC

    if v1_ctx is None:
        try:
            v1_ctx = AC._build_legacy(user_key, naam, today)
        except Exception:
            v1_ctx = {}

    state, raw = _adapter.build_state(user_key, today)
    v2_ctx = _adapter.to_legacy_context(state, raw, today)

    log = raw.get("training_log") or []
    from . import activity as _activity
    run_only = _activity.running_log(log)
    all_summary = AC.training_summary(log, today) if log else {}
    run_summary = AC.training_summary(run_only, today) if run_only else {}

    v1t = (v1_ctx or {}).get("training") or {}
    v2t = v2_ctx.get("training") or {}
    gaps = sorted(set(state.source_gaps) & _adapter.SCHEMA_RELEVANT_SOURCES)

    running = {
        "v1": {"km_per_week": v1t.get("km_per_week"), "runs_per_week": v1t.get("runs_per_week"),
               "trend": v1t.get("trend"), "onderbreking": bool(v1t.get("onderbreking"))},
        "v2": {"km_per_week": v2t.get("km_per_week"), "runs_per_week": v2t.get("runs_per_week"),
               "trend": v2t.get("trend"), "onderbreking": bool(v2t.get("onderbreking"))},
        "audit": {"all_activity_km_per_week": all_summary.get("km_per_week"),
                  "run_only_km_per_week": run_summary.get("km_per_week"),
                  "n_run": len(run_only), "n_nonrun": len(log) - len(run_only)},
        "classification": _classify_running(
            v1t.get("km_per_week"), v2t.get("km_per_week"),
            v1t.get("runs_per_week"), v2t.get("runs_per_week"),
            all_summary.get("km_per_week"), gaps, len(log) - len(run_only)),
    }

    def _health_keys(ctx):
        h = (ctx or {}).get("health") or {}
        return sorted({(k.get("bron"), k.get("status")) for k in (h.get("actuele_klachten") or [])}), \
            sorted(h.get("terugkerend") or [])
    v1_ak, v1_rec = _health_keys(v1_ctx)
    v2_ak, v2_rec = _health_keys(v2_ctx)

    return {
        "athlete_key": user_key,
        "overall_v2": state.overall,
        "source_health": [{"source": s.source, "available": s.available} for s in state.sources],
        "schema_relevant_gaps": gaps,
        "running_load": running,
        "health_diff": {"v1_active_n": len(v1_ak), "v2_active_n": len(v2_ak),
                        "v1_recurring": v1_rec, "v2_recurring": v2_rec},
        "belasting_signaal": {"v1": bool(((v1_ctx or {}).get("feedback") or {}).get("belasting_signaal")),
                              "v2": bool((v2_ctx.get("feedback") or {}).get("belasting_signaal"))},
    }
