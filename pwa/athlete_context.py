"""BeBetter masterbrein — één gedeelde, taakgerichte atleetcontext.

De kleinste goede centrale contextlaag BOVEN bestaande, betrouwbare stores (geen
nieuwe database, geen embeddings/RAG). Verzamelt wat BeBetter al over een atleet
weet, past deterministische recency/relevantie toe, en levert:

  build_athlete_context(user_key)   -> gestructureerde context (alle categorieën)
  schema_projection(ctx)            -> taakgerichte subset voor Schema-planning
  to_prompt_text(proj)              -> compacte, gestructureerde prompt-tekst
  ui_sections(ctx)                  -> 'Bekende atleetcontext' voor de UI
  used_summary(ctx)                 -> traceability (booleans/tellingen, geen tekst)

Bronnen (source of truth): intake_store (intake, coach-notities, profiel/geheugen,
belasting-stand, on-hold), Garmin-state, FinalSurge trainingslog + kalenderlabels.
Later herbruikbaar door Feedback/Dossier/Home/Teampuls — geen Schema-kopie van
waarheid. `assemble()` is puur (raw in → context uit) zodat recency deterministisch
te testen is; `_gather()` doet de best-effort fetch.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

_HIER = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HIER)
for _p in (_ROOT, _HIER):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import intake_store

# ── Recency-beleid (deterministisch, per contexttype) ────────────────────────
_NOTE_RECENT_DAGEN = 45          # coach-observaties: recent venster
_KLACHT_RECENT_DAGEN = 21        # acute klacht-vermelding in notities
_KLACHT_RECURRING_MIN = 2        # zelfde klacht in ≥2 notities (andere datums) = terugkerend
_INTAKE_VEROUDERD_DAGEN = 120    # intake-klacht ouder dan dit = 'mogelijk verouderd'
_BELASTING_STAND_DAGEN = 3       # opgeslagen belasting-stand ouder dan dit = niet 'actueel'

_KLACHT_WOORDEN = (
    "pijn", "blessure", "klacht", "achilles", "knie", "hamstring", "kuit",
    "scheen", "heup", "rug", "voet", "enkel", "hiel", "itb", "zeer", "stijf",
    "ontsteking", "fasciitis", "peesplaat", "overbelast",
)


def _iso(d) -> str:
    return d if isinstance(d, str) else (d.isoformat() if d else "")


def _parse_d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


# ── Trainingshistorie uit het log (puur, geen pandas) ────────────────────────
def _week_key(d: date) -> date:
    return d - timedelta(days=d.weekday())            # maandag van de week


def training_summary(log: list, today: date) -> dict:
    """Volume/frequentie (laatste 4 wk), trend (4 wk vs 4 wk ervóór) en een
    trainings-ONDERBREKING (recente 0-km-weken na een actieve periode)."""
    if not log:
        return {}
    wk_km: dict = {}
    wk_runs: dict = {}
    for e in log:
        d = _parse_d(e.get("date"))
        if not d or d > today:
            continue
        km = e.get("actual_km") or 0
        if e.get("completed") or km:
            wk = _week_key(d)
            wk_km[wk] = wk_km.get(wk, 0.0) + float(km or 0)
            if not e.get("is_race"):
                wk_runs[wk] = wk_runs.get(wk, 0) + 1

    this_mon = _week_key(today)
    def _wk_range(n0, n1):                              # weken [n0..n1) terug
        return [this_mon - timedelta(weeks=w) for w in range(n0, n1)]
    laatste4 = _wk_range(0, 4)
    vorige4 = _wk_range(4, 8)
    km4 = sum(wk_km.get(w, 0.0) for w in laatste4)
    km_prev4 = sum(wk_km.get(w, 0.0) for w in vorige4)
    runs4 = sum(wk_runs.get(w, 0) for w in laatste4)

    trend = "stabiel"
    if km_prev4 > 0:
        if km4 >= km_prev4 * 1.2:
            trend = "opbouwend"
        elif km4 <= km_prev4 * 0.7:
            trend = "afbouwend/minder"
    elif km4 > 0:
        trend = "hervat"

    # Onderbreking: aaneengesloten recente weken met 0 km (binnen de laatste 10),
    # ná een week mét km. Zo herkennen we 'weer begonnen na X weken minder'.
    weken10 = _wk_range(0, 10)
    onderbreking = None
    streak = 0
    for w in weken10:                                  # nieuw → oud
        if wk_km.get(w, 0.0) <= 0.1:
            streak += 1
        else:
            break
    if streak >= 2:
        onderbreking = f"laatste {streak} weken (bijna) niet getraind"
    else:
        # ook: recent hervat na een gat (0-km-weken direct vóór de actieve weken)
        gat = 0
        gestart = False
        for w in weken10:
            if wk_km.get(w, 0.0) > 0.1:
                gestart = True
            elif gestart:
                gat += 1
        if gestart and gat >= 3:
            onderbreking = f"recent hervat na ~{gat} weken minder/niet trainen"

    return {
        "km_per_week": round(km4 / 4, 1),
        "runs_per_week": round(runs4 / 4, 1),
        "trend": trend,
        "onderbreking": onderbreking,
    }


def _note_klachten(notes: list, today: date) -> dict:
    """Scan coach-notities op klacht-signalen: recent (kort venster) + terugkerend
    (≥2 keer op verschillende datums). Oude losse incidenten vallen weg."""
    recent, per_woord = [], {}
    for n in notes or []:
        tekst = (n.get("tekst") or "")
        low = tekst.lower()
        d = _parse_d(n.get("datum"))
        woorden = {w for w in _KLACHT_WOORDEN if w in low}
        if not woorden:
            continue
        for w in woorden:
            per_woord.setdefault(w, set()).add(_iso(d) if d else tekst[:12])
        if d and (today - d).days <= _KLACHT_RECENT_DAGEN and (today - d).days >= 0:
            recent.append({"datum": _iso(d), "tekst": tekst.strip()[:160],
                           "acuut": (today - d).days <= _KLACHT_RECENT_DAGEN})
    recurring = sorted(w for w, ds in per_woord.items() if len(ds) >= _KLACHT_RECURRING_MIN)
    recent.sort(key=lambda x: x["datum"], reverse=True)
    return {"recent": recent[:4], "recurring": recurring}


def assemble(user_key: str, naam: str, raw: dict, today: date | None = None) -> dict:
    """PUUR: bouw de gestructureerde context uit al-verzamelde ruwe data (`raw`).
    `raw` keys: intake, intake_ts, notes, profiel, belasting, garmin, on_hold,
    training (of training_log), labels."""
    today = today or date.today()
    ik = raw.get("intake") or {}
    notes = raw.get("notes") or []
    profiel = (raw.get("profiel") or "").strip()
    garmin = (raw.get("garmin") or "").strip()
    on_hold = raw.get("on_hold") or None
    labels = raw.get("labels") or []
    intake_ts = _parse_d(raw.get("intake_ts") or ik.get("updated_at") or (ik.get("_opgeslagen") or "")[:10])

    # A. PROFILE (structureel — geldig tot gewijzigd)
    profile = _compact({
        "doel": ik.get("doel"),
        "trainingsdagen": ik.get("trainingsdagen"),
        "zones": ik.get("zones"),
        "zone_type": ik.get("zone_type"),
        "loopervaring": ik.get("loopervaring"),
        "voorkeur_leuk": ik.get("leuk"),
        "voorkeur_niet_leuk": ik.get("niet_leuk"),
    })

    # B. TRAINING HISTORY
    training = raw.get("training")
    if training is None:
        training = training_summary(raw.get("training_log") or [], today)
    training = _compact({
        "huidig_volume_intake": ik.get("huidig_volume"),
        "km_per_week": training.get("km_per_week"),
        "runs_per_week": training.get("runs_per_week"),
        "trend": training.get("trend"),
        "onderbreking": training.get("onderbreking") or (
            f"on hold sinds {on_hold.get('since')}: {on_hold.get('reden')}" if on_hold else None),
        "eerdere_schema_ervaring": ik.get("eerdere_schemas"),
        "reageerde_goed_op": ik.get("wat_werkte"),
        "reageerde_slecht_op": ik.get("wat_niet_werkte"),
    })

    # C. RECOVERY / LIFESTYLE (structureel)
    recovery = _compact({
        "slaap": ik.get("slaap"),
        "leefritme": ik.get("leefritme"),
        "werkdruk_stress": ik.get("werkdruk"),
        "herstelcapaciteit": ik.get("herstelcapaciteit"),
        "garmin_herstel": garmin or None,
    })

    # D. HEALTH / COMPLAINTS (recency + terugkerend)
    kl = _note_klachten(notes, today)
    intake_klacht = ik.get("huidige_klachten")
    intake_verouderd = bool(intake_ts and (today - intake_ts).days > _INTAKE_VEROUDERD_DAGEN)
    actuele = []
    for r in kl["recent"]:
        actuele.append({"tekst": r["tekst"], "bron": "coach-notitie", "datum": r["datum"], "status": "recent"})
    if intake_klacht:
        actuele.append({"tekst": intake_klacht, "bron": "intake", "datum": _iso(intake_ts),
                        "status": "mogelijk verouderd" if intake_verouderd else "gemeld bij intake"})
    health = _compact({
        "actuele_klachten": actuele or None,
        "terugkerend": kl["recurring"] or None,
        "blessurehistorie": ik.get("blessurehistorie"),
    })

    # E. FEEDBACK / COACH SIGNALS (actuele belasting + recente observaties)
    bel = raw.get("belasting") or None
    bel_actueel = None
    if isinstance(bel, dict) and bel.get("ernst"):
        stand_d = _parse_d(bel.get("_stand_datum"))
        vers = (stand_d is None) or ((today - stand_d).days <= _BELASTING_STAND_DAGEN)
        if vers and not bel.get("_afgehandeld"):
            bel_actueel = {"ernst": bel.get("ernst"), "signalen": (bel.get("signalen") or [])[:3]}
    recente_notities = []
    for n in notes:
        d = _parse_d(n.get("datum"))
        if d and 0 <= (today - d).days <= _NOTE_RECENT_DAGEN:
            recente_notities.append({"datum": _iso(d), "tekst": (n.get("tekst") or "").strip()[:160]})
    recente_notities = recente_notities[:3]
    feedback = _compact({
        "belasting_signaal": bel_actueel,
        "recente_coach_observaties": recente_notities or None,
    })

    # F. GOALS / CALENDAR
    goals = _compact({
        "doel": ik.get("doel"),
        "wedstrijddatum": ik.get("wedstrijddatum") or ik.get("wedstrijddatum_tekst"),
        "race_prioriteit": ik.get("race_prioriteit"),
        "tussenraces": ik.get("tussenraces"),
        "kalender_labels": [f"{l.get('start_date','')}: {l.get('name','')}" for l in labels][:6] or None,
    })

    # G. COACH KNOWLEDGE
    coach = _compact({
        "coach_memory": profiel or None,
        "coach_notitie_intake": ik.get("coach_notitie"),
    })

    ctx = {
        "user_key": user_key, "naam": naam,
        "profile": profile, "training": training, "recovery": recovery,
        "health": health, "feedback": feedback, "goals": goals, "coach": coach,
    }
    ctx["missing"] = _missing(ctx)
    return ctx


# ── Helpers ──────────────────────────────────────────────────────────────────
def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


_CORE_CATS = ("profile", "training", "recovery", "health", "feedback", "goals", "coach")


def _missing(ctx: dict) -> list:
    labels = {
        "training": "trainingshistorie", "recovery": "herstel & leefritme",
        "health": "klachten/gezondheid", "feedback": "recente signalen",
        "goals": "races/agenda", "coach": "coachkennis",
    }
    return [labels[c] for c in _CORE_CATS if c in labels and not ctx.get(c)]


def used_summary(ctx: dict) -> dict:
    """Traceability voor logs/debug — GEEN gevoelige tekst, alleen booleans/tellingen."""
    h = ctx.get("health") or {}
    tr = ctx.get("training") or {}
    fb = ctx.get("feedback") or {}
    return {
        "profile": bool(ctx.get("profile")),
        "training_history": bool(tr),
        "onderbreking": bool(tr.get("onderbreking")),
        "lifestyle_context": bool(ctx.get("recovery")),
        "active_complaints": len(h.get("actuele_klachten") or []),
        "recurring_complaints": len(h.get("terugkerend") or []),
        "load_signal": bool(fb.get("belasting_signaal")),
        "coach_notes_used": len(fb.get("recente_coach_observaties") or []),
        "coach_memory": bool((ctx.get("coach") or {}).get("coach_memory")),
        "goals_calendar": bool(ctx.get("goals")),
    }


# ── Schema-projectie + prompt-tekst ──────────────────────────────────────────
def schema_projection(ctx: dict) -> dict:
    """Taakgerichte subset voor Schema-planning (geen admin/documentruis)."""
    return {k: ctx.get(k) for k in _CORE_CATS if ctx.get(k)} | {"naam": ctx.get("naam")}


_SECTIE_TITELS = {
    "training": "Belastbaarheid & trainingshistorie",
    "recovery": "Herstel & leefritme",
    "health": "Gezondheid & klachten",
    "feedback": "Actuele signalen",
    "profile": "Profiel & voorkeuren",
    "goals": "Doelen & agenda",
    "coach": "Coachkennis",
}


def to_prompt_text(proj: dict) -> str:
    """Compacte, gestructureerde context vóór de AI. Bevat expliciet een NEGATIEF
    ('geen bekend') voor klachten/signalen als die er niet zijn — voorkomt dat de
    AI iets verzint. Geen platte dump: alleen geselecteerde, relevante velden."""
    delen = ["━━━ BEKENDE ATLEETCONTEXT (BeBetter) — weeg mee, verzin niets bij ━━━"]
    for cat in ("training", "recovery", "health", "feedback", "profile", "goals", "coach"):
        blok = proj.get(cat)
        if not blok:
            continue
        regels = _blok_regels(cat, blok)
        if regels:
            delen.append(_SECTIE_TITELS.get(cat, cat) + ":\n" + "\n".join("  - " + r for r in regels))
    # Anti-hallucinatie: expliciet negatief als er geen klachten/signalen zijn.
    if not (proj.get("health") or {}).get("actuele_klachten") and not (proj.get("feedback") or {}).get("belasting_signaal"):
        delen.append("Actuele klachten/signalen: GEEN bekend bij BeBetter (verzin er geen).")
    return "\n\n".join(delen)


# V-25: expliciete labels zodat verschillende volume-CONCEPTEN niet als tegenstrijdig lezen.
# 'km per week' = recent berekend gemiddelde (FS-log); 'huidig volume intake' = eigen opgave bij
# intake. Teampuls toont daarnaast de rolling-7 referentie ('laatste 7 dagen · gem. X km/wk').
# Geen rekenwijziging — alleen duidelijker benoemen.
_FIELD_LABELS = {
    "km_per_week": "km/week (recent gemiddelde)",
    "huidig_volume_intake": "volume bij intake (eigen opgave)",
}


def _blok_regels(cat: str, blok: dict) -> list:
    regels = []
    if cat == "health":
        for k in (blok.get("actuele_klachten") or []):
            regels.append(f"klacht: {k['tekst']} ({k['bron']}, {k['datum']}, {k['status']})")
        if blok.get("terugkerend"):
            regels.append("terugkerend: " + ", ".join(blok["terugkerend"]))
        if blok.get("blessurehistorie"):
            regels.append("blessurehistorie: " + str(blok["blessurehistorie"]))
        return regels
    if cat == "feedback":
        bs = blok.get("belasting_signaal")
        if bs:
            regels.append(f"belasting {bs['ernst']}: " + "; ".join(bs.get("signalen") or []))
        for n in (blok.get("recente_coach_observaties") or []):
            regels.append(f"coach ({n['datum']}): {n['tekst']}")
        return regels
    for k, v in blok.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        regels.append(f"{_FIELD_LABELS.get(k, k.replace('_', ' '))}: {v}")
    return regels


def ui_sections(ctx: dict) -> list:
    """'Bekende atleetcontext' voor de UI: leesbare secties; onbekend = duidelijk zo."""
    secties = []
    for cat in ("training", "recovery", "health", "feedback", "goals", "profile", "coach"):
        blok = ctx.get(cat)
        # V-22: het doel staat al in 'Doelen & agenda' (goals) → niet nóg eens in 'Profiel &
        # voorkeuren' herhalen. Alleen deze UI-sectie; de AI-context (ctx) blijft ongemoeid.
        if cat == "profile" and isinstance(blok, dict) and ctx.get("goals", {}).get("doel"):
            blok = {k: v for k, v in blok.items() if k != "doel"}
        regels = _blok_regels(cat, blok) if blok else []
        secties.append({"titel": _SECTIE_TITELS.get(cat, cat),
                        "regels": regels, "onbekend": not regels})
    return secties


# ── Fetch (best-effort) ──────────────────────────────────────────────────────
def _gather(user_key: str) -> dict:
    raw = {}
    try:
        intakes = intake_store.load_intakes() or {}
    except Exception:
        intakes = {}
    try:
        laatste = intake_store.load_laatste_intakes() or {}
    except Exception:
        laatste = {}
    ik = intake_store.nieuwste_intake(intakes.get(user_key), laatste.get(user_key)) or {}
    raw["intake"] = ik if isinstance(ik, dict) else {}
    raw["intake_ts"] = intake_store._intake_ts(raw["intake"]) if raw["intake"] else ""
    for key, fn in (("notes", lambda: intake_store.load_notes().get(user_key, [])),
                    ("profiel", lambda: (intake_store.load_profielen().get(user_key, {}) or {}).get("profiel", "")),
                    ("on_hold", lambda: intake_store.load_on_hold().get(user_key)),
                    ("garmin", lambda: intake_store.garmin_context_text(user_key))):
        try:
            raw[key] = fn()
        except Exception:
            raw[key] = None
    # belasting-stand (opgeslagen; geen herberekening)
    try:
        stand = intake_store.load_belasting() or {}
        res = next((r for r in stand.get("resultaten", []) if r.get("user_key") == user_key), None)
        if res:
            res = dict(res)
            res["_stand_datum"] = stand.get("datum")
            res["_afgehandeld"] = user_key in (stand.get("afgehandeld") or {})
        raw["belasting"] = res
    except Exception:
        raw["belasting"] = None
    # FinalSurge: trainingslog (voor historie) + kalenderlabels — best-effort
    try:
        import fs_client as FS
        raw["training_log"] = FS.get_training_log(user_key, months=4)
    except Exception:
        raw["training_log"] = []
    try:
        import fs_client as FS
        vandaag = date.today()
        raw["labels"] = FS.get_calendar_labels(user_key, vandaag - timedelta(days=7),
                                                vandaag + timedelta(days=90))
    except Exception:
        raw["labels"] = []
    return raw


# ── Masterbrein V2 feature-gate (Fase B) ─────────────────────────────────────
# Eén centrale keuzegrens voor de Schema-contextmigratie. Server-side env, geen
# frontend-toggle, geen verspreide conditionals. Rollback = zet de env terug op
# 'legacy' (of verwijder 'm) — geen codeherstel van Schema-businesslogica nodig.
#
#   legacy  (default): v1-pad ongewijzigd (huidige production).
#   shadow           : output blijft v1; V2 wordt daarnaast gebouwd + vergeleken
#                      (diagnostics onder ctx["_shadow"]), production-output verandert niet.
#   v2               : Schema-context komt via de V2 compatibility-adapter (run-only,
#                      source-health-aware). GEEN stille fallback naar v1 bij V2-failure.
_SCHEMA_BRAIN_ENV = "BEBETTER_SCHEMA_BRAIN"
_SCHEMA_BRAIN_MODES = ("legacy", "shadow", "v2")


def schema_brain_mode() -> str:
    m = (os.environ.get(_SCHEMA_BRAIN_ENV) or "legacy").strip().lower()
    return m if m in _SCHEMA_BRAIN_MODES else "legacy"


def _build_legacy(user_key: str, naam: str, today: date | None) -> dict:
    raw = _gather(user_key)
    if not naam:
        ik = raw.get("intake") or {}
        naam = ik.get("athlete_name") or ik.get("naam") or user_key
    return assemble(user_key, naam, raw, today)


def build_athlete_context(user_key: str, naam: str = "", today: date | None = None) -> dict:
    """Publieke ingang: verzamel + assembleer de gestructureerde atleetcontext.

    Contract (shape van de teruggegeven dict) is identiek in alle modi zodat
    Schema-consumers ongewijzigd blijven. Alleen de INHOUD kan uit V2 komen."""
    mode = schema_brain_mode()

    if mode == "v2":
        # Actieve V2-modus: GEEN stille fallback. Faalt V2, dan faalt de build
        # zichtbaar (caller levert lege context — nooit de oude sportmix-waarde).
        try:
            from brain import adapter as _adapter
            return _adapter.build_context(user_key, naam, today)
        except Exception as e:
            import traceback
            sys.stderr.write(f"[SCHEMA_BRAIN v2] FAILED for {user_key}: {e}\n")
            traceback.print_exc()
            raise

    ctx = _build_legacy(user_key, naam, today)

    if mode == "shadow":
        # Production-output blijft v1; hang een deterministische V2-diff aan voor
        # diagnostics. Nooit fataal — shadow mag production niet raken.
        try:
            from brain import shadow as _shadow
            ctx["_shadow"] = _shadow.semantic_compare(user_key, naam, today, v1_ctx=ctx)
        except Exception as e:
            ctx["_shadow"] = {"error": str(e)[:160]}

    return ctx
