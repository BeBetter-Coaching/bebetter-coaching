"""Feedback-module voor de PWA — AI-concept op de trainingen van atleten.

Hergebruikt fs_client (welke trainingen aandacht nodig hebben) + ai_feedback
(het AI-concept, in de stijl van de coach). V1 = ophalen + concept genereren +
kopiëren; het terugschrijven van de reactie naar FinalSurge is een aparte
write-stap (net als de schema-push) en volgt later.

Lui importeren: ai_feedback importeert ai_client → anthropic.Anthropic() dat
zonder ANTHROPIC_API_KEY al bij import crasht. Daarom pas binnen genereer().
fs_client is veilig te importeren (geen AI). De volledige workout-dicts cachen
we kort in het geheugen, zodat genereer() niet de zware lijst-call hoeft te
herhalen.
"""
from __future__ import annotations

import os
import sys
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS                                  # veilig: geen AI
import intake_store                                     # skip-opslag + on-hold (gedeeld met Streamlit)

_cache: dict[str, dict] = {}                            # workout_key -> volledige workout_data


def heeft_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def _reacties(w: dict) -> list[str]:
    out = []
    for c in (w.get("athlete_comments") or []):
        if isinstance(c, str):
            tekst = c
        elif isinstance(c, dict):
            tekst = c.get("comment") or c.get("text") or c.get("message") or ""
        else:
            tekst = ""
        if tekst.strip():
            out.append(tekst.strip())
    return out


def te_beoordelen(days_back: int = 7) -> dict:
    """Trainingen die coaching-aandacht nodig hebben, genormaliseerd voor de lijst.

    Zelfde vlaggen als de Streamlit-home-telling: ook UITGEVOERDE geplande
    trainingen zónder tekstje meenemen (include_planned_no_notes), en de groep
    'los schema' uitsluiten. Zo zie je iedereen die getraind heeft, niet alleen
    wie iets typte.
    """
    if not heeft_token():
        return {"items": [], "fs": False}
    try:
        workouts = FS.get_workouts_needing_feedback(
            days_back=days_back,
            include_planned_no_notes=True,
            exclude_groups={"los schema"},
        )
    except Exception:
        return {"items": [], "fs": True, "err": "Kon FinalSurge niet bereiken."}

    workouts = _filter_skipped(workouts)                # overgeslagen eruit
    items = []
    for w in workouts:
        wid = w.get("workout_key") or (str(w.get("athlete_key", "")) + ":" + str(w.get("workout_date", "")))
        _cache[wid] = w
        naam = w.get("athlete_name", "")
        items.append({
            "id": wid,
            "naam": naam,
            "voornaam": w.get("athlete_first_name") or (naam.split(" ")[0] if naam else ""),
            "datum": (w.get("workout_date") or "")[:10],
            "workout": w.get("workout_name") or "Training",
            "notitie": (w.get("post_notes") or "").strip(),
            "reacties": _reacties(w),
            "gesprek": _gesprek(w),
        })
    return {"items": items, "fs": True}


def genereer(wid: str) -> str:
    """AI-concept voor de training met dit id (uit de gecachete lijst)."""
    w = _cache.get(wid)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst en probeer opnieuw.")
    import ai_feedback                                   # lui: pas hier is de key nodig
    return ai_feedback.generate_feedback(w)


def _coach_athlete_key(athlete_key: str):
    """De coach-atleet-relatiesleutel (om de teller in FinalSurge te resetten)."""
    try:
        for a in FS.get_athletes():
            if a.get("user_key") == athlete_key:
                return a.get("coach_athlete_key")
    except Exception:
        pass
    return None


def plaats(wid: str, tekst: str) -> bool:
    """Post de (bewerkte) feedback als coach-reactie in FinalSurge. WRITE-actie.

    Hergebruikt exact `fs_client.post_comment` (beproefd in Streamlit). Geen AI.
    """
    w = _cache.get(wid)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst en probeer opnieuw.")
    tekst = (tekst or "").strip()
    if not tekst:
        raise ValueError("Lege feedback.")
    ak = w.get("athlete_key", "")
    wk = w.get("workout_key", "")
    if not (ak and wk):
        raise ValueError("Geen FinalSurge-koppeling voor deze training.")
    FS.post_comment(workout_key=wk, user_key=ak, comment=tekst,
                    coach_athlete_key=_coach_athlete_key(ak))
    return True


def thread(wid: str) -> list[dict]:
    """De volledige comment-conversatie (atleet + coach) op deze training —
    zodat je ook je eigen al-gegeven feedback ziet."""
    w = _cache.get(wid)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst.")
    wk, ak = w.get("workout_key", ""), w.get("athlete_key", "")
    if not (wk and ak):
        return []
    try:
        comments = FS.get_comments(wk, ak)
        coach_key = FS.get_coach_key()
    except Exception:
        return []
    out = []
    for c in comments:
        tekst = (c.get("comment") or "").strip()
        if not tekst:
            continue
        out.append({
            "coach": c.get("user_key") == coach_key,
            "tekst": tekst,
            "datum": c.get("timestamp") or c.get("created_at") or c.get("date") or "",
        })
    return out


def _athlete_latest_ts(w: dict) -> str:
    """Laatste tijdstempel van een atleet-bericht in de thread (of '')."""
    return max((m.get("timestamp") or "" for m in (w.get("thread") or [])
                if m.get("van") == "atleet"), default="")


def _gesprek(w: dict) -> list:
    """De thread genormaliseerd voor de UI: [{coach, wie, tekst}] chronologisch."""
    out = []
    for m in (w.get("thread") or []):
        tekst = (m.get("tekst") or m.get("comment") or "").strip()
        if not tekst:
            continue
        out.append({"coach": m.get("van") == "coach",
                    "wie": m.get("naam") or "", "tekst": tekst})
    return out


def _snapshot(w: dict) -> dict:
    """Momentopname bij overslaan — ZELFDE velden als Streamlit (_skip_snapshot),
    zodat skips tussen Streamlit en de app 1-op-1 overeenkomen."""
    return {
        "date": date.today().isoformat(),
        "athlete_ts": _athlete_latest_ts(w),
        "notes": bool(w.get("post_notes")),
        "felt": bool(w.get("felt")),
        "effort": bool(w.get("effort")),
    }


def overslaan(wid: str) -> bool:
    """Sla een training over (uit de lijst tot de atleet weer nieuwe input geeft)."""
    w = _cache.get(wid)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst.")
    wk = w.get("workout_key", "")
    if not wk:
        raise ValueError("Geen workout-sleutel.")
    sk = intake_store.load_skipped()
    sk[wk] = _snapshot(w)
    intake_store.save_skipped(sk)
    return True


def _filter_skipped(workouts: list) -> list:
    """Overgeslagen trainingen eruit — tenzij de atleet ná het overslaan NIEUWE
    input gaf (nieuwe reactie/notitie/gevoel/RPE). EXACT als Streamlit
    _filter_skipped en werkt op dezelfde gedeelde skipped.json (skip in Streamlit
    = weg in de app, en andersom)."""
    try:
        sk = intake_store.load_skipped()
    except Exception:
        return workouts
    if not sk:
        return workouts
    uit, veranderd = [], False
    for w in workouts:
        wk = w.get("workout_key", "")
        snap = sk.get(wk)
        if snap is None:
            uit.append(w)
            continue
        cur_ts = _athlete_latest_ts(w)
        if isinstance(snap, dict):
            nieuw = (
                (cur_ts and cur_ts > (snap.get("athlete_ts") or ""))
                or (bool(w.get("post_notes")) and not snap.get("notes"))
                or (bool(w.get("felt")) and not snap.get("felt"))
                or (bool(w.get("effort")) and not snap.get("effort"))
            )
        else:
            nieuw = cur_ts[:10] > str(snap)[:10]
        if nieuw:
            del sk[wk]
            veranderd = True
            uit.append(w)
    if veranderd:
        try:
            intake_store.save_skipped(sk)
        except Exception:
            pass
    return uit


def dagoverzicht() -> dict:
    """Home-metertjes — EXACT zoals Streamlit `_fetch_day_stats`: wachten op
    feedback / vandaag gepost / afhakers / aankomende races (zonder wens) /
    schema-actie nodig / feedback-voortgang%. De vier zware FinalSurge-sweeps
    draaien parallel (net als Streamlit) zodat de home snel blijft."""
    if not heeft_token():
        return {"fs": False, "wachten": 0, "gepost": 0, "afhakers": 0,
                "races": 0, "schema": 0, "pct": 100, "atleten": 0}
    try:
        on_hold = set((intake_store.load_on_hold() or {}).keys())
    except Exception:
        on_hold = set()

    wachten = gepost = afhakers = races = schema = 0
    atleten = 0
    # SERIEEL, niet parallel: elke sweep parallelt intern al over ~67 atleten;
    # vier tegelijk = thread-storm + FinalSurge-throttling → sweeps geven soms 0.
    # Achter elkaar duurt even lang (FS is de bottleneck) maar is betrouwbaar.
    try:
        wk, stats = FS.get_workouts_needing_feedback(7, None, False, True,
                                                     {"los schema"}, True)
        wachten = len(_filter_skipped(wk))
        gepost = stats.get("posted_today", 0)
    except Exception:
        pass
    try:
        afhakers = len(FS.get_compliance_alerts(7, on_hold, {"los schema"}))
    except Exception:
        pass
    try:
        rows = FS.get_schema_end_dates(60, on_hold)
        schema = sum(1 for r in rows
                     if r["days_left"] is None or r["days_left"] <= 7)
    except Exception:
        pass
    try:
        races = sum(1 for r in FS.get_upcoming_races(7) if not r.get("wish_given"))
    except Exception:
        pass
    try:
        atleten = len(FS.get_athletes())          # = Streamlit-hero-telling (uniek)
    except Exception:
        pass
    totaal = wachten + gepost
    pct = int(gepost / totaal * 100) if totaal else 100
    return {"fs": True, "wachten": wachten, "gepost": gepost, "afhakers": afhakers,
            "races": races, "schema": schema, "pct": pct, "atleten": atleten}
