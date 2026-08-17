"""Masterbrein v2 — intake → typed evidence (canonieke intake-kennis).

Één centrale mapping die de RIJKE intake-velden als typed `Evidence` in
`AthleteState` brengt, zodat álle consumers (Schema, Dossier, Home, Teampuls,
rapportages) dezelfde waarheid lezen — géén per-module intake-parser en géén
ruwe passthrough meer voor deze kennis.

Harde regels (spiegelen de opdracht):
  • intake blijft brondata; hier alleen VERBATIM overnemen (geen her-interpretatie);
  • bijna alles is `ATHLETE_REPORTED` (de atleet meldde het zelf) — nooit `FACT`
    of `DERIVED` verzinnen; objectieve identiteitsvelden (leeftijd/horloge) horen
    in het Dossier, niet in de planning-evidence;
  • `unknown blijft unknown`: een leeg veld levert géén Evidence;
  • freshness komt uit `intake_ts` + de centrale `recency`-vensters;
  • blessurehistorie = `HISTORICAL` (verleden, geen actuele klacht → botst niet
    met de klacht-lifecycle en lekt niet naar Feedback/Home);
  • géén nieuwe athlete-identity; `athlete_key` = de canonieke `user_key`.

Deze functie voegt UITSLUITEND nieuwe evidence-keys toe die `state._base_evidence`
en `complaints.build` nog niet leveren (geen dubbele evidence op dezelfde key).
"""
from __future__ import annotations

from datetime import date

from . import recency
from .models import (ACTIVE, ATHLETE_REPORTED, COACH_REPORTED, HISTORICAL, INTAKE_STORE,
                     LOW, STALE, STRUCTURAL, Evidence)

_MAXLEN = 240        # verbatim, maar begrensd (zelfde geest als complaints/coach)


def _ev(key: str, domain: str, value, athlete_key: str, ik_ts: str, *,
        status: str, truth: str = ATHLETE_REPORTED, reporter: str = "athlete",
        detail: dict | None = None) -> Evidence:
    return Evidence(
        key=key, domain=domain, value=str(value).strip()[:_MAXLEN],
        truth_type=truth, status=status, strength=LOW,
        source="intake", source_kind=INTAKE_STORE, observed_at=ik_ts,
        athlete_key=athlete_key, reporter=reporter, detail=detail or {},
    )


def intake_evidence(raw: dict, athlete_key: str, today: date) -> list:
    """Typed evidence uit de rijke intake-velden (verbatim, ATHLETE_REPORTED).

    Levert alleen keys die elders in de brain-pipeline nog NIET bestaan:
    goal.doel/goal.race, recovery.*, complaint.* en coach.memory worden al door
    `state._base_evidence` / `complaints.build` geleverd en hier bewust overgeslagen.
    """
    ik = raw.get("intake") or {}
    if not ik:
        return []
    ik_ts = str(raw.get("intake_ts") or ik.get("updated_at") or "")[:10]
    # 'huidig' venster: recente intake = ACTIVE, oudere = STALE (provisional window).
    fresh = recency.within(ik_ts, today, recency.LIFESTYLE_STALE) if ik_ts else True
    cur = ACTIVE if fresh else STALE

    out: list = []

    def add(key, domain, veld, *, status, truth=ATHLETE_REPORTED, reporter="athlete"):
        v = ik.get(veld)
        if v not in (None, "", [], {}):
            out.append(_ev(key, domain, v, athlete_key, ik_ts,
                           status=status, truth=truth, reporter=reporter))

    # ── PROFILE (structureel — geldig tot gewijzigd) ─────────────────────────
    add("profile.experience", "profile", "loopervaring", status=STRUCTURAL)
    add("profile.preference_likes", "profile", "leuk", status=STRUCTURAL)
    add("profile.preference_dislikes", "profile", "niet_leuk", status=STRUCTURAL)

    # ── BESCHIKBAARHEID (huidige planning-context) ───────────────────────────
    add("training_response.available_days", "training_response", "trainingsdagen", status=cur)
    add("training_response.time_per_session", "training_response", "tijd_per_training", status=cur)

    # ── TRAININGSRESPONS / historie (structureel geleerd) ────────────────────
    add("training_response.schema_history", "training_response", "eerdere_schemas", status=STRUCTURAL)
    add("training_response.responds_well", "training_response", "wat_werkte", status=STRUCTURAL)
    add("training_response.responds_poorly", "training_response", "wat_niet_werkte", status=STRUCTURAL)
    add("training_response.quality_experience", "training_response", "kwaliteitservaring", status=STRUCTURAL)

    # ── BELASTBAARHEID: intake-gerapporteerd volume + referenties ────────────
    add("load.volume_intake", "load", "huidig_volume", status=cur)
    add("load.reference_performance", "load", "referentie_prestatie", status=cur)
    add("load.longest_recent", "load", "langste_afstand", status=cur)

    # ── GEZONDHEID: blessurehistorie = verleden (geen actuele klacht) ────────
    add("health.injury_history", "health", "blessurehistorie", status=HISTORICAL)

    # ── DOELEN / agenda (planning) ───────────────────────────────────────────
    add("goal.race_priority", "goal", "race_prioriteit", status=cur)
    add("goal.intermediate_races", "goal", "tussenraces", status=cur)

    # ── COACH: intake-notitie (eerste indruk/afspraken) ──────────────────────
    add("coach.intake_note", "coach", "coach_notitie",
        status=STALE, truth=COACH_REPORTED, reporter="coach")

    return out
