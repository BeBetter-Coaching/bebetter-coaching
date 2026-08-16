"""Masterbrein v2 — Dossier Fase A: snapshot-diff-motor + capture-orkestratie.

Twee zuivere lagen + één onzuivere, gated, NIET-FATALE capture-laag:

  • `derive_events(prev, current, today)` — PUUR: geen I/O, geen AI. Leidt
    HistoryEvents af uit STATUS-OVERGANGEN tussen twee AthleteStates. Hergebruikt
    de bestaande complaint-lifecycle + interruption-derivatie (geen nieuwe
    intelligentie). Harde regels:
      - prev == None  → []   (vanaf-nu: géén fake baseline-events uit de 1e build)
      - source-gap in de relevante bron (prev óf current) → sla die diff over
        (bronuitval is source-health, NOOIT een athlete-event; §19)
      - alleen betekenisvolle overgangen → 1 event (geen ACTIVE↔RECENT-ruis; §10)

  • `derive_feedback_events(...)` — PUUR: leidt een athlete-klacht + (conservatief)
    een coach-response af uit een geposte Feedback-reactie.

  • `capture(prev, current, today)` / `capture_feedback(...)` — gated + best-effort.
    Schrijven alleen in shadow/on-modus; falen mag NOOIT de caller breken.

Gate `BEBETTER_DOSSIER_HISTORY`:
    off     (default) → capture is een no-op (nul gedragsverandering)
    derive            → events afleiden voor diagnostiek, NIET persistent
    shadow            → afleiden + persistent naar geïsoleerde history-store
                        (geen enkele consumer leest die in Fase A)
    on                → idem persistent (gereserveerd voor de latere cockpit)
"""
from __future__ import annotations

import os
from datetime import date

from . import events as E
from . import history_store as _store
from .models import (ACTIVE, ATHLETE_REPORTED, COACH_REPORTED, DERIVED, HIGH,
                     HISTORICAL, LOW, MEDIUM, RECENT, RECURRING, RESOLVED)

# Bronnen waarvan de betrouwbaarheid de klacht-/load-diff bepaalt. Een gap hierin
# (in prev óf current) maakt de betreffende diff onbetrouwbaar → overslaan.
_LOAD_HEALTH_SOURCE = "fs.training_log"

_MODES = ("off", "derive", "shadow", "on")
_PERSIST_MODES = ("shadow", "on")


def mode() -> str:
    m = (os.environ.get("BEBETTER_DOSSIER_HISTORY") or "off").strip().lower()
    return m if m in _MODES else "off"


def enabled() -> bool:
    return mode() != "off"


# ── Helpers: lees semantiek uit een AthleteState ─────────────────────────────
def _complaint_groups(state) -> dict:
    """{area: Evidence} voor de afgeleide klacht-GROEPEN (geen losse mentions)."""
    out = {}
    if not state:
        return out
    for e in state.evidence:
        if e.domain == "health" and e.key.startswith("complaint.") \
                and not e.key.startswith("complaint.mention."):
            area = (e.detail or {}).get("area") or e.value or e.key.split(".", 1)[-1]
            out[str(area)] = e
    return out


def _interruption(state):
    if not state:
        return None
    return next((e for e in state.evidence if e.key == "load.interruption"), None)


def _gaps(state) -> set:
    return set(getattr(state, "source_gaps", []) or [])


def _iso(today: date) -> str:
    return today.isoformat()


# ── PUUR: snapshot-diff → events ─────────────────────────────────────────────
def derive_events(prev, current, today: date | None = None) -> list:
    """Leidt HistoryEvents af uit de overgang prev → current. Puur, deterministisch."""
    today = today or date.today()
    if prev is None or current is None:
        return []                                     # vanaf-nu: geen baseline-events

    out: list = []
    ak = current.athlete_key

    # Betrouwbaarheids-gate: is de load/health-bron in één van beide builds uitgevallen?
    lh_unreliable = _LOAD_HEALTH_SOURCE in (_gaps(prev) | _gaps(current))

    if not lh_unreliable:
        out += _diff_complaints(ak, prev, current, today)
        out += _diff_interruption(ak, prev, current, today)

    return out


# live = klacht die momenteel speelt (niet resolved/historical)
_LIVE = (ACTIVE, RECENT, RECURRING)


def _diff_complaints(ak: str, prev, current, today: date) -> list:
    pc = _complaint_groups(prev)
    cc = _complaint_groups(current)
    out = []
    for area in sorted(set(pc) | set(cc)):
        p = pc.get(area)
        c = cc.get(area)
        ps = p.status if p else None
        cs = c.status if c else None
        if c is None:
            # Klacht is uit current verdwenen (mentions volledig verouderd). Zonder
            # expliciete 'resolved'-melding is dit géén betrouwbare resolution → skip.
            continue

        det = c.detail or {}
        dates = det.get("dates") or []
        first_seen = dates[0] if dates else (c.observed_at or _iso(today))
        last_seen = c.observed_at or (dates[-1] if dates else _iso(today))
        resolved_at = det.get("resolved_at") or last_seen
        prov = list(c.provenance or [])
        # De klacht ontstaat uit een (atleet-/coach-)melding; het diff-event legt de
        # lifecycle vast. We labelen de melding-herkomst ATHLETE_REPORTED (coach-
        # bevestiging zit in strength/patterns, niet in dit lifecycle-event).
        truth = ATHLETE_REPORTED

        etype = eff = None
        if ps in (None, HISTORICAL):
            if cs in _LIVE:
                etype, eff = E.COMPLAINT_STARTED, first_seen
            # cs == RESOLVED zonder eerdere open klacht → niets (geen betekenis)
        elif ps in (ACTIVE, RECENT):
            if cs == RECURRING:
                etype, eff = E.COMPLAINT_RECURRED, last_seen
            elif cs == RESOLVED:
                etype, eff = E.COMPLAINT_RESOLVED, resolved_at
        elif ps == RECURRING:
            if cs == RESOLVED:
                etype, eff = E.COMPLAINT_RESOLVED, resolved_at
        elif ps == RESOLVED:
            if cs in _LIVE:
                etype, eff = E.COMPLAINT_REACTIVATED, last_seen

        if not etype:
            continue
        estatus = E.RESOLVED if etype == E.COMPLAINT_RESOLVED else E.ACTIVE
        out.append(E.HistoryEvent(
            athlete_key=ak, event_type=etype, domain="health", entity=area,
            effective_at=eff, recorded_at=_iso(today), status=estatus,
            truth_type=truth, strength=c.strength or MEDIUM,
            importance=(HIGH if cs in (ACTIVE, RECURRING) else MEDIUM),
            source="brain.diff", source_kind=DERIVED, reporter="system",
            title=_complaint_title(etype, area),
            value=area, evidence_refs=[c.id], provenance_ids=prov,
            transition={"from": ps or "ABSENT", "to": cs},
            detail={"count": det.get("count"), "dates": dates,
                    "resolved_at": det.get("resolved_at") or ""},
        ))
    return out


def _complaint_title(etype: str, area: str) -> str:
    return {
        E.COMPLAINT_STARTED: f"Klacht gestart: {area}",
        E.COMPLAINT_RECURRED: f"Klacht terugkerend: {area}",
        E.COMPLAINT_RESOLVED: f"Klacht hersteld: {area}",
        E.COMPLAINT_REACTIVATED: f"Klacht weer actief: {area}",
    }.get(etype, area)


def _diff_interruption(ak: str, prev, current, today: date) -> list:
    p = _interruption(prev)
    c = _interruption(current)
    out = []
    eff = _iso(today)          # geen betrouwbare fysiologische startdatum → vastleg-datum
    if c is not None and p is None:
        out.append(E.HistoryEvent(
            athlete_key=ak, event_type=E.TRAINING_INTERRUPTION_STARTED, domain="load",
            entity="training", effective_at=eff, recorded_at=eff, status=E.ACTIVE,
            truth_type=DERIVED, strength=c.strength or MEDIUM, importance=HIGH,
            source="brain.diff", source_kind=DERIVED, reporter="system",
            title="Trainingsonderbreking gestart", value=c.value,
            evidence_refs=[c.id], transition={"from": "TRAINING", "to": "INTERRUPTED"},
            detail={"effective_is_recorded": True},
        ))
    elif c is None and p is not None:
        out.append(E.HistoryEvent(
            athlete_key=ak, event_type=E.TRAINING_RESUMED, domain="load",
            entity="training", effective_at=eff, recorded_at=eff, status=E.RESOLVED,
            truth_type=DERIVED, strength=MEDIUM, importance=MEDIUM,
            source="brain.diff", source_kind=DERIVED, reporter="system",
            title="Training hervat", value="hervat",
            transition={"from": "INTERRUPTED", "to": "TRAINING"},
            detail={"effective_is_recorded": True},
        ))
    return out


# ── PUUR: Feedback-reactie → events (conservatief) ───────────────────────────
def derive_feedback_events(athlete_key: str, workout_key: str, workout_date: str,
                           athlete_messages, coach_text: str,
                           today: date | None = None) -> list:
    """Leidt uit één geposte Feedback-reactie af:
      • per gedetecteerde klacht in de atleet-berichten → athlete_complaint_reported;
      • ALLEEN als er een klacht is: één coach_response_recorded (geen 'goed gedaan'-spam).
    Klachtdetectie hergebruikt de BEWEZEN belasting._vind_klachten via complaints._vind."""
    today = today or date.today()
    if not (athlete_key and workout_key):
        return []
    from . import complaints as _complaints

    eff = str(workout_date or "")[:10] or _iso(today)
    areas = []
    for msg in (athlete_messages or []):
        for lab in _complaints._vind(msg or ""):
            areas.append(_complaints._area(lab))
    areas = sorted(set(a for a in areas if a))

    out = []
    for area in areas:
        out.append(E.HistoryEvent(
            athlete_key=athlete_key, event_type=E.ATHLETE_COMPLAINT_REPORTED,
            domain="health", entity=f"{area}@{workout_key}", effective_at=eff,
            recorded_at=_iso(today), status=E.ACTIVE, truth_type=ATHLETE_REPORTED,
            strength=LOW, importance=MEDIUM, source="feedback", source_kind="FS",
            reporter="athlete", title=f"Klacht gemeld in feedback: {area}",
            value=area, workout_key=workout_key,
            detail={"area": area, "via": "feedback"},
        ))
    if areas and (coach_text or "").strip():
        out.append(E.HistoryEvent(
            athlete_key=athlete_key, event_type=E.COACH_RESPONSE_RECORDED,
            domain="feedback", entity=workout_key, effective_at=_iso(today),
            recorded_at=_iso(today), status=E.ACTIVE, truth_type=COACH_REPORTED,
            strength=LOW, importance=LOW, source="feedback", source_kind="FS",
            reporter="coach", title="Coach-reactie op klacht vastgelegd",
            value=None, workout_key=workout_key,
            detail={"complaint_areas": areas, "has_text": True},
        ))
    return out


# ── Gated, NIET-FATALE capture ───────────────────────────────────────────────
def capture(prev, current, today: date | None = None) -> dict:
    """Leid events af uit de snapshot-diff en persisteer ze (gated, best-effort).

    Retourneert compacte diagnostiek. Gooit NOOIT — een history-fout mag de
    brain-build/consumer nooit raken."""
    m = mode()
    if m == "off":
        return {"mode": m, "derived": 0, "written": 0}
    try:
        evs = derive_events(prev, current, today)
        written = 0
        if m in _PERSIST_MODES and evs:
            ok, err, written = _store.append_events(current.athlete_key, evs)
            if not ok:
                return {"mode": m, "derived": len(evs), "written": 0, "error": err}
        return {"mode": m, "derived": len(evs), "written": written,
                "types": sorted({e.event_type for e in evs})}
    except Exception as e:                              # pragma: no cover — vangnet
        return {"mode": m, "derived": 0, "written": 0, "error": str(e)[:160]}


def capture_feedback(athlete_key: str, workout_key: str, workout_date: str,
                     athlete_messages, coach_text: str,
                     today: date | None = None) -> dict:
    """Additieve Feedback-history-hook — gated + best-effort + niet-fataal."""
    m = mode()
    if m == "off":
        return {"mode": m, "derived": 0, "written": 0}
    try:
        evs = derive_feedback_events(athlete_key, workout_key, workout_date,
                                     athlete_messages, coach_text, today)
        written = 0
        if m in _PERSIST_MODES and evs:
            ok, err, written = _store.append_events(athlete_key, evs)
            if not ok:
                return {"mode": m, "derived": len(evs), "written": 0, "error": err}
        return {"mode": m, "derived": len(evs), "written": written}
    except Exception as e:                              # pragma: no cover — vangnet
        return {"mode": m, "derived": 0, "written": 0, "error": str(e)[:160]}
