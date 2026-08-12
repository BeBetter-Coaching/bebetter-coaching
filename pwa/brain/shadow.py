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
