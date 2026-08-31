"""Feedback — ISO-kalenderweek overzicht (maandag → zondag).

PRESENTATIE-ONLY dag-aggregatie voor het weekoverzicht/-chart in de Feedback-
cockpit. Buckets de al-bestaande trainingslog-entries per ISO-kalenderweek
(ma–zo) → dag-run-km + weektotalen.

BELANGRIJK — dit is GEEN nieuwe belastings-waarheid. De canonieke belasting-%
blijft de app-brede ROLLING-7-daagse waarde uit `belasting.analyse_belasting`
→ `coach_read.load_metric` (getoond via `/api/cockpit`.load_observation). Deze
module herberekent die NIET en toont geen concurrerend "+X%". Het levert enkel
een kalenderweek-VOLUME-beeld (dag-km + weekvolume + optioneel weekduur/tempo)
voor de grafiek — twee verschillende concepten, niet als dezelfde metriek.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS
from dossier import _is_run, _run_km

_DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]


def iso_week_range(ref: date) -> tuple[date, date]:
    """Maandag→zondag van de ISO-week waarin `ref` valt (weekday(): ma=0 … zo=6)."""
    monday = ref - timedelta(days=ref.weekday())
    return monday, monday + timedelta(days=6)


def _entry_dag(e: dict) -> str:
    return str(e.get("date") or "")[:10]


def _act_seconds(w: dict) -> float:
    """Uitgevoerde duur (seconden) uit de eerste activiteit; 0 als onbekend."""
    acts = w.get("Activities") or []
    act = acts[0] if acts else {}
    try:
        return float(act.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def week_overzicht(entries: list[dict], ref_date: date, workouts: list[dict] | None = None,
                   today: date | None = None) -> dict:
    """Bucket run-km per dag over de ISO-kalenderweek (ma–zo) van `ref_date`.

    `entries`  : trainingslog-entries (belasting._entry_van_workout-vorm: date,
                 actual_km, completed, activity_type/name).
    `workouts` : optioneel de ruwe FS-workouts (voor duur/tempo-weektotalen).
    Alléén VOLTOOIDE runs tellen mee voor het km-volume (zelfde regel als de
    canonieke analyse); dagen zonder run blijven 0. Toekomstige dagen (na
    `today`) worden als projectie gemarkeerd, nooit als 0-prestatie verward.
    """
    today = today or date.today()
    monday, sunday = iso_week_range(ref_date)
    week_num = ref_date.isocalendar()[1]

    per_dag: dict[str, float] = {}
    for e in entries:
        try:
            d = date.fromisoformat(_entry_dag(e))
        except ValueError:
            continue
        if d < monday or d > sunday:
            continue
        if not e.get("completed") or not _is_run(e):
            continue
        km = _run_km(e)
        if km > 0:
            per_dag[d.isoformat()] = per_dag.get(d.isoformat(), 0.0) + km

    dagen = []
    for i in range(7):
        d = monday + timedelta(days=i)
        iso = d.isoformat()
        dagen.append({
            "dag": _DAGEN[i],
            "datum": iso,
            "label": f"{_DAGEN[i]} {d.day}",
            "km": round(per_dag.get(iso, 0.0), 1),
            "is_future": d > today,
            "is_today": d == today,
        })

    weekvolume = round(sum(x["km"] for x in dagen), 1)

    # Optionele weekduur/-tempo alléén als de ruwe workouts een duur dragen
    # (anders eerlijk weglaten — geen verzonnen totaal).
    totale_sec = 0.0
    if workouts:
        for w in workouts:
            try:
                d = date.fromisoformat((w.get("workout_date") or "")[:10])
            except ValueError:
                continue
            if monday <= d <= sunday and FS.is_executed_workout(w):
                totale_sec += _act_seconds(w)
    duur = _format_duur(totale_sec) if totale_sec > 0 else None
    tempo = _tempo(totale_sec, weekvolume) if (totale_sec > 0 and weekvolume > 0) else None

    return {
        "week": week_num, "maandag": monday.isoformat(), "zondag": sunday.isoformat(),
        "range_label": f"ma {monday.day} {_MND[monday.month - 1]} – zo {sunday.day} {_MND[sunday.month - 1]}",
        "dagen": dagen, "weekvolume_km": weekvolume,
        "totale_duur": duur, "gem_tempo": tempo,
    }


_MND = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]


def _format_duur(sec: float) -> str:
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _tempo(sec: float, km: float) -> str:
    """Gemiddeld tempo (min/km) over de week-run-km."""
    if km <= 0:
        return ""
    per_km = sec / km
    m, s = divmod(int(round(per_km)), 60)
    return f"{m}:{s:02d}"


def week_for_athlete(user_key: str, ref_date: date, today: date | None = None) -> dict:
    """Laadt de ISO-week (ma–zo) van `ref_date` voor één atleet en aggregeert.
    Read-only; hergebruikt de bestaande FS-toegang (get_workouts_deduped)."""
    from belasting import _entry_van_workout
    monday, sunday = iso_week_range(ref_date)
    workouts = FS.get_workouts_deduped(user_key, monday, sunday)
    entries = [_entry_van_workout(w) for w in workouts]
    return week_overzicht(entries, ref_date, workouts=workouts, today=today)
