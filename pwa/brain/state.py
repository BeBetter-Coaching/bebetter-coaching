"""Masterbrein v2 — L5 current state + good-is-good + explain (Fase A).

`assemble()` is PUUR (raw+health in → AthleteState uit) zodat de hele
intelligentie deterministisch testbaar is zonder FinalSurge/AI. `build_athlete_state()`
is de onzuivere ingang (gather → assemble → last-known-good). De good-is-good-gate
is deterministisch en wordt NOOIT GOOD zolang een taak-relevante bron ontbreekt.
"""
from __future__ import annotations

from datetime import date, datetime

from . import complaints as _complaints
from . import contradictions as _contradictions
from . import derive as _derive
from . import intake_evidence as _intake_evidence
from . import patterns as _patterns
from . import recency
from . import sources as _sources
from . import zones as _zones
from .models import (ACTIVE, ATHLETE_REPORTED, ATTENTION, COACH_REPORTED, CONFLICT,
                     GOOD, HIGH, HISTORICAL, INSUFFICIENT_DATA, LOW, MEDIUM, RECENT,
                     RECURRING, RESOLVED, STABLE, STALE, SCHEMA_VERSION, AthleteState,
                     Evidence)


def _base_evidence(raw: dict, athlete_key: str, today: date) -> list:
    """L2 basis-evidence uit de goedkope bronnen (goal/coach/lifestyle/load-signaal)."""
    out = []
    ik = raw.get("intake") or {}
    ik_ts = str(raw.get("intake_ts") or "")[:10]

    if ik.get("doel"):
        out.append(Evidence(key="goal.doel", domain="goal", value=ik["doel"],
                            truth_type=ATHLETE_REPORTED, status=ACTIVE, strength=MEDIUM,
                            source="intake", source_kind="INTAKE_STORE", observed_at=ik_ts,
                            athlete_key=athlete_key, reporter="athlete"))
    race = ik.get("wedstrijddatum") or ik.get("wedstrijddatum_tekst")
    if race:
        out.append(Evidence(key="goal.race", domain="goal", value=race,
                            truth_type=ATHLETE_REPORTED, status=ACTIVE, strength=LOW,
                            source="intake", source_kind="INTAKE_STORE", observed_at=ik_ts,
                            athlete_key=athlete_key, reporter="athlete"))

    profiel = (raw.get("profiel") or "").strip()
    if profiel:
        out.append(Evidence(key="coach.memory", domain="coach", value=profiel[:400],
                            truth_type=COACH_REPORTED, status=STALE, strength=LOW,
                            source="coach_memory", source_kind="INTAKE_STORE",
                            athlete_key=athlete_key, reporter="coach",
                            detail={"undated": True}))

    for n in raw.get("notes") or []:
        datum = str(n.get("datum") or "")[:10]
        if recency.within(datum, today, recency.COACH_NOTE_RECENT):
            out.append(Evidence(key="coach.observation", domain="coach",
                                value=(n.get("tekst") or "").strip()[:200],
                                truth_type=COACH_REPORTED, status=RECENT, strength=MEDIUM,
                                source="coach_note", source_kind="INTAKE_STORE",
                                observed_at=datum, athlete_key=athlete_key, reporter="coach"))

    for veld, key in (("slaap", "recovery.slaap"), ("werkdruk", "recovery.werkdruk"),
                      ("leefritme", "recovery.leefritme"), ("herstelcapaciteit", "recovery.herstel")):
        if ik.get(veld):
            stale = not recency.within(ik_ts, today, recency.LIFESTYLE_STALE) if ik_ts else False
            out.append(Evidence(key=key, domain="recovery", value=ik[veld],
                                truth_type=ATHLETE_REPORTED, status=(STALE if stale else ACTIVE),
                                strength=LOW, source="intake", source_kind="INTAKE_STORE",
                                observed_at=ik_ts, athlete_key=athlete_key, reporter="athlete"))

    garmin = (raw.get("garmin") or "").strip()
    if garmin:
        out.append(Evidence(key="recovery.garmin", domain="recovery", value=garmin[:200],
                            truth_type="FACT", status=ACTIVE, strength=MEDIUM,
                            source="garmin", source_kind="INTAKE_STORE", athlete_key=athlete_key))

    bel = raw.get("belasting")
    if isinstance(bel, dict) and bel.get("ernst"):
        fresh = recency.within(str(bel.get("_stand_datum"))[:10], today, recency.LOAD_SIGNAL_FRESH) \
            if bel.get("_stand_datum") else True
        if fresh and not bel.get("_afgehandeld"):
            out.append(Evidence(key="load.signal", domain="load", value=bel["ernst"],
                                truth_type="DERIVED", status=ACTIVE, strength=MEDIUM,
                                source="belasting", source_kind="INTAKE_STORE",
                                observed_at=str(bel.get("_stand_datum") or "")[:10],
                                athlete_key=athlete_key,
                                detail={"signalen": (bel.get("signalen") or [])[:3]}))

    # (Rijke intake-kennis als typed evidence draait als EIGEN geïsoleerde stage in
    #  assemble() — zo wist een fout daar niet de goal/recovery-basis, en vice versa.)
    return out


def _health_map(health: list) -> dict:
    return {h.source: h for h in health}


def _carry_last_known_good(evidence: list, health: list, prev, today: date) -> tuple:
    """Bij een gefaalde bron: behoud vorige evidence van die bron als STALE (niet
    live). Geeft (evidence, source_gaps). Nooit nieuwe HIGH-strength o.b.v. niets."""
    gaps = [h.source for h in health if not h.available]
    if not prev or not gaps:
        return evidence, gaps
    gapset = set(gaps)
    have_ids = {e.id for e in evidence}
    for e in prev.evidence:
        touched = e.source in gapset or any(p in gapset for p in (e.provenance or []))
        if touched and e.id not in have_ids:
            e2 = Evidence.from_dict(e.to_dict())
            e2.status = STALE
            if e2.strength == "HIGH":
                e2.strength = MEDIUM
            e2.detail = {**(e2.detail or {}), "last_known_good": True, "source_stale": True}
            evidence.append(e2)
            have_ids.add(e2.id)
    return evidence, gaps


# Sub-builders die een KERNCOMPONENT voor het overall-oordeel leveren. Faalt één
# hiervan, dan mist het oordeel een essentieel stuk → nooit vals GOOD/STABLE.
_JUDGMENT_CRITICAL_STAGES = ("base_evidence", "complaints", "derive", "last_known_good")


def _good_is_good(evidence: list, health: list, gaps: list, errors: list | None = None) -> str:
    # Een gefaalde kern-stage betekent: oordeel mist een essentieel component →
    # INSUFFICIENT_DATA (geen vals STABLE/GOOD). Source-gaps blijven via de normale
    # weg lopen (die degraderen al correct).
    if any((e.get("stage") in _JUDGMENT_CRITICAL_STAGES) for e in (errors or [])):
        return INSUFFICIENT_DATA
    hm = _health_map(health)
    # taak-relevante kernbron voor 'load stabiel' = training_log (of last-known-good)
    tl = hm.get("fs.training_log")
    # 'has_load' = ECHTE belastbaarheid (afgeleid uit trainingslog/belasting), NIET
    # de door de atleet zelf gemelde intake-volume/referenties. Anders zou een
    # rijke intake de source-health-gate omzeilen (nooit GOOD/STABLE zonder bron).
    has_load = any(e.domain == "load" and e.key.startswith("load.")
                   and e.source != "intake" for e in evidence)
    tl_ok = bool(tl and tl.available) or has_load
    if not tl_ok:
        return INSUFFICIENT_DATA

    active_complaint = any(e.domain == "health" and e.key.startswith("complaint.")
                           and not e.key.startswith("complaint.mention.")
                           and e.status in (ACTIVE, RECURRING) for e in evidence)
    neg_recovery = any(
        (e.key == "recovery.rpe_trend" and e.value == "zwaarder") or
        (e.key == "recovery.feeling_trend" and e.value == "slechter") or
        (e.key == "load.signal" and e.value == "hoog")
        for e in evidence)
    conflict = any(e.status == CONFLICT for e in evidence)

    if active_complaint or neg_recovery or conflict:
        return ATTENTION

    # GOOD is een POSITIEVE claim: alleen bij een bevestigd goed-verdragen patroon
    # (well_tolerated met subjectieve onderbouwing = strength MEDIUM+) én geen
    # trainingsonderbreking. Anders STABLE — rustig, maar zonder te veel te beweren.
    well = next((e for e in evidence if e.key == "load.well_tolerated"), None)
    interruption = any(e.key == "load.interruption" for e in evidence)
    if has_load:
        if well and well.strength in (HIGH, MEDIUM) and not interruption:
            return GOOD
        return STABLE
    return INSUFFICIENT_DATA


def _safe_stage(errors: list, stage: str, fn, fallback):
    """Voer één build-stage geïsoleerd uit. Een onverwachte exception mag NOOIT de
    hele AthleteState wissen: hij wordt technisch gelogd (echte traceback) + als
    diagnostic vastgelegd, en de stage degradeert naar `fallback` zodat alle
    onafhankelijke evidence/intakefacts behouden blijven (partial truth).
    NB: dit is GEEN brede stille catch — het is per-stage isolatie mét diagnostic;
    echte source-failures lopen ONgewijzigd via SourceHealth/source_gaps."""
    try:
        return fn()
    except Exception as e:                               # pragma: no cover — vangnet
        import sys, traceback
        sys.stderr.write(f"[brain.assemble] stage '{stage}' faalde voor build: {e}\n")
        traceback.print_exc()
        errors.append({"stage": stage, "error": type(e).__name__ + ": " + str(e)[:200]})
        return fallback


def assemble(user_key: str, naam: str, raw: dict, health: list,
             today: date | None = None, prev=None) -> AthleteState:
    """PUUR (op I/O na): bouw AthleteState uit al-verzamelde raw + health.

    Elke sub-builder draait GEÏSOLEERD (`_safe_stage`): faalt er één onverwacht,
    dan degradeert alleen die slice en blijft de rest (incl. onafhankelijke intake-
    facts) beschikbaar → partial AthleteState i.p.v. totale uitval. De opgelopen
    build-fouten staan in `state.build_errors` (diagnostic, transient — niet
    gepersisteerd)."""
    today = today or date.today()
    hm = _health_map(health)
    errors: list = []

    evidence = list(_safe_stage(errors, "base_evidence",
                                lambda: _base_evidence(raw, user_key, today), []))
    evidence += _safe_stage(errors, "intake_evidence",
                            lambda: _intake_evidence.intake_evidence(raw, user_key, today), [])
    evidence += _safe_stage(errors, "zones", lambda: _zones.build(raw, hm, user_key, today), [])
    evidence += _safe_stage(errors, "complaints", lambda: _complaints.build(raw, user_key, today), [])
    evidence += _safe_stage(errors, "derive", lambda: _derive.all(raw, user_key, today, evidence), [])
    evidence += _safe_stage(errors, "patterns", lambda: _patterns.all(evidence, raw, user_key, today), [])
    evidence += _safe_stage(errors, "contradictions",
                            lambda: _contradictions.detect(evidence, raw, user_key, today), [])

    evidence, gaps = _safe_stage(
        errors, "last_known_good",
        lambda: _carry_last_known_good(evidence, health, prev, today),
        (evidence, [h.source for h in health if not h.available]))
    overall = _safe_stage(errors, "good_is_good",
                          lambda: _good_is_good(evidence, health, gaps, errors), INSUFFICIENT_DATA)
    conflicts = [e.id for e in evidence if e.status == CONFLICT]

    st = AthleteState(
        athlete_key=user_key, naam=naam or user_key,
        built_at=datetime.now().isoformat(timespec="seconds"),
        overall=overall, schema_version=SCHEMA_VERSION,
        sources=health, evidence=evidence, conflicts=conflicts, source_gaps=gaps,
    )
    # Diagnostic: welke build-stages onverwacht faalden (leeg = alles gebouwd).
    # Runtime-attribuut (transient, niet in de snapshot) — consumers lezen het via
    # getattr zodat een uit de snapshot herbouwde state ook veilig blijft.
    st.build_errors = errors
    return st


def build_athlete_state(user_key: str, naam: str = "", today: date | None = None,
                        prev=None) -> AthleteState:
    """Onzuivere ingang: gather (I/O) → assemble (puur)."""
    raw, health = _sources.gather(user_key, today)
    if not naam:
        ik = raw.get("intake") or {}
        naam = ik.get("athlete_name") or ik.get("naam") or user_key
    return assemble(user_key, naam, raw, health, today, prev)


# ── Explainability (puur) ────────────────────────────────────────────────────
def explain(evidence_id: str, state: AthleteState) -> dict:
    """Verklaar één claim: truth-type, bron(nen), datums, provenance-keten, strength."""
    ev = state.get(evidence_id)
    if not ev:
        return {"error": "onbekende evidence-id"}

    def _chain(eid, depth=0, seen=None):
        seen = seen or set()
        if eid in seen or depth > 6:
            return []
        seen.add(eid)
        node = state.get(eid)
        rows = []
        if node:
            rows.append({"id": node.id, "key": node.key, "truth_type": node.truth_type,
                         "source": node.source, "observed_at": node.observed_at,
                         "status": node.status, "strength": node.strength})
            for pid in node.provenance:
                rows += _chain(pid, depth + 1, seen)
        else:
            rows.append({"id": eid, "source": eid, "unresolved": True})
        return rows

    return {
        "claim": ev.value,
        "key": ev.key,
        "truth_type": ev.truth_type,
        "status": ev.status,
        "strength": ev.strength,
        "observed_at": ev.observed_at,
        "sources": sorted({r.get("source", "") for r in _chain(evidence_id)} - {""}),
        "provenance": _chain(evidence_id),
        "detail": ev.detail,
    }
