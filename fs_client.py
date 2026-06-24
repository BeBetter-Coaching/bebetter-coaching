"""FinalSurge API client."""

from __future__ import annotations

import os
import re
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

BASE_URL = "https://beta.finalsurge.com/api"
TOKEN_FILE = os.path.expanduser("~/.fs_auth_token")

# Connect-timeout 5s, read-timeout 30s — voorkomt dat de app oneindig hangt
_TIMEOUT = (5, 30)
# Max parallelle requests bij per-atleet loops
_MAX_WORKERS = 8

_token: Optional[str] = None
_coach_key: Optional[str] = None

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
    # Probeer Streamlit secrets eerst (cloud)
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


def get_athletes() -> list[dict]:
    """Geeft alle atleten terug als platte lijst, met groepsnaam erbij."""
    data = _get("TeamAthleteList")
    top_groups = data.get("data") or []
    seen = set()
    result = []

    for top in top_groups:
        # Geneste structuur: top → groups[] → athletes[]
        for group in top.get("groups", []):
            group_name = group.get("name") or group.get("group_name") or "Overig"
            for a in group.get("athletes", []):
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

    return result


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

        def _safe_float(val):
            try:
                return round(float(val), 2) if val else None
            except (ValueError, TypeError):
                return None

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
            "activity_type": (w.get("activity_type_name") or "Hardlopen"),
            "planned_km":   _safe_float(act.get("planned_amount")),
            "planned_min":  round(float(act.get("planned_duration")) / 60, 0) if act.get("planned_duration") else None,
            "actual_km":    _safe_float(act.get("amount")),
            "actual_min":   round(float(act.get("duration")) / 60, 0) if act.get("duration") else None,
            "pace":         act.get("pace_display"),       # gemiddelde pace HELE run
            "hr_avg":       act.get("hr_avg"),
            "completed":    bool(w.get("has_actual_data")),
            "is_race":      bool(w.get("is_race")),
            "post_notes":   (w.get("post_workout_notes") or "").strip(),
            "felt":         w.get("felt"),
            "effort":       w.get("effort"),
            "laps":         [],  # wordt ingevuld voor recente workouts
        }

        # Voor recente workouts: haal lapdata op voor interval-analyse
        if date_str >= detail_cutoff.isoformat() and entry["completed"] and entry["workout_key"]:
            try:
                details = get_workout_details(entry["workout_key"], user_key)
                detail_acts = details.get("Activities") or []
                if detail_acts:
                    raw_laps = detail_acts[0].get("Laps") or []
                    # Comprimeer: bewaar alleen pace + afstand + hartslag per lap
                    laps = []
                    for lap in raw_laps[:30]:
                        if not isinstance(lap, dict):
                            continue
                        laps.append({
                            "dist": lap.get("distance_display") or lap.get("amount"),
                            "pace": lap.get("pace_display"),
                            "hr":   lap.get("hr_avg"),
                        })
                    entry["laps"] = laps
            except Exception:
                pass  # lapdata is bonus, nooit blokkerend

        result.append(entry)

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


def post_comment(workout_key: str, user_key: str, comment: str,
                 coach_athlete_key: str = None) -> dict:
    result = _post("WorkoutCommentSave", {
        "key": workout_key,
        "comment_text": comment,
        "comment_image": None,
    })
    # Na het posten direct markeren als gelezen zodat het getal in FinalSurge verdwijnt
    mark_workout_comments_read(coach_athlete_key or user_key)
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


def get_workouts_needing_feedback(
    days_back: int = 1,
    athlete_filter: list[str] = None,
    include_data_only: bool = False,
    include_planned_no_notes: bool = False,
    exclude_groups: set | None = None,
    return_stats: bool = False,
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
    coach_key = get_coach_key()  # gecachet na eerste call
    athletes = get_athletes()
    if athlete_filter:
        athletes = [a for a in athletes if a["user_key"] in athlete_filter]
    if exclude_groups:
        athletes = [a for a in athletes
                    if not group_is_excluded(a.get("group"), exclude_groups)]

    def _is_athlete_comment(c: dict) -> bool:
        if "is_athlete" in c:
            return bool(c["is_athlete"])
        return c.get("user_key") != coach_key

    def _ts(c: dict) -> str:
        return c.get("timestamp") or c.get("created_at") or ""

    # ── Fase 1: workouts parallel ophalen ──────────────────────────────────
    prefetched = dict(_parallel_per_athlete(
        athletes,
        lambda a: (a["user_key"], get_workouts_deduped(a["user_key"], start, end)),
    ))

    # ── Pre-filter op workout-data (geen API-calls nodig) ──────────────────
    candidates: list[dict] = []
    for athlete in athletes:
        user_key = athlete["user_key"]
        for w in prefetched.get(user_key, []):
            post_notes = (w.get("post_workout_notes") or "").strip()
            comment_count = w.get("CommentCount") or 0
            has_data = bool(w.get("has_actual_data"))
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

            # Een run hoort pas in de feedbacklijst als hij ook echt is
            # UITGEVOERD. Een nog te doen geplande run (ook van vandaag), zelfs
            # met een comment erop, telt niet als 'wachten op feedback' — dat is
            # verwarrend. Enige uitzondering: gemiste/overgeslagen trainingen die
            # je expliciet via de 'zonder notities'-toggle wilt zien.
            if not has_data and not (include_data_only and is_skipped):
                continue

            if (
                not has_athlete_input
                and not (include_data_only and (is_data_only or is_skipped))
                and not (include_planned_no_notes and is_planned_no_notes)
            ):
                continue

            candidates.append({
                "athlete": athlete,
                "w": w,
                "workout_key": workout_key,
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
                if cand["comment_count"] else []
            )
        except Exception:
            cand["_comments"] = []
            cand["_comments_failed"] = True
        return cand

    with_comments = _parallel_per_athlete(candidates, _fetch_comments)

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
        coach_responded_after = bool(last_coach_ts) and last_coach_ts[:10] > workout_date_str
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

    final = _parallel_per_athlete(detail_candidates, _fetch_details)

    # ── Resultaten bouwen ─────────────────────────────────────────────────
    results = []
    for cand in final:
        athlete = cand["athlete"]
        post_notes = cand["post_notes"]
        athlete_comments = cand["_athlete_comments"]
        comments_sorted = cand["_comments_sorted"]

        thread: list[dict] = []
        if post_notes:
            thread.append({
                "tekst": post_notes,
                "van": "atleet",
                "naam": athlete["first_name"],
                "timestamp": "",
                "_display": False,
            })
        for c in comments_sorted:
            tekst = c.get("comment") or ""
            if tekst.strip():
                is_coach = not _is_athlete_comment(c)
                thread.append({
                    "tekst": tekst,
                    "van": "coach" if is_coach else "atleet",
                    "naam": c.get("first_name") or ("jij" if is_coach else athlete["first_name"]),
                    "timestamp": c.get("timestamp", ""),
                })

        results.append({
            "athlete_name": athlete["name"],
            "athlete_first_name": athlete["first_name"],
            "athlete_key": athlete["user_key"],
            "workout_key": cand["workout_key"],
            "workout_name": cand["w"].get("name") or cand["w"].get("description") or "Training",
            "workout_date": cand["workout_date_str"],
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
        return results, {"posted_today": posted_today}
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
            if w.get("has_actual_data") and w.get("workout_date")
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
        has_data = bool(w.get("has_actual_data"))
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
        coach_responded_after = bool(last_coach_ts) and last_coach_ts[:10] > workout_date_str
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


def delete_workout(workout_key: str, user_key: str) -> dict:
    """Verwijder een workout van de atleet."""
    return _post("WorkoutDelete", {"key": workout_key}, params={
        "scope": "USER",
        "scope_key": user_key,
    })


# ---------------------------------------------------------------------------
# Schema-verloop
# ---------------------------------------------------------------------------

def get_athlete_zones(user_key: str) -> dict:
    """
    Haal zones op voor een atleet uit FinalSurge.
    Geeft een dict terug met 'zone_type', 'zones_text', en debug-info.
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

        if lines:
            return {
                "zone_type": zone_type,
                "zones_text": "\n".join(lines),
                "raw": run_zones,
                "endpoint_used": "ZoneList",
            }

        return {"error": "Zones gevonden maar kon ze niet parsen", "raw": run_zones}

    except Exception as e:
        return {"error": str(e)}


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
        and not group_is_excluded(a.get("group"), exclude_groups)
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
