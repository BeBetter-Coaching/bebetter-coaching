"""Masterbrein v2 — L1 bronnen + source health (Fase A).

Elke bron levert `(data, SourceHealth)`. De harde invariant: LEEG en GEFAALD
zijn nooit dezelfde toestand. Een geslaagde fetch die niets vindt → available,
niet-stale. Een exception of ontbrekende credential → unavailable + error.

Alleen goedkope bronnen die Masterbrein v1 al gebruikt + zones. GEEN
comments/thread/workout-builder fan-out (te duur voor een standaard build).
Dit is de enige onzuivere laag; `assemble()` (state.py) werkt puur op de output.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

_HIER = os.path.dirname(os.path.abspath(__file__))
_PWA = os.path.dirname(_HIER)
_ROOT = os.path.dirname(_PWA)
for _p in (_ROOT, _PWA):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import intake_store

from .models import SourceHealth


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ok(source, data, coverage=None):
    cs, ce = (coverage or ("", ""))
    return data, SourceHealth(source=source, available=True, stale=False,
                              last_success=_now_iso(), coverage_start=str(cs),
                              coverage_end=str(ce))


def _fail(source, err, fallback):
    return fallback, SourceHealth(source=source, available=False, stale=False,
                                  error=str(err)[:120])


def _fs_ready() -> bool:
    """FinalSurge bruikbaar? Zonder token nooit 'gefaald' loggen als netwerkfout."""
    try:
        import fs_client as FS
        return bool(FS.get_token())
    except Exception:
        return False


def gather(user_key: str, today: date | None = None) -> tuple[dict, list]:
    """Verzamel alle Fase-A-bronnen. Geeft (raw, health[]). Nooit een exception
    naar boven: elke bron valt terug op leeg + een expliciete unavailable-health."""
    today = today or date.today()
    raw: dict = {}
    health: list = []

    # ── intake (nieuwste) ───────────────────────────────────────────────────
    try:
        intakes = intake_store.load_intakes() or {}
        laatste = intake_store.load_laatste_intakes() or {}
        ik = intake_store.nieuwste_intake(intakes.get(user_key), laatste.get(user_key)) or {}
        ik = ik if isinstance(ik, dict) else {}
        raw["intake"] = ik
        raw["intake_ts"] = intake_store._intake_ts(ik) if ik else ""
        d, h = _ok("intake", ik)
        health.append(h)
    except Exception as e:
        raw["intake"], raw["intake_ts"] = {}, ""
        health.append(_fail("intake", e, {})[1])

    # ── goedkope intake_store-bronnen ───────────────────────────────────────
    for name, src, fn in (
        ("notes", "coach_notes", lambda: intake_store.load_notes().get(user_key, [])),
        ("profiel", "coach_memory",
         lambda: (intake_store.load_profielen().get(user_key, {}) or {}).get("profiel", "")),
        ("on_hold", "on_hold", lambda: intake_store.load_on_hold().get(user_key)),
        ("garmin", "garmin", lambda: intake_store.garmin_context_text(user_key)),
    ):
        try:
            raw[name] = fn()
            health.append(_ok(src, raw[name])[1])
        except Exception as e:
            raw[name] = None
            health.append(_fail(src, e, None)[1])

    # ── belasting-stand (opgeslagen; geen herberekening) ────────────────────
    try:
        stand = intake_store.load_belasting() or {}
        res = next((r for r in stand.get("resultaten", []) if r.get("user_key") == user_key), None)
        if res:
            res = dict(res)
            res["_stand_datum"] = stand.get("datum")
            res["_afgehandeld"] = user_key in (stand.get("afgehandeld") or {})
        raw["belasting"] = res
        health.append(_ok("belasting", res or {}, coverage=(stand.get("datum", ""), stand.get("datum", "")))[1])
    except Exception as e:
        raw["belasting"] = None
        health.append(_fail("belasting", e, None)[1])

    # ── FinalSurge: trainingslog + kalenderlabels + zones ───────────────────
    if not _fs_ready():
        for src in ("fs.training_log", "fs.labels", "fs.zones"):
            health.append(SourceHealth(source=src, available=False, error="geen FinalSurge-sessie"))
        raw["training_log"], raw["labels"], raw["zones"] = [], [], {}
        return raw, health

    import fs_client as FS
    start = today - timedelta(days=120)
    try:
        raw["training_log"] = FS.get_training_log(user_key, months=4)
        health.append(_ok("fs.training_log", raw["training_log"], coverage=(start, today))[1])
    except Exception as e:
        raw["training_log"] = []
        health.append(_fail("fs.training_log", e, [])[1])

    try:
        raw["labels"] = FS.get_calendar_labels(user_key, today - timedelta(days=7),
                                                today + timedelta(days=90))
        health.append(_ok("fs.labels", raw["labels"], coverage=(today - timedelta(days=7),
                                                                 today + timedelta(days=90)))[1])
    except Exception as e:
        raw["labels"] = []
        health.append(_fail("fs.labels", e, [])[1])

    try:
        z = FS.get_athlete_zones(user_key) or {}
        if z.get("error"):
            raw["zones"] = {}
            health.append(SourceHealth(source="fs.zones", available=False, error=str(z["error"])[:120]))
        else:
            raw["zones"] = z
            health.append(_ok("fs.zones", z)[1])
    except Exception as e:
        raw["zones"] = {}
        health.append(_fail("fs.zones", e, {})[1])

    return raw, health
