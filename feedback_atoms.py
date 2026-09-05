"""Feedback Auto-Safe Builder (v8) — deterministische zin-atomen + AUTO_SAFE / REVIEW_REQUIRED.

Architectuur: plan intent → MetricAuthority → deterministische feiten → GOEDGEKEURDE zin-atomen →
deterministische assemblage → AUTO_SAFE. Onvoldoende zekerheid → REVIEW_REQUIRED.

Voor AUTO_SAFE komt ELKE athlete-facing zin uit application-code (een geregistreerd atoom). De LLM
is NIET de feitelijke auteur van automatisch-verstuurbare feedback. Atomen respecteren
MetricAuthority: een secundaire metriek mag een correct uitgevoerde primaire training niet als
afwijkend kwalificeren (Sophie-fix). Geen nieuwe fetch buiten de gedeelde builder/zones-read (die op
`w` wordt gestasht en door `_build_workout_context` wordt hergebruikt); geen truth store.
"""
from __future__ import annotations

import re

import metric_authority as MA

AUTO_SAFE = "AUTO_SAFE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

# ── atoom-helpers ─────────────────────────────────────────────────────────────
def _atom(aid, text, category, priority, authority="ANY", provenance=None):
    return {"id": aid, "text": text, "category": category, "priority": priority,
            "authority": authority, "provenance": provenance or []}


_QUESTION = re.compile(r"\?")
_RECOVERY_ZONE_Q = re.compile(r"(welke\s+zone|goede?\s+zone|rustig\s+genoeg|z\s*1|op\s+gevoel)", re.I)
_UNAVAIL = re.compile(
    r"er\s+.{0,20}?niet\s+bij|niet\s+bij\s+(kunnen\s+)?zijn|kan\s+niet\s+(komen|mee|meedoen|erbij)|"
    r"ben\s+er\s+niet|niet\s+aanwezig|red\s+het\s+niet|haal\s+het\s+niet|mis\s+ik|ben\s+afwezig", re.I)

_COMPLAINT_AREA_NL = {
    "scheen": "scheen", "scheenbeen": "scheen", "knie": "knie", "hiel": "hiel", "kuit": "kuit",
    "achilles": "achillespees", "hamstring": "hamstring", "lies": "lies", "voet": "voet",
    "enkel": "enkel", "rug": "rug",
}


def _athlete_text(w) -> str:
    return "\n".join([str(w.get("post_notes") or "")]
                     + [str(c) for c in (w.get("athlete_comments") or []) if str(c or "").strip()]).strip()


def _hr_pace_zones(zones_result):
    """Haal HR- en tempo-zonestruct uit de zones-respons (primair + secundair, geen fetch)."""
    zt = zones_result.get("zone_type")
    prim = zones_result.get("zones") or []
    sec_t = zones_result.get("secondary_zone_type")
    sec = zones_result.get("secondary_zones") or []
    hr = prim if zt == "hartslag" else (sec if sec_t == "hartslag" else [])
    pace = prim if zt == "tempo" else (sec if sec_t == "tempo" else [])
    return hr, pace


def _avg_zone(zones, value, is_pace):
    if not zones or value is None:
        return None
    import fs_client as _fs
    cls = _fs.classify_pace_hr_zone(zones, value, is_pace=is_pace)
    return cls["num"] if (cls and cls.get("status") == "IN_ZONE") else None


# ── evidence + atoom-selectie ─────────────────────────────────────────────────
def build_decision(w: dict) -> dict:
    """Bouw deterministisch de AUTO_SAFE/REVIEW_REQUIRED-beslissing + de atomen. Fetch (builder +
    zones) gebeurt hier ÉÉN keer en wordt op `w` gestasht zodat `_build_workout_context` (REVIEW-pad)
    ze hergebruikt (geen dubbele fetch). Nooit fataal: bij een fout → REVIEW_REQUIRED."""
    try:
        return _build_decision(w)
    except Exception as e:
        return {"status": REVIEW_REQUIRED, "atoms": [], "authority": None,
                "reasons": [f"error:{type(e).__name__}"], "text": ""}


def _build_decision(w: dict) -> dict:
    import fs_client as _fs
    if (w.get("workout_type") or "unknown") != "run":
        return {"status": REVIEW_REQUIRED, "atoms": [], "authority": None,
                "reasons": ["non_run"], "text": ""}
    details = w.get("details") or {}
    ak, wk = w.get("athlete_key", ""), w.get("workout_key", "")
    plan_desc = (details.get("description") or "")
    activities = details.get("Activities") or []
    laps = activities[0].get("Laps", []) if activities else []

    # gedeelde reads (stash voor _build_workout_context) — geen extra fan-out
    builder_raw = []
    if details.get("has_structured_workout") and wk and ak:
        try:
            builder_raw = _fs.get_workout_builder(wk, ak) or []
        except Exception:
            builder_raw = []
    w["_builder_raw"] = builder_raw
    zones_result = {}
    if ak:
        try:
            zones_result = _fs.get_athlete_zones(ak) or {}
        except Exception:
            zones_result = {}
    w["_zones_result"] = zones_result

    planned_blocks = _fs._planned_blocks(builder_raw)
    authority = MA.derive(planned_blocks, plan_desc, w.get("workout_type"))
    hr_zones, pace_zones = _hr_pace_zones(zones_result)
    is_structured = len(planned_blocks) >= 2
    atext = _athlete_text(w)
    reasons = []
    atoms = []

    # E. FALSE CLAIM CORRECTIE (hoogste prioriteit) — Douwe
    try:
        import feedback_facts as _ff
        rec = _ff.recovery_claim_contradiction(
            _fs.assess_workout_blocks(builder_raw, laps, hr_zones, "hartslag").get("blocks", []),
            hr_zones, atext) if hr_zones else None
    except Exception:
        rec = None
    if rec:
        atoms.append(_atom("recovery_blocks_z2_not_z1", rec, "correction", 100, "HR", ["rest_blocks"]))

    # D. GESTRUCTUREERDE OBSERVATIE — Jordi (alleen op de autoritaire metriek + MATCHED + schoon)
    block_atom = None
    if is_structured and authority["primary"] in (MA.HR, MA.PACE, MA.DUAL):
        metric_nl = "hartslag" if authority["primary"] in (MA.HR, MA.DUAL) else "tempo"
        z = hr_zones if metric_nl == "hartslag" else pace_zones
        try:
            import feedback_facts as _ff
            assess = _fs.assess_workout_blocks(builder_raw, laps, z, metric_nl)
            if assess.get("confidence") == "MATCHED":
                s = _ff.block_sequence_sentence(assess.get("blocks", []), z,
                                                is_pace=(metric_nl == "tempo"), zone_type=metric_nl)
                if s:
                    block_atom = _atom("block_sequence", s, "observation", 70, authority["primary"], ["blocks"])
        except Exception:
            block_atom = None
        if block_atom:
            atoms.append(block_atom)
        elif not rec:
            reasons.append("structured_block_coupling_insufficient")

    # C. PLAN VS UITVOERING — PRIMAIRE metriek (continue trainingen) — Sophie
    if not is_structured and not rec and MA.carries_compliance_judgment(authority):
        prim = authority["primary"]
        act = activities[0] if activities else {}
        if prim == MA.HR and hr_zones and authority["hr_target_zones"]:
            avg = _fs._safe_float(act.get("hr_avg"))
            zone = _avg_zone(hr_zones, avg, is_pace=False)
            ceil = max(authority["hr_target_zones"])
            if zone is not None and zone <= ceil:
                txt = ("Op hartslag bleef je binnen het rustige bereik dat voor deze training bedoeld was."
                       if ceil <= 2 else "Op hartslag zat je binnen de geplande zone.")
                atoms.append(_atom("hr_compliant", txt, "plan_execution", 60, "HR", ["avg_hr", "plan_hr"]))
            elif zone is not None:
                reasons.append("hr_above_target")           # geen valse compliance-claim → review
        elif prim == MA.PACE and pace_zones and authority["pace_target_zones"]:
            pm = _fs._pace_to_float(act.get("pace_display") or "")
            sec = pm * 60 if pm not in (0, float("inf")) else None
            zone = _avg_zone(pace_zones, sec, is_pace=True)
            ceil = max(authority["pace_target_zones"])
            if zone is not None and zone <= ceil:
                atoms.append(_atom("pace_compliant", "Qua tempo bleef je binnen de afgesproken zone.",
                                   "plan_execution", 60, "PACE", ["avg_pace", "plan_pace"]))
            elif zone is not None:
                reasons.append("pace_above_target")

    # B. DIRECT ANTWOORD op een deterministisch beantwoordbare vraag (herstel-zone) — Matthijs
    has_question = bool(_QUESTION.search(atext))
    answered = False
    if has_question and _RECOVERY_ZONE_Q.search(atext) and authority["primary"] == MA.HR \
            and authority["hr_target_zones"] and min(authority["hr_target_zones"]) <= 2:
        atoms.append(_atom("recovery_zone_answer",
                           "Voor dit soort hersteltrainingen zou ik op Z1 sturen.",
                           "answer", 90, "HR", ["plan_hr"]))
        answered = True

    # F. KLACHT / BELASTING CHECK-IN (neutraal) — Douwe scheen
    diag = w.get("_brein_diag") or {}
    areas = [a for a in (diag.get("complaint_areas") or []) if a]
    intensity_high = bool(rec or block_atom) or _rpe_high(w) or (authority["primary"] in (MA.HR,) and False)
    if areas and (intensity_high or is_structured):
        for a in areas:
            area = _COMPLAINT_AREA_NL.get(str(a).lower().strip())
            if area:
                atoms.append(_atom(f"complaint_{area}",
                                   f"Hou ook even in de gaten hoe je {area} hierop reageert.",
                                   "complaint", 50, "ANY", ["complaint"]))
                break

    # H. AANWEZIGHEID / LOGISTIEK
    if _UNAVAIL.search(atext):
        atoms.append(_atom("attendance", "Jammer dat je er niet bij kunt zijn.", "logistics", 20,
                           "ANY", ["athlete_message"]))

    # ── beslissing ────────────────────────────────────────────────────────────
    content = [a for a in atoms if a["category"] in
               ("correction", "observation", "plan_execution", "answer")]
    if has_question and not answered:
        reasons.append("unanswerable_question")
        status = REVIEW_REQUIRED
    elif "hr_above_target" in reasons or "pace_above_target" in reasons:
        status = REVIEW_REQUIRED                             # afwijking bestaat maar geen veilig atoom
    elif "structured_block_coupling_insufficient" in reasons and not content:
        status = REVIEW_REQUIRED
    elif not content:
        reasons.append("no_supported_content")
        status = REVIEW_REQUIRED
    else:
        status = AUTO_SAFE

    text = assemble(atoms) if status == AUTO_SAFE else ""
    if status == AUTO_SAFE:
        # defense in depth: elke zin moet een geregistreerd atoom zijn + de guards halen
        if not _final_is_atoms_only(text, atoms) or not _passes_guards(text, atext):
            status, text, reasons = REVIEW_REQUIRED, "", reasons + ["defense_in_depth_failed"]
    return {"status": status, "atoms": atoms, "authority": authority, "reasons": reasons, "text": text}


def _rpe_high(w) -> bool:
    try:
        e = w.get("effort")
        return bool(e) and float(str(e).split()[0].replace(",", ".")) >= 7
    except (TypeError, ValueError):
        return False


# ── deterministische assemblage ───────────────────────────────────────────────
_ORDER = {"answer": 0, "correction": 1, "observation": 2, "plan_execution": 3,
          "complaint": 4, "context": 5, "logistics": 6, "ack": 7}


def assemble(atoms) -> str:
    """Deterministische volgorde → 2–5 zinnen. Geen LLM. Dedupt op tekst."""
    seen, ordered = set(), []
    for a in sorted(atoms, key=lambda x: (_ORDER.get(x["category"], 9), -x["priority"])):
        t = a["text"].strip()
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    return " ".join(ordered[:5])


def _final_is_atoms_only(text: str, atoms) -> bool:
    """Bewijs dat de AUTO_SAFE-tekst UITSLUITEND uit geregistreerde atoom-teksten bestaat."""
    norm = re.sub(r"\s+", " ", text or "").strip()
    rebuilt = re.sub(r"\s+", " ", assemble(atoms)).strip()
    return norm == rebuilt and norm != ""


def _passes_guards(text: str, athlete_message: str) -> bool:
    try:
        import feedback_facts as _ff
        return _ff.validate_draft(text, is_running=True, athlete_message=athlete_message).get("ok", False)
    except Exception:
        return False
