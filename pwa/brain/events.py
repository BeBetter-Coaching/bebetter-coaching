"""Masterbrein v2 — Dossier Fase A: HistoryEvent-model (append-only geheugenlaag).

Een `HistoryEvent` is een longitudinale representatie van een BETEKENISVOLLE
verandering/gebeurtenis — NIET een tweede waarheid naast `Evidence`. Evidence
beschrijft "wat geldt nu" (recomputed per build); een HistoryEvent legt "wat
veranderde op moment T" onherroepelijk vast. De brug terug naar de onderbouwing
loopt via `evidence_refs` / `provenance_ids` (geen data-duplicatie).

Harde eigenschappen (zie dossier-architecture-design.md §D):
  • deterministische, semantische `id` (nooit runtime-timestamp / lijstpositie /
    random UUID) → herbouwen van dezelfde overgang levert hetzelfde event → dedupe;
  • plat + JSON-serialiseerbaar (zelfde stijl als `Evidence`), forward-compatible;
  • hergebruikt de bestaande enums (truth_type / status / strength) uit `models`;
  • géén vrije AI-tekst in de canonieke velden (title/value zijn deterministisch).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import MEDIUM, UNKNOWN, stable_id

EVENT_SCHEMA_VERSION = 1

# ── Event-types ──────────────────────────────────────────────────────────────
# Fase A leidt alleen de betrouwbaar-afleidbare types af (klacht-lifecycle +
# interruption/return + Feedback-klacht). De overige types zijn NU al gedefinieerd
# zodat het model forward-compatible is (coach-editor/schema-hooks in latere fasen),
# maar worden in Fase A NIET geëmit.

# Klacht-lifecycle (afgeleid uit complaints-evidence-overgangen)
COMPLAINT_STARTED = "complaint_started"
COMPLAINT_RECURRED = "complaint_recurred"          # became recurring
COMPLAINT_RESOLVED = "complaint_resolved"
COMPLAINT_REACTIVATED = "complaint_reactivated"    # resolved → weer actief

# Trainingsonderbreking / hervatting (afgeleid uit load.interruption-overgang)
TRAINING_INTERRUPTION_STARTED = "training_interruption_started"
TRAINING_RESUMED = "training_resumed"

# Feedback-interactie (additieve, niet-fatale hook ná de locked send)
ATHLETE_COMPLAINT_REPORTED = "athlete_complaint_reported"
COACH_RESPONSE_RECORDED = "coach_response_recorded"

# ── Forward-compatible (nog NIET geëmit in Fase A) ───────────────────────────
GOAL_SET = "goal_set"
GOAL_CHANGED = "goal_changed"
RACE_PLANNED = "race_planned"
RACE_COMPLETED = "race_completed"
ZONES_CHANGED = "zones_changed"
ZONE_REVIEW_FLAGGED = "zone_review_flagged"
ON_HOLD_STARTED = "on_hold_started"
ON_HOLD_RESUMED = "on_hold_resumed"
SCHEMA_BLOCK_STARTED = "schema_block_started"
SCHEMA_RECALIBRATED = "schema_recalibrated"
COACH_DECISION = "coach_decision"
COACH_CONTEXT_ADDED = "coach_context_added"
COACH_CORRECTION = "coach_correction"
PATTERN_CONFIRMED = "pattern_confirmed"
INTERPRETATION_REJECTED = "interpretation_rejected"

EVENT_TYPES = {
    COMPLAINT_STARTED, COMPLAINT_RECURRED, COMPLAINT_RESOLVED, COMPLAINT_REACTIVATED,
    TRAINING_INTERRUPTION_STARTED, TRAINING_RESUMED,
    ATHLETE_COMPLAINT_REPORTED, COACH_RESPONSE_RECORDED,
    GOAL_SET, GOAL_CHANGED, RACE_PLANNED, RACE_COMPLETED,
    ZONES_CHANGED, ZONE_REVIEW_FLAGGED, ON_HOLD_STARTED, ON_HOLD_RESUMED,
    SCHEMA_BLOCK_STARTED, SCHEMA_RECALIBRATED,
    COACH_DECISION, COACH_CONTEXT_ADDED, COACH_CORRECTION,
    PATTERN_CONFIRMED, INTERPRETATION_REJECTED,
}

# ── Event-status (los van Evidence-status; beschrijft de event-levensloop) ────
ACTIVE = "ACTIVE"
RESOLVED = "RESOLVED"
HISTORICAL = "HISTORICAL"
SUPERSEDED = "SUPERSEDED"

# ── Importance (deterministisch, zie design §F) ──────────────────────────────
# History-RETENTIE ≠ prominentie: alles wordt bewaard, importance stuurt alleen
# hoe prominent de cockpit het later toont.


def event_id(athlete_key: str, event_type: str, domain: str, entity: str,
             effective_at: str) -> str:
    """Deterministische event-id uit SEMANTIEK (nooit runtime-ts/positie/random).

    Identiteit = (atleet, type, domein, entiteit, effectieve datum). BEWUST géén
    provenance in de id: mentions stapelen over builds, maar dezelfde overgang
    houdt dezelfde id → idempotente append/dedupe blijft kloppen ook als er later
    onderbouwing bijkomt. Provenance is metadata (traceerbaarheid), geen identiteit.
    """
    return "e_" + stable_id("evt", athlete_key, event_type, domain, entity,
                            effective_at or "")


@dataclass
class HistoryEvent:
    athlete_key: str
    event_type: str                              # één van EVENT_TYPES
    domain: str = ""                             # health | load | goal | zones | coach | schema | source | feedback
    entity: str = ""                             # semantische entiteit (bv. klacht-gebied "kuit")
    effective_at: str = ""                       # ISO-datum: wanneer het GOLD
    recorded_at: str = ""                        # ISO-datum: wanneer VASTGELEGD (scheidt "toen" van "nu")
    status: str = ACTIVE                         # ACTIVE | RESOLVED | HISTORICAL | SUPERSEDED
    truth_type: str = UNKNOWN                    # FACT | DERIVED | ATHLETE_REPORTED | COACH_REPORTED | AI_INTERPRETATION
    strength: str = UNKNOWN                      # HIGH | MEDIUM | LOW
    importance: str = MEDIUM                     # HIGH | MEDIUM | LOW (deterministisch)
    source: str = ""                             # bron-label (bv. "brain.diff", "fs.training_log", "feedback")
    source_kind: str = ""                        # FS | INTAKE_STORE | DERIVED | AI
    reporter: str = ""                           # athlete | coach | system
    title: str = ""                              # korte, deterministische samenvatting (geen AI)
    value: object = None                         # compacte deterministische waarde/summary
    workout_key: str = ""                        # optionele workout-provenance
    related_ref: str = ""                        # optioneel: race | schema_block | ...
    evidence_refs: list = field(default_factory=list)    # ids van onderliggende Evidence (huidige state)
    provenance_ids: list = field(default_factory=list)   # ids van bron-Evidence (mentions e.d.)
    transition: dict = field(default_factory=dict)       # {"from": ..., "to": ...} (optioneel)
    resolved_by: str = ""                        # event-id (optioneel, correctie-/opvolgingsketen)
    superseded_by: str = ""                      # event-id (optioneel)
    detail: dict = field(default_factory=dict)
    schema_version: int = EVENT_SCHEMA_VERSION
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = event_id(self.athlete_key, self.event_type, self.domain,
                              self.entity, self.effective_at)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HistoryEvent":
        known = {k: d.get(k) for k in cls.__dataclass_fields__ if k != "id"}
        ev = cls(**{k: v for k, v in known.items() if v is not None})
        if d.get("id"):
            ev.id = d["id"]
        return ev
