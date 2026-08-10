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
import threading
import time
from datetime import date, datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import fs_client as FS                                  # veilig: geen AI
import intake_store                                     # skip-opslag + on-hold (gedeeld met Streamlit)

_cache: dict[str, dict] = {}                            # workout_key -> workout_data (details lazy)


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
    _ensure_details(wid)                                 # lichte queue → details nu alsnog laden
    import ai_feedback                                   # lui: pas hier is de key nodig
    return ai_feedback.generate_feedback(_cache.get(wid) or w)


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


# ════════════════════════════════════════════════════════════════════════════
# FASE 1 — Feedback-inbox fundament: lichte gecachete queue + lazy workout-detail
# ════════════════════════════════════════════════════════════════════════════
# Doel: Feedback bij openen vrijwel altijd ONMIDDELLIJK bruikbaar (net als Home).
# Twee lagen: in-memory (_QUEUE_MEM, ~0 ms) + durabele snapshot (intake_store →
# feedback_queue.json, overleeft Render-deploy/restart, gedeeld). Stale-while-
# revalidate + single-flight; bij FinalSurge-fout valt alles terug op de laatst
# geldige snapshot. De queue is LICHT (include_details=False); de zware workout-
# details worden lazy per focus geladen (detail()). Los van Home (eigen store/lock).

_QUEUE_MEM: dict = {}
_QLOCK = threading.Lock()
_QREFRESHING = False

_FELT = {"1": "Geweldig", "2": "Goed", "3": "Normaal", "4": "Slecht", "5": "Vreselijk"}


def _felt_obj(felt) -> dict | None:
    if not felt:
        return None
    k = str(felt).split(".")[0]
    return {"waarde": k, "label": _FELT.get(k, k)}


def _queue_valid(snap) -> bool:
    return bool(snap and snap.get("fs") and isinstance(snap.get("items"), list))


def _herstel_cache(snap: dict) -> None:
    """Repopuleer _cache uit de (durabele) snapshot zodat detail/genereer/plaats na
    een restart werken zonder een volledige sweep."""
    for wid, w in (snap.get("_volle") or {}).items():
        _cache.setdefault(wid, w)


# ── Diagnostiek (fase 2.2 punt 1: alleen meten, geen structurele wijziging) ───
# Laatste persist-uitkomst, zodat een verse queue-refresh kan rapporteren of het
# wegschrijven van de durable snapshot lukte (save-fouten mogen niet onzichtbaar
# blijven). Bevat nooit gevoelige inhoud — alleen ok/fouttype.
_LAST_PERSIST: dict = {"ok": None, "error": None, "at": None}

# Fase-timings van de laatste sweep (alleen meten). Wordt NIET in de snapshot
# opgeslagen — puur transiënt geheugen zodat een verse refresh in zijn diag kan
# uitsplitsen waar de ~12 sec zit. Bevat geen gevoelige inhoud.
_LAST_SWEEP_DIAG: dict = {}


def _snapshot_leeftijd_sec(snap: dict):
    ber = snap.get("berekend") if isinstance(snap, dict) else None
    if not ber:
        return None
    try:
        return int((datetime.now() - datetime.fromisoformat(ber)).total_seconds())
    except Exception:
        return None


def _durable_load_diag() -> tuple[dict, int, str]:
    """(snapshot, duur_ms, uitkomst). uitkomst ∈ success|empty|missing|invalid|error:<type>."""
    t0 = time.perf_counter()
    try:
        durable = intake_store.load_feedback_queue()
    except Exception as e:
        return {}, int((time.perf_counter() - t0) * 1000), "error:" + type(e).__name__
    ms = int((time.perf_counter() - t0) * 1000)
    if not durable:
        return {}, ms, "missing"
    if not _queue_valid(durable):
        return durable, ms, "invalid"
    return durable, ms, ("empty" if not durable.get("items") else "success")


def _queue_current_diag() -> tuple[dict, dict]:
    """Beste bekende snapshot + diagnostiek over de bron.
    Bron: mem (in-memory) | durable (GitHub) | none. Warmt bij durable het
    geheugen + _cache op (ongewijzigd gedrag)."""
    global _QUEUE_MEM
    if _queue_valid(_QUEUE_MEM):
        return _QUEUE_MEM, {"bron": "mem", "durable_load_ms": 0, "durable_uitkomst": "mem"}
    durable, ms, uitkomst = _durable_load_diag()
    if _queue_valid(durable):
        _QUEUE_MEM = durable
        _herstel_cache(durable)
        return durable, {"bron": "durable", "durable_load_ms": ms, "durable_uitkomst": uitkomst}
    return {}, {"bron": "none", "durable_load_ms": ms, "durable_uitkomst": uitkomst}


def _queue_current() -> dict:
    """Beste bekende queue-snapshot (zonder diagnostiek) — voor detail()/herstel."""
    snap, _ = _queue_current_diag()
    return snap


def _queue_persist(snap: dict) -> tuple[bool, str]:
    """Persisteer de snapshot; geeft (ok, fout) terug zodat de aanroeper save-
    fouten zichtbaar kan maken in de diagnostiek. Retry/SHA-gedrag ONGEWIJZIGD."""
    global _QUEUE_MEM, _LAST_PERSIST
    _QUEUE_MEM = snap
    try:
        ok, err = intake_store.save_feedback_queue(snap)
    except Exception as e:
        ok, err = False, type(e).__name__ + ": " + str(e)[:120]
    _LAST_PERSIST = {"ok": bool(ok), "error": (err or None) if not ok else None,
                     "at": datetime.now().isoformat(timespec="seconds")}
    return bool(ok), err or ""


def _categorie(w: dict) -> tuple[str, str]:
    """Uitlegbare categorie + preview uit ECHTE data (geen score)."""
    post = (w.get("post_notes") or "").strip()
    reacties = _reacties(w)
    if post or reacties:
        return "reactie", (post or (reacties[0] if reacties else ""))[:90]
    if w.get("felt") or w.get("effort"):
        fo = _felt_obj(w.get("felt"))
        return "gevoel", (f"Gevoel: {fo['label']}" if fo else "Gevoel/RPE")
    return "uitgevoerd", ""


# ── Coachgroepen (begeleide abonnementen) ────────────────────────────────────
# Centrale bron = fs_client.get_athletes (group/all_groups). Hier alléén de
# presentatievolgorde + canonieke labels voor de Feedback-queue. Los
# trainingsschema staat er BEWUST niet in: die groep is al uit de sweep
# gefilterd (exclude_groups={"los schema"}) en heeft geen Feedback-werkvoorraad.
_GROEPEN = [
    ("start_to_run", "Start to Run", ("start", "run")),
    ("getting_better", "Getting Better", ("getting", "better")),
    ("high_performer", "High Performer", ("high", "performer")),
    ("comfort", "Comfort", ("comfort",)),
]
_GROEP_RANK = {k: i for i, (k, _l, _w) in enumerate(_GROEPEN)}
_GROEP_RANK["overig"] = 9
_GROEP_LABEL = {k: l for k, l, _w in _GROEPEN}
_GROEP_LABEL["overig"] = "Overig"


def _canon_groep(groepen: list) -> str:
    """Map de (alle_)groepen van een atleet op één canonieke begeleide-groep-sleutel.
    Woord-subset-match (zoals fs_client.group_is_excluded), in vaste volgorde →
    deterministisch. Geen match → 'overig'."""
    low = [(g or "").lower() for g in (groepen or []) if g]
    for key, _label, woorden in _GROEPEN:
        for g in low:
            if all(w in g for w in woorden):
                return key
    return "overig"


def _queue_item(wid: str, w: dict) -> dict:
    naam = w.get("athlete_name", "")
    categorie, preview = _categorie(w)
    groepen = w.get("athlete_groups") or ([w.get("athlete_group")] if w.get("athlete_group") else [])
    groep = _canon_groep(groepen)
    return {
        "id": wid, "athlete_key": w.get("athlete_key", ""),
        "naam": naam,
        "voornaam": w.get("athlete_first_name") or (naam.split(" ")[0] if naam else ""),
        "datum": (w.get("workout_date") or "")[:10],
        "workout": w.get("workout_name") or "Training",
        "categorie": categorie, "preview": preview,
        "groep": groep, "groep_label": _GROEP_LABEL.get(groep, "Overig"),
        "workout_type": w.get("workout_type") or "unknown",
        "heeft_thread": bool(_gesprek(w)),
        "athlete_ts": _athlete_latest_ts(w),
    }


_CAT_RANK = {"reactie": 0, "gevoel": 1, "uitgevoerd": 2}


def _bouw_queue() -> dict:
    """De zware sweep (alleen bij refresh) → LICHTE queue (geen details)."""
    global _LAST_SWEEP_DIAG
    if not heeft_token():
        return {"fs": False, "items": [], "gepost": 0}
    try:
        workouts, stats = FS.get_workouts_needing_feedback(
            days_back=7, include_planned_no_notes=True,
            exclude_groups={"los schema"}, return_stats=True, include_details=False)
    except Exception:
        oud = _queue_current()
        if oud:
            return {**oud, "verouderd": True}
        return {"fs": True, "items": [], "gepost": 0, "err": "FinalSurge onbereikbaar."}
    _t_build = time.perf_counter()
    workouts = _filter_skipped(workouts)
    items, volle = [], {}
    for w in workouts:
        wid = w.get("workout_key") or (str(w.get("athlete_key", "")) + ":" + str(w.get("workout_date", "")))
        volle[wid] = w
        items.append(_queue_item(wid, w))
    # Fase-timings + tellingen uit de sweep bewaren voor de refresh-diag
    # (transiënt; niet in de snapshot). build_ms = queue-opbouw ná FinalSurge.
    _LAST_SWEEP_DIAG = {
        "roster_ms": stats.get("roster_ms"),
        "workouts_fanout_ms": stats.get("workouts_fanout_ms"),
        "comments_ms": stats.get("comments_ms"),
        "build_ms": int((time.perf_counter() - _t_build) * 1000),
        "athlete_count": stats.get("athlete_count"),
        "candidate_count": stats.get("candidate_count"),
        "comment_fetch_count": stats.get("comment_fetch_count"),
    }
    return {
        "fs": True, "items": items, "gepost": stats.get("posted_today", 0),
        "berekend": datetime.now().isoformat(timespec="seconds"),
        "datum": date.today().isoformat(), "_volle": volle,
    }


def _groep_samenvatting(items: list) -> list:
    """Groepen (in vaste volgorde) met hun aantal, voor de queue-selector."""
    tel: dict = {}
    for i in items:
        g = i.get("groep", "overig")
        tel[g] = tel.get(g, 0) + 1
    volgorde = sorted(tel.keys(), key=lambda g: _GROEP_RANK.get(g, 9))
    return [{"key": g, "label": _GROEP_LABEL.get(g, "Overig"), "count": tel[g]} for g in volgorde]


def _queue_public(snap: dict, cached: bool, **extra) -> dict:
    """Snapshot → publieke payload (zonder _volle), gesorteerd: groep
    (Start to Run→…→Comfort→Overig), dan categorie (reactie→gevoel→uitgevoerd),
    daarbinnen OUDSTE onbeantwoord eerst. `groepen` = selector-samenvatting."""
    items = sorted(snap.get("items", []),
                   key=lambda i: (_GROEP_RANK.get(i.get("groep"), 9),
                                  _CAT_RANK.get(i["categorie"], 9),
                                  i.get("athlete_ts") or "", i.get("datum") or ""))
    out = {"fs": True, "items": items, "groepen": _groep_samenvatting(items),
           "gepost": snap.get("gepost", 0),
           "berekend": snap.get("berekend"), "datum": snap.get("datum"),
           "cached": cached}
    out.update(extra)
    return out


def _diag(snap: dict, extra: dict) -> dict:
    """Diagnostiekblok voor de queue-respons (fase 2.2 punt 1 — alleen meten)."""
    d = {"snapshot_aanwezig": bool(snap),
         "item_count": len(snap.get("items", [])) if snap else 0,
         "generated_at": snap.get("berekend") if snap else None,
         "leeftijd_sec": _snapshot_leeftijd_sec(snap) if snap else None}
    d.update(extra)
    return d


def queue(refresh: bool = False) -> dict:
    """Feedback-queue. Standaard direct uit de cache (geheugen→store); refresh=True
    herbouwt (single-flight) en behoudt bij FinalSurge-fout de laatst geldige lijst.
    Elke respons draagt een `diag`-blok (bron/snapshot/persist) voor de koude-start-
    diagnose — geen gevoelige inhoud."""
    if not heeft_token():
        return {"fs": False, "items": []}
    if not refresh:
        snap, bron = _queue_current_diag()
        if snap:
            return _queue_public(snap, cached=True, diag=_diag(snap, bron))
        return {"fs": True, "items": [], "pending": True, "cached": False,
                "diag": _diag({}, bron)}

    global _QREFRESHING
    with _QLOCK:
        bezig = _QREFRESHING
        if not bezig:
            _QREFRESHING = True
    if bezig:
        snap, bron = _queue_current_diag()
        if snap:
            return _queue_public(snap, cached=True, verversen_bezig=True, diag=_diag(snap, {**bron, "verversen_bezig": True}))
        return {"fs": True, "items": [], "pending": True, "cached": False,
                "diag": _diag({}, {**bron, "verversen_bezig": True})}
    try:
        _t_refresh = time.perf_counter()
        snap = _bouw_queue()
        if _queue_valid(snap) and "_volle" in snap:
            _herstel_cache(snap)
            _t_persist = time.perf_counter()
            ok, err = _queue_persist(snap)
            persist_ms = int((time.perf_counter() - _t_persist) * 1000)
            total_refresh_ms = int((time.perf_counter() - _t_refresh) * 1000)
            return _queue_public(snap, cached=False, diag=_diag(snap, {
                "bron": "sweep", "persist_ok": ok,
                "persist_error": (err[:120] if (err and not ok) else None),
                **_LAST_SWEEP_DIAG,
                "persist_ms": persist_ms,
                "total_refresh_ms": total_refresh_ms}))
        oud, bron = _queue_current_diag()                 # sweep faalde/leeg → oude houden
        if oud:
            return _queue_public(oud, cached=True, refresh_mislukt=True, diag=_diag(oud, {**bron, "refresh_mislukt": True}))
        return {"fs": True, "items": snap.get("items", []), "cached": False,
                "err": snap.get("err"), "diag": _diag({}, {"bron": "sweep", "sweep_leeg": True})}
    finally:
        with _QLOCK:
            _QREFRESHING = False


# ── Lazy workout-detail (per focus) + centrale deterministische signalen ─────

def _ensure_details(wid: str) -> None:
    """Laad de workout-details één keer (lazy). Lichte-queue-workouts hebben ze niet;
    de oude /api/feedback-flow wel → dan no-op."""
    w = _cache.get(wid)
    if not w or w.get("details"):
        return
    ak, wk = w.get("athlete_key"), w.get("workout_key") or wid
    if not (ak and wk):
        return
    try:
        w["details"] = FS.get_workout_details(wk, ak)
    except Exception:
        w["details"] = {}


def afwijking(planned_km, actual_km) -> dict:
    """Afstandsafwijking, deterministisch vóór AI. Banden (LOCKED):
    <10 ignore · 10–15 mention_neutral · 15–20 mention_if_context · >20 mention_contextual.
    Geen geplande afstand → n/a. Nooit automatisch negatief (dat bepaalt de AI/context)."""
    try:
        p, a = float(planned_km or 0), float(actual_km or 0)
    except (TypeError, ValueError):
        return {"pct": None, "relevance": "n/a"}
    if not p or not a:
        return {"pct": None, "relevance": "n/a"}
    pct = round((a - p) / p * 100, 1)
    m = abs(pct)
    if m < 10:
        rel = "ignore"
    elif m <= 15:
        rel = "mention_neutral"
    elif m <= 20:
        rel = "mention_if_context"
    else:
        rel = "mention_contextual"
    return {"pct": pct, "relevance": rel}


def _actual_zone(act: dict, zone_type: str, zones: list) -> dict | None:
    """Zone van het gemiddelde — deterministisch via de bestaande zonetabel."""
    if zone_type == "hartslag":
        hr = act.get("hr_avg")
        try:
            hr = float(hr) if hr else None
        except (TypeError, ValueError):
            hr = None
        return FS.zone_van_waarde(zones, hr, is_pace=False) if hr else None
    if zone_type == "tempo":
        pm = FS._pace_to_float(act.get("pace_display") or "")
        ps = pm * 60 if pm not in (0, float("inf")) else None
        return FS.zone_van_waarde(zones, ps, is_pace=True) if ps else None
    return None


def _plan_steps_flat(steps) -> list:
    """(zone, intensity) per zone-doel-stap in geplande volgorde; recurset repeat-
    blokken (step['data']). Deterministisch, geen AI. intensity is één van
    WARMUP/ACTIVE/REST/COOLDOWN (zoals wij ze in de builder wegschrijven) of ''."""
    out: list = []

    def _walk(sts):
        for s in sts:
            if not isinstance(s, dict):
                continue
            inten = (s.get("intensity") or "").upper()
            inner = s.get("data") or []
            if inner:                                   # repeat-/groepsblok → binnenstappen
                _walk(inner)
                continue
            if inten == "REST":
                continue
            for t in (s.get("target") or []):
                if isinstance(t, dict) and "zone" in (t.get("targetType") or "") and t.get("zone"):
                    try:
                        out.append((int(t["zone"]), inten))
                    except (TypeError, ValueError):
                        pass
                    break

    _walk(steps or [])
    return out


def _collapse(seq: list) -> list:
    """Opeenvolgende duplicaten samenvouwen: [2,2,3,3] → [2,3] (de vorm)."""
    out: list = []
    for z in seq:
        if not out or out[-1] != z:
            out.append(z)
    return out


def _label_zones(seq: list) -> str:
    """Zone-reeks → leesbaar label: progressief 'Z2 → Z3', interval 'Z2 / Z4',
    breed 'Z2–Z5'. (Aanroeper bepaalt of dit de kern of de volledige structuur is.)"""
    distinct = sorted(set(seq))
    if not distinct:
        return ""
    if len(distinct) == 1:
        return f"Z{distinct[0]}"
    vorm = _collapse(seq)
    progressief = vorm == sorted(vorm) and len(vorm) == len(distinct)
    if progressief:
        return " → ".join(f"Z{z}" for z in vorm)
    if len(distinct) <= 3:
        return " / ".join(f"Z{z}" for z in distinct)
    return f"Z{distinct[0]}–Z{distinct[-1]}"


def _plan_analyse(w: dict, d: dict, zones: list) -> dict:
    """Geplande trainings-KERNINTENTIE uit de WorkoutBuilder — deterministisch.

    Regels (semantisch, geen AI):
    • Kern = de zones van de ACTIVE-stappen. Warming-up/cooling-down (WARMUP/
      COOLDOWN) tellen NIET mee voor de kern — anders krijgt een progressieve
      Z2→Z3-loop met warmup Z1 ten onrechte 'Z1 → Z2 → Z3'.
    • Een gemiddelde is nooit de classificatie: bij een multi-zone KERN tonen we
      geen enkelvoudige (actual-)zone.
    • Fallback: ontbreken de intensity-labels (oudere/handmatige workouts), dan
      kunnen we de kern niet betrouwbaar isoleren → we tonen de VOLLEDIGE feitelijke
      structuur en claimen géén kernintentie (kern=False).

    Geeft: {single_zone|None, structuur, structured_multi, kern:bool, context}.
    """
    leeg = {"single_zone": None, "structuur": "", "structured_multi": False, "kern": False, "context": ""}
    if not d.get("has_structured_workout"):
        return leeg
    wk, ak = w.get("workout_key"), w.get("athlete_key")
    if not (wk and ak):
        return leeg
    try:
        steps = FS.get_workout_builder(wk, ak) or []
    except Exception:
        return leeg

    flat = _plan_steps_flat(steps)                       # [(zone, intensity)]
    if not flat:
        return leeg

    heeft_labels = any(inten in ("WARMUP", "ACTIVE", "COOLDOWN") for _z, inten in flat)
    if heeft_labels:
        kern_seq = [z for z, inten in flat if inten == "ACTIVE"]
        wu = sorted({z for z, inten in flat if inten == "WARMUP"})
        cd = sorted({z for z, inten in flat if inten == "COOLDOWN"})
        if kern_seq:                                     # betrouwbare kern
            seq, kern = kern_seq, True
            ctx = []
            if wu:
                ctx.append("warming-up " + "/".join(f"Z{z}" for z in wu))
            if cd:
                ctx.append("cooling-down " + "/".join(f"Z{z}" for z in cd))
            context = " · ".join(ctx)
        else:                                            # labels aanwezig maar geen ACTIVE → volledige structuur
            seq, kern, context = [z for z, _ in flat], False, ""
    else:                                                # geen betrouwbare labels → volledige structuur
        seq, kern, context = [z for z, _ in flat], False, ""

    distinct = sorted(set(seq))
    if not distinct:
        return leeg
    if len(distinct) == 1:                               # één duidelijke (kern)zone
        num = distinct[0]
        naam = next((z["naam"] for z in zones if z.get("num") == num), "")
        return {"single_zone": {"num": num, "naam": naam}, "structuur": "",
                "structured_multi": False, "kern": kern, "context": context}
    return {"single_zone": None, "structuur": _label_zones(seq),
            "structured_multi": True, "kern": kern, "context": context}


def detail(wid: str) -> dict:
    """Lazy focus-detail voor één workout: trainingssamenvatting (gepland↔uitgevoerd,
    tempo/HF, zones deterministisch), afstandsafwijking, gevoel/RPE, laps, plan-
    structuur + gesprek. Eén workout — geen roster-sweep. Zones/afwijking worden in
    code bepaald (AI rekent nooit zelf)."""
    w = _cache.get(wid)
    if not w:
        _queue_current()                                 # probeer _cache te herstellen
        w = _cache.get(wid)
    if not w:
        return {"ok": False, "err": "Training niet in beeld — ververs de queue."}
    _ensure_details(wid)
    w = _cache.get(wid) or w
    d = w.get("details") or {}
    activities = d.get("Activities") or []
    act = activities[0] if activities else {}

    # Deterministisch workouttype (bron: fs_client.classify_workout_type). Run-
    # specifieke analyse (zones/tempo/afstandsafwijking/laps) draait ALLEEN bij run;
    # niet-runs krijgen feitelijke context zonder hardloopoordeel.
    wt = w.get("workout_type") or "unknown"
    is_run = (wt == "run")

    zone_type, zones = "", []
    ak = w.get("athlete_key", "")
    if ak and is_run:
        try:
            zr = FS.get_athlete_zones(ak)
            if zr.get("zones"):
                zone_type = zr.get("zone_type", "")
                zones = zr.get("zones", [])
        except Exception:
            pass
    plan = _plan_analyse(w, d, zones) if zones else {
        "single_zone": None, "structuur": "", "structured_multi": False, "kern": False, "context": None}
    # Semantische regel: bij een gestructureerde/multi-zone training NOOIT een
    # enkelvoudige actual-zone tonen (het gemiddelde is misleidend). Alleen bij
    # één duidelijke intentie (of geen builder) is de actual-zone betekenisvol.
    actual_zone = None
    if zones and not plan["structured_multi"]:
        actual_zone = _actual_zone(act, zone_type, zones)

    def _num(x, factor=1):
        try:
            return round(float(x) / factor, 1) if x else None
        except (TypeError, ValueError):
            return None

    gepland = {}
    if act.get("planned_amount"):
        gepland["km"] = _num(act.get("planned_amount"))
    if act.get("planned_duration"):
        gepland["min"] = _num(act.get("planned_duration"), 60)
    if plan["single_zone"]:
        gepland["zone"] = plan["single_zone"]
    if plan["structuur"]:
        gepland["structuur"] = plan["structuur"]

    uitgevoerd = {
        "km": _num(act.get("amount")),
        "min": _num(act.get("duration"), 60),
        "pace": act.get("pace_display"),
        "hr_avg": act.get("hr_avg"), "hr_max": act.get("hr_max"),
        "zone": actual_zone,
    }
    laps = []
    if is_run:
        for lap in (act.get("Laps") or [])[:20]:
            if isinstance(lap, dict):
                laps.append({"pace": lap.get("pace_display"), "hr": lap.get("hr_avg"),
                             "afstand": lap.get("distance_display") or lap.get("amount")})

    return {
        "ok": True, "id": wid, "naam": w.get("athlete_name", ""),
        "voornaam": w.get("athlete_first_name") or "",
        "workout": w.get("workout_name") or "Training",
        "datum": (w.get("workout_date") or "")[:10],
        "categorie": _categorie(w)[0],
        "workout_type": wt, "is_run": is_run,
        # TIJDELIJKE data-controle: ruwe FinalSurge type-velden vs. classificatie.
        # Alleen GUID/typenaam — geen notities/comments/gevoel/persoonsgegevens.
        "type_debug": {
            "workout_key": w.get("workout_key"),
            "activity_type_key": w.get("_dbg_at_key"),
            "activity_type_name": w.get("_dbg_at_name"),
            "act0_activity_type_key": w.get("_dbg_at0_key"),
            "act0_activity_type_name": w.get("_dbg_at0_name"),
            "classified_workout_type": wt,
        },
        "zone_type": zone_type or None,
        "gepland": gepland or None,
        "uitgevoerd": uitgevoerd,
        "afwijking": afwijking(act.get("planned_amount"), act.get("amount")) if is_run else None,
        "gevoel": _felt_obj(w.get("felt")),
        "rpe": w.get("effort"),
        "is_structured": plan["structured_multi"],
        "plan_is_kern": plan["kern"],
        "plan_context": plan["context"] or None,
        "plan_beschrijving": (d.get("description") or "").strip()[:600] or None,
        "plan_structuur": plan["structuur"] or None,
        "laps": laps,
        "gesprek": _gesprek(w),
    }
