"""Dossier Fase B v1 — read-only cockpit view-model (menselijke Masterbrein-cockpit).

Leeslaag BOVEN Masterbrein V2: selecteert + prioriteert wat `AthleteState` al weet
en levert één view-model voor de cockpit. **Geen tweede engine, geen writes, geen
nieuwe intelligentie, geen backfill.** Alle betekenis komt uit de bestaande
projecties (`adapter.build_state` → `for_dossier`/`for_home` + `state.explain`
+ `history_store`). Zie `dossier-fase-b-cockpit-design.md`.

Guardrails:
  • hergebruikt de deterministische attention-selectie via de gedeelde brain-
    projectie `for_home` (NIET de Home-module/UI) — read-only;
  • production history-capture blijft OFF; Zone 4 toont de eerlijke empty-state;
  • strikt read-only.
"""
from __future__ import annotations

from datetime import date

import athlete_read as _read                       # Canonical Athlete Read Layer v1 (gedeelde state-read)
from brain import adapter as _adapter
from brain import projections as _proj
from brain import state as _state
from brain import history as _history
from brain import history_store as _hstore
from brain import recency as _recency
from brain.models import (ACTIVE, ATTENTION, CONFLICT, GOOD, HIGH, INSUFFICIENT_DATA,
                          MEDIUM, RECENT, RECURRING, STABLE, STALE)

# ── Domeinkaarten (Z3): kaart → welke evidence-domeinen/keys erin vallen ──────
# Volgorde = weergavevolgorde. 'match' bepaalt of een evidence-item in de kaart hoort.
_CARDS = [
    ("belastbaarheid", "Belastbaarheid & trainingshistorie",
     lambda e: e["domain"] in ("load", "training_response", "zones")),
    ("gezondheid", "Gezondheid & klachten",
     lambda e: e["domain"] == "health"),
    ("herstel", "Herstel & leefritme",
     lambda e: e["domain"] == "recovery"),
    ("doelen", "Doelen & agenda",
     lambda e: e["domain"] == "goal"),
    ("profiel", "Profiel & voorkeuren",
     lambda e: e["domain"] == "profile"),
    ("coach", "Coachkennis",
     lambda e: e["domain"] == "coach"),
]

# Leesbare labels per evidence-key (fallback = geprettificeerde key).
_LABELS = {
    "goal.doel": "Doel", "goal.race": "Wedstrijd", "goal.race_priority": "Race-prioriteit",
    "goal.intermediate_races": "Tussenraces",
    "load.volume_intake": "Huidig volume (intake)", "load.reference_performance": "Referentieprestatie",
    "load.longest_recent": "Langste recent", "load.km_per_week": "Km/week (recent, run-only)",
    "load.runs_per_week": "Runs/week", "load.trend": "Belastingstrend",
    "load.interruption": "Trainingsonderbreking", "load.signal": "Belastingssignaal",
    "load.well_tolerated": "Belasting goed verdragen", "load.possible_relation": "Mogelijk verband",
    "recovery.slaap": "Slaap", "recovery.werkdruk": "Werkdruk/stress", "recovery.leefritme": "Leefritme",
    "recovery.herstel": "Herstelcapaciteit", "recovery.garmin": "Garmin-herstel",
    "recovery.rpe_trend": "Ervaren inspanning (trend)", "recovery.feeling_trend": "Gevoel (trend)",
    "health.injury_history": "Blessurehistorie",
    "training_response.available_days": "Trainingsdagen", "training_response.time_per_session": "Tijd per sessie",
    "training_response.schema_history": "Eerdere schema-ervaring", "training_response.responds_well": "Reageert goed op",
    "training_response.responds_poorly": "Reageert slecht op", "training_response.quality_experience": "Kwaliteitservaring",
    "profile.experience": "Loopervaring", "profile.preference_likes": "Voorkeur (blij van)",
    "profile.preference_dislikes": "Voorkeur (ziet tegenop)",
    "coach.memory": "Coachgeheugen", "coach.intake_note": "Coach-notitie (intake)",
    "zones.personal": "Zones", "zones.structural_over": "Zone-review",
}

_STRENGTH_RANK = {HIGH: 0, MEDIUM: 1}
_LIVE = (ACTIVE, RECENT, RECURRING)
_CORE_SOURCE = "fs.training_log"          # taak-relevante kernbron voor betrouwbaarheid


# ── Identiteit ───────────────────────────────────────────────────────────────
def _identity(key: str, state) -> tuple:
    naam = getattr(state, "naam", "") or key
    groep = ""
    try:
        import fs_client as FS
        for g, leden in (FS.get_athletes_by_group() or {}).items():
            for a in leden:
                if a.get("user_key") == key:
                    return (a.get("name") or naam, g)
    except Exception:
        pass
    return (naam, groep)


def _is_complaint_group(e: dict) -> bool:
    return e["domain"] == "health" and e["key"].startswith("complaint.") \
        and not e["key"].startswith("complaint.mention.")


def _label(key: str) -> str:
    if key in _LABELS:
        return _LABELS[key]
    if key.startswith("complaint."):
        return "Klacht"
    return key.split(".", 1)[-1].replace("_", " ").capitalize()


def _prov_light(e: dict) -> dict:
    """Lichte provenance-chip per claim (§12-E): truth-type + bron + datum/status/strength."""
    return {"truth_type": e.get("truth_type"), "source": e.get("source"),
            "observed_at": e.get("observed_at") or (e.get("detail") or {}).get("resolved_at") or "",
            "status": e.get("status"), "strength": e.get("strength")}


def _value_text(e: dict) -> str:
    if _is_complaint_group(e):
        area = (e.get("detail") or {}).get("area") or e.get("value")
        return str(area)
    v = e.get("value")
    return "" if v is None else str(v)


# ── Attention (Z1) — gedeelde brain-selectie, read-only ──────────────────────
def _mentions_for(state_obj, area: str) -> list:
    ms = [ev for ev in state_obj.evidence if ev.key == f"complaint.mention.{area}"]
    ms.sort(key=lambda ev: ev.observed_at or "", reverse=True)
    return ms


def _attention(st) -> list:
    """Aandachtskaarten uit de single truth `state.evidence` — dezelfde deterministische
    selectie-semantiek als de brain-projecties, maar ZONDER Home's LOW-suppressie:
    een cockpit moet zijn EIGEN ATTENTION kunnen verklaren (een LOW-strength actieve
    klacht die `overall=ATTENTION` maakt, moet hier zichtbaar zijn — Home verbergt LOW
    alleen om lijstruis op het cross-atleet-scherm te vermijden). Read-only, geen
    nieuwe afleiding. Elke kaart draagt het domein dat hij (eventueel) opent.
    Kernbron-gap = betrouwbaarheidskaart die GÉÉN domein opent (§12-C)."""
    cards = []

    for e in st.evidence:
        k = e.key
        if e.domain == "health" and k.startswith("complaint.") \
                and not k.startswith("complaint.mention.") and e.status in _LIVE:
            area = (e.detail or {}).get("area") or e.value
            ms = _mentions_for(st, str(area))
            why = (ms[0].value if ms else str(area))
            datum = (ms[0].observed_at if ms else e.observed_at) or ""
            st_txt = "terugkerend" if e.status == RECURRING else "actief"
            cards.append(_card_obj("complaint", "health", "gezondheid",
                                   f"Klacht: {area} — {st_txt}",
                                   f"{why}" + (f" · {datum}" if datum else ""), e, rank=0))
        elif k == "load.signal" and e.value == "hoog":
            sig = (e.detail or {}).get("signalen") or []
            cards.append(_card_obj("load_signal", "load", "belastbaarheid",
                                   "Verhoogd belastingssignaal",
                                   "; ".join(sig) or str(e.value or ""), e, rank=1))
        elif k == "load.possible_relation":
            # V-05: NOOIT de ruwe enum-value ("possible_relation") als coach-tekst tonen.
            # Bouw een leesbare zin uit de detail (klacht + de vastgelegde 'associatie'-caveat);
            # overdrijf de zekerheid niet (expliciet géén causaliteit).
            _det = e.detail or {}
            _comp = _det.get("complaint")
            _note = _det.get("note") or "associatie, geen oorzaak"
            _why = f"Signaal bij '{_comp}' — {_note}" if _comp else _note
            cards.append(_card_obj("possible_relation", "load", "belastbaarheid",
                                   "Mogelijk verband klacht ↔ training",
                                   _why, e, rank=1))
        elif k == "zones.structural_over" and e.value == "ZONE_REVIEW_CANDIDATE":
            cards.append(_card_obj("zone_review", "zones", "belastbaarheid",
                                   "Zones mogelijk niet passend", "zone-review kandidaat", e, rank=2))
        elif (k == "recovery.rpe_trend" and e.value == "zwaarder") or \
             (k == "recovery.feeling_trend" and e.value == "slechter"):
            cards.append(_card_obj("recovery_neg", "recovery", "herstel",
                                   "Herstel onder druk", f"{_label(k)}: {e.value}", e, rank=2))

    for cid in getattr(st, "conflicts", []) or []:
        e = st.get(cid)
        if e:
            cards.append(_card_obj("conflict", e.domain, _domain_to_card(e.domain),
                                   "Tegenstrijdige bron",
                                   (e.detail or {}).get("resolution") or "coach-check nodig",
                                   e, rank=1))

    if _CORE_SOURCE in set(getattr(st, "source_gaps", []) or []):
        cards.append({"id": "srcgap.training_log", "kind": "source_gap", "domain": "load",
                      "opens": None, "title": "Trainingslog niet beschikbaar",
                      "why": "belastbaarheid onzeker — bouw/oordeel voorzichtig", "rank": 1,
                      "strength": MEDIUM, "prov": None})

    cards.sort(key=lambda c: (c.get("rank", 9), _STRENGTH_RANK.get(c.get("strength"), 9)))
    return cards


def _card_obj(kind, domain, opens, title, why, e, rank):
    return {"id": e.id, "kind": kind, "domain": domain, "opens": opens,
            "title": title, "why": why, "rank": rank, "strength": e.strength,
            "prov": _prov_light(e.to_dict())}


_DOMAIN_TO_CARD = {"load": "belastbaarheid", "training_response": "belastbaarheid",
                   "zones": "belastbaarheid", "health": "gezondheid", "recovery": "herstel",
                   "goal": "doelen", "profile": "profiel", "coach": "coach"}


def _domain_to_card(domain: str) -> str:
    return _DOMAIN_TO_CARD.get(domain, "")


# ── Recent veranderd (Z2) — alléén échte recency (§12-D) ─────────────────────
def _changes(state_obj, today: date) -> list:
    """v1: uitsluitend verschuivingen die AthleteState nú echt als recency draagt.
    Zelfde vorm als een HistoryEvent-slice zodat capture-aan later drop-in vervangt."""
    out = []
    for ev in state_obj.evidence:
        d = ev.detail or {}
        if _is_complaint_group({"domain": ev.domain, "key": ev.key}) and ev.status in (RECENT, RECURRING):
            dates = d.get("dates") or []
            if not dates:
                continue
            area = d.get("area") or ev.value
            st = "terugkerend" if ev.status == RECURRING else "recent gemeld"
            out.append(_change(f"Klacht {area}: {st}", dates[-1], ev, {"to": ev.status}, str(area)))
        elif ev.key == "load.interruption":
            out.append(_change("Trainingsonderbreking", today.isoformat(), ev,
                               {"to": "INTERRUPTED"}, "training"))
        elif ev.status == STALE and d.get("last_known_good"):
            out.append(_change(f"Bron verouderd: {_label(ev.key)}", ev.observed_at or "", ev,
                               {"to": "STALE"}, ev.key))
    # conflicten als verschuiving
    for cid in getattr(state_obj, "conflicts", []) or []:
        ev = state_obj.get(cid)
        if ev:
            out.append(_change("Tegenstrijdige bron", today.isoformat(), ev,
                               {"to": "CONFLICT"}, ev.entity if hasattr(ev, "entity") else ev.key))
    out.sort(key=lambda c: c["effective_at"], reverse=True)
    return out


def _change(title, eff, ev, transition, entity):
    return {"title": title, "effective_at": eff or "", "entity": str(entity),
            "transition": transition, "provenance_refs": [ev.id],
            "source": "state", "derived_from": "state"}


# ── Doelen & planning (compacte projectie, §Doelen) ─────────────────────────
# Projecteert BESTAANDE canonical truth: doel/race uit AthleteState goal-evidence,
# schema-blok/uitvoerwijze uit de reeds geladen intake (laatst geconfigureerde blok).
# GEEN nieuwe schema-state, GEEN extra FS-call — puur zichtbaar maken wat er al is.
def _schema_status(eind: str, today: date) -> str:
    if not eind:
        return ""
    try:
        e = date.fromisoformat(str(eind)[:10])
    except Exception:
        return ""
    d = (e - today).days
    return f"loopt — nog {d} dag{'en' if d != 1 else ''}" if d >= 0 \
        else f"afgelopen — {abs(d)} dag{'en' if abs(d) != 1 else ''} geleden"


def _planning(dossier_evs: list, raw: dict, today: date) -> dict:
    ev = {e["key"]: e for e in dossier_evs}

    def gval(k):
        e = ev.get(k)
        return _value_text(e) if e else ""

    ik = (raw or {}).get("intake") or {}
    rows = []
    doel = gval("goal.doel") or (ik.get("doel") or "")
    if doel:
        rows.append({"label": "Hoofddoel", "value": str(doel)})
    race = gval("goal.race") or (ik.get("wedstrijddatum") or "")
    if race:
        rows.append({"label": "Wedstrijddatum", "value": str(race)})
    prio = gval("goal.race_priority")
    if prio:
        rows.append({"label": "Race-prioriteit", "value": str(prio)})
    start, eind = (ik.get("startdatum") or ""), (ik.get("schema_einddatum") or "")
    if start or eind:
        rows.append({"label": "Schema-blok (laatst geconfigureerd)",
                     "value": f"{start or '?'} → {eind or '?'}"})
        st = _schema_status(eind, today)
        if st:
            rows.append({"label": "Schema-status", "value": st})
        if start or eind or doel:
            rows.append({"label": "Uitvoerwijze",
                         "value": "tijd (minuten)" if ik.get("op_tijd") else "afstand (km)"})
    return {"rows": rows, "onbekend": not rows}


# ── Belasting-observatie (Teampuls-coherentie, §Journey B) ───────────────────
# Zelfde stored stand als Teampuls/Home (geen recompute, geen nieuwe engine). Maakt de
# belastingobservatie zichtbaar in Dossier voor ELKE relevante toestand:
#   • actief-hoog + open Home-actie  → de reden achter een rode Home-trigger (+200%);
#   • afgehandeld                    → verklaart waarom er géén open Home-actie is;
#   • let_op                         → monitoring, nog geen coachactie.
# Dit is de canonieke, altijd-aanwezige verklaringsregel: eerder toonde de UI de
# actief-hoge case NIET (die leunde alleen op de attention-kaart), waardoor de reden
# van een rode Home/Teampuls-trigger in Dossier kon verdwijnen. None = geen (relevant)
# signaal. Verzint niets: leest alleen `raw["belasting"]` (dezelfde stand als Home/Teampuls).
#   • home_action = canonieke 'open Home-actie' = zichtbaar in `zichtbare_resultaten`
#     = precies `not _afgehandeld` (escalatie/expiry al ingebakken in `_afgehandeld`);
#   • delta_pct   = het percentage boven de referentie uit `metrics.ratio` (bv. +200%),
#     alléén als de stand die canonieke waarde draagt — nooit verzonnen.
def _load_observation(raw: dict, today: date) -> dict | None:
    bel = (raw or {}).get("belasting") or {}
    ernst = bel.get("ernst")
    if ernst not in ("hoog", "let_op"):
        return None
    # ZELFDE freshness-guard als `load.signal` (state.py, `recency.LOAD_SIGNAL_FRESH`):
    # een verouderde belastingstand is GEEN actuele Teampuls-observatie en mag niet
    # bovenaan Dossier blijven staan. Geen datum bekend → behandel als vers (bewezen
    # gedrag van load.signal).
    sd = str(bel.get("_stand_datum") or "")[:10]
    if sd and not _recency.within(sd, today, _recency.LOAD_SIGNAL_FRESH):
        return None
    afgehandeld = bool(bel.get("_afgehandeld"))
    # v2: +X% via de ENE gedeelde load-metric-projectie (coach_read), zodat Dossier
    # exact dezelfde delta toont als Home/Teampuls. Alleen een positieve volume-sprong
    # is een 'delta' (klacht/rpe-signaal zonder volume → geen verzonnen percentage).
    import coach_read
    _p = coach_read.load_metric(bel)["pct"]
    delta_pct = _p if isinstance(_p, int) and _p > 0 else None
    return {"ernst": ernst,
            "signalen": "; ".join((bel.get("signalen") or [])[:3]),
            "afgehandeld": afgehandeld,
            "home_action": not afgehandeld,
            "delta_pct": delta_pct,
            "datum": sd}


# ── Domeinkaarten (Z3) ───────────────────────────────────────────────────────
def _domains(dossier_evs: list, open_cards: set) -> list:
    cards = []
    for card_key, titel, match in _CARDS:
        regels = []
        for e in dossier_evs:
            if e["key"].startswith("complaint.mention."):
                continue
            if e["key"] == "coach.observation":
                continue
            if _is_complaint_group(e) and e.get("status") not in _LIVE:
                continue                                   # resolved/historisch niet in de v1-kaart
            if not match(e):
                continue
            val = _value_text(e)
            if _is_complaint_group(e):
                val = f"{val} ({str(e.get('status') or '').lower()})"
            if val in ("", "None"):
                continue
            regels.append({"label": _label(e["key"]), "value": val,
                           "prov": _prov_light(e), "evidence_id": e.get("id")})
        cards.append({"key": card_key, "titel": titel, "regels": regels,
                      "onbekend": not regels, "open": card_key in open_cards})
    return cards


# ── Betrouwbaarheid / source-health (Z0/Z5) ──────────────────────────────────
def _reliability(st) -> dict:
    gaps = list(getattr(st, "source_gaps", []) or [])
    stale = any(ev.status == STALE and (ev.detail or {}).get("last_known_good")
                for ev in st.evidence)
    if st.overall == INSUFFICIENT_DATA:
        level = "red"
    elif gaps or stale:
        level = "amber"
    else:
        level = "green"
    return {"level": level, "gaps": gaps, "stale": stale,
            "core_gap": _CORE_SOURCE in gaps}


def _sources(state_obj) -> list:
    out = []
    for s in getattr(state_obj, "sources", []) or []:
        sd = s.to_dict() if hasattr(s, "to_dict") else dict(s)
        out.append({"source": sd.get("source"), "available": sd.get("available"),
                    "stale": sd.get("stale"), "last_success": sd.get("last_success"),
                    "coverage_start": sd.get("coverage_start"), "coverage_end": sd.get("coverage_end"),
                    "error": sd.get("error")})
    return out


# ── Publieke ingang ──────────────────────────────────────────────────────────
def cockpit(key: str, today: date | None = None) -> dict:
    """Bouw het read-only cockpit view-model voor één atleet. Read-only; nooit een
    write. Gooit door bij een bronfout (endpoint → ok:false → UI toont source-health
    'context tijdelijk niet beschikbaar', NOOIT 'niets bekend')."""
    today = today or date.today()
    # Canonical Athlete Read Layer v1: gedeelde state-read (hot-read → single-flight → LKG).
    # Geen tweede build_state-pad meer; `raw` komt uitsluitend uit een live gather (NOOIT uit de
    # snapshot). Is er geen live build én geen LKG (state None) → gooi door zodat de route ok:false
    # levert en de UI de source-health-staat toont ("interne fout ≠ niets bekend", §9).
    read = _read.get_state(key, today=today)                   # gated capture = no-op (OFF)
    state_obj, raw = read.state, read.raw
    if state_obj is None:
        raise RuntimeError("AthleteState onbeschikbaar (geen live build en geen last-known-good)")
    raw_ok = bool(read.freshness.get("raw_available", raw is not None))
    dossier = _proj.for_dossier(state_obj)
    dossier_evs = dossier["evidence"]

    naam, groep = _identity(key, state_obj)
    attention = _attention(state_obj)

    # welke domeinkaarten open (max 2, o.b.v. aandachtsoorzaak; source-gap opent niets)
    opens = [c["opens"] for c in attention if c.get("opens")]
    open_cards = set()
    for o in opens:
        if o and o not in open_cards:
            open_cards.add(o)
        if len(open_cards) >= 2:
            break

    changes = _changes(state_obj, today)
    # raw-afhankelijke secties degraderen alleen als er geen live raw is (pure LKG-fallback):
    # nooit fake belasting/planning uit de snapshot.
    planning = _planning(dossier_evs, raw if raw_ok else {}, today)
    load_observation = _load_observation(raw, today) if raw_ok else None
    domains = _domains(dossier_evs, open_cards)

    # Zone 4 — tijdlijn (capture OFF → eerlijke empty-state)
    events = [_event_view(e) for e in _hstore.get_recent_events(key, limit=25)]
    timeline = {"events": events,
                "capture_mode": _history.mode(),
                "empty_reason": None if events else "capture_off"}

    return {
        "ok": True, "key": key, "naam": naam, "groep": groep,
        # Canonical Athlete Read Layer v1: generation/freshness reizen mee zodat 'Waarom?' de
        # exact getoonde generatie kan verklaren (Gate 3) en de client mem-vs-fresh kan zien.
        "state_generation_id": read.state_generation_id,
        "read_freshness": dict(read.freshness),
        "status": {"overall": state_obj.overall,
                   "insufficient": state_obj.overall == INSUFFICIENT_DATA,
                   "reliability": _reliability(state_obj)},
        "attention": attention,
        "attention_domains": sorted(open_cards),
        "load_observation": load_observation,
        "changes": changes,
        "planning": planning,
        "domains": domains,
        "timeline": timeline,
        "source_health": _sources(state_obj),
        # Partial-truth diagnostic: build-stages die onverwacht faalden (geen bronfout).
        # Leeg = volledige build. De cockpit toont hiermee eerlijk dat een deel niet
        # berekend kon worden, zónder alle bekende kennis te verbergen.
        "build_diagnostic": list(getattr(state_obj, "build_errors", []) or []),
    }


def _event_view(ev) -> dict:
    d = ev.to_dict() if hasattr(ev, "to_dict") else dict(ev)
    return {k: d.get(k) for k in ("event_type", "domain", "entity", "title", "value",
                                  "effective_at", "recorded_at", "status", "truth_type",
                                  "strength", "importance", "transition", "source")}


def explain_claim(key: str, evidence_id: str, today: date | None = None,
                  gen: str = "") -> dict:
    """'Waarom?'-laag (§12-E): provenance-keten voor één claim, on-demand.

    Canonical Athlete Read Layer v1 (Gate 3) — generatiecoherentie: de uitleg wordt uit
    dezelfde gedeelde state-read gehaald als de getoonde cockpit. Vraagt de client een `gen`
    die niet (meer) de actuele generatie is, dan verklaren we NIET stil een nieuwere staat —
    we markeren `generation_changed` en verzinnen geen uitleg voor de oude claim."""
    read = _read.get_state(key, today=today or date.today())
    state_obj = read.state
    current_gen = read.state_generation_id
    if gen and gen != current_gen:
        return {"explain": None, "generation_changed": True, "current_generation": current_gen,
                "note": "De context is intussen ververst — deze onderbouwing hoort bij een oudere staat."}
    if state_obj is None:
        return {"explain": None, "generation_changed": bool(gen),
                "current_generation": current_gen, "note": "Context nu niet beschikbaar."}
    return {"explain": _state.explain(evidence_id, state_obj),
            "generation_changed": False, "current_generation": current_gen}
