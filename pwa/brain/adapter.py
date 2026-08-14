"""Masterbrein v2 — compatibility-adapter voor Schema (Fase B).

Grens van de migratie: bestaande Schema-code → bestaande publieke `athlete_context`
API → Masterbrein V2. Schema roept NOOIT rechtstreeks `brain.*` internals aan;
het blijft de legacy contextdict (dezelfde shape als v1 `assemble()`) consumeren,
maar de INHOUD komt nu uit V2:

  • intelligentie (load run-only, klachten-lifecycle, trend, onderbreking,
    belastingsignaal, zone-precedence, contradictions) → `projections.for_schema`;
  • deterministische passthrough (profiel/voorkeuren, leefstijl, doelen/agenda,
    coach-geheugen, verbatim recente coach-notities) → rechtstreeks uit de al
    opgehaalde `raw` (geen her-interpretatie, identiek aan v1-bron).

Harde eigenschappen:
  • RUN-ONLY: km/week + runs/week komen uit `load.*` evidence (V2 draait die al
    op `activity.running_log`), nooit uit de sportmix-`training_summary`.
  • SOURCE-HEALTH blijft betekenisvol: een ontbrekende taak-relevante bron wordt
    NIET platgestreken tot "stabiel"/"geen klachten"; de onzekerheid gaat mee de
    contexttekst in.
  • ÉÉN state-build per contextbuild (één gather); snapshot load→build→save met
    last-known-good, zonder het hot-read principe of de Schema-flow te breken.
  • GEEN stille fallback: bij V2-failure in actieve modus faalt de build zichtbaar
    (de caller levert dan lege context, nooit de oude sportmix-waarde).
"""
from __future__ import annotations

from datetime import date

from . import projections
from . import snapshot as _snapshot
from . import sources as _sources
from . import state as _state
from .models import (ACTIVE, ATTENTION, RECENT, RECURRING, STALE)

# Taak-relevante bronnen voor Schema-planning. Een gap hierin moet zichtbaar
# blijven in de contextrepresentatie (SourceHealth-invariant).
SCHEMA_RELEVANT_SOURCES = {"fs.training_log", "fs.zones", "intake"}

# bron-labels identiek aan v1 (coach-notitie/intake/training) voor _herijking + UI
_BRON_LABEL = {
    "coach_note": "coach-notitie",
    "intake": "intake",
    "fs.training_log": "training",
}


def _compact(d: dict) -> dict:
    # identieke compactie als v1 (athlete_context._compact) — geen import-cycle nodig
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _ev(evs: list, key: str):
    return next((e for e in evs if e.get("key") == key), None)


def _is_stale(e: dict) -> bool:
    return e.get("status") == STALE or bool((e.get("detail") or {}).get("last_known_good"))


# ── Orchestration: snapshot load → gather (1×) → assemble → save ──────────────
def build_state(user_key: str, today: date | None = None, gather_fn=None):
    """Bouw één V2 AthleteState met last-known-good + durable snapshot.

    Retourneert (state, raw). `gather_fn` is injecteerbaar voor tests/outage-sim;
    default = `sources.gather`. Snapshot-fouten mogen de build NOOIT laten crashen
    (best-effort persist); een snapshot-read-fout valt veilig terug op prev=None.
    """
    today = today or date.today()
    gather = gather_fn or _sources.gather

    try:
        prev = _snapshot.load_snapshot(user_key)
    except Exception:
        prev = None

    raw, health = gather(user_key, today)
    ik = raw.get("intake") or {}
    naam = ik.get("athlete_name") or ik.get("naam") or user_key
    state = _state.assemble(user_key, naam, raw, health, today, prev=prev)

    try:
        _snapshot.save_snapshot(state)               # best-effort, nooit fataal
    except Exception:
        pass

    # Dossier Fase A — history-capture (gated, shadow, NIET-FATAAL). Default OFF:
    # verandert niets aan Schema/Feedback. In shadow leidt dit events af uit de
    # snapshot-diff (prev → state) en schrijft ze naar de geïsoleerde history-store;
    # geen enkele consumer leest die in Fase A. Een fout hier mag de build nooit raken.
    try:
        from . import history as _history
        if _history.enabled():
            _history.capture(prev, state, today)
    except Exception:
        pass
    return state, raw


# ── Vertaling V2 AthleteState → legacy contextdict (puur) ────────────────────
def to_legacy_context(state, raw: dict, today: date | None = None) -> dict:
    """Vertaal AthleteState + raw deterministisch naar de v1-contextdict-shape.

    Intelligentie uit `for_schema(state)`; passthrough-velden (verbatim, geen
    her-interpretatie) uit `raw`. De shape is exact die van `athlete_context.assemble`
    zodat `schema_projection` / `to_prompt_text` / `ui_sections` / `used_summary`
    en `_herijking` ongewijzigd blijven werken."""
    today = today or date.today()
    proj = projections.for_schema(state)             # ← V2 is de bron voor Schema
    evs = proj.get("evidence") or []
    gaps = set(proj.get("source_gaps") or [])
    ik = raw.get("intake") or {}

    tl_gap = "fs.training_log" in gaps
    intake_gap = "intake" in gaps

    # ── A. PROFILE (structureel — passthrough, identiek aan v1) ──────────────
    profile = _compact({
        "doel": ik.get("doel"),
        "trainingsdagen": ik.get("trainingsdagen"),
        "zones": ik.get("zones"),
        "zone_type": ik.get("zone_type"),
        "loopervaring": ik.get("loopervaring"),
        "voorkeur_leuk": ik.get("leuk"),
        "voorkeur_niet_leuk": ik.get("niet_leuk"),
    })

    # ── B. TRAINING HISTORY — RUN-ONLY uit V2 load.* evidence ────────────────
    km_ev = _ev(evs, "load.km_per_week")
    runs_ev = _ev(evs, "load.runs_per_week")
    trend_ev = _ev(evs, "load.trend")
    intr_ev = _ev(evs, "load.interruption")

    km = km_ev.get("value") if km_ev else None
    runs = runs_ev.get("value") if runs_ev else None
    trend = trend_ev.get("value") if trend_ev else None
    onderbreking = intr_ev.get("value") if intr_ev else None

    # last-known-good stale-markering: nooit als vers/HIGH presenteren
    if km_ev and _is_stale(km_ev) and km is not None:
        km = f"{km} (laatst bekend, mogelijk verouderd)"
    if onderbreking is None:
        on_hold = raw.get("on_hold") or None
        if isinstance(on_hold, dict) and on_hold.get("since"):
            onderbreking = f"on hold sinds {on_hold.get('since')}: {on_hold.get('reden')}"

    training = _compact({
        "huidig_volume_intake": ik.get("huidig_volume"),
        "km_per_week": km,
        "runs_per_week": runs,
        "trend": trend,
        "onderbreking": onderbreking,
        "eerdere_schema_ervaring": ik.get("eerdere_schemas"),
        "reageerde_goed_op": ik.get("wat_werkte"),
        "reageerde_slecht_op": ik.get("wat_niet_werkte"),
        # SOURCE-HEALTH: geen stille "stabiel" bij bronuitval
        "databron_onzeker": ("recente trainingslog niet beschikbaar — belastbaarheid "
                             "onzeker, bouw conservatief op" if tl_gap else None),
    })

    # ── C. RECOVERY / LIFESTYLE (structureel — passthrough) ──────────────────
    garmin = (raw.get("garmin") or "").strip()
    recovery = _compact({
        "slaap": ik.get("slaap"),
        "leefritme": ik.get("leefritme"),
        "werkdruk_stress": ik.get("werkdruk"),
        "herstelcapaciteit": ik.get("herstelcapaciteit"),
        "garmin_herstel": garmin or None,
    })

    # ── D. HEALTH / COMPLAINTS — V2 lifecycle (status), verbatim tekst ───────
    actuele = _actuele_klachten(state, evs, today)
    terugkerend = sorted({(e.get("detail") or {}).get("area") or e.get("value")
                          for e in evs if e.get("key", "").startswith("complaint.")
                          and not e.get("key", "").startswith("complaint.mention.")
                          and e.get("status") == RECURRING})
    health = _compact({
        "actuele_klachten": actuele or None,
        "terugkerend": terugkerend or None,
        "blessurehistorie": ik.get("blessurehistorie"),
    })

    # ── E. FEEDBACK — belastingsignaal uit V2; coach-notities verbatim ───────
    bel_ev = _ev(evs, "load.signal")
    bel_actueel = None
    if bel_ev:
        bel_actueel = {"ernst": bel_ev.get("value"),
                       "signalen": ((bel_ev.get("detail") or {}).get("signalen") or [])[:3]}
    recente_notities = _recente_coach_observaties(raw, today)
    feedback = _compact({
        "belasting_signaal": bel_actueel,
        "recente_coach_observaties": recente_notities or None,
    })

    # ── F. GOALS / CALENDAR (passthrough) ────────────────────────────────────
    labels = raw.get("labels") or []
    goals = _compact({
        "doel": ik.get("doel"),
        "wedstrijddatum": ik.get("wedstrijddatum") or ik.get("wedstrijddatum_tekst"),
        "race_prioriteit": ik.get("race_prioriteit"),
        "tussenraces": ik.get("tussenraces"),
        "kalender_labels": [f"{l.get('start_date','')}: {l.get('name','')}" for l in labels][:6] or None,
    })

    # ── G. COACH KNOWLEDGE (passthrough) ─────────────────────────────────────
    profiel = (raw.get("profiel") or "").strip()
    coach = _compact({
        "coach_memory": profiel or None,
        "coach_notitie_intake": ik.get("coach_notitie"),
    })

    ctx = {
        "user_key": state.athlete_key, "naam": state.naam,
        "profile": profile, "training": training, "recovery": recovery,
        "health": health, "feedback": feedback, "goals": goals, "coach": coach,
        # V2-verrijking (inert voor v1-consumers; beschikbaar voor diagnostics)
        "_brain": {"overall": state.overall,
                   "source_gaps": sorted(gaps),
                   "schema_relevant_gaps": sorted(gaps & SCHEMA_RELEVANT_SOURCES),
                   "conflicts": list(state.conflicts)},
    }
    ctx["missing"] = _missing(ctx)
    return ctx


def _actuele_klachten(state, evs: list, today: date) -> list:
    """Bouw legacy `actuele_klachten` (list van {tekst,bron,datum,status}) uit V2:
    de STATUS-beslissing komt uit de klacht-lifecycle (for_schema houdt alleen
    actief/recent/recurring), de TEKST is de verbatim melding (geen her-interpretatie)."""
    out = []
    for grp in evs:
        key = grp.get("key", "")
        if not key.startswith("complaint.") or key.startswith("complaint.mention."):
            continue
        st = grp.get("status")
        if st not in (ACTIVE, RECENT, RECURRING):
            continue
        area = (grp.get("detail") or {}).get("area") or grp.get("value")
        # laatste verbatim melding voor dit gebied (uit volledige state, niet for_schema)
        mentions = [e for e in state.evidence
                    if e.key == f"complaint.mention.{area}"]
        mentions.sort(key=lambda e: e.observed_at or "", reverse=True)
        m = mentions[0] if mentions else None
        tekst = (m.value if m else area)
        bron = _BRON_LABEL.get(m.source, "melding") if m else "melding"
        datum = (m.observed_at if m else grp.get("observed_at")) or ""
        intake_only = bool(m and m.source == "intake")
        status_txt = ("terugkerend" if st == RECURRING
                      else ("mogelijk verouderd" if intake_only and _intake_klacht_oud(m, today)
                            else "recent"))
        out.append({"tekst": str(tekst)[:160], "bron": bron, "datum": datum, "status": status_txt})
    # meest recent eerst
    out.sort(key=lambda x: x["datum"], reverse=True)
    return out[:4]


def _intake_klacht_oud(m, today: date) -> bool:
    from . import recency
    return not recency.within(m.observed_at, today, recency.INTAKE_COMPLAINT_STALE) if m.observed_at else False


def _recente_coach_observaties(raw: dict, today: date) -> list:
    """Verbatim recente coach-notities (≤45d), identiek aan v1 (geen interpretatie)."""
    from . import recency
    out = []
    for n in raw.get("notes") or []:
        datum = str(n.get("datum") or "")[:10]
        if recency.within(datum, today, recency.COACH_NOTE_RECENT):
            out.append({"datum": datum, "tekst": (n.get("tekst") or "").strip()[:160]})
    out.sort(key=lambda x: x["datum"], reverse=True)
    return out[:3]


_CORE_CATS = ("profile", "training", "recovery", "health", "feedback", "goals", "coach")


def _missing(ctx: dict) -> list:
    labels = {
        "training": "trainingshistorie", "recovery": "herstel & leefritme",
        "health": "klachten/gezondheid", "feedback": "recente signalen",
        "goals": "races/agenda", "coach": "coachkennis",
    }
    return [labels[c] for c in _CORE_CATS if c in labels and not ctx.get(c)]


# ── Feedback: compacte longitudinale sessiecontext (task projection) ─────────
FEEDBACK_RELEVANT_SOURCES = {"fs.training_log", "coach_notes", "fs.zones"}

_TREND_NL = {"opbouwend": "opbouwend", "afbouwend/minder": "afbouwend",
             "stabiel": "stabiel", "hervat": "net hervat"}


def feedback_context(state, workout_key: str = "") -> dict:
    """Deterministische Feedback-sessiecontext uit `for_feedback(state)` — compact,
    recency/relevance-gefilterd, NOOIT een history-dump. Geeft zowel gestructureerde
    velden (voor diagnostics/shadow) als een korte prompttekst (voor de AI).

    SOURCE-HEALTH: bij een ontbrekende taak-relevante bron wordt GEEN load/klacht-
    claim gedaan; de onzekerheid gaat expliciet mee zodat de AI niet vals geruststelt."""
    proj = projections.for_feedback(state, workout_key)
    evs = proj.get("evidence") or []
    gaps = set(proj.get("source_gaps") or [])
    tl_gap = "fs.training_log" in gaps

    km = _ev(evs, "load.km_per_week")
    runs = _ev(evs, "load.runs_per_week")
    trend = _ev(evs, "load.trend")
    intr = _ev(evs, "load.interruption")
    comp = _ev(evs, "training.compliance")
    rpe = _ev(evs, "recovery.rpe_trend")
    feel = _ev(evs, "recovery.feeling_trend")
    complaints = [e for e in evs if e.get("key", "").startswith("complaint.")
                  and not e.get("key", "").startswith("complaint.mention.")
                  and e.get("status") in (ACTIVE, RECENT, RECURRING)]

    regels: list[str] = []
    if tl_gap:
        regels.append("Recente hardloopbelasting: onbekend (trainingslog tijdelijk niet "
                      "beschikbaar) — doe hier geen aannames over.")
    elif km is not None:
        stale = _is_stale(km)
        kmv = km.get("value")
        rv = runs.get("value") if runs else None
        tv = _TREND_NL.get(str((trend or {}).get("value")), (trend or {}).get("value"))
        stuk = f"Recente hardloopbelasting: ~{kmv} km/week"
        if rv is not None:
            stuk += f", {rv} runs/week"
        if tv:
            stuk += f" (trend: {tv})"
        if stale:
            stuk += " [laatst bekend, mogelijk verouderd]"
        regels.append(stuk + ".")
    if intr is not None:
        regels.append(f"Belangrijk: {intr.get('value')}.")
    if comp is not None:
        regels.append(f"Trainingsopvolging recent: ~{comp.get('value')}% van gepland afgemaakt.")
    subj = []
    if rpe is not None and rpe.get("value") in ("zwaarder", "lichter"):
        subj.append(f"inspanning voelt {rpe.get('value')}")
    if feel is not None and feel.get("value") in ("beter", "slechter"):
        subj.append(f"gevoel {feel.get('value')}")
    if subj:
        regels.append("Subjectieve trend: " + ", ".join(subj) + ".")
    for c in complaints[:2]:
        area = (c.get("detail") or {}).get("area") or c.get("value")
        st = "terugkerend" if c.get("status") == RECURRING else "recent gemeld"
        regels.append(f"Aandacht: klacht rond {area} ({st}) — houd hier rekening mee, "
                      f"maar leg geen oorzakelijk verband met deze training.")

    tekst = ""
    if regels:
        tekst = ("━━━ WAT BEBETTER AL WEET OVER DEZE ATLEET (achtergrond — verzin niets bij) ━━━\n"
                 + "\n".join("- " + r for r in regels)
                 + "\n\nGebruik dit alleen als achtergrond. Vraag NIET naar informatie die hier "
                   "al staat (zoals recente kilometers of frequentie). Noem alleen wat voor DEZE "
                   "training relevant is; verzin geen trainingsplan of weekopbouw.")

    return {
        "workout_key": workout_key,
        "overall": state.overall,
        "source_gaps": sorted(gaps & FEEDBACK_RELEVANT_SOURCES),
        "has_load": km is not None and not tl_gap,
        "complaint_areas": [(c.get("detail") or {}).get("area") or c.get("value") for c in complaints],
        "prompt_block": tekst,
    }


def feedback_context_block(user_key: str, workout_key: str = "", today: date | None = None,
                           gather_fn=None) -> dict:
    """Impure ingang: build_state (1 gather, snapshot, last-known-good) → Feedback-
    sessiecontext. Nooit fataal: bij een fout geeft het een lege, veilige context."""
    try:
        state, _raw = build_state(user_key, today, gather_fn=gather_fn)
    except Exception as e:
        return {"prompt_block": "", "source_gaps": [], "has_load": False,
                "complaint_areas": [], "error": str(e)[:120]}
    return feedback_context(state, workout_key)


# ── Publieke ingang voor de gate (impure) ────────────────────────────────────
def build_context(user_key: str, naam: str = "", today: date | None = None,
                  gather_fn=None) -> dict:
    """Impure ingang: build_state (gather+assemble+snapshot) → legacy contextdict.
    `naam` overschrijft alleen als expliciet meegegeven (contract-compat met v1)."""
    state, raw = build_state(user_key, today, gather_fn=gather_fn)
    ctx = to_legacy_context(state, raw, today)
    if naam:
        ctx["naam"] = naam
    return ctx
