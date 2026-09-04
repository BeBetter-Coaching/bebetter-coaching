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
import re
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


def _home_invalidate_feedback() -> None:
    """Server-side invalidatie-seam Feedback → Home. Na een BEVESTIGDE post/skip markeert
    Home zijn feedbacktegel als 'moet revalideren' (géén handmatige teller-mutatie), zodat
    de volgende Home-read — óók na reload/koude start — de tegel via de canonieke sweep
    ververst i.p.v. een bevroren waarde te tonen. Lui geïmporteerd (home_core importeert
    feedback_core; top-level import = cyclus) en NOOIT fataal: een Home-hapering mag
    post/skip niet breken."""
    try:
        import home_core
        home_core.invalidate_feedback()
    except Exception:
        pass


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


# ── Masterbrein V2 feedback-gate (Fase 2) ────────────────────────────────────
# Eén centrale keuzegrens (server-side env, geen frontend-toggle). Zelfde patroon
# als de Schema-gate. legacy = huidige Feedback-intelligence; shadow = V2-context
# wordt gebouwd voor diagnostiek maar NIET in de prompt geïnjecteerd (output blijft
# legacy); v2 = de longitudinale Masterbrein-context gaat mee de AI-prompt in.
_FEEDBACK_BRAIN_MODES = ("legacy", "shadow", "v2")


def feedback_brain_mode() -> str:
    m = (os.environ.get("BEBETTER_FEEDBACK_BRAIN") or "legacy").strip().lower()
    return m if m in _FEEDBACK_BRAIN_MODES else "legacy"


_RACE_WOORDEN = ("wedstrijd", "race", "wedstrijden", "startnummer", "parkrun", "marathon",
                 "halve marathon", "10 km wedstrijd", "5 km wedstrijd", "koers", "loop ik",
                 "start ik", "pr ", "pr.", "persoonlijk record")


def _athlete_raises_race(w: dict) -> bool:
    """Feedback v1 (A) — noemt de atleet in DEZE feedback/thread zelf een wedstrijd? Zo ja mag de
    (verder weg gelegen) race-context als reactie worden gebruikt; anders NOOIT proactief noemen.
    Puur op de atleet-teksten (post_notes + atleet-comments + atleet-thread), niet op coachtekst."""
    stukken = list(_atleet_berichten(w))
    if (w.get("post_notes") or "").strip():
        stukken.append(w["post_notes"])
    laag = " ".join(stukken).lower()
    return any(term in laag for term in _RACE_WOORDEN)


def _brein_context(w: dict) -> str:
    """Longitudinale Masterbrein-sessiecontext voor deze workout. Nooit fataal;
    legacy → ''; shadow → gebouwd voor diagnostiek maar niet geïnjecteerd; v2 →
    de prompttekst. Geen extra FinalSurge-fan-out buiten de brain-gather."""
    mode = feedback_brain_mode()
    if mode == "legacy":
        return ""
    ak = w.get("athlete_key", "")
    if not ak:
        return ""
    try:
        from brain import adapter as _ad
        raised = _athlete_raises_race(w)
        block = _ad.feedback_context_block(ak, w.get("workout_key", ""), athlete_raised_race=raised)
        w["_brein_diag"] = {k: block.get(k) for k in
                            ("source_gaps", "has_load", "complaint_areas", "overall")}
        return (block.get("prompt_block") or "") if mode == "v2" else ""
    except Exception:
        return ""


_NEAR_FUTURE_DAYS = 5
_WD_FULL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


def _generation_date():
    """P1 — ÉÉN tijdzone-bewuste 'vandaag' (generatiedatum) als anker voor relatieve datumtaal.
    Val terug op de naïeve lokale datum als de zone niet beschikbaar is."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        return datetime.now(ZoneInfo("Europe/Amsterdam")).date()
    except Exception:
        from datetime import date as _date
        return _date.today()


def _relative_day_label(d, today) -> str:
    """Deterministische relatieve dag t.o.v. de generatiedatum: vandaag/morgen/overmorgen, dan de
    weekdag (binnen een week), anders 'over N dagen'. Nooit door de AI uit een datum afgeleid."""
    n = (d - today).days
    if n == 0:
        return "vandaag"
    if n == 1:
        return "morgen"
    if n == 2:
        return "overmorgen"
    if 3 <= n <= 6:
        return _WD_FULL[d.weekday()]
    return f"over {n} dagen"


def _near_future_block(w: dict) -> str:
    """P1 — begrensde near-future planning voor de generatie: de eerstvolgende (max 3) GEPLANDE
    sessies met datum, type, geplande afstand/duur en race-markering. ÉÉN bounded FinalSurge-read
    (upcoming workouts) die NERGENS anders wordt gehaald (geen dubbele call), en ALLEEN bij een
    expliciete generatie-actie — dus geen nieuwe fan-out op het snelle case-open-pad. Best-effort:
    faalt stil naar ''. Deterministisch; de relevantie-afweging (wél/niet noemen) doet de AI."""
    ak = w.get("athlete_key", "")
    if not ak:
        return ""
    try:
        import fs_client as FS
        from datetime import date, timedelta
        today = _generation_date()                           # P1: één tz-bewuste generatiedatum
        try:
            wd = date.fromisoformat((w.get("workout_date") or "")[:10])
        except ValueError:
            wd = today
        anchor = max(today, wd)                              # strikt ná de beoordeelde training/vandaag
        start, end = anchor + timedelta(days=1), today + timedelta(days=_NEAR_FUTURE_DAYS)
        if end < start:
            return ""
        wk_key = w.get("workout_key", "")
        upcoming = FS.get_workouts_deduped(ak, start, end) or []
        _WD = ["ma", "di", "wo", "do", "vr", "za", "zo"]
        rows = []
        for x in sorted(upcoming, key=lambda z: str(z.get("workout_date"))[:10]):
            if wk_key and x.get("workout_key") == wk_key:
                continue
            if not FS.is_planned_workout(x):
                continue
            try:
                dd = date.fromisoformat(str(x.get("workout_date") or "")[:10])
            except ValueError:
                continue
            if dd <= anchor:
                continue
            naam = (x.get("name") or "training").strip()
            km = FS._norm_km(x.get("planned_amount"), x.get("planned_amount_type") or x.get("amount_type"))
            if km is None:
                for act in (x.get("Activities") or []):
                    km = FS._norm_km(act.get("planned_amount"), act.get("planned_amount_type") or act.get("amount_type"))
                    if km is not None:
                        break
            pd = x.get("planned_duration") or next(
                (a.get("planned_duration") for a in (x.get("Activities") or []) if a.get("planned_duration")), None)
            try:
                mins = round(float(pd) / 60) if pd else None
            except (TypeError, ValueError):
                mins = None
            meta = []
            if km is not None:
                meta.append(f"{km:g} km")
            if mins:
                meta.append(f"{mins} min")
            tag = " [WEDSTRIJD]" if x.get("is_race") else ""
            rel = _relative_day_label(dd, today)                 # P1: deterministische relatieve dag
            rows.append(f"- {rel} ({_WD[dd.weekday()]} {dd.day}/{dd.month}): {naam}"
                        + ((" · " + ", ".join(meta)) if meta else "") + tag)
            if len(rows) >= 3:
                break
        if not rows:
            return ""
        return ("━━━ KOMENDE GEPLANDE TRAININGEN (deterministisch uit FinalSurge — verzin er niets bij) ━━━\n"
                + "\n".join(rows)
                + "\nNeem de RELATIEVE dag (bijv. 'morgen', 'overmorgen', 'zaterdag') LETTERLIJK over "
                  "zoals hierboven vermeld; reken die NOOIT zelf uit een datum of trainingsdatum.\n"
                  "Weeg deze sessies ALLEEN mee als het voor DEZE feedback uitmaakt (de atleet noemt een "
                  "komende dag/sessie, er is een verhoogd belasting-/herstelsignaal, deze training was "
                  "onverwacht/extra, de atleet meldt pijn/vermoeidheid, de atleet vraagt om een schema- "
                  "of wedstrijdwijziging, of de eerstvolgende sessie is fors/zwaar). Anders hoef je ze "
                  "niet te noemen. Zeg NOOIT toe dat je het schema aanpast (coach-agency).")
    except Exception:
        return ""


# Herkenning van een verbindings-/horloge-onderbreking of hervatting in de atleet-tekst.
_SESSION_SPLIT_RE = re.compile(
    r"verbind|verbinding|weg\s*(viel|gevallen|vallen)|opnieuw|verder\s*ge|doorge(lopen|gaan)|hervat|"
    r"connect|drop|gps|horloge|klok|watch|uitgevallen|onderbroken|opgestart|gesplitst",
    re.I)


def _session_context(w: dict) -> str:
    """P0 — niet-persistente, deterministische SESSIE-COHERENTIE voor de generatie. Herkent dat
    meerdere same-day hardloop-registraties van dezelfde atleet WAARSCHIJNLIJK één sessie zijn (bv.
    gesplitst door verbindings-/horloge-uitval), zodat de AI een klein fragment (bv. 0,85 km) niet
    als 'vroeg gestopte training' leest. GEEN destructieve merge, GEEN nieuwe fetch (leest de
    in-proces queue-cache `_cache`), GEEN persistente state. Nooit op één factor; ander sport of
    twee volle losse runs → SEPARATE (geen blok). Best-effort: faalt stil naar ''."""
    ak = w.get("athlete_key", "")
    day = str(w.get("workout_date") or "")[:10]
    wk = w.get("workout_key", "")
    if not ak or not day:
        return ""
    try:
        def _acts(x):
            d = x.get("details") or {}
            return (d.get("Activities") if isinstance(d, dict) else None) or x.get("Activities") or []

        def _exec_km(x):
            for a in _acts(x):
                km = FS._norm_km((a or {}).get("amount"), (a or {}).get("amount_type"))
                if km is not None:
                    return km
            return None

        def _planned_km(x):
            for a in _acts(x):
                km = FS._norm_km((a or {}).get("planned_amount"),
                                 (a or {}).get("planned_amount_type") or (a or {}).get("amount_type"))
                if km is not None:
                    return km
            return FS._norm_km(x.get("planned_amount"), x.get("planned_amount_type"))

        def _sport(x):
            return str(x.get("workout_type") or "").lower()

        def _comments(x):
            cs = [str(c).strip() for c in (x.get("athlete_comments") or []) if str(c or "").strip()]
            pn = str(x.get("post_notes") or "").strip()
            if pn:
                cs.append(pn)
            return cs

        cur_sport = _sport(w)
        run_like = ("run", "running", "hardlopen", "")
        sibs = []
        for x in list(_cache.values()):
            if x is w or x.get("athlete_key") != ak:
                continue
            if str(x.get("workout_date") or "")[:10] != day:
                continue
            if wk and x.get("workout_key") == wk:
                continue
            xs = _sport(x)
            if xs not in run_like and xs != cur_sport:
                continue                                       # ander sport → geen gesplitste sessie
            sibs.append(x)
        if not sibs:
            return ""

        members = [w] + sibs
        dists = [d for d in (_exec_km(m) for m in members) if d is not None]
        if len(dists) < 2:
            return ""
        summed = sum(dists)
        planned = max([p for p in (_planned_km(m) for m in members) if p is not None] or [0]) or None
        allc = []
        for m in members:
            allc.extend(_comments(m))
        # Meerfactor-bewijs (nooit één alleen): fragment + gepland-totaal-match + hervat/verbind-comment.
        frag = (min(dists) / max(dists) < 0.3) and (min(dists) < 2.0)
        plan_match = bool(planned) and abs(summed - planned) / planned < 0.20
        comment_hit = any(_SESSION_SPLIT_RE.search(c) for c in allc)
        if sum([bool(frag), bool(plan_match), bool(comment_hit)]) < 2:
            return ""                                          # onvoldoende bewijs → los behandelen

        reg = [f"- registratie {km:g} km" if km is not None else "- registratie (afstand onbekend)"
               for km in (_exec_km(m) for m in members)]
        blok = ["━━━ ZELFDE-DAG SESSIE-CONTEXT (deterministisch — meerdere registraties op dezelfde dag) ━━━",
                "Deze atleet heeft vandaag meerdere hardloop-registraties die WAARSCHIJNLIJK dezelfde "
                "sessie zijn (mogelijk gesplitst door bijv. een verbindings-/horloge-onderbreking):"] + reg
        tot = f"Samen ~{summed:.1f} km"
        if planned:
            tot += f", gepland ~{planned:g} km"
        blok.append(tot + ".")
        if comment_hit:
            _c = next((c for c in allc if _SESSION_SPLIT_RE.search(c)), "")
            if _c:
                blok.append(f"In een andere registratie van dezelfde sessie schreef de atleet: \"{_c[:240]}\".")
        blok.append(
            "Behandel DEZE registratie daarom NIET als een losse, vroeg afgebroken training; concludeer "
            "NIET dat de training 'vroeg gestopt' is. Verwijs naar 'deze registratie' i.p.v. de hele "
            "training, en stel GEEN vraag die in een andere registratie al is beantwoord (vraag bijv. "
            "niet 'wat er gebeurde' als een andere registratie de onderbreking al uitlegt). Twijfel je, "
            "benoem de onzekerheid ('deze registratie lijkt onderdeel van een langere sessie').")
        return "\n".join(blok)
    except Exception:
        return ""


# --- Conversation-aware dispatch (Fase 2 — Feedback conversation parity) ----------
# De eerste feedback op een training is een trainingsanalyse; zodra de atleet daarna
# inhoudelijk reageert loopt er een gesprek en moet de AI daarop antwoorden. De keuze is
# DETERMINISTISCH — puur op spreker + volgorde, nooit een LLM/tekstheuristiek — en spiegelt
# 1:1 het bewezen Streamlit-gedrag (main.py: last_van=="atleet" én coach in de thread).
INITIAL_ANALYSIS = "INITIAL_ANALYSIS"
FOLLOW_UP_REPLY = "FOLLOW_UP_REPLY"


def feedback_mode(thread) -> str:
    """Bepaal deterministisch of dit een eerste analyse of een vervolgreactie is.

    FOLLOW_UP_REPLY  ⇔  de thread bevat minstens één coachbericht ÉN het laatste
    relevante (niet-lege) bericht komt van de atleet. Anders INITIAL_ANALYSIS.

    Geen LLM, geen inhoudsheuristiek: alleen `van` (spreker) en de volgorde beslissen.
    Malformed/lege input → veilige INITIAL_ANALYSIS. Lege-tekst berichten tellen niet mee
    als gesprekstobeurt (spiegelt de queue-opbouw die blanco comments al weglaat), zodat
    een blanco/irrelevante athlete-reply geen valse follow-up forceert."""
    if not isinstance(thread, list):
        return INITIAL_ANALYSIS
    msgs = [m for m in thread
            if isinstance(m, dict) and (m.get("tekst") or "").strip()]
    if not msgs:
        return INITIAL_ANALYSIS
    if msgs[-1].get("van") == "atleet" and any(m.get("van") == "coach" for m in msgs):
        return FOLLOW_UP_REPLY
    return INITIAL_ANALYSIS


def _refresh_thread(w: dict) -> None:
    """§9 — lees vóór (her)genereren de ACTUELE thread-state van de server, zodat een
    athlete-comment dat ná de queue-opbouw binnenkwam de mode meebepaalt (geen stale
    gesprekstoestand). Hergebruikt exact de queue-thread-vorm (fs_client.get_workout_thread
    → build_thread). NON-FATAAL: faalt de live-read, dan blijft de gecachete thread staan
    (nooit slechter dan de Streamlit-parity). Overschrijft alleen bij een niet-lege verse
    thread, zodat een transiënte lege read een bestaand gesprek nooit wist."""
    wk, ak = w.get("workout_key"), w.get("athlete_key")
    if not (wk and ak):
        return
    try:
        fresh = FS.get_workout_thread(wk, ak, w.get("post_notes") or "",
                                      w.get("athlete_first_name") or "")
    except Exception:
        return
    if fresh:
        w["thread"] = fresh


# --- FC-1: gedeelde restore-on-miss route + no-resurrection guard -----------------
# `_cache` is process-local en kan na een deploy/OOM-recycle leeg zijn. `detail()`
# herstelde al op miss, maar `genereer()`/`plaats()` niet → coach kreeg "Training niet
# meer in beeld" tot een refresh. Onderstaande ÉNE helper geeft alle drie hetzelfde
# gedrag: cache → herstel uit de bestaande durable snapshot → opnieuw opzoeken, met een
# canonieke skip/afwezigheid-guard zodat een geskipte/verdwenen training niet herleeft.

def _is_canonically_skipped(w: dict) -> bool:
    """True als deze workout canoniek is overgeslagen (gedeelde skipped.json) én de atleet
    daarna geen nieuwe input gaf — EXACT de `_filter_skipped`/`_apply_skips`-semantiek
    (incl. her-activatie). Bij een leesfout: niet als skip behandelen (we blokkeren een
    actieve workout niet op een transiënte fout; skip blijft elders gefilterd)."""
    try:
        return not _filter_skipped([w])
    except Exception:
        return False


def get_or_restore_workout(wid: str) -> dict | None:
    """Eén gedeelde restore-route voor Feedback-workouts (detail/genereer/plaats).

    1) process-local `_cache` eerst;
    2) miss → herstel via de bestaande durable/current queue-snapshot
       (`_queue_current` → `_herstel_cache`, `setdefault` op dezelfde wid → identity blijft);
    3) opnieuw opzoeken.
    Geeft None als de workout canoniek niet meer bestaat: niet in cache én niet in de
    snapshot (gepost/verwijderd), óf canoniek overgeslagen (skipped.json). Resurrect dus
    nooit een geskipte/verdwenen training en verandert geen identity. Geen nieuwe store."""
    w = _cache.get(wid)
    if not w:
        _queue_current()                                 # herstel _cache uit durable snapshot
        w = _cache.get(wid)
    if not w:
        return None                                      # canoniek weg: niet in cache én snapshot
    if _is_canonically_skipped(w):                       # nooit een overgeslagen training resurrecten
        return None
    return w


def _verwijder_uit_queue(wid: str) -> None:
    """Ná een succesvolle post: haal deze nu-beantwoorde workout canoniek weg als openstaand
    item — uit `_cache` (in-proces re-post/hergeneratie-guard) én uit de queue-snapshot
    (mem + durable, zodat een stale durable snapshot hem ná een recycle niet resurrecteert).
    Zo valt een tweede `genereer`/`plaats` door dezelfde 'niet in cache én niet in snapshot →
    None'-route als een echt verdwenen workout. GEEN nieuwe store — een veilige mutatie van
    de BESTAANDE snapshot. Non-fataal: de reactie is al geplaatst; faalt de persist, dan is
    het niet slechter dan voorheen. Concurrency-veilig via `_QLOCK` (zelfde lock als de sweep);
    een concurrent sweep sluit een beantwoorde workout sowieso uit (coach had het laatste
    woord), dus de uitkomst convergeert.

    Class 1 (coherence van de statistieken): in DEZELFDE atomische mutatie stijgt `gepost` met
    precies 1. Zo blijft de open-set (`wachten`) én de teller (`gepost`/`pct`) direct coherent op
    de eerstvolgende fast-read — zonder queue/Home-rebuild. Exact-één-keer: de guard hierboven
    keert al terug als het item al weg is (retry/dubbele post → geen tweede increment), en de
    FC-1 re-post-guard blokkeert een tweede `plaats` sowieso. Skip loopt hier NOOIT langs (die
    raakt alleen `skipped.json`), dus een skip verhoogt `gepost` niet. De volgende sweep
    overschrijft `gepost` met het autoritatieve `posted_today` (geen drift over sweeps heen)."""
    global _QUEUE_MEM
    _cache.pop(wid, None)                                 # in-proces: niet opnieuw actionable
    persist_snap = None
    try:
        with _QLOCK:
            snap = _QUEUE_MEM if _queue_valid(_QUEUE_MEM) else _durable_load_diag()[0]
            if not _queue_valid(snap):
                return
            items = snap.get("items") or []
            volle = snap.get("_volle") or {}
            if wid not in volle and not any(it.get("id") == wid for it in items):
                return                                    # al weg uit de snapshot (retry → geen 2e increment)
            persist_snap = {**snap,
                            "items": [it for it in items if it.get("id") != wid],
                            "_volle": {k: v for k, v in volle.items() if k != wid},
                            "gepost": int(snap.get("gepost", 0) or 0) + 1}
            _QUEUE_MEM = persist_snap
    except Exception:
        return
    if persist_snap is not None:
        _queue_persist(persist_snap)                     # durable (non-fataal via _LAST_PERSIST)


def genereer(wid: str) -> str:
    """AI-concept voor de training met dit id (uit de gecachete lijst).

    Conversation-aware: eerste analyse → generate_feedback; loopt er al een gesprek waarin
    de atleet als laatste reageerde → generate_reply op dat laatste bericht. De mode wordt
    deterministisch bepaald op de VERSE thread-state (zie feedback_mode/_refresh_thread)."""
    w = get_or_restore_workout(wid)                      # FC-1: herstel op miss (deploy/recycle)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst en probeer opnieuw.")
    _ensure_details(wid)                                 # lichte queue → details nu alsnog laden
    w = _cache.get(wid) or w
    _refresh_thread(w)                                   # §9: actuele thread-state vóór dispatch
    brein = _brein_context(w)                            # Masterbrein-context (gated)
    nf = _near_future_block(w)                            # P1: begrensde near-future planning (bounded read)
    sess = _session_context(w)                            # P0: same-day sessie-coherentie (in-proces, geen fetch)
    if brein or nf or sess:
        # kopie: cache niet met prompttekst muteren
        w = {**w, "brein_context": brein, "near_future_block": nf, "session_block": sess}
    import ai_feedback                                   # lui: pas hier is de key nodig
    thread = w.get("thread") or []
    if feedback_mode(thread) == FOLLOW_UP_REPLY:
        # Vervolg in een lopend gesprek: reageer op het laatste athlete-bericht, met
        # dezelfde centrale waarheid + Masterbrein-context als de eerste analyse.
        return ai_feedback.generate_reply(w, thread)
    return ai_feedback.generate_feedback(w)


def plaats(wid: str, tekst: str) -> bool:
    """Post de (bewerkte) feedback als coach-reactie in FinalSurge. WRITE-actie.

    Hergebruikt exact `fs_client.post_comment` (beproefd in Streamlit). Geen AI.
    De coach↔atleet-relatiesleutel voor de badge-reset komt uit de gecachete, bewezen
    roster-map (`fs_client.coach_athlete_key_for`) — geen fragiele per-post live lookup en
    nooit een `user_key`-gok (zie FC-1)."""
    w = get_or_restore_workout(wid)                      # FC-1: herstel op miss (deploy/recycle)
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
                    coach_athlete_key=FS.coach_athlete_key_for(ak))

    # Dossier Fase A — additieve, NIET-FATALE history-hook ná de (locked) send.
    # De reactie is op dit punt al succesvol geplaatst; history-capture komt daarna
    # en mag de send/skip/draft/queue/AI NOOIT raken. Gefaald = stil gediagnosticeerd,
    # geen user-facing failure. Gated via BEBETTER_DOSSIER_HISTORY (default off).
    try:
        from brain import history as _history
        if _history.enabled():
            _history.capture_feedback(
                athlete_key=ak, workout_key=wk,
                workout_date=str(w.get("workout_date") or w.get("date") or ""),
                athlete_messages=_atleet_berichten(w), coach_text=tekst)
    except Exception:
        pass

    # Home's feedbacktegel server-side laten revalideren (geen handmatige teller).
    # Non-fataal: de reactie is al geplaatst.
    _home_invalidate_feedback()

    # Canoniek afhandelen: verwijder de nu-beantwoorde workout uit de queue-snapshot zodat
    # een stale durable snapshot hem ná een recycle NIET opnieuw postbaar maakt, en een
    # warme cache dat in-proces ook niet doet (FC-1 re-post-guard). Non-fataal.
    _verwijder_uit_queue(wid)
    return True


# --- Sessie-samenvatting (Feedback Summary Parity) --------------------------------
# Herstel van de bewezen Streamlit-functionaliteit: één coaching-handover over de
# feedback die deze sessie ÉCHT is gepost. Hergebruikt exact de pure core
# ai_feedback.generate_session_summary — geen tweede prompt, geen FinalSurge/Masterbrein-
# write. De sessielog is workflow-state (client-side, in-memory), geen nieuwe truth-store.

def session_log_item(wid: str, tekst: str) -> dict:
    """Canoniek sessielog-item voor één ZOJUIST succesvol geposte feedback: server-
    bevestigde identiteit uit de queue-cache + de geposte tekst. Vorm = precies wat
    generate_session_summary verwacht (athlete_name/workout_name/feedback_text) plus
    workout_key voor client-side dedup. Alleen aanroepen ná een geslaagde plaats()."""
    w = _cache.get(wid) or {}
    groepen = w.get("athlete_groups") or ([w.get("athlete_group")] if w.get("athlete_group") else [])
    groep = _canon_groep(groepen)
    return {
        "athlete_name": w.get("athlete_name", ""),
        "workout_name": w.get("workout_name") or "Training",
        "workout_key": w.get("workout_key") or wid,
        "feedback_text": (tekst or "").strip(),
        "datum": (w.get("workout_date") or "")[:10],            # Feedback v1 (F): per-datum groepering
        "groep_label": _GROEP_LABEL.get(groep, "Overig"),       # Feedback v1 (F): per-groep groepering
    }


def _clean_summary_items(items) -> list[dict]:
    """Normaliseer + valideer de client-sessielog tot de 3 velden die de core wil.
    Dedupt op workout_key (anders athlete|workout) zodat een dubbele/retried post nooit
    dubbel telt, en dropt lege/malformed items. Geen nieuwe truth — puur opschonen."""
    out: list[dict] = []
    seen: set = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        naam = (it.get("athlete_name") or "").strip()
        workout = (it.get("workout_name") or "").strip()
        tekst = (it.get("feedback_text") or "").strip()
        if not (naam and tekst):                          # geen naam of geen tekst → geen echt item
            continue
        sleutel = it.get("workout_key") or f"{naam}|{workout}"
        if sleutel in seen:
            continue
        seen.add(sleutel)
        out.append({"athlete_name": naam,
                    "workout_name": workout or "Training",
                    "feedback_text": tekst,
                    # Feedback v1 (F): datum/groep meenemen voor per-datum/per-groep-samenvatting.
                    # Puur presentatie; verandert NIET welke items meetellen (successfully-posted truth).
                    "datum": (it.get("datum") or "")[:10],
                    "groep_label": (it.get("groep_label") or "Overig")})
    return out


def session_summary(coach: str, items) -> str:
    """Sessie-samenvatting via de BEWEZEN pure core (ai_feedback.generate_session_summary).
    Geen eigen prompt, geen alternatieve samenvattingslogica, geen FinalSurge/Masterbrein-
    write. Alleen genormaliseerde, daadwerkelijk geposte items tellen mee; lege set → ''."""
    clean = _clean_summary_items(items)
    if not clean:
        return ""
    import ai_feedback                                     # lui: pas hier is de key nodig
    return ai_feedback.generate_session_summary((coach or "").strip(), clean)


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


# ── Feedback-scoped in-memory skip-state (P0 hot-read: 0 externe I/O) ─────────
# De canonieke skip-store blijft `skipped.json` (gedeeld met Streamlit). Deze in-proces
# mirror zorgt dat de WARME queue-read (`_apply_skips`) de skip-reconciliatie doet ZONDER
# per-read GitHub-lezing/-schrijving. Hydratatie gebeurt op de niet-hot paden (prewarm,
# durable-restore, sweep) en na `overslaan`. `None` = nog niet gehydrateerd.
_SKIP_MEM: dict | None = None


def _skips_hydrate() -> None:
    """(Her)laad de skip-store één keer in het geheugen. Alleen op niet-hot paden
    (prewarm/restore/sweep). Non-fataal: bij leesfout blijft de vorige mem-staat staan."""
    global _SKIP_MEM
    try:
        _SKIP_MEM = dict(intake_store.load_skipped() or {})
    except Exception:
        if _SKIP_MEM is None:
            _SKIP_MEM = {}


def _skips_current() -> dict:
    """Skip-state uit het geheugen. Lazy one-shot hydratatie als nog niet geladen
    (`None`); daarna 0 externe I/O. De hot queue-read leunt hierop."""
    global _SKIP_MEM
    if _SKIP_MEM is None:
        _skips_hydrate()
    return _SKIP_MEM if _SKIP_MEM is not None else {}


def _skip_reactivated(w: dict, snap) -> bool:
    """ZELFDE her-activatie-semantiek als `_filter_skipped`: nieuwe atleet-input ná de skip."""
    cur_ts = _athlete_latest_ts(w)
    if isinstance(snap, dict):
        return bool(
            (cur_ts and cur_ts > (snap.get("athlete_ts") or ""))
            or (bool(w.get("post_notes")) and not snap.get("notes"))
            or (bool(w.get("felt")) and not snap.get("felt"))
            or (bool(w.get("effort")) and not snap.get("effort")))
    return cur_ts[:10] > str(snap)[:10]


def overslaan(wid: str) -> bool:
    """Sla een training over (uit de lijst tot de atleet weer nieuwe input geeft).

    CANONIEKE persistence: een skip is pas 'gelukt' als de gedeelde store (skipped.json)
    de write BEVESTIGT. Faalt `save_skipped`, dan mag dit NOOIT stil succes melden — dan
    zou de UI de training verbergen terwijl hij na reload/koude read terugkomt (verloren
    skip). We gooien in dat geval, zodat de API géén 200/ok teruggeeft en de client de
    optimistische verwijdering terugrolt. De duurzame feedback-queue-snapshot wordt
    daarnaast geïnvalideerd (zie `queue()`-leespad → `_apply_skips`), zodat een
    verouderde queue de skip niet opnieuw introduceert."""
    w = _cache.get(wid)
    if not w:
        raise ValueError("Training niet meer in beeld — ververs de lijst.")
    wk = w.get("workout_key", "")
    if not wk:
        raise ValueError("Geen workout-sleutel.")
    global _SKIP_MEM
    sk = intake_store.load_skipped()
    sk[wk] = _snapshot(w)
    ok, err = intake_store.save_skipped(sk)
    if not ok:
        # Persistence niet bewezen → geen success-response (geen verloren skip).
        raise RuntimeError("Overslaan niet opgeslagen: " + (err or "onbekende opslagfout"))
    _SKIP_MEM = dict(sk)                                  # in-memory reconcile → volgende hot read filtert zonder store-read
    # Home's feedbacktegel server-side laten revalideren (geen handmatige teller).
    _home_invalidate_feedback()
    return True


def _filter_skipped(workouts: list) -> list:
    """WRITE-pad (sweep + canonieke skip-guard): overgeslagen trainingen eruit — tenzij de
    atleet ná het overslaan NIEUWE input gaf (her-activatie). Leest de skip-state uit het
    geheugen (`_skips_current`, lazy one-shot hydratatie) en PERSISTEERT een her-activatie
    canoniek (skipped.json) + werkt de in-memory mirror bij. ZELFDE semantiek/store als
    Streamlit. NIET het hot leespad — dat is `_apply_skips` (0 externe I/O)."""
    global _SKIP_MEM
    sk = dict(_skips_current())
    if not sk:
        return workouts
    uit, veranderd = [], False
    for w in workouts:
        wk = w.get("workout_key", "")
        snap = sk.get(wk)
        if snap is None:
            uit.append(w)
            continue
        if _skip_reactivated(w, snap):
            del sk[wk]
            veranderd = True
            uit.append(w)
    if veranderd:
        _SKIP_MEM = dict(sk)                              # mirror bijwerken
        try:
            intake_store.save_skipped(sk)                 # canonieke her-activatie-persist (write-pad)
        except Exception:
            pass
    return uit


def _filter_skipped_mem(workouts: list) -> list:
    """HOT-pad: zelfde filter/her-activatie-BESLISSING als `_filter_skipped`, maar PUUR
    lezend uit het geheugen — GEEN store-lezing en GEEN store-schrijving, en GEEN mutatie
    van de skip-mirror. Een her-geactiveerde workout (nieuwe atleet-input ná skip) wordt
    getoond; de canonieke opruiming van die skip (store + mirror) gebeurt op het
    achtergrond/write-pad (`_filter_skipped` in de sweep). Zo blijft de hot read 0 I/O en
    kan de write-pad de her-activatie later alsnog canoniek persisteren."""
    sk = _skips_current()
    if not sk:
        return workouts
    uit = []
    for w in workouts:
        wk = w.get("workout_key", "")
        snap = sk.get(wk)
        if snap is None or _skip_reactivated(w, snap):    # niet-geskipt óf her-geactiveerd → tonen
            uit.append(w)
    return uit


def _wid(w: dict) -> str:
    """Canonieke item-id voor een workout — ZELFDE afleiding als `_bouw_queue`."""
    return w.get("workout_key") or (str(w.get("athlete_key", "")) + ":" + str(w.get("workout_date", "")))


def _apply_skips(snap: dict) -> dict:
    """Filter een (mogelijk verouderde) queue-snapshot tegen de CANONIEKE skip-store,
    zodat élke queue-read — warme mem, koude durable of verse sweep — geen overgeslagen
    training terugbrengt. Zo kan een skip die ná de laatste sweep is gezet nooit via een
    stale `feedback_queue.json` opnieuw verschijnen (koude read / reload / restart).

    Werkt op `_volle` (de echte workout-dicts in de snapshot) → exact dezelfde
    `_filter_skipped`-semantiek als de sweep, inclusief her-activatie zodra de atleet
    nieuwe input gaf. Ontbreekt `_volle` (oudere lichte snapshot), dan filteren we op de
    skip-keys zelf (veilige richting: verbergen). Idempotent en niet-muterend voor de
    snapshot (levert een nieuwe dict met gefilterde `items`)."""
    items = snap.get("items") or []
    if not items:
        return snap
    sk = _skips_current()                                # HOT: in-memory skip-state, 0 externe I/O
    if not sk:
        return snap
    volle = snap.get("_volle") or {}
    if volle:
        houd = {_wid(w) for w in _filter_skipped_mem(list(volle.values()))}
        gefilterd = [it for it in items if it.get("id") in houd]
    else:
        gefilterd = [it for it in items if it.get("id") not in sk]
    if len(gefilterd) == len(items):
        return snap
    return {**snap, "items": gefilterd}


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
                                                     {"los schema"}, True,
                                                     include_unplanned_reactions=True)
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
    """(snapshot, duur_ms, uitkomst). uitkomst ∈ success|empty|missing|invalid|error:<type>,
    met een bron-suffix (`:github` | `:local_mirror` | `:none`) uit de LKG-resiliente read."""
    t0 = time.perf_counter()
    try:
        durable = intake_store.load_feedback_queue()
    except Exception as e:
        return {}, int((time.perf_counter() - t0) * 1000), "error:" + type(e).__name__
    ms = int((time.perf_counter() - t0) * 1000)
    src = getattr(intake_store, "last_feedback_queue_source", lambda: "durable")()
    if not durable:
        return {}, ms, "missing:" + src
    if not _queue_valid(durable):
        return durable, ms, "invalid:" + src
    return durable, ms, ("empty:" if not durable.get("items") else "success:") + src


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
        _skips_hydrate()                                 # skip-state warm bij durable-restore → hot read = 0 I/O
        src = getattr(intake_store, "last_feedback_queue_source", lambda: "durable")()
        bron = "local_mirror" if src == "local_mirror" else "durable"
        return durable, {"bron": bron, "durable_load_ms": ms,
                         "durable_uitkomst": uitkomst, "source": src}
    return {}, {"bron": "none", "durable_load_ms": ms, "durable_uitkomst": uitkomst}


def prewarm_queue() -> dict:
    """Feedback-only startup pre-warm: laad de durable LKG één keer → warmt `_QUEUE_MEM`
    + `_cache`, zodat de eerste Feedback-open direct uit geheugen serveert (onafhankelijk
    van GitHub-latency op dat moment). Non-fataal en Feedback-gescoped: raakt geen andere
    module/store en heeft géén FinalSurge-token nodig (de durable-read gebruikt de GitHub-
    store). Geeft een diag terug voor server-side logging."""
    t0 = time.perf_counter()
    try:
        snap, bron = _queue_current_diag()               # zet _QUEUE_MEM + _cache bij succes
        _skips_hydrate()                                 # Feedback-scoped skip-state warm → hot read = 0 I/O
    except Exception as e:
        return {"ok": False, "error": type(e).__name__ + ": " + str(e)[:120],
                "prewarm_ms": int((time.perf_counter() - t0) * 1000)}
    ms = int((time.perf_counter() - t0) * 1000)
    n = len(snap.get("items", [])) if snap else 0
    return {"ok": bool(snap), "source": bron.get("bron"),
            "durable_uitkomst": bron.get("durable_uitkomst"),
            "durable_load_ms": bron.get("durable_load_ms"),
            "items": n, "prewarm_ms": ms}


def _queue_current() -> dict:
    """Beste bekende queue-snapshot (zonder diagnostiek) — voor detail()/herstel."""
    snap, _ = _queue_current_diag()
    return snap


# Statussen voor de canonieke open-set (Class 1). 'valid' (structureel bruikbare snapshot,
# `_queue_valid`) en 'fresh' (recent genoeg, `berekend` binnen `_OPEN_TTL_SEC`) zijn EXPLICIET
# verschillende begrippen:
#   FRESH   = geldige ÉN recente snapshot → bewezen-actuele open-set + count.
#   STALE   = geldige maar VERLOPEN snapshot → de open-set-count is nog steeds de per-read
#             gereconcilieerde waarheid (skip/post ZIJN verwerkt via `_apply_skips`/
#             `_verwijder_uit_queue`), dus die count wordt DIRECT getoond; 'stale' betekent enkel
#             dat er mogelijk NIEUWE, nog-niet-geveegde items zijn → niet-blokkerende
#             achtergrond-refresh. (Round-2 regressie A: een skip/post moet Home meteen bijwerken,
#             niet 12–20s wachten op een sweep.)
#   UNKNOWN = geen geldige snapshot op deze instance → GEEN count (nooit een bevroren integer).
# Alleen bij UNKNOWN mag een consumer geen count tonen; STALE toont de gereconcilieerde count.
OPEN_FRESH = "FRESH"
OPEN_STALE = "STALE"
OPEN_UNKNOWN = "UNKNOWN"

# Freshness-venster van de queue-snapshot: gelijk aan de client-side Home-TTL (cockpitStale,
# 15 min). Hergebruikt de bestaande `berekend` op de snapshot — geen nieuwe store/timestamp.
_OPEN_TTL_SEC = 15 * 60


def canonical_open_actions() -> dict:
    """Class 1 — DE ENE canonieke open-set van coach-feedbackacties. Home-tegel,
    Feedback-lijst én de Home-Prioriteiten-feedbackafleiding leiden hun 'wat staat open?'
    hieruit af, zodat ze per definitie niet kunnen divergeren (parity by construction).

    Bron = dezelfde gedeelde queue-snapshot + skip-reconciliatie (`_apply_skips` →
    `_filter_skipped`, inclusief her-activatie) die élke Feedback-read gebruikt, plus
    post-verwijdering (`_verwijder_uit_queue` haalt de beantwoorde workout uit `items`+`_volle`).
    GEEN FinalSurge-sweep, GEEN tweede skiplogica/store, GEEN client-delta.

    Onderscheidt STRUCTURELE geldigheid van FRESHNESS (zie de statusdefinities hierboven):
    - geen geldige snapshot            → UNKNOWN (geen count).
    - geldige snapshot                 → count = per-read gereconcilieerde open-set
                                          (`_apply_skips` incl. skip/post) — DIRECT bruikbaar;
                                          status FRESH als `berekend` recent is, anders STALE
                                          (zelfde count, maar met een achtergrond-refresh-hint voor
                                          eventuele nieuwe items). `gepost` volgt `posted_today`.
    Alleen UNKNOWN levert geen count; een skip/post is via `_apply_skips`/`_verwijder_uit_queue`
    ook op een STALE snapshot al verwerkt, dus wordt de nieuwe count meteen gereflecteerd (A)."""
    snap = _queue_current()
    if not _queue_valid(snap):
        return {"status": OPEN_UNKNOWN, "wachten": None, "gepost": None,
                "pct": None, "open_ids": None}
    open_items = _apply_skips(snap).get("items", [])
    wachten = len(open_items)
    gepost = int(snap.get("gepost", 0) or 0)
    totaal = wachten + gepost
    leeftijd = _snapshot_leeftijd_sec(snap)
    fresh = leeftijd is not None and leeftijd <= _OPEN_TTL_SEC
    return {"status": OPEN_FRESH if fresh else OPEN_STALE,
            "wachten": wachten, "gepost": gepost,
            "pct": int(gepost / totaal * 100) if totaal else 100,
            "open_ids": [it.get("id") for it in open_items]}


def feedback_open_truth() -> dict | None:
    """Back-compat dunne wrapper op `canonical_open_actions` (Class 1). FRESH én STALE → de
    open-set-dict (wachten/gepost/pct/open_ids; STALE draagt dezelfde per-read gereconcilieerde
    count); UNKNOWN → None. Nieuwe code gebruikt `canonical_open_actions` direct."""
    truth = canonical_open_actions()
    if truth.get("status") == OPEN_UNKNOWN:
        return None
    return {"wachten": truth["wachten"], "gepost": truth["gepost"],
            "pct": truth["pct"], "open_ids": truth["open_ids"]}


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


def _atleet_berichten(w: dict) -> list[str]:
    """Canonieke atleet-berichten — ÉÉN bron, dezelfde die `detail()` via `_gesprek`
    toont: de thread (post_notes + atleet-comments, chronologisch). Zo kan de queue
    nooit 'reactie' zeggen terwijl detail 'geen bericht van de atleet' toont (F/G).

    Fallback op post_notes/athlete_comments alleen als er (nog) geen thread is
    opgebouwd (oudere/lichte records) — dan is dát de canonieke bron."""
    uit = [(m.get("tekst") or "").strip() for m in (w.get("thread") or [])
           if m.get("van") == "atleet" and (m.get("tekst") or "").strip()]
    if uit:
        return uit
    fallback = []
    if (w.get("post_notes") or "").strip():
        fallback.append(w["post_notes"].strip())
    fallback += _reacties(w)
    return fallback


def _categorie(w: dict) -> tuple[str, str]:
    """Uitlegbare categorie + preview uit ECHTE data (geen score). 'reactie' wordt
    afgeleid uit dezelfde canonieke atleet-berichten die detail toont (invariant)."""
    berichten = _atleet_berichten(w)
    if berichten:
        return "reactie", berichten[0][:90]
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
            exclude_groups={"los schema"}, return_stats=True, include_details=False,
            include_unplanned_reactions=True)
    except Exception:
        oud = _queue_current()
        if oud:
            return {**oud, "verouderd": True}
        return {"fs": True, "items": [], "gepost": 0, "err": "FinalSurge onbereikbaar."}
    _t_build = time.perf_counter()
    _skips_hydrate()                                     # verse skip-state vóór de write-pad-reconciliatie
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
    """Snapshot → publieke payload (zonder _volle). DETERMINISTISCHE volgorde (Feedback v1 E):
    DATUM eerst (oudste actionable eerst — de coach werkt de achterstand chronologisch weg zodat
    niets veroudert), dan groep (Start to Run→…→Comfort→Overig), dan categorie
    (reactie→gevoel→uitgevoerd), dan athlete-timestamp, dan naam. Dit is de ENIGE sort-waarheid:
    de client rendert exact deze volgorde (geen tweede client-sort). `groepen` = selector-samenvatting.

    ELKE read passeert eerst `_apply_skips`: de canonieke skip-store filtert een
    verouderde snapshot, zodat een net overgeslagen training nooit via een koude/mem
    read terugkomt (bron van waarheid = skipped.json, niet de queue-snapshot)."""
    snap = _apply_skips(snap)
    items = sorted(snap.get("items", []),
                   key=lambda i: ((i.get("datum") or ""),                    # datum eerst (oudste actionable eerst)
                                  _GROEP_RANK.get(i.get("groep"), 9),
                                  _CAT_RANK.get(i["categorie"], 9),
                                  i.get("athlete_ts") or "",
                                  (i.get("naam") or "").lower()))
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
            # FinalSurge-fout tijdens de sweep → `_bouw_queue` gaf de LKG terug met
            # `verouderd`. Behoud die items (nooit blanken) én markeer het refresh-falen.
            verouderd = bool(snap.get("verouderd"))
            extra = {"verouderd": True} if verouderd else {}
            return _queue_public(snap, cached=verouderd, **extra, diag=_diag(snap, {
                "bron": ("sweep_verouderd" if verouderd else "sweep"), "persist_ok": ok,
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
    _upgrade_workout_type(w)


def _upgrade_workout_type(w: dict) -> None:
    """Verrijk workout_type met de bewezen rijke bron (WorkoutPlannedCompleted,
    hetzelfde `Activities[0].activity_type_*` dat Streamlit gebruikt) zodra die is
    geladen. De lichte queue heeft dit veld vaak niet → daar blijft het (voorlopig)
    `unknown`. Hergebruikt `fs_client.classify_workout_type` op het detailobject —
    geen nieuwe classifier, geen extra FinalSurge-call. Een eerder bewezen type
    wordt NOOIT gedegradeerd: we upgraden alleen als het huidige `unknown` is en het
    detail een bewezen type oplevert. Nooit `unknown → run` zonder bewijs."""
    if (w.get("workout_type") or "unknown") != "unknown":
        return
    t = FS.classify_workout_type(w.get("details") or {})
    if t != "unknown":
        w["workout_type"] = t


def afwijking(planned_km, actual_km) -> dict:
    """Afstandsafwijking, deterministisch vóór AI. Eén centrale band (geünificeerd
    met `brain.derive.distance_deviation`, productbeslissing 13 aug 2026):
      <10%   → ignore   (NIET benoemen)
      10–20% → notable  (benoembaar; niet problematiseren bij goede RPE/gevoel/training)
      >=20%  → clear     (benoembaar; NOOIT automatisch negatief)
    Geen geplande afstand → n/a. Het oordeel (goed/slecht) bepaalt de AI/context, nooit deze functie.
    `relevance` blijft 'ignore'/'n/a' voor de UI-chip-gate; 'notable'/'clear' tonen de chip."""
    try:
        p, a = float(planned_km or 0), float(actual_km or 0)
    except (TypeError, ValueError):
        return {"pct": None, "relevance": "n/a", "report": False}
    if not p or not a:
        return {"pct": None, "relevance": "n/a", "report": False}
    pct = round((a - p) / p * 100, 1)
    m = abs(pct)
    if m < 10:
        rel = "ignore"
    elif m < 20:
        rel = "notable"
    else:
        rel = "clear"
    return {"pct": pct, "relevance": rel, "report": rel != "ignore",
            "direction": "over" if pct > 0 else "under"}


def _actual_zone(act: dict, zone_type: str, zones: list) -> dict | None:
    """Zone van het gemiddelde — deterministisch én EERLIJK: geeft alleen `{num,naam}` terug
    als het gemiddelde ECHT binnen een persoonlijke zone valt (IN_ZONE). Een out-of-range
    gemiddelde (sneller/langzamer dan de zones, of in een gat) levert None — nooit een stille
    clamp die als membership oogt (FC-2). De rijke out-of-range-context gaat via de AI-laag."""
    if zone_type == "hartslag":
        hr = act.get("hr_avg")
        try:
            hr = float(hr) if hr else None
        except (TypeError, ValueError):
            hr = None
        cls = FS.classify_pace_hr_zone(zones, hr, is_pace=False) if hr else None
    elif zone_type == "tempo":
        pm = FS._pace_to_float(act.get("pace_display") or "")
        ps = pm * 60 if pm not in (0, float("inf")) else None
        cls = FS.classify_pace_hr_zone(zones, ps, is_pace=True) if ps else None
    else:
        return None
    if cls and cls["status"] == "IN_ZONE":
        return {"num": cls["num"], "naam": cls["naam"]}
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
    w = get_or_restore_workout(wid)                      # FC-1: gedeelde restore-on-miss route
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
