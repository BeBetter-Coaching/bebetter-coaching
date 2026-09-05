"""FinalSurge API client."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

BASE_URL = "https://beta.finalsurge.com/api"
TOKEN_FILE = os.path.expanduser("~/.fs_auth_token")

# Connect-timeout 5s, read-timeout 12s — P0 startup-repair: kapt FinalSurge
# tail-latency zodat één hangende call een sweep-worker niet 30s bezet (geen
# retry-loop; de bestaande "behoud laatste geldige snapshot"-fallback vangt een
# gedropte atleet op en de volgende achtergrond-sweep haalt 'm alsnog).
_TIMEOUT = (5, 12)
# Max parallelle requests bij per-atleet loops (P0: 8→16, halveert het aantal
# fanout-golven; pool schaalt mee via de mount hieronder → pool 16/32).
_MAX_WORKERS = 16

_token: Optional[str] = None
_coach_key: Optional[str] = None

# Roster-memo (Coach Read Performance v1): TeamAthleteList is dezelfde data voor
# élke sweep binnen één coach-read, maar werd ~7× per Home-load en 2-3× per Teampuls-
# open opnieuw over het netwerk gehaald (geen cache). Eén korte in-proces memo dedupt
# dat binnen de request-lifecycle — ZELFDE bewezen patroon als `_coach_key` en
# `_COACH_ATHLETE_MAP` (één FinalSurge-identiteit per proces). Geen nieuwe truth/store:
# alleen een read-dedup met een korte TTL, zodat een roster-mutatie snel doorkomt.
_roster_cache: Optional[list] = None
_roster_ts: float = 0.0
_ROSTER_TTL_SEC = 90
_roster_lock = threading.Lock()

# Gedeelde sessie: hergebruikt TCP/TLS-verbindingen (sneller) en is thread-safe
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(
    pool_connections=_MAX_WORKERS, pool_maxsize=_MAX_WORKERS * 2
))


# ---------------------------------------------------------------------------
# Auth token management
# ---------------------------------------------------------------------------

class TokenNotFoundError(Exception):
    pass


def _read_cached_token() -> Optional[str]:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
        return token if token else None
    return None


def save_token(token: str):
    with open(TOKEN_FILE, "w") as f:
        f.write(token.strip())
    try:
        os.chmod(TOKEN_FILE, 0o600)  # alleen eigenaar mag lezen
    except Exception:
        pass
    global _token
    _token = token.strip()
    reset_roster_cache()  # nieuw token → mogelijk andere coach/roster; memo weg


def _read_streamlit_secret_token() -> Optional[str]:
    """Lees FS_TOKEN uit Streamlit secrets als die beschikbaar zijn (cloud deployment)."""
    try:
        import streamlit as st
        token = st.secrets.get("FS_TOKEN", "")
        return token.strip() if token and token.strip() else None
    except Exception:
        return None


def get_token() -> str:
    global _token
    if _token:
        return _token
    # Gehoste PWA (Render): FS_TOKEN als omgevingsvariabele — zelfde token als
    # in Streamlit-secrets. Additief: raakt de Streamlit-paden hieronder niet.
    env = os.environ.get("FS_TOKEN", "").strip()
    if env:
        _token = env
        return _token
    # Probeer Streamlit secrets (Streamlit Cloud)
    secret = _read_streamlit_secret_token()
    if secret:
        _token = secret
        return _token
    # Dan lokaal opgeslagen token (Windows/Mac)
    cached = _read_cached_token()
    if cached:
        _token = cached
        return _token
    raise TokenNotFoundError("Geen auth-token gevonden.")


def reset_session():
    global _token, _coach_key
    _token = None
    _coach_key = None
    reset_roster_cache()  # sessie-reset → gecachete roster mag niet blijven hangen
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)


def is_mac() -> bool:
    import platform
    return platform.system() == "Darwin"


def is_windows() -> bool:
    import platform
    return platform.system() == "Windows"


def try_get_token_via_applescript() -> Optional[str]:
    """Alleen beschikbaar op macOS via AppleScript + Chrome."""
    if not is_mac():
        return None
    script = """
    tell application "Google Chrome"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "finalsurge.com" then
                    return execute t javascript "localStorage.getItem('auth-token')"
                end if
            end repeat
        end repeat
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=20
        )
        token = result.stdout.strip().strip('"')
        if token and token != "null" and len(token) > 20:
            return token
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict = None) -> dict:
    resp = _session.get(f"{BASE_URL}/{path}", params=params, headers=_headers(),
                        timeout=_TIMEOUT)
    if resp.status_code == 401:
        raise TokenNotFoundError("Sessie verlopen — vernieuw je token.")
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: dict, params: dict = None) -> dict:
    resp = _session.post(f"{BASE_URL}/{path}", json=payload, params=params,
                         headers=_headers(), timeout=_TIMEOUT)
    if resp.status_code == 401:
        raise TokenNotFoundError("Sessie verlopen — vernieuw je token.")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Bekende activity type keys (gevonden via browser-interceptie)
# ---------------------------------------------------------------------------

ACTIVITY_TYPE_KEYS = {
    "Run":           {"key": "00000001-0001-0001-0001-000000000001", "name": "Hardlopen"},
    "Bike":          {"key": "00000002-0002-0002-0002-000000000002", "name": "Fiets"},
    "Swim":          {"key": "00000003-0003-0003-0003-000000000003", "name": "Zwem"},
    "CrossTraining": {"key": "00000004-0004-0004-0004-000000000004", "name": "Cross training"},
    "Rest":          {"key": "00000006-0006-0006-0006-000000000006", "name": "Rust dag"},
    "Strength":      {"key": "00000007-0007-0007-0007-000000000007", "name": "Kracht training"},
}

# ── Deterministische workout-classificatie (ÉÉN bron van waarheid, vóór AI) ────
# Interne types: run | strength | bike | swim | cross_training | other | unknown.
# Hergebruikt de bestaande ACTIVITY_TYPE_KEYS-GUID's (hoogste waarheid) + de
# FinalSurge activity_type_name (EN + NL). GEEN agressieve keyword-guessing:
# expliciete metadata gaat vóór; titel is alleen een conservatieve laatste stap.
_TYPE_BY_GUID = {
    "00000001-0001-0001-0001-000000000001": "run",
    "00000002-0002-0002-0002-000000000002": "bike",
    "00000003-0003-0003-0003-000000000003": "swim",
    "00000004-0004-0004-0004-000000000004": "cross_training",
    "00000006-0006-0006-0006-000000000006": "other",       # Rest → geen coaching-metrics
    "00000007-0007-0007-0007-000000000007": "strength",
}
# Exacte activity_type_name-waarden (EN uit ACTIVITY_TYPE_KEYS + NL uit FinalSurge).
_TYPE_BY_NAME = {
    "run": "run", "hardlopen": "run", "running": "run",
    "bike": "bike", "fiets": "bike", "cycling": "bike",
    "swim": "swim", "zwem": "swim", "swimming": "swim",
    "crosstraining": "cross_training", "cross training": "cross_training", "cross-training": "cross_training",
    "rest": "other", "rust dag": "other", "rustdag": "other",
    "strength": "strength", "kracht training": "strength", "krachttraining": "strength",
}


def _type_from_guid(v) -> str | None:
    return _TYPE_BY_GUID.get(str(v).strip().lower()) if v else None


def _type_from_name(v) -> str | None:
    if not v:
        return None
    s = str(v).strip().lower()
    return _TYPE_BY_NAME.get(s)


def classify_workout_type(w: dict) -> str:
    """Bepaal deterministisch het workouttype VÓÓR AI, zodat queue/detail/AI dezelfde
    waarde hergebruiken en run-specifieke logica niet op niet-runs wordt toegepast.

    Volgorde (hoogste waarheid eerst, geen gok):
      1. expliciete activity_type_key (GUID) — top-level, dan Activities[0]
      2. expliciete activity_type_name (EN/NL) — top-level, dan Activities[0]
      3. conservatieve titel-fallback: alléén ondubbelzinnige krachttermen
      4. anders 'unknown' (nooit een run-aanname)
    """
    if not isinstance(w, dict):
        return "unknown"
    acts = w.get("Activities") or []
    act0 = acts[0] if (acts and isinstance(acts[0], dict)) else {}
    for src in (w.get("activity_type_key"), act0.get("activity_type_key")):
        t = _type_from_guid(src)
        if t:
            return t
    for src in (w.get("activity_type_name"), act0.get("activity_type_name")):
        t = _type_from_name(src)
        if t:
            return t
    naam = (w.get("name") or "").strip().lower()
    if any(term in naam for term in ("krachttraining", "kracht training", "strength training")):
        return "strength"
    return "unknown"


# ---------------------------------------------------------------------------
# FinalSurge API calls
# ---------------------------------------------------------------------------

def get_coach_key() -> str:
    global _coach_key
    if _coach_key:
        return _coach_key
    data = _get("Settings")
    _coach_key = (data.get("data") or {}).get("user_key") or ""
    return _coach_key


def get_raw_team_data() -> dict:
    """
    Geeft de ruwe TeamAthleteList response terug — alleen voor debug-doeleinden.
    Gebruik dit om de exacte veldnamen van atleten te inspecteren.
    """
    return _get("TeamAthleteList")


def _extract_athlete(a: dict, group_name: str, seen: set) -> Optional[dict]:
    """Helper: bouw een atleet-dict uit een raw API-object."""
    key = a.get("user_key")
    if not key or key in seen:
        return None
    seen.add(key)
    # FinalSurge slaat de coach↔atleet relatiesleutel op als "coachathlete_key"
    # (let op: geen underscore tussen coach en athlete — zo heet het in de API)
    coach_athlete_key = (
        a.get("coachathlete_key")       # correct veld naam in FinalSurge API
        or a.get("coach_athlete_key")   # alternatieve spelling als fallback
        or a.get("key")
        or key  # laatste fallback op user_key
    )
    # E-mail kan onder verschillende sleutels staan (of ontbreken)
    email = (
        a.get("email") or a.get("Email") or a.get("email_address")
        or a.get("EmailAddress") or a.get("user_email") or ""
    )
    return {
        "user_key": key,
        "coach_athlete_key": coach_athlete_key,
        "name": f"{a.get('first_name', '')} {a.get('last_name', '')}".strip(),
        "first_name": a.get("first_name", ""),
        "last_name": a.get("last_name", ""),
        "email": email,
        "group": group_name,
        # "Hide Workouts from Athlete": vaste einddatum óf X dagen vooruit
        "hide_after_date": (a.get("hide_after_date") or "")[:10] or None,
        "hide_days_out": a.get("hide_days_out"),
        "_raw_keys": list(a.keys()),  # debug: welke velden heeft dit object?
    }


def reset_roster_cache() -> None:
    """Maak de roster-memo leeg (voor tests en na een expliciete roster-mutatie)."""
    global _roster_cache, _roster_ts
    with _roster_lock:
        _roster_cache = None
        _roster_ts = 0.0


def get_athletes(refresh: bool = False) -> list[dict]:
    """Geeft alle atleten terug als platte lijst, met groepsnaam erbij.

    Korte in-proces memo (ROSTER_TTL): binnen één coach-read (of een paar seconden)
    hergebruiken alle sweeps dezelfde roster i.p.v. TeamAthleteList telkens opnieuw
    op te halen. `refresh=True` omzeilt de memo. Nooit een lege/mislukte fetch cachen."""
    global _roster_cache, _roster_ts
    if not refresh:
        with _roster_lock:
            if _roster_cache is not None and (time.monotonic() - _roster_ts) < _ROSTER_TTL_SEC:
                return list(_roster_cache)          # eigen lijst-kopie; dicts gedeeld (bestaand gedrag)
    data = _get("TeamAthleteList")
    top_groups = data.get("data") or []
    seen = set()
    result = []
    # Een atleet kan in meerdere groepen zitten. We houden ALLE groepen bij,
    # zodat uitsluiting (los schema) klopt ook als de eerste groep een andere is.
    alle_groepen: dict = {}

    for top in top_groups:
        # Geneste structuur: top → groups[] → athletes[]
        for group in top.get("groups", []):
            group_name = group.get("name") or group.get("group_name") or "Overig"
            for a in group.get("athletes", []):
                _k = a.get("user_key")
                if _k:
                    alle_groepen.setdefault(_k, []).append(group_name)
                athlete = _extract_athlete(a, group_name, seen)
                if athlete:
                    result.append(athlete)

    # Fallback: als de geneste structuur geen atleten opleverde,
    # probeer dan of de top-level items direct atleten zijn (platte structuur)
    if not result:
        for a in top_groups:
            if a.get("user_key"):
                athlete = _extract_athlete(a, "Overig", seen)
                if athlete:
                    result.append(athlete)

    # Alle groepen per atleet meegeven voor robuuste uitsluiting
    for a in result:
        a["all_groups"] = alle_groepen.get(a["user_key"], [a.get("group", "")])

    # Alleen een écht gevulde roster memoiseren — een lege/transiënte fetch nooit
    # cachen (dan retryt de volgende call), analoog aan het `_valid`-principe elders.
    if result:
        with _roster_lock:
            _roster_cache = result
            _roster_ts = time.monotonic()
    return list(result)


def is_executed_workout(w: dict) -> bool:
    """
    Of een workout daadwerkelijk is UITGEVOERD.

    has_actual_data is onbetrouwbaar: FinalSurge zet dat ook op true bij
    geplande (structured) workouts die nog niet gelopen zijn. We kijken daarom
    naar echte uitvoeringssignalen: voltooiingsstatus, stats of completion.
    """
    status = (w.get("workout_status_text") or "").strip().lower()
    if status:
        # "Planned" = nog niet gedaan; al het andere ("Completed", e.d.) wel
        return status != "planned"
    if w.get("has_stats"):
        return True
    try:
        if float(w.get("workout_completion") or 0) > 0:
            return True
    except (ValueError, TypeError):
        pass
    # Geen status-veld beschikbaar → val terug op has_actual_data
    return bool(w.get("has_actual_data"))


def get_athletes_by_group() -> dict[str, list[dict]]:
    """Geeft atleten gegroepeerd per groepsnaam."""
    athletes = get_athletes()
    groups: dict[str, list[dict]] = {}
    for a in athletes:
        g = a.get("group", "Overig")
        groups.setdefault(g, []).append(a)
    return groups


def group_is_excluded(group_name: str, exclude_groups) -> bool:
    """
    True als de groepsnaam bij een uit te sluiten groep hoort.

    Matcht als alle woorden van een zoekterm als deelstring in de groepsnaam
    voorkomen (genormaliseerd, case-insensitief). Zo vangt exclude
    {'los schema'} ook '1. Los trainingsschema', "Losse schema's" en
    'Los schema (geen feedback)', terwijl echte trainingsgroepen veilig
    blijven (die bevatten nooit zowel 'los' als 'schema').
    """
    if not exclude_groups:
        return False
    g = (group_name or "").strip().lower()
    if not g:
        return False
    for term in exclude_groups:
        woorden = term.strip().lower().split()
        if woorden and all(w in g for w in woorden):
            return True
    return False


def is_planned_workout(w: dict) -> bool:
    """
    True als deze workout een geplande training is (geen losse watch-sync).

    Een training kan op meerdere manieren gepland zijn in FinalSurge:
    via de workout builder (has_structured_workout), via een gepland
    volume/tijd op de activiteit OF op de workout zelf, of via een
    beschrijving. Eerder werd alleen naar de activiteit + beschrijving
    gekeken, waardoor builder-trainingen zonder gepland volume ten
    onrechte als 'losse activiteit' golden.
    """
    if w.get("has_structured_workout"):
        return True
    if (w.get("description") or "").strip():
        return True
    if w.get("planned_amount") or w.get("planned_duration"):
        return True
    for act in (w.get("Activities") or []):
        if act.get("planned_amount") or act.get("planned_duration"):
            return True
    return False


def _pace_to_float(pace_str) -> float:
    """Converteer pace string (bijv. '3:12' of '3:12/km') naar float min/km. Hoger = langzamer."""
    if not pace_str:
        return float('inf')
    try:
        p = str(pace_str).split('/')[0].strip()
        parts = p.split(':')
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
        return float(p)
    except Exception:
        return float('inf')


def get_workouts(user_key: str, start: date, end: date, ishistory: bool = False) -> list[dict]:
    data = _get("WorkoutList", {
        "scope": "USER",
        "scopekey": user_key,
        "startdate": start.isoformat(),
        "enddate": end.isoformat(),
        "ishistory": "true" if ishistory else "false",
        "completedonly": "false",
    })
    return data.get("data") or []


def get_workouts_deduped(user_key: str, start: date, end: date) -> list[dict]:
    """
    Haal workouts op via beide modi (history + planned) en dedupliceer op key.
    History en planned worden tegelijk opgehaald om latency te halveren.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_hist = pool.submit(get_workouts, user_key, start, end, True)
        fut_plan = pool.submit(get_workouts, user_key, start, end, False)
        try:
            w_history = fut_hist.result()
        except Exception:
            w_history = []
        try:
            w_planned = fut_plan.result()
        except Exception:
            w_planned = []
    seen_keys: set[str] = set()
    workouts = []
    for w in w_history + w_planned:
        k = w.get("key")
        if k and k not in seen_keys:
            seen_keys.add(k)
            workouts.append(w)
    return workouts


def _parallel_per_athlete(athletes: list[dict], fetch_fn) -> list:
    """
    Voer fetch_fn(athlete) parallel uit voor alle atleten.
    Geeft de niet-None resultaten terug in dezelfde volgorde als de input.
    """
    results: dict[int, object] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_fn, a): i for i, a in enumerate(athletes)}
        for fut in as_completed(futures):
            try:
                results[futures[fut]] = fut.result()
            except Exception:
                results[futures[fut]] = None
    return [results[i] for i in range(len(athletes)) if results.get(i) is not None]


def _safe_float(val):
    try:
        return round(float(val), 2) if val else None
    except (ValueError, TypeError):
        return None


def _norm_km(val, unit):
    """Normaliseer afstand naar kilometers o.b.v. de eenheid."""
    v = _safe_float(val)
    if v is None:
        return None
    u = (unit or "km").strip().lower()
    if u in ("m", "meter", "meters"):
        return round(v / 1000, 2)
    if u in ("mi", "mile", "miles"):
        return round(v * 1.60934, 2)
    if u in ("yd", "yard", "yards"):
        return round(v * 0.0009144, 2)
    if u in ("ft", "feet", "foot"):
        return round(v * 0.0003048, 2)
    return v  # km of onbekend → aannemen km


def _fetch_compressed_laps(workout_key: str, user_key: str) -> list[dict]:
    """Haal lapdata op en comprimeer naar pace + afstand + hartslag per lap.
    Lege lijst bij elke fout — lapdata is bonus, nooit blokkerend."""
    try:
        details = get_workout_details(workout_key, user_key)
        detail_acts = details.get("Activities") or []
        if not detail_acts:
            return []
        laps = []
        for lap in (detail_acts[0].get("Laps") or [])[:30]:
            if not isinstance(lap, dict):
                continue
            laps.append({
                "dist": lap.get("distance_display") or lap.get("amount"),
                "pace": lap.get("pace_display"),
                "hr":   lap.get("hr_avg"),
            })
        return laps
    except Exception:
        return []


def get_training_log(user_key: str, months: int = 4, detail_weeks: int = 6) -> list[dict]:
    """
    Haal trainingslog op voor de afgelopen X maanden.
    Voor de meest recente `detail_weeks` weken worden ook lapdata opgehaald,
    zodat de AI interval-tempo's kan onderscheiden van het overall gemiddelde.
    """
    end = date.today()
    start = end - timedelta(days=months * 30)
    detail_cutoff = end - timedelta(weeks=detail_weeks)

    workouts = get_workouts_deduped(user_key, start, end)
    if not workouts:
        return []

    result = []
    for w in workouts:
        date_str = (w.get("workout_date") or "")[:10]
        if not date_str:
            continue

        activities = w.get("Activities") or []
        act = activities[0] if activities else {}

        # Workout description (bevat de geplande structuur, bijv. "5x 1000m Z4")
        description = (w.get("description") or "").strip()
        workout_name = (w.get("name") or "").strip()
        # Als name en description hetzelfde zijn, bewaar maar één
        if description == workout_name:
            description = ""

        entry = {
            "date": date_str,
            "workout_key": w.get("key") or "",
            "name": workout_name or description or "Training",
            "description": description,
            "activity_type": (w.get("activity_type_name") or act.get("activity_type_name") or "Hardlopen"),
            "amount_type":  act.get("amount_type"),
            "planned_km":   _norm_km(act.get("planned_amount"), act.get("planned_amount_type") or act.get("amount_type")),
            "planned_min":  round(float(act.get("planned_duration")) / 60, 0) if act.get("planned_duration") else None,
            "actual_km":    _norm_km(act.get("amount"), act.get("amount_type")),
            "actual_min":   round(float(act.get("duration")) / 60, 0) if act.get("duration") else None,
            "pace":         act.get("pace_display"),       # gemiddelde pace HELE run
            "hr_avg":       act.get("hr_avg"),
            # has_actual_data is onbetrouwbaar (true ook bij geplande, niet
            # gelopen trainingen) → gebruik de echte uitvoeringsstatus, anders
            # tellen geplande km mee in het volume.
            "completed":    is_executed_workout(w),
            "is_race":      bool(w.get("is_race")),
            "post_notes":   (w.get("post_workout_notes") or "").strip(),
            "felt":         w.get("felt"),
            "effort":       w.get("effort"),
            "laps":         [],  # wordt ingevuld voor recente workouts
        }

        result.append(entry)

    # Voor recente workouts: lapdata parallel ophalen voor interval-analyse
    # (was serieel: 15-25 calls achter elkaar maakten het dossier traag).
    detail_cutoff_str = detail_cutoff.isoformat()
    detail_entries = [e for e in result
                      if e["date"] >= detail_cutoff_str and e["completed"] and e["workout_key"]]
    if detail_entries:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_compressed_laps, e["workout_key"], user_key): e
                       for e in detail_entries}
            for fut in as_completed(futures):
                futures[fut]["laps"] = fut.result()

    # Post-processing: voor race-entries, vervang data met de snelste activiteit op die dag.
    # Reden: atleten doen wu → race → cd als losse activiteiten; de wu wordt soms
    # ten onrechte als race-uitvoering gezien omdat het de eerste activiteit is.
    from collections import defaultdict as _dd2
    by_date: dict = _dd2(list)
    for entry in result:
        by_date[entry["date"]].append(entry)

    for entry in result:
        if not entry["is_race"] or not entry["completed"]:
            continue
        same_day = [
            e for e in by_date[entry["date"]]
            if e["completed"] and e["workout_key"] != entry["workout_key"]
        ]
        if not same_day:
            continue
        fastest = min(same_day, key=lambda e: _pace_to_float(e.get("pace")))
        fastest_pace = _pace_to_float(fastest.get("pace"))
        race_pace = _pace_to_float(entry.get("pace"))
        # Vervang alleen als er een duidelijk snellere activiteit is (>15% sneller)
        if fastest_pace < race_pace * 0.85:
            entry["actual_km"] = fastest.get("actual_km") or entry["actual_km"]
            entry["actual_min"] = fastest.get("actual_min") or entry["actual_min"]
            entry["pace"] = fastest.get("pace") or entry["pace"]
            entry["hr_avg"] = fastest.get("hr_avg") or entry["hr_avg"]
            entry["laps"] = fastest.get("laps") or entry["laps"]
            entry["_race_corrected"] = True  # markering voor debugging

    return sorted(result, key=lambda x: x["date"])


def get_fastest_activity_on_day(user_key: str, race_date_str: str) -> dict:
    """
    Geeft de activity-data van de snelste voltooide activiteit op een specifieke dag.
    Gebruikt in de feedback module om de echte race te identificeren (niet de warming-up).
    """
    try:
        race_dt = date.fromisoformat(race_date_str[:10])
    except Exception:
        return {}
    try:
        day_workouts = get_workouts(user_key, race_dt, race_dt, ishistory=True)
        if not day_workouts:
            day_workouts = get_workouts(user_key, race_dt, race_dt, ishistory=False)
    except Exception:
        return {}

    completed = [w for w in day_workouts if w.get("has_actual_data")]
    if not completed:
        return {}

    def _act_pace(w):
        acts = w.get("Activities") or []
        if not acts:
            return float('inf')
        return _pace_to_float(acts[0].get("pace_display"))

    fastest = min(completed, key=_act_pace)
    acts = fastest.get("Activities") or []
    return acts[0] if acts else {}


def get_workout_details(workout_key: str, user_key: str) -> dict:
    """Haal volledige workout details op (planned vs completed, activities, etc.)."""
    data = _get("WorkoutPlannedCompleted", {
        "key": workout_key,
        "scope": "USER",
        "scopekey": user_key,
    })
    return data.get("data") or {}


def get_workout_builder(workout_key: str, user_key: str) -> list[dict]:
    """
    Haal de geplande workout structuur op (zones, intervallen, stappen).
    Geeft een lijst van stappen terug, of een lege lijst als er geen structuur is.
    """
    try:
        data = _get("WorkoutBuilderGet", {
            "scope": "USER",
            "scopekey": user_key,
            "workout_key": workout_key,
            "array": "true",
            "newobject": "true",
        })
        options = (data.get("data") or {}).get("target_options") or []
        if not options:
            return []
        # Neem de eerste target option (primaire workout structuur)
        return options[0].get("steps") or []
    except Exception:
        return []


def has_real_builder(workout_key: str, user_key: str) -> bool:
    """
    Controleer of een workout een echte WorkoutBuilder structuur heeft met zone-targets.
    FinalSurge retourneert altijd een target_options structuur, ook zonder echte builder.
    Een 'echte' builder heeft stappen met targetType != 'open'.
    """
    try:
        data = _get("WorkoutBuilderGet", {
            "scope": "USER",
            "scopekey": user_key,
            "workout_key": workout_key,
            "array": "true",
            "newobject": "true",
        })
        options = (data.get("data") or {}).get("target_options") or []
        if not options:
            return False
        steps = options[0].get("steps") or []
        if not steps:
            return False
        # Controleer of er stappen zijn met echte zone-targets (niet alleen 'open')
        for step in steps:
            for t in (step.get("target") or []):
                if t.get("targetType") not in ("open", "", None):
                    return True
            # Ook inner steps van repeat-blokken controleren
            for inner in (step.get("data") or []):
                for t in (inner.get("target") or []):
                    if t.get("targetType") not in ("open", "", None):
                        return True
        return False
    except Exception:
        return False


def get_comments(workout_key: str, user_key: str) -> list[dict]:
    data = _get("WorkoutComment", {
        "scope": "USER",
        "scopeKey": user_key,
        "key": workout_key,
    })
    comments = data.get("data")
    if not comments or not isinstance(comments, list):
        return []
    # Normaliseer: zorg dat 'comment' altijd de tekst bevat (veld heet 'text' in API)
    for c in comments:
        if "comment" not in c or not c["comment"]:
            c["comment"] = c.get("text") or c.get("comment_text") or ""
    return comments


# ── Coach↔atleet relatiesleutel (badge-reset) — één keer opgebouwd + gecachet ──────
# De FinalSurge-notificatieteller reset via CoachAthleteResetCounter en heeft de
# coach↔atleet-RELATIESLEUTEL nodig — NIET de user_key. Streamlit bouwt hiervoor één
# keer een map (COACH_ATHLETE_KEY) uit de roster; de PWA deed dat per post live, wat bij
# throttle/fout None opleverde en dan (fout) op user_key terugviel. Hieronder dezelfde
# bewezen bron (get_athletes) als één gecachete map, resilient tegen transiënte FS-fouten.
_COACH_ATHLETE_MAP: dict = {}
_COACH_ATHLETE_LOCK = threading.Lock()


def build_coach_athlete_map(refresh: bool = False) -> dict:
    """Bouw (en cache) de `user_key → coach_athlete_key`-relatie-map één keer uit de roster
    (`get_athletes`) — dezelfde bron/semantiek als Streamlit's `COACH_ATHLETE_KEY`.
    RESILIENT: een lege/mislukte roster-read wist een eerder gebouwde map NIET, zodat een
    transiënte FS-hapering de reeds bekende relatiesleutels niet kwijtraakt."""
    global _COACH_ATHLETE_MAP
    if _COACH_ATHLETE_MAP and not refresh:
        return _COACH_ATHLETE_MAP
    with _COACH_ATHLETE_LOCK:
        if _COACH_ATHLETE_MAP and not refresh:
            return _COACH_ATHLETE_MAP
        try:
            nieuw = {a["user_key"]: a.get("coach_athlete_key")
                     for a in get_athletes() if a.get("user_key")}
        except Exception:
            nieuw = {}
        if nieuw:                                        # alleen overschrijven bij een échte roster
            _COACH_ATHLETE_MAP = nieuw
    return _COACH_ATHLETE_MAP


def coach_athlete_key_for(user_key: str) -> Optional[str]:
    """De ECHTE coach↔atleet-relatiesleutel voor de reset-teller, of None.

    Cache-first (geen live call per post voor bekende atleten); één verse poging bij een
    onbekende sleutel (nieuwe atleet). Geeft NOOIT `user_key` als gok terug: is de enige
    bekende waarde gelijk aan `user_key` (roster-fallback in `_extract_athlete`), dan is de
    echte relatiesleutel niet betrouwbaar bekend → None, zodat de aanroeper liever niet
    reset dan de verkeerde/geen relatie te resetten."""
    if not user_key:
        return None
    m = build_coach_athlete_map()
    if user_key not in m:
        m = build_coach_athlete_map(refresh=True)        # nieuwe atleet? één verse roster-poging
    cak = m.get(user_key)
    if not cak or cak == user_key:                       # geen echte relatiesleutel bekend
        return None
    return cak


def post_comment(workout_key: str, user_key: str, comment: str,
                 coach_athlete_key: str = None) -> dict:
    result = _post("WorkoutCommentSave", {
        "key": workout_key,
        "comment_text": comment,
        "comment_image": None,
    })
    # Reset de notificatieteller ALLEEN met een betrouwbare relatiesleutel. Nooit met een
    # gegokte user_key (dat reset de verkeerde/geen relatie → badge blijft staan). Ontbreekt
    # de sleutel, dan slaan we de reset eerlijk over (retrybaar bij een volgende post/refresh);
    # de comment-write zelf is dan al gelukt.
    if coach_athlete_key:
        mark_workout_comments_read(coach_athlete_key)
    else:
        print("[fs_client] reset overgeslagen: geen betrouwbare coach_athlete_key "
              f"(user_key={user_key}) — badge niet gereset, comment wél geplaatst")
    return result


def mark_workout_comments_read(coach_athlete_key: str) -> None:
    """
    Reset de notificatieteller achter de atleet in FinalSurge.
    Endpoint: CoachAthleteResetCounter?coach_athlete_key=<relatie-key>  (GET)
    """
    try:
        _get("CoachAthleteResetCounter", {"coach_athlete_key": coach_athlete_key})
    except Exception:
        pass  # stil falen — teller blijft staan maar app werkt gewoon door


def is_athlete_comment(c: dict, coach_key: str) -> bool:
    """Canonieke coach/atleet-classificatie van één comment (module-niveau, zodat
    zowel de queue-opbouw als een verse single-workout thread-read exact dezelfde
    waarheid gebruiken). Identiek aan de bewezen closure in get_workouts_needing_feedback:
    respecteer een expliciet `is_athlete`-veld, val anders terug op user_key≠coach_key."""
    if "is_athlete" in c:
        return bool(c["is_athlete"])
    return c.get("user_key") != coach_key


def build_thread(comments_sorted: list, post_notes: str,
                 athlete_first_name: str, coach_key: str) -> list[dict]:
    """Bouw de `van`-genormaliseerde thread voor één workout — de ENIGE bron van de
    thread-vorm (queue-opbouw én verse read gebruiken dit). Volgorde: post_notes eerst
    (atleet, geen tijdstempel, niet-tonend), daarna de comments chronologisch. Lege
    tekst wordt overgeslagen — een blanco comment is nooit een echte gesprekstobeurt."""
    thread: list[dict] = []
    if post_notes:
        thread.append({
            "tekst": post_notes,
            "van": "atleet",
            "naam": athlete_first_name,
            "timestamp": "",
            "_display": False,
        })
    for c in comments_sorted:
        tekst = c.get("comment") or ""
        if tekst.strip():
            is_coach = not is_athlete_comment(c, coach_key)
            thread.append({
                "tekst": tekst,
                "van": "coach" if is_coach else "atleet",
                "naam": c.get("first_name") or ("jij" if is_coach else athlete_first_name),
                "timestamp": c.get("timestamp", ""),
            })
    return thread


def get_workout_thread(workout_key: str, user_key: str, post_notes: str = "",
                       athlete_first_name: str = "") -> list[dict]:
    """Verse thread-state voor één workout: haalt de comments LIVE op en bouwt dezelfde
    `van`-genormaliseerde structuur als de queue (via build_thread), chronologisch
    gesorteerd. Gebruikt door Feedback bij (her)genereren zodat een athlete-comment dat
    ná de queue-opbouw binnenkwam alsnog de mode meebepaalt (geen stale gesprekstoestand)."""
    comments = get_comments(workout_key, user_key)
    coach_key = get_coach_key()
    comments_sorted = sorted(
        comments, key=lambda c: c.get("timestamp") or c.get("created_at") or "")
    return build_thread(comments_sorted, post_notes, athlete_first_name, coach_key)


def get_workouts_needing_feedback(
    days_back: int = 1,
    athlete_filter: list[str] = None,
    include_data_only: bool = False,
    include_planned_no_notes: bool = False,
    exclude_groups: set | None = None,
    return_stats: bool = False,
    include_details: bool = True,
    include_unplanned_reactions: bool = False,
) -> list[dict] | tuple[list[dict], dict]:
    """
    Geeft workouts terug die coaching-aandacht nodig hebben.

    exclude_groups: groepsnamen (case-insensitief) die volledig worden
                    overgeslagen, bijv. {"los schema"} — die atleten
                    krijgen geen feedback.
    return_stats:   geef ook statistieken terug als tweede waarde:
                    {"posted_today": n} = aantal workouts waarop vandaag
                    een coach-comment is gepost (door wie dan ook).

    Drie parallelle fasen om latency te minimaliseren:
      1. Alle atleten-workouts tegelijk ophalen (2×parallel per atleet)
      2. Comments ophalen voor pre-gefilterde candidates
      3. Workout-details ophalen voor definitief geselecteerde workouts
    """
    end = date.today()
    start = end - timedelta(days=days_back)
    today_str = date.today().isoformat()
    # Fase-timings (alleen meten, geen gedrag/scope-wijziging). Wordt via de
    # stats-dict teruggegeven zodat de Feedback-diag kan uitsplitsen waar de
    # sweep-tijd zit. Bevat geen gevoelige inhoud.
    _t_start = time.perf_counter()
    coach_key = get_coach_key()  # gecachet na eerste call
    athletes = get_athletes()
    if athlete_filter:
        athletes = [a for a in athletes if a["user_key"] in athlete_filter]
    if exclude_groups:
        athletes = [
            a for a in athletes
            if not any(group_is_excluded(g, exclude_groups)
                       for g in (a.get("all_groups") or [a.get("group")]))
        ]
    _roster_ms = int((time.perf_counter() - _t_start) * 1000)

    def _is_athlete_comment(c: dict) -> bool:
        if "is_athlete" in c:
            return bool(c["is_athlete"])
        return c.get("user_key") != coach_key

    def _ts(c: dict) -> str:
        return c.get("timestamp") or c.get("created_at") or ""

    # ── Fase 1: workouts parallel ophalen ──────────────────────────────────
    _t_fanout = time.perf_counter()
    prefetched = dict(_parallel_per_athlete(
        athletes,
        lambda a: (a["user_key"], get_workouts_deduped(a["user_key"], start, end)),
    ))
    _fanout_ms = int((time.perf_counter() - _t_fanout) * 1000)

    # ── Pre-filter op workout-data (geen API-calls nodig) ──────────────────
    candidates: list[dict] = []
    for athlete in athletes:
        user_key = athlete["user_key"]
        for w in prefetched.get(user_key, []):
            post_notes = (w.get("post_workout_notes") or "").strip()
            comment_count = w.get("CommentCount") or 0
            has_data = is_executed_workout(w)
            felt = w.get("felt")
            effort = w.get("effort")
            workout_key = w.get("key")
            if not workout_key:
                continue

            has_athlete_input = bool(post_notes or comment_count or felt or effort)
            workout_date_str = (w.get("workout_date") or "")[:10]
            is_past = bool(workout_date_str) and workout_date_str < today_str
            _planned = is_planned_workout(w)

            # Een VOLTOOIDE geplande training zonder notitie hoort altijd
            # getoond te worden, ook als die vandaag is gedaan (geen is_past-eis).
            is_planned_no_notes = has_data and not has_athlete_input and _planned
            # Data-only = voltooide LOSSE activiteit (geen plan) zonder notitie.
            is_data_only = has_data and not has_athlete_input and not _planned
            # Overgeslagen = verleden, niet gedaan, geen notitie.
            is_skipped = is_past and not has_data and not has_athlete_input

            # Een nog te doen geplande run ZONDER input telt niet als 'wachten op
            # feedback' (verwarrend). Maar een nog niet uitgevoerde run MÉT een
            # reactie/notitie van de atleet wél: die vraagt misschien iets, bijv.
            # waarom hij de training niet gaat doen. Dus we sluiten alleen runs
            # uit die niet uitgevoerd zijn ÉN geen atleet-input hebben.
            # Feedback v1 (D) — unplanned coverage: laat een UITGEVOERDE, ongeplande run zonder
            # list-level atleet-input tóch door als PROBE-kandidaat, zodat fase 2 zijn comments
            # ophaalt. Hij overleeft de comment-filter alleen als er een ECHTE atleet-comment blijkt
            # (die filter eist athlete_comments). Zo verschijnt een ad-hoc run met een atleet-reactie,
            # maar niet elke ongeplande run. Opt-in (default off → Streamlit-gedrag ongewijzigd).
            _probe_unplanned = bool(include_unplanned_reactions and is_data_only and not has_athlete_input)
            if (
                not has_athlete_input
                and not (include_data_only and (is_data_only or is_skipped))
                and not (include_planned_no_notes and is_planned_no_notes)
                and not _probe_unplanned
            ):
                continue

            candidates.append({
                "athlete": athlete,
                "w": w,
                "workout_key": workout_key,
                "_probe_unplanned": _probe_unplanned,
                "workout_date_str": workout_date_str,
                "post_notes": post_notes,
                "comment_count": comment_count,
                "felt": felt,
                "effort": effort,
                "has_athlete_input": has_athlete_input,
                "is_data_only": is_data_only,
                "is_skipped": is_skipped,
                "is_planned_no_notes": is_planned_no_notes,
            })

    # ── Fase 2: comments parallel ophalen ─────────────────────────────────
    # Fouten binnen de fetch MOETEN worden opgevangen: anders valt de hele
    # kandidaat uit _parallel_per_athlete (None → weggefilterd) en mist de
    # coach die atleet volledig. Een lege commentlijst is altijd beter dan
    # een verdwenen atleet.
    def _fetch_comments(cand: dict) -> dict:
        try:
            cand["_comments"] = (
                get_comments(cand["workout_key"], cand["athlete"]["user_key"])
                if (cand["comment_count"] or cand.get("_probe_unplanned")) else []
            )
        except Exception:
            cand["_comments"] = []
            cand["_comments_failed"] = True
        return cand

    # Aantal kandidaten dat daadwerkelijk een comment-fetch (API-call) doet.
    _comment_fetch_count = sum(1 for c in candidates if c["comment_count"] or c.get("_probe_unplanned"))
    _t_comments = time.perf_counter()
    with_comments = _parallel_per_athlete(candidates, _fetch_comments)
    _comments_ms = int((time.perf_counter() - _t_comments) * 1000)

    # Vandaag gepost: workouts met ≥1 coach-comment van vandaag — geldt voor
    # beide coaches (zelfde account) en blijft kloppen over sessies/apparaten heen
    posted_today = sum(
        1 for cand in with_comments
        if any(
            not _is_athlete_comment(c) and _ts(c)[:10] == today_str
            for c in cand["_comments"]
        )
    )

    # ── Comment-gebaseerde filter ──────────────────────────────────────────
    detail_candidates: list[dict] = []
    for cand in with_comments:
        comments = cand["_comments"]
        comments_sorted = sorted(comments, key=_ts)
        athlete_comments = [c for c in comments if _is_athlete_comment(c)]
        coach_comments   = [c for c in comments if not _is_athlete_comment(c)]
        post_notes = cand["post_notes"]
        workout_date_str = cand["workout_date_str"]

        if (
            not post_notes and not cand["felt"] and not cand["effort"]
            and not athlete_comments
            and not (include_data_only and (cand["is_data_only"] or cand["is_skipped"]))
            and not (include_planned_no_notes and cand["is_planned_no_notes"])
        ):
            continue

        last_coach_ts = max((_ts(c) for c in coach_comments), default="") if coach_comments else ""
        # >= zodat een coach-reactie op DEZELFDE dag als de training ook telt
        # (training en reactie zijn vaak dezelfde dag). Een succeswens van vóór
        # de training (datum < trainingsdatum) telt terecht níét als reactie.
        coach_responded_after = bool(last_coach_ts) and last_coach_ts[:10] >= workout_date_str
        post_notes_need_response = bool(post_notes) and not coach_responded_after

        if coach_comments and not athlete_comments:
            if not post_notes_need_response:
                continue
        if coach_comments and athlete_comments and comments_sorted:
            if not _is_athlete_comment(comments_sorted[-1]):
                continue

        cand["_athlete_comments"] = athlete_comments
        cand["_comments_sorted"] = comments_sorted
        detail_candidates.append(cand)

    # ── Fase 3: workout-details parallel ophalen ───────────────────────────
    # Ook hier fouten opvangen: details zijn alleen voor de grafiek/data, een
    # mislukte fetch mag de atleet nooit uit de lijst laten vallen.
    def _fetch_details(cand: dict) -> dict:
        try:
            cand["_details"] = get_workout_details(
                cand["workout_key"], cand["athlete"]["user_key"]
            )
        except Exception:
            cand["_details"] = {}
        return cand

    # include_details=False (lichte queue voor de PWA-inbox): sla de zware
    # workout-detail-fetch over → veel sneller. Details worden dan lazy per
    # workout opgehaald in de focus-view. Default True = ongewijzigd (Streamlit).
    if include_details:
        final = _parallel_per_athlete(detail_candidates, _fetch_details)
    else:
        final = detail_candidates

    # ── Resultaten bouwen ─────────────────────────────────────────────────
    results = []
    for cand in final:
        athlete = cand["athlete"]
        post_notes = cand["post_notes"]
        athlete_comments = cand["_athlete_comments"]
        comments_sorted = cand["_comments_sorted"]

        # Eén bron van waarheid voor de thread-vorm (queue én verse read): build_thread.
        thread = build_thread(comments_sorted, post_notes, athlete["first_name"], coach_key)

        results.append({
            "athlete_name": athlete["name"],
            "athlete_first_name": athlete["first_name"],
            "athlete_key": athlete["user_key"],
            # Coachgroep meesturen zodat de Feedback-queue erop kan groeperen
            # (centrale bron: get_athletes → group/all_groups). Extra keys →
            # Streamlit/Home negeren ze, dus backward-compatible.
            "athlete_group": athlete.get("group", ""),
            "athlete_groups": athlete.get("all_groups") or ([athlete["group"]] if athlete.get("group") else []),
            "workout_key": cand["workout_key"],
            "workout_name": cand["w"].get("name") or cand["w"].get("description") or "Training",
            "workout_date": cand["workout_date_str"],
            # Deterministisch workouttype (run/strength/bike/…): één bron van
            # waarheid zodat queue/detail/AI run-logica alleen op runs toepassen.
            "workout_type": classify_workout_type(cand["w"]),
            "post_notes": post_notes,
            "felt": cand["felt"],
            "effort": cand["effort"],
            "athlete_comments": [c.get("comment", "") for c in athlete_comments if c.get("comment")],
            "thread": thread,
            "details": cand.get("_details", {}),
            "data_only": cand["is_data_only"],
            "planned_no_notes": cand["is_planned_no_notes"],
        })

    if return_stats:
        return results, {
            "posted_today": posted_today,
            # Fase-timings + tellingen (alleen meten; geen gevoelige inhoud).
            "roster_ms": _roster_ms,
            "workouts_fanout_ms": _fanout_ms,
            "comments_ms": _comments_ms,
            "athlete_count": len(athletes),
            "candidate_count": len(candidates),
            "comment_fetch_count": _comment_fetch_count,
        }
    return results


def get_last_activity_dates(lookback_days: int = 60) -> dict:
    """
    Geeft per user_key de datum van de laatst voltooide activiteit terug
    (ISO-string) binnen de lookback. Voor het inactiviteits-signaal in admin.
    Atleten zonder voltooide activiteit krijgen None.
    """
    today = date.today()
    start = today - timedelta(days=lookback_days)
    athletes = get_athletes()

    def _last(a: dict):
        try:
            workouts = get_workouts_deduped(a["user_key"], start, today)
        except Exception:
            return (a["user_key"], None)
        done = [
            (w.get("workout_date") or "")[:10]
            for w in workouts
            if is_executed_workout(w) and w.get("workout_date")
        ]
        return (a["user_key"], max(done) if done else None)

    return dict(_parallel_per_athlete(athletes, _last))


def diagnose_athlete_feedback(user_key: str, days_back: int = 10) -> list[dict]:
    """
    Diagnose: waarom komt een workout van deze atleet wel/niet in de
    feedbacklijst? Loopt dezelfde logica na als get_workouts_needing_feedback,
    maar filtert niets weg en geeft per workout de beslissing + reden terug.
    """
    end = date.today()
    start = end - timedelta(days=days_back)
    coach_key = get_coach_key()

    def _is_athlete_comment(c: dict) -> bool:
        if "is_athlete" in c:
            return bool(c["is_athlete"])
        return c.get("user_key") != coach_key

    def _ts(c: dict) -> str:
        return c.get("timestamp") or c.get("created_at") or ""

    workouts = get_workouts_deduped(user_key, start, end)
    rapport = []
    for w in workouts:
        post_notes = (w.get("post_workout_notes") or "").strip()
        comment_count = w.get("CommentCount") or 0
        has_data = is_executed_workout(w)
        felt = w.get("felt")
        effort = w.get("effort")
        workout_key = w.get("key")
        acts = w.get("Activities") or []
        act_types = [a.get("activity_type_name") or "?" for a in acts]
        workout_date_str = (w.get("workout_date") or "")[:10]

        has_athlete_input = bool(post_notes or comment_count or felt or effort)
        _planned = is_planned_workout(w)
        # Gelijk aan get_workouts_needing_feedback: voltooide geplande training
        # zonder notitie telt altijd, ongeacht of die vandaag of eerder was.
        is_planned_no_notes = has_data and not has_athlete_input and _planned

        rij = {
            "datum": workout_date_str,
            "naam": w.get("name") or w.get("description") or "Training",
            "activiteiten": ", ".join(act_types) or "—",
            "gepland": _planned,
            "voltooid": has_data,
            "gevoel": felt,
            "rpe": effort,
            "post_notes": bool(post_notes),
            "comments": comment_count,
        }

        if not workout_key:
            rij["beslissing"] = "❌ overgeslagen"
            rij["reden"] = "geen workout_key"
            rapport.append(rij)
            continue

        if not has_athlete_input:
            if is_planned_no_notes:
                rij["beslissing"] = "✅ komt door"
                rij["reden"] = ("uitgevoerde geplande training zonder notitie. Wordt altijd "
                                "getoond (toggle 'geplande trainingen zonder notities' staat aan).")
            else:
                rij["beslissing"] = "❌ niet getoond (standaard)"
                rij["reden"] = ("losse activiteit zonder plan én zonder input van de atleet. "
                                "Komt alleen met de toggle 'ook trainingen zonder notities'.")
            rapport.append(rij)
            continue

        # Comments ophalen voor het laatste-woord-oordeel
        try:
            comments = get_comments(workout_key, user_key) if comment_count else []
        except Exception:
            comments = []
        athlete_comments = [c for c in comments if _is_athlete_comment(c)]
        coach_comments = [c for c in comments if not _is_athlete_comment(c)]
        comments_sorted = sorted(comments, key=_ts)

        last_coach_ts = max((_ts(c) for c in coach_comments), default="") if coach_comments else ""
        # >= zodat een coach-reactie op DEZELFDE dag als de training ook telt
        # (training en reactie zijn vaak dezelfde dag). Een succeswens van vóór
        # de training (datum < trainingsdatum) telt terecht níét als reactie.
        coach_responded_after = bool(last_coach_ts) and last_coach_ts[:10] >= workout_date_str
        post_notes_need_response = bool(post_notes) and not coach_responded_after

        if coach_comments and not athlete_comments and not post_notes_need_response:
            rij["beslissing"] = "❌ niet getoond"
            rij["reden"] = (f"coach reageerde al na de training ({last_coach_ts[:10]}) en er is "
                            "geen losse atleet-reactie die nog antwoord nodig heeft.")
        elif coach_comments and athlete_comments and comments_sorted and not _is_athlete_comment(comments_sorted[-1]):
            rij["beslissing"] = "❌ niet getoond"
            rij["reden"] = "laatste bericht in de thread is van de coach (atleet is aan zet, niet jij)."
        else:
            rij["beslissing"] = "✅ komt door"
            rij["reden"] = "atleet-input aanwezig, coach is aan zet."
        rapport.append(rij)

    rapport.sort(key=lambda r: r["datum"], reverse=True)
    return rapport


# ---------------------------------------------------------------------------
# Workout aanmaken (voor schema-import)
# ---------------------------------------------------------------------------

def save_workout(
    user_key: str,
    workout_date: str,          # "YYYY-MM-DD"
    name: str,
    description: str = "",
    activity_type: str = "Run",  # CSV-waarde: Run / Bike / Swim / CrossTraining / Rest
    planned_distance_km: float = None,
    planned_duration_min: float = None,
) -> dict:
    """
    Maak een geplande workout aan op de kalender van de atleet.
    activity_type: CSV-waarden zoals gedefinieerd in ACTIVITY_TYPE_KEYS.
    Geeft de API-respons terug.
    """
    type_info = ACTIVITY_TYPE_KEYS.get(activity_type, ACTIVITY_TYPE_KEYS["Run"])

    # Bouw planned waarden om
    planned_duration_sec = int(planned_duration_min * 60) if planned_duration_min else None
    planned_amount = round(float(planned_distance_km), 2) if planned_distance_km else None

    payload = {
        "key": None,
        "workout_date": f"{workout_date}T00:00:00",
        "order": 1,
        "name": name,
        "description": description,
        "is_race": False,
        "has_routes": False,
        "has_attachments": False,
        "Activity": {
            "elevation_gain_type": "me",
            "elevation_gain": None,
            "elevation_loss_type": "me",
            "elevation_loss": None,
            "activity_type_key": type_info["key"],
            "activity_type_name": type_info["name"],
            "activity_sub_type_key": "",
            "activity_sub_type_name": "",
            "planned_duration": planned_duration_sec,
            "planned_amount": planned_amount,
            "planned_amount_type": "km",
            "duration": None,
            "amount": None,
            "amount_type": "km",
            "pace": None,
            "pace_type": "km",
            "hr_avg": None,
            "hr_max": None,
            "power_avg": None,
            "power_max": None,
            "cadence_avg": None,
            "cadence_max": None,
            "calories": None,
        },
        "felt": None,
        "effort": None,
        "post_workout_notes": None,
        "save_to_library": False,
        "save_to_library_key": "00000000-0000-0000-0000-000000000000",
        "workout_time": "",
        "race_place_overall": None,
        "race_age_group": None,
    }

    resp = _post("WorkoutSave", payload, params={
        "scope": "USER",
        "scope_key": user_key,
    })

    # Valideer de response: FinalSurge geeft soms HTTP 200 maar success=False
    if not resp.get("success", True):
        msg = resp.get("message") or resp.get("error") or str(resp)
        raise RuntimeError(f"WorkoutSave mislukt: {msg}")

    return resp


def save_workout_builder(
    user_key: str,
    workout_key: str,
    target_options: list,
    workout_name: str = "",
) -> dict:
    """
    Sla de Workout Builder structuur op (zones, stappen, intervallen).
    target_options: lijst zoals teruggegeven door generate_builder_steps().
    """
    resp = _post(
        "WorkoutBuilderSave",
        {
            "target_options": target_options,
            "workout_name": workout_name,
        },
        params={
            "scope": "USER",
            "scopekey": user_key,
            "workout_key": workout_key,
        },
    )
    # FinalSurge kan HTTP 200 geven maar success=False — vang dit op
    if isinstance(resp, dict) and resp.get("success") is False:
        msg = resp.get("message") or resp.get("error") or str(resp)
        raise RuntimeError(f"WorkoutBuilderSave afgewezen door FinalSurge: {msg}")
    return resp


def get_workout_builder_raw(workout_key: str, user_key: str) -> list[dict]:
    """Volledige target_options van een workout-builder (voor het omzetten van zones)."""
    try:
        data = _get("WorkoutBuilderGet", {
            "scope": "USER", "scopekey": user_key, "workout_key": workout_key,
            "array": "true", "newobject": "true",
        })
        return (data.get("data") or {}).get("target_options") or []
    except Exception:
        return []


def _flip_zone_targets(targets, van: str, naar: str) -> int:
    """Draai zone-doeltypes om in een target-array. Geeft aantal omgezet terug.
    Alleen ZONE-doelen (pace_zone/hr_zone); vaste pace-doelen (wandelen) blijven."""
    n = 0
    for t in (targets or []):
        if isinstance(t, dict) and t.get("targetType") == van:
            t["targetType"] = naar
            n += 1
    return n


def convert_builder_target_type(target_options: list, naar: str = "hr") -> tuple[list, int]:
    """
    Zet de zone-doelen van een workout-builder om tussen tempo en hartslag.
    naar: 'hr' (tempo→hartslag) of 'tempo' (hartslag→tempo). Structuur, zone-
    nummers en wandel-/open-doelen blijven ongewijzigd. Geeft (nieuwe_opts, aantal).
    """
    import copy
    opts = copy.deepcopy(target_options)
    van_zone, naar_zone = ("pace_zone", "hr_zone") if naar == "hr" else ("hr_zone", "pace_zone")
    naar_top = "hr" if naar == "hr" else "pace"
    flips = 0
    for opt in opts:
        if not isinstance(opt, dict):
            continue
        for step in opt.get("steps") or []:
            flips += _flip_zone_targets(step.get("target"), van_zone, naar_zone)
            for inner in (step.get("data") or []):
                flips += _flip_zone_targets(inner.get("target"), van_zone, naar_zone)
        if flips and opt.get("target") in ("pace", "hr"):
            opt["target"] = naar_top
    return opts, flips


def convert_schema_zones(user_key: str, start: date, end: date, naar: str = "hr",
                         progress_callback=None) -> dict:
    """
    Zet alle geplande workouts in [start, end] om van tempo↔hartslag (alleen de
    zone-doelen). Uitgevoerde trainingen en trainingen zonder builder-structuur
    worden overgeslagen. Geeft een rapport {omgezet, overgeslagen, fouten, n_todo}.
    """
    workouts = get_workouts(user_key, start, end)
    todo = [w for w in workouts if not is_executed_workout(w) and w.get("key")]
    omgezet, overgeslagen, fouten = [], [], []
    for i, w in enumerate(todo):
        wk = w["key"]
        naam = (w.get("name") or "").strip() or "training"
        datum = (w.get("workout_date") or "")[:10]
        if progress_callback:
            progress_callback(i, len(todo), f"{datum} {naam}")
        try:
            raw = get_workout_builder_raw(wk, user_key)
            if not raw:
                overgeslagen.append(f"{datum} · {naam} (geen structuur)")
                continue
            conv, flips = convert_builder_target_type(raw, naar)
            if flips == 0:
                _al = "hartslag" if naar == "hr" else "tempo"
                overgeslagen.append(f"{datum} · {naam} (geen zones om te zetten, al op {_al}?)")
                continue
            save_workout_builder(user_key, wk, conv, naam)
            omgezet.append(f"{datum} · {naam} ({flips} stappen)")
        except Exception as e:
            fouten.append(f"{datum} · {naam}: {e}")
    return {"omgezet": omgezet, "overgeslagen": overgeslagen,
            "fouten": fouten, "n_todo": len(todo)}


def delete_workout(workout_key: str, user_key: str) -> dict:
    """Verwijder een geplande workout van de atleet (FinalSurge WorkoutDelete).

    GET met alle parameters in de query string — exact zoals de web-app het doet:
    ?scope=USER&scopekey=<user>&workout_key=<workout>. Response bevat 'success'.
    """
    resp = _get("WorkoutDelete", {
        "scope": "USER",
        "scopekey": user_key,
        "workout_key": workout_key,
    })
    if isinstance(resp, dict) and resp.get("success") is False:
        msg = resp.get("error_description") or resp.get("message") or str(resp)
        raise RuntimeError(f"WorkoutDelete afgewezen door FinalSurge: {msg}")
    return resp


# ---------------------------------------------------------------------------
# Schema-verloop
# ---------------------------------------------------------------------------

def _zone_struct_from_entry(entry: dict) -> list:
    """Parse alleen de zone-STRUCT (num/naam/low/high in native eenheid) uit één ZoneList-entry.
    Gedeeld door de primaire + secundaire modaliteit; geen tekstopmaak (die is alleen voor primair)."""
    struct = []
    for i in range(1, 11):
        name = entry.get(f"zone_{i}_name")
        low_raw = entry.get(f"zone_{i}_low")
        high_raw = entry.get(f"zone_{i}_high")
        if not name:
            break
        if low_raw is None and high_raw is None:
            break
        short_name = re.sub(r"^Zone\s*\d+\s*:\s*", "", name).strip()
        try:
            struct.append({"num": i, "naam": short_name,
                           "low": float(low_raw) if low_raw is not None else None,
                           "high": float(high_raw) if high_raw is not None else None})
        except (TypeError, ValueError):
            pass
    return struct


def _entry_zone_type(entry: dict) -> str:
    raw = (entry.get("zone_type") or entry.get("type") or "").upper()
    return "hartslag" if raw in ("H", "HR", "HEART_RATE", "HEARTRATE") else "tempo"


def get_athlete_zones(user_key: str) -> dict:
    """
    Haal zones op voor een atleet uit FinalSurge.
    Geeft een dict terug met 'zone_type', 'zones_text', en debug-info.

    v5 (additief, GEEN extra fetch): als DEZELFDE ZoneList-respons ook een run-zonetabel van de
    ANDERE modaliteit bevat (bv. naast hartslag ook tempo), dan komen die als 'secondary_zone_type'
    + 'secondary_zones' mee. Bestaande consumers negeren die keys; alleen de continue-run
    divergentie-guard gebruikt ze (recovery-run niet blanket 'goed' verklaren als de andere
    modaliteit boven het rustige bereik zat).
    """
    try:
        # Correct endpoint: ZoneList?user_key=... (geen scope/scopekey)
        data = _get("ZoneList", {"user_key": user_key})
        zones_raw = data.get("data") or []

        if not zones_raw:
            return {"error": "Geen zones gevonden (lege data)"}

        # Zoek hardloop-zones (activity_type_key bevat "run" of type 1)
        run_zones = None
        for entry in (zones_raw if isinstance(zones_raw, list) else [zones_raw]):
            atype = (
                entry.get("activity_type_name") or
                entry.get("activity_type_key") or
                entry.get("sport") or ""
            ).lower()
            if "run" in atype or "hardlo" in atype:
                run_zones = entry
                break
        if run_zones is None:
            run_zones = zones_raw[0] if isinstance(zones_raw, list) else zones_raw

        zone_type_raw = (
            run_zones.get("zone_type") or
            run_zones.get("type") or ""
        ).upper()
        # FinalSurge gebruikt "H" = Heart Rate, "P" = Pace
        zone_type = "hartslag" if zone_type_raw in ("H", "HR", "HEART_RATE", "HEARTRATE") else "tempo"

        # FinalSurge slaat zones op als losse velden: zone_1_name, zone_1_low, zone_1_high, ...
        # Tempozones worden opgeslagen in seconden/km — omzetten naar min:sec
        is_pace = (zone_type == "tempo")

        def _fmt(val):
            """Zet waarde om naar leesbare eenheid (sec→min:sec voor tempo)."""
            if val is None:
                return None
            try:
                v = float(val)
            except (TypeError, ValueError):
                return str(val)
            if is_pace and v > 60:
                m, s = divmod(int(round(v)), 60)
                return f"{m}:{s:02d}"
            return str(int(v)) if v == int(v) else str(round(v, 1))

        lines = []
        zones_struct = []  # (num, naam, low_bpm/sec, high_bpm/sec) in NATIVE eenheid
        unit = "bpm" if zone_type == "hartslag" else "min/km"
        for i in range(1, 11):
            name = run_zones.get(f"zone_{i}_name")
            low_raw = run_zones.get(f"zone_{i}_low")
            high_raw = run_zones.get(f"zone_{i}_high")
            if not name:
                break
            if low_raw is None and high_raw is None:
                break
            short_name = re.sub(r"^Zone\s*\d+\s*:\s*", "", name).strip()
            try:
                zones_struct.append({
                    "num": i, "naam": short_name,
                    "low": float(low_raw) if low_raw is not None else None,
                    "high": float(high_raw) if high_raw is not None else None,
                })
            except (TypeError, ValueError):
                pass

            # Voor tempozones: lage seconden = sneller, hoge seconden = langzamer
            # FinalSurge: low = langzame grens (hoge seconden), high = snelle grens (lage seconden)
            # Toon als "snel-langzaam min/km" (snelste grens eerst)
            if is_pace and low_raw is not None and high_raw is not None:
                try:
                    l, h = float(low_raw), float(high_raw)
                    fast, slow = (h, l) if l > h else (l, h)
                    fast_s, slow_s = _fmt(fast), _fmt(slow)
                    # Z1: sla langzame grens over als die > 10 min/km is (open grens)
                    if slow_s and int(float(slow_raw if l > h else high_raw)) > 600:
                        lines.append(f"Z{i} ({short_name}): >{fast_s} {unit}")
                    else:
                        lines.append(f"Z{i} ({short_name}): {fast_s}-{slow_s} {unit}")
                except Exception:
                    lines.append(f"Z{i} ({short_name}): {_fmt(low_raw)}-{_fmt(high_raw)} {unit}")
            elif low_raw is not None and high_raw is not None:
                lines.append(f"Z{i} ({short_name}): {_fmt(low_raw)}-{_fmt(high_raw)} {unit}")
            elif high_raw is not None:
                lines.append(f"Z{i} ({short_name}): <{_fmt(high_raw)} {unit}")
            elif low_raw is not None:
                lines.append(f"Z{i} ({short_name}): >{_fmt(low_raw)} {unit}")

        # v5 — secundaire run-zonetabel van de ANDERE modaliteit uit DEZELFDE respons (geen fetch).
        secondary_type, secondary_struct = None, []
        for entry in (zones_raw if isinstance(zones_raw, list) else [zones_raw]):
            if entry is run_zones:
                continue
            atype = (entry.get("activity_type_name") or entry.get("activity_type_key")
                     or entry.get("sport") or "").lower()
            if "run" not in atype and "hardlo" not in atype:
                continue
            et = _entry_zone_type(entry)
            if et != zone_type:
                st = _zone_struct_from_entry(entry)
                if st:
                    secondary_type, secondary_struct = et, st
                    break

        if lines:
            return {
                "zone_type": zone_type,
                "zones_text": "\n".join(lines),
                "zones": zones_struct,
                "secondary_zone_type": secondary_type,
                "secondary_zones": secondary_struct,
                "raw": run_zones,
                "endpoint_used": "ZoneList",
            }

        return {"error": "Zones gevonden maar kon ze niet parsen", "raw": run_zones}

    except Exception as e:
        return {"error": str(e)}


def zone_van_waarde(zones: list[dict], waarde: float, is_pace: bool) -> dict | None:
    """Dunne, EERLIJKE adapter op de canonieke `classify_pace_hr_zone` (FC-2, contract 1):
    geeft `{num, naam}` UITSLUITEND bij ECHTE zonemembership (IN_ZONE); een out-of-range
    waarde levert None — nooit meer een stille nearest-zone clamp die als membership oogt.
    Zo classificeert elke consumer (Feedback, Masterbrein, Schema) dezelfde waarde identiek.
    Wie de out-of-range-status wél nodig heeft, gebruikt `classify_pace_hr_zone` rechtstreeks."""
    cls = classify_pace_hr_zone(zones, waarde, is_pace)
    if cls["status"] == "IN_ZONE":
        return {"num": cls["num"], "naam": cls["naam"]}
    return None


# ── FC-2: EERLIJKE zone-classificatie + deterministische blok-assessment vóór AI ─────
# zone_van_waarde (hierboven) clampt out-of-range naar de dichtstbijzijnde zone — bewust
# behouden voor bestaande consumers (Masterbrein/Schema). Voor Feedback mag een out-of-range
# NOOIT als echte membership worden gepresenteerd; daarom onderstaande expliciete classifier.

def classify_pace_hr_zone(zones: list, waarde, is_pace: bool) -> dict:
    """Deterministische, EERLIJKE zone-classificatie: geeft expliciet aan of een waarde
    ECHT binnen een persoonlijke zone valt of daarbuiten — GEEN stille nearest-zone clamp die
    eruitziet als membership. `num`/`naam` worden ALLEEN gezet bij IN_ZONE.

    status:
      IN_ZONE            — valt binnen een persoonlijke zone (echte membership)
      ABOVE_HARDEST_ZONE — voorbij de zwaarste kant (pace: sneller dan de snelste zone;
                           HF: boven de hoogste zone)
      BELOW_EASIEST_ZONE — voorbij de makkelijkste kant (pace: langzamer dan de langzaamste;
                           HF: onder de laagste zone)
      BETWEEN_ZONES      — binnen het totale bereik maar in een gat tussen zones
      UNKNOWN            — onvoldoende/ongeldige brondata
    Extra (metadata, NOOIT membership): nearest_num/nearest_naam, delta (>=0), unit, edge.
    """
    unit = "sec/km" if is_pace else "bpm"
    res = {"status": "UNKNOWN", "num": None, "naam": None, "nearest_num": None,
           "nearest_naam": None, "delta": None, "unit": unit, "edge": None}
    if not zones or waarde is None:
        return res
    try:
        w = float(waarde)
    except (TypeError, ValueError):
        return res
    banden = []
    for z in zones:
        lo, hi = z.get("low"), z.get("high")
        grenzen = [g for g in (lo, hi) if g is not None]
        if not grenzen or "num" not in z:
            continue
        banden.append({"num": z["num"], "naam": z.get("naam", ""),
                       "onder": min(grenzen), "boven": max(grenzen)})
    if not banden:
        return res
    # 1) echte membership (inclusief ondergrens, exclusief bovengrens)
    for b in banden:
        if b["onder"] <= w < b["boven"]:
            return {**res, "status": "IN_ZONE", "num": b["num"], "naam": b["naam"]}
    # 1b) GRENS-INCLUSIVITEIT (Round-2 regressie B): een waarde EXACT op een bovengrens die niet
    # door een aangrenzende zone is geclaimd — de laatste (langzaamste/laagste) zone, óf een waarde
    # die in een 1-seconde/1-bpm gat tussen twee zones valt (FinalSurge-zonetabellen hebben zulke
    # gaten) — hoort BIJ die zone. Zo wordt 5:34, exact de bovengrens van zone 5:14–5:34, IN die zone
    # geplaatst i.p.v. als BETWEEN_ZONES ('net erbuiten'). Contigue tabellen blijven ONGEWIJZIGD: daar
    # claimde de aangrenzende zone die grens al via zijn ondergrens in de lus hierboven (consistent
    # met `_block_target_status`, dat ook inclusief is).
    for b in banden:
        if w == b["boven"]:
            return {**res, "status": "IN_ZONE", "num": b["num"], "naam": b["naam"]}
    # 2) buiten alle banden — bepaal de kant deterministisch (metadata, geen membership)
    hardste_grens = min(b["onder"] for b in banden) if is_pace else max(b["boven"] for b in banden)
    makkelijkste_grens = max(b["boven"] for b in banden) if is_pace else min(b["onder"] for b in banden)
    hardste_band = min(banden, key=lambda b: b["onder"]) if is_pace else max(banden, key=lambda b: b["boven"])
    makkelijkste_band = max(banden, key=lambda b: b["boven"]) if is_pace else min(banden, key=lambda b: b["onder"])
    voorbij_hardste = (w < hardste_grens) if is_pace else (w > hardste_grens)
    voorbij_makkelijkste = (w > makkelijkste_grens) if is_pace else (w < makkelijkste_grens)
    if voorbij_hardste:
        return {**res, "status": "ABOVE_HARDEST_ZONE", "edge": "harder",
                "nearest_num": hardste_band["num"], "nearest_naam": hardste_band["naam"],
                "delta": round(abs(w - hardste_grens), 1)}
    if voorbij_makkelijkste:
        return {**res, "status": "BELOW_EASIEST_ZONE", "edge": "easier",
                "nearest_num": makkelijkste_band["num"], "nearest_naam": makkelijkste_band["naam"],
                "delta": round(abs(w - makkelijkste_grens), 1)}
    # 3) in een gat tussen zones: dichtstbijzijnde grens als metadata
    dichtst = min(banden, key=lambda b: min(abs(w - b["onder"]), abs(w - b["boven"])))
    return {**res, "status": "BETWEEN_ZONES", "nearest_num": dichtst["num"],
            "nearest_naam": dichtst["naam"],
            "delta": round(min(abs(w - dichtst["onder"]), abs(w - dichtst["boven"])), 1)}


def _hms_to_s(v) -> float | None:
    """'MM:SS' of 'HH:MM:SS' of losse seconden → seconden. None bij onbruikbaar."""
    s = str(v or "").strip()
    if not s or s in ("00:00", "0"):
        return None
    if ":" in s:
        try:
            parts = [int(p) for p in s.split(":")]
        except ValueError:
            return None
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _dist_to_m(dist, unit) -> float | None:
    """Geplande afstand → meters (km default; 'm' = meters; 'mi' = mijl)."""
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return None
    u = (unit or "km").lower()
    if u in ("mi", "mile", "miles"):
        return d * 1609.34
    if u in ("m", "meter", "meters"):
        return d
    return d * 1000.0


def _lap_dist_m(lap: dict) -> float | None:
    a = lap.get("amount")
    try:
        return float(a) * 1000.0 if a is not None else None      # lap.amount = km
    except (TypeError, ValueError):
        return None


def _lap_time_s(lap: dict) -> float | None:
    for k in ("duration", "total_time", "moving_time", "elapsed_time",
              "total_timer_time", "time"):
        if lap.get(k) is not None:
            s = _hms_to_s(lap.get(k))
            if s:
                return s
    return None


def _planned_blocks(steps: list) -> list:
    """Geplande blokken in volgorde met type + doelzone + EXPLICIETE target-metric + geplande
    maat (dist_m/time_s) — voor de blok-assessment. Houdt WARMUP/ACTIVE/REST/COOLDOWN (anders
    dan `_plan_steps_flat`). Recurset repeat-/groepsblokken (`step['data']`). Deterministisch."""
    out: list = []

    def _walk(sts):
        for s in sts:
            if not isinstance(s, dict):
                continue
            inner = s.get("data") or []
            if inner:
                _walk(inner)
                continue
            inten = (s.get("intensity") or "").upper() or "ACTIVE"
            zone, metric = None, None
            for t in (s.get("target") or []):
                if not isinstance(t, dict):
                    continue
                tt = (t.get("targetType") or "").lower()
                if "zone" in tt and t.get("zone"):
                    try:
                        zone = int(t["zone"])
                    except (TypeError, ValueError):
                        zone = None
                    # EXPLICIETE geplande metric leidt (contract 3): pace vs HF vs anders
                    if "pace" in tt or "speed" in tt:
                        metric = "tempo"
                    elif "hr" in tt or "heart" in tt:
                        metric = "hartslag"
                    break
            dtype = (s.get("durationType") or "").upper()
            dist = s.get("durationDist")
            dur = s.get("duration") or ""
            dur_kind, dur_val, dur_label = None, None, ""
            if dtype == "DISTANCE" and dist:
                m = _dist_to_m(dist, s.get("distUnit") or "km")
                if m:
                    dur_kind, dur_val = "dist", m
                try:
                    dist_clean = int(dist) if float(dist) == int(float(dist)) else dist
                except (TypeError, ValueError):
                    dist_clean = dist
                dur_label = f"{dist_clean} {s.get('distUnit') or 'km'}"
            elif dur and dur != "00:00":
                secs = _hms_to_s(dur)
                if secs:
                    dur_kind, dur_val = "time", secs
                dur_label = f"{dur} min"
            out.append({"type": inten, "zone": zone, "metric": metric, "dur": dur_label,
                        "dur_kind": dur_kind, "dur_val": dur_val})

    _walk(steps or [])
    for i, b in enumerate(out, 1):
        b["index"] = i
    return out


def _block_lap_compatible(block: dict, lap: dict) -> bool:
    """Structurele verificatie van een positionele koppeling: de geplande maat van het blok
    (afstand óf tijd) moet binnen tolerantie overeenkomen met dezelfde maat van de lap. Kan de
    benodigde dimensie niet geverifieerd worden (ontbreekt op de lap, of het blok heeft geen
    geplande maat) → False (conservatief; dan geen MATCHED)."""
    kind = block.get("dur_kind")
    planned = block.get("dur_val")
    if kind == "dist":
        actual = _lap_dist_m(lap)
    elif kind == "time":
        actual = _lap_time_s(lap)
    else:
        return False
    if not planned or not actual:
        return False
    ratio = actual / planned
    return 0.7 <= ratio <= 1.43                          # ~±35% speling (GPS/handmatige laps)


def _block_target_status(block: dict, observed, zones: list, is_pace: bool) -> str:
    """Per-blok target-status: ON_TARGET / ABOVE_TARGET / BELOW_TARGET / UNKNOWN / NOT_EVALUATED.
    WARMUP/REST/COOLDOWN → NOT_EVALUATED (nooit als targetblok beoordelen). Geen doelzone of
    geen meetwaarde of geen zonegrenzen → UNKNOWN (geen vergelijking gokken)."""
    if block.get("type") in ("WARMUP", "REST", "COOLDOWN"):
        return "NOT_EVALUATED"
    tz = block.get("zone")
    if tz is None or observed is None:
        return "UNKNOWN"
    target = next((z for z in zones if z.get("num") == tz), None)
    if not target or target.get("low") is None or target.get("high") is None:
        return "UNKNOWN"
    lo, hi = min(target["low"], target["high"]), max(target["low"], target["high"])
    if is_pace:                                          # kleinere sec = harder
        if observed < lo:
            return "ABOVE_TARGET"
        if observed > hi:
            return "BELOW_TARGET"
        return "ON_TARGET"
    if observed > hi:                                    # hogere bpm = harder
        return "ABOVE_TARGET"
    if observed < lo:
        return "BELOW_TARGET"
    return "ON_TARGET"


def assess_workout_blocks(steps: list, laps: list, zones: list, zone_type: str) -> dict:
    """Deterministische blok-assessment vóór AI. Koppel geplande blokken aan uitgevoerde laps
    ALLEEN bij AANTOONBAAR betrouwbare structurele overeenkomst — gelijke aantallen ÉN per
    positie een geplande-maat↔lap-maat die binnen tolerantie klopt (contract 2). Gelijke
    aantallen alléén is niet genoeg (auto-laps kunnen toevallig even talrijk zijn); dan blijft
    het AMBIGUOUS. De vergelijkings-metric komt uit het GEPLANDE target (pace/HF); wijkt die af
    van de zonetabel, dan UNKNOWN i.p.v. stil converteren (contract 3). NOOIT gokken; geen
    fysiologische conclusie — alleen feiten + status.

    confidence: MATCHED | AMBIGUOUS | UNAVAILABLE (PARTIAL gereserveerd)."""
    planned = _planned_blocks(steps)
    laps = [l for l in (laps or []) if isinstance(l, dict)]
    if not planned or not laps or not zones or zone_type not in ("tempo", "hartslag"):
        return {"confidence": "UNAVAILABLE", "blocks": []}
    if len(planned) != len(laps):                        # aantallen verschillen → niet koppelbaar
        return {"confidence": "AMBIGUOUS", "blocks": [], "reason": "count_mismatch",
                "planned_count": len(planned), "lap_count": len(laps)}
    if not all(_block_lap_compatible(b, l) for b, l in zip(planned, laps)):
        # gelijke aantallen maar structuur (duur/afstand) matcht niet 1-op-1 → geen MATCHED
        return {"confidence": "AMBIGUOUS", "blocks": [], "reason": "structure_mismatch",
                "planned_count": len(planned), "lap_count": len(laps)}
    blocks = []
    for b, lap in zip(planned, laps):
        resolved = b.get("metric") or zone_type          # geplande target-metric leidt; anders zonetabel
        row = {"index": b["index"], "type": b["type"], "target_zone": b["zone"],
               "dur": b["dur"], "metric": ("tempo" if resolved == "tempo" else "hr"),
               "observed_pace": None, "observed_hr": None}
        if resolved != zone_type:
            # geplande target in andere metric dan de enige persoonlijke zonetabel → niet vergelijken
            blocks.append({**row, "status": "UNKNOWN"})
            continue
        is_pace = (resolved == "tempo")
        if is_pace:
            pm = _pace_to_float(lap.get("pace_display") or "")
            observed = pm * 60 if pm not in (0, float("inf")) else None
            row["observed_pace"] = lap.get("pace_display")
        else:
            try:
                observed = float(lap.get("hr_avg")) if lap.get("hr_avg") else None
            except (TypeError, ValueError):
                observed = None
            row["observed_hr"] = int(observed) if observed is not None else None
        blocks.append({**row, "status": _block_target_status(b, observed, zones, is_pace)})
    return {"confidence": "MATCHED", "blocks": blocks}


def get_calendar_labels(user_key: str, start: date, end: date) -> list[dict]:
    """
    Haal kalender-labels op voor een atleet in een bepaalde periode.
    Labels zijn reminders van de coach (vakantie, verjaardag, etc.)
    """
    data = _get("CalendarLabelList", {
        "scope": "USER",
        "scopekey": user_key,
        "startdate": start.isoformat(),
        "enddate": end.isoformat(),
    })
    labels = data.get("data") or []
    return [
        {
            "name": l.get("name", ""),
            "start_date": (l.get("start_date") or "")[:10],
            "end_date": (l.get("end_date") or "")[:10],
            "color": l.get("back_color", ""),
        }
        for l in labels if l.get("name")
    ]


_MIN_SCHEMA_WORKOUTS = 4  # minder dan 4 geplande trainingen = "los schema", niet tellen


def get_planned_workouts_from(user_key: str, vanaf: date, horizon_days: int = 180) -> list[dict]:
    """Geplande (gestructureerde, niet-race) trainingen voor één atleet vanaf een datum.

    Basis voor 'verlengen' (laatste datum bepalen) en 'bijsturen' (resterende
    trainingen tonen/verwijderen). Alleen echte schema-trainingen, gesorteerd op datum.
    Elk item: {'key', 'date' (YYYY-MM-DD), 'name'}.
    """
    end = vanaf + timedelta(days=horizon_days)
    try:
        workouts = get_workouts(user_key, vanaf, end)
    except Exception:
        return []
    out = []
    for w in workouts:
        wd = w.get("workout_date")
        if not wd or not w.get("has_structured_workout") or w.get("is_race"):
            continue
        d = wd[:10]
        if d < vanaf.isoformat():
            continue
        out.append({"key": w.get("key"), "date": d, "name": w.get("name", "") or "training"})
    out.sort(key=lambda x: x["date"])
    return out


def get_last_planned_date(user_key: str, horizon_days: int = 180) -> str | None:
    """Datum (YYYY-MM-DD) van de laatste geplande training vanaf vandaag, of None."""
    planned = get_planned_workouts_from(user_key, date.today(), horizon_days)
    return planned[-1]["date"] if planned else None


def get_schema_end_dates(
    horizon_days: int = 60,
    on_hold_keys: set | None = None,
) -> list[dict]:
    """
    Bepaal voor elke atleet wanneer het laatste geplande workout is.
    Geeft een gesorteerde lijst terug (vroegste einddatum eerst).

    horizon_days : hoe ver vooruit we kijken
    on_hold_keys : user_keys van atleten die buiten beschouwing blijven

    Kijkt ook 21 dagen terug: een atleet met een echt schema dat net is
    afgelopen krijgt een negatieve days_left ("verlopen") in plaats van
    onzichtbaar te worden.
    """
    today = date.today()
    start = today - timedelta(days=21)
    end = today + timedelta(days=horizon_days)
    athletes = get_athletes_by_group()
    skip = set(on_hold_keys or [])

    todo = [
        {**athlete, "_group": group_name}
        for group_name, members in athletes.items()
        for athlete in members
        if athlete["user_key"] not in skip
    ]

    def _fetch(athlete: dict) -> dict:
        user_key = athlete["user_key"]
        try:
            workouts = get_workouts(user_key, start, end)
        except Exception:
            workouts = []

        # Alleen structured workouts tellen — races en losse events worden uitgesloten.
        # Minder dan _MIN_SCHEMA_WORKOUTS = "los schema" (losse trainingen, geen echt schema).
        structured = [
            w for w in workouts
            if w.get("workout_date")
            and w.get("has_structured_workout")
            and not w.get("is_race")
        ]
        planned_dates = [w["workout_date"][:10] for w in structured]

        if len(planned_dates) >= _MIN_SCHEMA_WORKOUTS:
            last_date_str = max(planned_dates)
            days_left = (date.fromisoformat(last_date_str) - today).days
        else:
            last_date_str = None
            days_left = None

        # Zichtbaar voor de atleet: FinalSurge "Hide Workouts from Athlete".
        # Vaste einddatum (hide_after_date) of X dagen vooruit (hide_days_out).
        # De atleet ziet niets ná die datum.
        visible_until = athlete.get("hide_after_date")
        if not visible_until and athlete.get("hide_days_out") is not None:
            try:
                visible_until = (today + timedelta(days=int(athlete["hide_days_out"]))).isoformat()
            except (ValueError, TypeError):
                visible_until = None

        if visible_until:
            verborgen_dates = [d for d in planned_dates if d > visible_until]
            hidden_count = len(verborgen_dates)
            visible_days_left = (date.fromisoformat(visible_until) - today).days
        else:
            hidden_count = 0
            visible_days_left = None

        return {
            "name": athlete["name"],
            "first_name": athlete["first_name"],
            "user_key": user_key,
            "group": athlete["_group"],
            "last_date": last_date_str,
            "days_left": days_left,
            "visible_until": visible_until,
            "hidden_count": hidden_count,
            "visible_days_left": visible_days_left,
        }

    results = _parallel_per_athlete(todo, _fetch)

    # Sorteer: eerst geen schema, dan kortst lopende, dan langst
    def sort_key(r):
        if r["days_left"] is None:
            return -1
        return r["days_left"]

    results.sort(key=sort_key)
    return results


def get_compliance_alerts(
    days_back: int = 7,
    on_hold_keys: set | None = None,
    exclude_groups: set | None = None,
    score_threshold: float = 0.5,
    min_low: int = 2,
) -> list[dict]:
    """
    Vind atleten die de afgelopen week ≥ min_low geplande trainingen hebben
    gemist of grotendeels niet hebben uitgevoerd (volume < score_threshold
    van gepland). Vroege waarschuwing voor blessure of motivatieverlies.

    Trainingen van vandaag tellen niet mee (kunnen nog gedaan worden).
    """
    today = date.today()
    start = today - timedelta(days=days_back)
    end = today - timedelta(days=1)
    skip = set(on_hold_keys or [])

    athletes = [
        a for a in get_athletes()
        if a["user_key"] not in skip
        and not any(group_is_excluded(g, exclude_groups)
                    for g in (a.get("all_groups") or [a.get("group")]))
    ]

    def _check(a: dict) -> dict | None:
        workouts = get_workouts_deduped(a["user_key"], start, end)
        planned = 0
        low = 0
        for w in workouts:
            if w.get("is_race"):
                continue
            act = (w.get("Activities") or [{}])[0]
            p_km = float(act.get("planned_amount") or 0)
            p_sec = float(act.get("planned_duration") or 0)
            if not (p_km or p_sec or (w.get("description") or "").strip()):
                continue
            planned += 1
            if not w.get("has_actual_data"):
                score = 0.0
            elif p_km:
                score = min(float(act.get("amount") or 0) / p_km, 1.0)
            elif p_sec:
                score = min(float(act.get("duration") or 0) / p_sec, 1.0)
            else:
                score = 1.0  # gepland zonder doelvolume → gedaan is gedaan
            if score < score_threshold:
                low += 1
        if planned and low >= min_low:
            return {
                "name": a["name"],
                "first_name": a["first_name"],
                "user_key": a["user_key"],
                "group": a.get("group", ""),
                "n_planned": planned,
                "n_low": low,
            }
        return None

    alerts = _parallel_per_athlete(athletes, _check)
    alerts.sort(key=lambda r: -r["n_low"])
    return alerts


# ---------------------------------------------------------------------------
# Aankomende races
# ---------------------------------------------------------------------------

def detect_race_type(name: str, description: str = "") -> str:
    """Detecteer het type race op basis van naam/omschrijving."""
    text = (name + " " + description).lower()
    if "hyrox" in text:
        return "HYROX"
    if any(x in text for x in ["marathon", "42km", "42,2"]) and "halve" not in text and "half" not in text:
        return "Marathon"
    if any(x in text for x in ["halve marathon", "half marathon", "21km", "21,1", "hm"]):
        return "Halve marathon"
    if any(x in text for x in ["10km", "10 km", "10k"]):
        return "10 km"
    if any(x in text for x in ["5km", "5 km", "5k"]):
        return "5 km"
    if any(x in text for x in ["triatlon", "triathlon", "ironman"]):
        return "Triathlon"
    if any(x in text for x in ["15km", "15 km"]):
        return "15 km"
    if any(x in text for x in ["cross", "veldloop"]):
        return "Veldloop / Cross"
    return "Race"


def get_upcoming_races(days_ahead: int = 21, athlete_filter: list[str] = None) -> list[dict]:
    """
    Geeft een lijst van aankomende races (is_race=True) voor alle atleten.
    days_ahead: hoeveel dagen vooruit kijken (standaard 21).
    """
    today = date.today()
    end = today + timedelta(days=days_ahead)
    athletes_by_group = get_athletes_by_group()
    coach_key = get_coach_key()

    todo = [
        {**athlete, "_group": group_name}
        for group_name, members in athletes_by_group.items()
        for athlete in members
        if not athlete_filter or athlete["user_key"] in athlete_filter
    ]

    def _is_coach_comment(c: dict) -> bool:
        if "is_athlete" in c:
            return not bool(c["is_athlete"])
        return c.get("user_key") == coach_key

    def _fetch(athlete: dict) -> list[dict]:
        user_key = athlete["user_key"]
        try:
            workouts = get_workouts(user_key, today, end)
        except Exception:
            return []

        races = []
        for w in workouts:
            if not w.get("is_race"):
                continue
            workout_key = w.get("key") or w.get("workout_key")
            if not workout_key:
                continue

            workout_date = (w.get("workout_date") or "")[:10]
            name = w.get("name") or w.get("description") or "Race"
            description = w.get("description") or ""
            race_type = detect_race_type(name, description)

            # Bestaande comments ophalen. Een coach-comment = wens al gegeven
            # (geldt voor beide coaches, blijft kloppen over sessies/apparaten).
            comment_count = w.get("CommentCount") or 0
            try:
                comments = get_comments(workout_key, user_key) if comment_count else []
            except Exception:
                comments = []
            wish_given = any(_is_coach_comment(c) for c in comments)

            races.append({
                "athlete_name": athlete["name"],
                "athlete_first_name": athlete["first_name"],
                "athlete_key": user_key,
                "workout_key": workout_key,
                "workout_name": name,
                "workout_date": workout_date,
                "race_type": race_type,
                "description": description,
                "comments": comments,
                "wish_given": wish_given,
                "group": athlete["_group"],
            })
        return races

    results = [race for races in _parallel_per_athlete(todo, _fetch) for race in races]
    results.sort(key=lambda r: r["workout_date"])
    return results


def get_recent_race_context(user_key: str, race_name: str, weeks_back: int = 8) -> str:
    """
    Zoek in recente trainingen (post_workout_notes + comments) naar opmerkingen
    over de aankomende race. Geeft relevante tekst terug als context voor de AI.
    """
    today = date.today()
    start = today - timedelta(weeks=weeks_back)
    coach_key = get_coach_key()

    try:
        workouts = get_workouts(user_key, start, today)
    except Exception:
        return ""

    snippets = []
    race_keywords = [w.lower() for w in race_name.split() if len(w) > 3]

    for w in workouts:
        notes = (w.get("post_workout_notes") or "").strip()
        if notes and any(kw in notes.lower() for kw in race_keywords):
            snippets.append(f"[{w.get('workout_date','')[:10]}] Notitie atleet: {notes[:300]}")

        comment_count = w.get("CommentCount") or 0
        if comment_count:
            try:
                comments = get_comments(w.get("key") or "", user_key)
                for c in comments:
                    tekst = (c.get("comment") or c.get("text") or "").strip()
                    if tekst and any(kw in tekst.lower() for kw in race_keywords):
                        is_coach = c.get("user_key") == coach_key
                        label = "Coach" if is_coach else "Atleet"
                        snippets.append(f"[{w.get('workout_date','')[:10]}] {label}: {tekst[:300]}")
            except Exception:
                pass

    return "\n".join(snippets[:8])  # max 8 fragmenten
