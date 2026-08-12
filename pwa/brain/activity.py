"""Masterbrein v2 — één canonieke running-selectie (Fase A).

HARD PRODUCTREGEL: alle hardloopmetrics (km/week, runs/week, running duration,
load-trend, running compliance, running interruption, distance deviation,
well_tolerated, possible_relation, structural_over_zone) mogen UITSLUITEND echte
hardloopactiviteiten bevatten. Fietsen/wandelen/zwemmen/kracht/HYROX tellen NOOIT
stil mee als hardloopkilometers.

Er wordt GEEN derde classifier uitgevonden: dit hergebruikt de bewezen canonieke
`dossier._is_run` / `dossier._run_km` (dezelfde die `belasting.py` gebruikt). Elke
running-derivation loopt via `running_log()` zodat downstream niet opnieuw hoeft te
gokken of iets hardlopen is.
"""
from __future__ import annotations

from dossier import _is_run, _run_km


def is_running_activity(workout: dict) -> bool:
    """Canoniek: is deze activiteit hardlopen? (wandelen/fietsen/etc. = False)."""
    return _is_run(workout)


def run_km(workout: dict) -> float:
    """Canonieke hardloop-km van één entry (0 voor niet-run; sanity-cap uit dossier)."""
    return _run_km(workout)


def running_log(log: list) -> list:
    """Filter een trainingslog tot ALLEEN hardloopactiviteiten, met run-only km.

    Elke behouden entry krijgt `actual_km` = canonieke hardloop-km (0 voor een
    niet-run wordt sowieso uitgefilterd). Overige velden (datum, planned, felt,
    effort, is_race, pace, hr) blijven ongewijzigd zodat downstream-derivaties er
    normaal op werken."""
    out = []
    for e in log or []:
        if not _is_run(e):
            continue
        out.append({**e, "actual_km": _run_km(e)})
    return out
