"""MetricAuthority (v8) — deterministisch welke metriek LEIDEND is voor plan-vs-uitvoering.

Kernproductregel: het GEPLANDE workout bepaalt de compliance-metriek. Een hartslaggestuurde
training wordt op hartslag beoordeeld; tempo is dan secundaire context en mag een correct
uitgevoerde HR-training niet als afwijkend kwalificeren (en omgekeerd). Alleen bij een expliciet
duaal plan (pace-target én HR-cap) tellen beide.

Puur deterministisch, geen fetch, geen LLM. Afgeleid uit de geplande target-metrics
(`fs_client._planned_blocks(...)[].metric`) met een expliciete beschrijvings-fallback; NOOIT uit
atleetvoorkeur of de zonetabel-soort. Onzeker → UNKNOWN (dan geen compliance-oordeel).
"""
from __future__ import annotations

import re

HR, PACE, RPE, DUAL, UNKNOWN = "HR", "PACE", "RPE", "DUAL", "UNKNOWN"

# Expliciete metric-signalen in vrije plantekst (fallback als de builder geen target-metric geeft).
_HR_DESC = re.compile(r"\b(hartslag|hf|hr|heart\s*rate|bpm)\b", re.I)
_PACE_DESC = re.compile(r"\b(tempo|pace|min/km|\d:\d\d\s*/?\s*km|drempel(tempo)?|threshold pace)\b", re.I)
_RPE_DESC = re.compile(r"\b(rpe|op gevoel|praattempo|conversational|gevoelsmatig|naar gevoel)\b", re.I)


def _from_blocks(planned_blocks) -> set:
    return {b.get("metric") for b in (planned_blocks or []) if b.get("metric")}


def _target_zones(planned_blocks, metric_nl) -> list:
    """Geplande doelzones voor de leidende metriek (voor compliance-checks)."""
    return sorted({b["zone"] for b in (planned_blocks or [])
                   if b.get("metric") == metric_nl and b.get("zone")
                   and b.get("type") not in ("WARMUP", "REST", "COOLDOWN")})


def derive(planned_blocks=None, plan_description: str = "", workout_type: str = "") -> dict:
    """Bepaal de autoritaire compliance-metriek. Geeft dict:
      {primary, secondary, source, confidence, hr_target_zones, pace_target_zones}
    primary ∈ HR|PACE|RPE|DUAL|UNKNOWN. Alleen HIGH/MEDIUM confidence draagt een compliance-oordeel."""
    metrics = _from_blocks(planned_blocks)
    hr_zones = _target_zones(planned_blocks, "hartslag")
    pace_zones = _target_zones(planned_blocks, "tempo")

    if metrics == {"hartslag"}:
        prim, sec, src, conf = HR, [PACE], "plan_blocks", "HIGH"
    elif metrics == {"tempo"}:
        prim, sec, src, conf = PACE, [HR], "plan_blocks", "HIGH"
    elif metrics == {"tempo", "hartslag"}:
        prim, sec, src, conf = DUAL, [], "plan_blocks", "HIGH"
    else:
        # geen expliciete target-metric in de builder → beschrijvings-fallback (zwakker bewijs)
        desc = plan_description or ""
        has_hr, has_pace, has_rpe = bool(_HR_DESC.search(desc)), bool(_PACE_DESC.search(desc)), bool(_RPE_DESC.search(desc))
        if has_hr and has_pace:
            prim, sec, src, conf = DUAL, [], "plan_description", "MEDIUM"
        elif has_hr:
            prim, sec, src, conf = HR, [PACE], "plan_description", "MEDIUM"
        elif has_pace:
            prim, sec, src, conf = PACE, [HR], "plan_description", "MEDIUM"
        elif has_rpe:
            prim, sec, src, conf = RPE, [], "plan_description", "MEDIUM"
        else:
            prim, sec, src, conf = UNKNOWN, [], "none", "LOW"

    return {"primary": prim, "secondary": sec, "source": src, "confidence": conf,
            "hr_target_zones": hr_zones, "pace_target_zones": pace_zones}


def carries_compliance_judgment(authority: dict) -> bool:
    """Alleen bij een bekende metriek (niet UNKNOWN/LOW) mag er een plan-compliance-oordeel komen."""
    return bool(authority) and authority.get("primary") not in (UNKNOWN, None) \
        and authority.get("confidence") in ("HIGH", "MEDIUM")
