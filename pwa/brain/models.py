"""Masterbrein v2 — canonieke modellen (Fase A).

Kleine, JSON-serialiseerbare typed modellen. Eén canonieke kenniseenheid =
`Evidence` (feit, melding, afgeleide of patroon — allemaal met provenance).
`SourceHealth` maakt "leeg" en "bron faalde" onherroepelijk verschillend.
`AthleteState` is de L5-uitkomst.

Geen zwaar framework, geen runtime-afhankelijkheden buiten de stdlib. De
dataclasses zijn bewust plat en serialiseerbaar zodat de snapshot (L-persist)
en de tests deterministisch met dicts kunnen werken.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 2

# ── Truth types ──────────────────────────────────────────────────────────────
FACT = "FACT"
DERIVED = "DERIVED"
ATHLETE_REPORTED = "ATHLETE_REPORTED"
COACH_REPORTED = "COACH_REPORTED"
AI_INTERPRETATION = "AI_INTERPRETATION"
UNKNOWN = "UNKNOWN"                     # ook gebruikt als status/strength "onbekend"
TRUTH_TYPES = {FACT, DERIVED, ATHLETE_REPORTED, COACH_REPORTED, AI_INTERPRETATION, UNKNOWN}

# ── Status (tijdgebonden context) ────────────────────────────────────────────
ACTIVE = "ACTIVE"
RECENT = "RECENT"
RECURRING = "RECURRING"
STRUCTURAL = "STRUCTURAL"
RESOLVED = "RESOLVED"
STALE = "STALE"
HISTORICAL = "HISTORICAL"
CONFLICT = "CONFLICT"
# (UNKNOWN hierboven telt ook als status)

# ── Strength (bewijskracht — hangt aan Evidence, niet aan de atleet) ──────────
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
# (UNKNOWN)

# ── Overall athlete state ────────────────────────────────────────────────────
GOOD = "GOOD"
STABLE = "STABLE"
ATTENTION = "ATTENTION"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# ── Source kinds ─────────────────────────────────────────────────────────────
FS = "FS"
INTAKE_STORE = "INTAKE_STORE"
DERIVED_KIND = "DERIVED"
AI_KIND = "AI"


def stable_id(*parts) -> str:
    """Deterministische id uit semantische identiteit (nooit random UUID).

    Zelfde bron-event bij rebuild → zelfde id. Voor afgeleiden/patronen: geef
    het venster + gesorteerde provenance mee zodat de id stabiel is over runs
    zolang de onderbouwing gelijk blijft (essentieel voor diffing/coachcorrecties)."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Evidence:
    key: str                                   # semantische sleutel: "complaint.achilles", "load.km_7d"
    domain: str                                # health | load | recovery | zones | goal | coach | training_response | source
    value: object = None
    truth_type: str = UNKNOWN
    status: str = UNKNOWN
    strength: str = UNKNOWN
    source: str = ""                           # "fs.training_log" | "intake" | "coach_note" | "belasting" | "brain.derive"
    source_kind: str = ""                      # FS | INTAKE_STORE | DERIVED | AI
    observed_at: str = ""                       # ISO-datum (of "")
    effective_from: str = ""
    effective_until: str = ""
    athlete_key: str = ""
    workout_key: str = ""
    reporter: str = ""                          # athlete | coach | system
    unit: str = ""
    provenance: list = field(default_factory=list)   # ids van onderliggende Evidence
    detail: dict = field(default_factory=dict)
    id: str = ""

    def __post_init__(self):
        if not self.id:
            # Basis-id voor brondata: bron + sleutel + datum + workout.
            self.id = stable_id(self.source, self.key, self.observed_at, self.workout_key)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        known = {k: d.get(k) for k in cls.__dataclass_fields__ if k != "id"}
        ev = cls(**{k: v for k, v in known.items() if v is not None})
        if d.get("id"):
            ev.id = d["id"]
        return ev


def derived_evidence(key, domain, value, *, status=UNKNOWN, strength=UNKNOWN,
                     provenance=None, detail=None, window="", truth_type=DERIVED,
                     source="brain.derive", athlete_key="", unit="",
                     observed_at="") -> Evidence:
    """Fabriek voor afgeleiden/patronen met een STABIELE id op type+venster+provenance."""
    prov = sorted(provenance or [])
    ev = Evidence(
        key=key, domain=domain, value=value, truth_type=truth_type, status=status,
        strength=strength, source=source, source_kind=DERIVED_KIND, athlete_key=athlete_key,
        unit=unit, observed_at=observed_at, provenance=prov, detail=detail or {},
        id=stable_id(key, window, *prov),
    )
    return ev


@dataclass
class SourceHealth:
    source: str
    available: bool
    stale: bool = False
    last_success: str = ""                      # ISO-datetime van de laatste geslaagde fetch
    coverage_start: str = ""
    coverage_end: str = ""
    error: str = ""                             # compacte categorie/melding (geen gevoelige inhoud)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceHealth":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class AthleteState:
    athlete_key: str
    naam: str
    built_at: str
    overall: str = INSUFFICIENT_DATA
    schema_version: int = SCHEMA_VERSION
    sources: list = field(default_factory=list)         # list[SourceHealth]
    evidence: list = field(default_factory=list)        # list[Evidence]
    conflicts: list = field(default_factory=list)       # evidence-ids met status CONFLICT
    source_gaps: list = field(default_factory=list)     # bronnamen die ontbreken/stale zijn

    # ── query-helpers (puur) ────────────────────────────────────────────────
    def by_domain(self, domain: str) -> list:
        return [e for e in self.evidence if e.domain == domain]

    def by_status(self, *status: str) -> list:
        s = set(status)
        return [e for e in self.evidence if e.status in s]

    def by_truth(self, *tt: str) -> list:
        s = set(tt)
        return [e for e in self.evidence if e.truth_type in s]

    def get(self, evidence_id: str):
        return next((e for e in self.evidence if e.id == evidence_id), None)

    def source(self, name: str):
        return next((s for s in self.sources if s.source == name), None)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "athlete_key": self.athlete_key,
            "naam": self.naam,
            "built_at": self.built_at,
            "overall": self.overall,
            "sources": [s.to_dict() for s in self.sources],
            "evidence": [e.to_dict() for e in self.evidence],
            "conflicts": list(self.conflicts),
            "source_gaps": list(self.source_gaps),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AthleteState":
        return cls(
            athlete_key=d.get("athlete_key", ""),
            naam=d.get("naam", ""),
            built_at=d.get("built_at", ""),
            overall=d.get("overall", INSUFFICIENT_DATA),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            sources=[SourceHealth.from_dict(s) for s in d.get("sources", [])],
            evidence=[Evidence.from_dict(e) for e in d.get("evidence", [])],
            conflicts=list(d.get("conflicts", [])),
            source_gaps=list(d.get("source_gaps", [])),
        )
