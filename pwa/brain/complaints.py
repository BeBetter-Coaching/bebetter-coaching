"""Masterbrein v2 — klacht-normalisatie + lifecycle (Fase A).

Eén centrale klacht-laag uit coach-notities, intake-klacht en post_notes van
uitgevoerde trainingen. Klachtdetectie hergebruikt de BEWEZEN
`belasting._vind_klachten` (zin-niveau, negatie/opgelost-herkenning) — geen
tweede regex-schatkist. Geen medische diagnose, geen causaliteit.

Per klacht-gebied wordt:
  • elke melding een eigen Evidence (ATHLETE_REPORTED / COACH_REPORTED) — provenance;
  • één afgeleide groep-Evidence met lifecycle-status:
      ACTIVE / RECENT / RECURRING / RESOLVED / HISTORICAL.
Een expliciete 'hersteld'-melding wist niets: history blijft, current = RESOLVED.
"""
from __future__ import annotations

import re
from datetime import date

from . import recency
from .models import (ATHLETE_REPORTED, COACH_REPORTED, DERIVED, HIGH, INTAKE_STORE,
                     LOW, MEDIUM, ACTIVE, RECENT, RECURRING, RESOLVED, HISTORICAL,
                     Evidence, derived_evidence, stable_id)

try:
    import belasting as _bel
except Exception:                                    # pragma: no cover
    _bel = None


def _area(label: str) -> str:
    """Normaliseer een klachtlabel naar een gebied ('pijn (knie)' → 'knie')."""
    if not isinstance(label, str):
        label = ""                                       # defensief: nooit re.search op non-str
    m = re.search(r"\(([^)]+)\)", label or "")
    if m:
        return m.group(1).strip().lower()
    return (label or "").strip().lower() or "onbekend"


def _vind(tekst: str) -> list:
    if not tekst or not _bel:
        return []
    try:
        return _bel._vind_klachten(tekst)
    except Exception:
        return []


def _resolved_areas(tekst: str) -> set:
    """Gebieden die in deze tekst als hersteld/opgelost worden genoemd.
    Hergebruikt belasting._LICHAAMSDELEN + _OPGELOST (bewezen semantiek)."""
    if not tekst or not _bel:
        return set()
    out = set()
    for zin in re.split(r"[.!?\n]+", tekst.lower()):
        if not _bel._OPGELOST.search(zin):
            continue
        for dp in _bel._LICHAAMSDELEN:
            dm = re.search(dp, zin)
            if dm:
                out.add(dm.group(0).strip().lower())
    return out


def _mentions(raw: dict, athlete_key: str, today: date) -> list:
    """Verzamel losse klacht-meldingen (nog zonder lifecycle)."""
    ms = []

    # coach-notities
    for n in raw.get("notes") or []:
        datum = str(n.get("datum") or "")[:10]
        for lab in _vind(n.get("tekst") or ""):
            ms.append({"area": _area(lab), "label": lab, "datum": datum,
                       "reporter": "coach", "source": "coach_note", "workout_key": "",
                       "truth": COACH_REPORTED, "kind": INTAKE_STORE})

    # intake-klacht
    ik = raw.get("intake") or {}
    ik_klacht = (ik.get("huidige_klachten") or "").strip()
    if ik_klacht:
        datum = str(raw.get("intake_ts") or "")[:10]
        # Herkent `_vind` geen gelabelde klacht in de vrije intaketekst, dan tóch één
        # 'onbekend'-melding met de ruwe tekst als label (sentinel "" — NIET een dict:
        # dat brak `_area(re.search(...))` met een TypeError → hele complaints-stage viel
        # om → onterecht "interne fout" + klacht onzichtbaar in Dossier terwijl Home hem
        # wél toont). Zo blijft een athlete-gemelde klacht altijd zichtbaar.
        for lab in (_vind(ik_klacht) or [""]):
            ms.append({"area": _area(lab) if lab else "onbekend",
                       "label": lab or ik_klacht[:60], "datum": datum,
                       "reporter": "athlete", "source": "intake", "workout_key": "",
                       "truth": ATHLETE_REPORTED, "kind": INTAKE_STORE,
                       "intake": True})

    # post_notes van uitgevoerde trainingen (goedkoop — al in training_log)
    for e in raw.get("training_log") or []:
        pn = (e.get("post_notes") or "").strip()
        if not pn:
            continue
        for lab in _vind(pn):
            ms.append({"area": _area(lab), "label": lab, "datum": str(e.get("date") or "")[:10],
                       "reporter": "athlete", "source": "fs.training_log",
                       "workout_key": e.get("workout_key") or "",
                       "truth": ATHLETE_REPORTED, "kind": "FS"})
    return ms


def build(raw: dict, athlete_key: str, today: date) -> list:
    """Klacht-evidence (meldingen + afgeleide groepen met lifecycle)."""
    ms = _mentions(raw, athlete_key, today)

    # verzamel resolved-signalen (per gebied) met datum
    resolved: dict = {}
    texts = [(str(n.get("datum") or "")[:10], n.get("tekst") or "") for n in (raw.get("notes") or [])]
    texts += [(str(e.get("date") or "")[:10], e.get("post_notes") or "")
              for e in (raw.get("training_log") or [])]
    for datum, tekst in texts:
        for area in _resolved_areas(tekst):
            if not resolved.get(area) or datum > resolved[area]:
                resolved[area] = datum

    out: list = []
    groups: dict = {}
    for m in ms:
        # melding-evidence
        ev = Evidence(
            key=f"complaint.mention.{m['area']}", domain="health", value=m["label"],
            truth_type=m["truth"], status=RECENT, strength=(MEDIUM if m["reporter"] == "coach" else LOW),
            source=m["source"], source_kind=m["kind"], observed_at=m["datum"],
            athlete_key=athlete_key, workout_key=m["workout_key"], reporter=m["reporter"],
            detail={"area": m["area"], "intake": bool(m.get("intake"))},
        )
        out.append(ev)
        groups.setdefault(m["area"], []).append((m, ev))

    for area, items in groups.items():
        datums = sorted({m["datum"] for m, _ in items if m["datum"]})
        prov = [ev.id for _, ev in items]
        last = datums[-1] if datums else ""
        last_age = recency.age_days(last, today)
        # terugkerend: ≥ min datums binnen het historische venster
        recent_datums = [d for d in datums
                         if (recency.age_days(d, today) or 10**6) <= recency.COMPLAINT_RECURRING_HISTORY.days]
        is_recurring = len(recent_datums) >= recency.COMPLAINT_RECURRING_MIN

        res_date = resolved.get(area)
        is_resolved = bool(res_date and (not last or res_date >= last))

        # lifecycle
        if is_resolved:
            status = RESOLVED
        elif is_recurring:
            status = RECURRING
        elif last_age is not None and last_age <= recency.COMPLAINT_ACUTE.days:
            status = ACTIVE
        elif last_age is not None and last_age <= recency.COMPLAINT_RECENT.days:
            status = RECENT
        else:
            status = HISTORICAL

        # kracht: coachbevestiging of meerdere meldingen = MEDIUM; intake-verouderd = LOW
        has_coach = any(m["reporter"] == "coach" for m, _ in items)
        strength = MEDIUM if (has_coach or len(datums) >= 2) else LOW

        grp = derived_evidence(
            key=f"complaint.{area}", domain="health", value=area,
            status=status, strength=strength, provenance=prov, window="complaint",
            athlete_key=athlete_key,
            detail={"area": area, "count": len(datums), "dates": datums,
                    "last_seen_days": last_age, "recurring": is_recurring,
                    "resolved": is_resolved, "resolved_at": res_date or ""},
        )
        grp.observed_at = last
        out.append(grp)

    return out
