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


# Stellige, ONGEKWALIFICEERDE absolute taal — alleen toegestaan bij ON_TARGET (anders een valse
# claim, Rick). De GEKWALIFICEERDE MOSTLY-zin ('Het grootste deel ... bleef je binnen ...; op sommige
# stukken liep het op') is bewust WEL toegestaan, dus die matcht hier NIET ('netjes binnen' is uniek
# voor het ON_TARGET-atoom).
_ABSOLUTE_RE = re.compile(r"netjes\s+(binnen|in de geplande zone|in de afgesproken zone)|"
                          r"volledig binnen|de hele training|precies volgens plan|helemaal binnen", re.I)

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


# ── ExecutionFit (v8.1) — praktische coaching-tolerantie i.p.v. binaire compliance ─
# Een echte training hoeft niet iedere seconde exact volgens plan te lopen; normale afwijking naar
# één AANGRENZENDE zone wordt PROPORTIONEEL beschreven, niet bestraft. Deterministisch, tijd-in-zone
# op de PRIMAIRE metriek. Athlete-facing NOOIT percentages; intern rekenen mag exact.
ON_TARGET, MOSTLY_ON_TARGET, MIXED, CLEARLY_ABOVE = \
    "ON_TARGET", "MOSTLY_ON_TARGET", "MIXED", "CLEARLY_ABOVE"

_NOISE_SECONDS = 90          # <= dit boven de bovengrens = meet-/ruis-uitstapje → nog ON_TARGET
_MOSTLY_MIN_SHARE = 0.80     # >= dit deel in/onder target + alleen aangrenzend → MOSTLY_ON_TARGET
_MIXED_MIN_SHARE = 0.50      # >= dit deel in/onder target → MIXED, anders CLEARLY_ABOVE
_SUSTAINED_SHARE = 0.15      # >= dit deel 2+ zones boven target → materieel andere sessie


def _lap_seconds(lap) -> float | None:
    """Tijd van een lap in seconden: uit de lapduur, anders geschat uit tempo × afstand."""
    import fs_client as _fs
    s = _fs._lap_time_s(lap)
    if s:
        return s
    pm = _fs._pace_to_float(lap.get("pace_display") or "")
    d = _fs._safe_float(lap.get("amount"))
    if pm not in (0, float("inf")) and d:
        return pm * 60 * d
    return None


def _zone_seconds(laps, zones, is_pace) -> dict:
    """Seconden per (effectieve) zone over de laps. Out-of-zone laps tellen mee op hun dichtstbijzijnde
    zone (zodat 'boven de hoogste zone' als boven-target meetelt). Ontbreekt de tijd overal, dan telt
    elke lap even zwaar (1s-eenheid) → shares blijven bruikbaar, de 90s-regel valt dan weg."""
    import fs_client as _fs
    from collections import defaultdict
    per = defaultdict(float)
    any_time = False
    for lap in laps or []:
        if not isinstance(lap, dict):
            continue
        if is_pace:
            pm = _fs._pace_to_float(lap.get("pace_display") or "")
            val = pm * 60 if pm not in (0, float("inf")) else None
        else:
            val = _fs._safe_float(lap.get("hr_avg"))
        if val is None:
            continue
        cls = _fs.classify_pace_hr_zone(zones, val, is_pace=is_pace)
        if not cls:
            continue
        num = cls.get("num") if cls.get("status") == "IN_ZONE" else cls.get("nearest_num")
        if not num:
            continue
        sec = _lap_seconds(lap)
        if sec is None:
            sec = 1.0
        else:
            any_time = True
        per[int(num)] += sec
    return {"per": dict(per), "has_time": any_time}


def execution_fit(laps, zones, is_pace, target_upper) -> dict | None:
    """Deterministische ExecutionFit t.o.v. de bovengrens `target_upper` van de PRIMAIRE metriek.
    Geeft None als er niets classificeerbaars is (dan geen plan-execution-atoom)."""
    if not zones or is_pace is None or not target_upper:
        return None
    zs = _zone_seconds(laps, zones, is_pace)
    per = zs["per"]
    total = sum(per.values())
    if total <= 0:
        return None
    U = int(target_upper)
    above_sec = sum(s for z, s in per.items() if z > U)
    in_sec = total - above_sec
    share_in = in_sec / total
    above_zones = [z for z, s in per.items() if z > U and s > 0]
    max_delta = max((z - U for z in above_zones), default=0)
    two_plus_sec = sum(s for z, s in per.items() if z >= U + 2)
    sustained = (two_plus_sec / total) >= _SUSTAINED_SHARE
    if zs["has_time"] and above_sec <= _NOISE_SECONDS and max_delta <= 1:
        cat = ON_TARGET
    elif not zs["has_time"] and share_in >= 0.98 and max_delta <= 1:
        cat = ON_TARGET                                      # zonder tijd: bijna alles in target = on target
    elif share_in >= _MOSTLY_MIN_SHARE and max_delta <= 1 and not sustained:
        cat = MOSTLY_ON_TARGET
    elif share_in >= _MIXED_MIN_SHARE and not sustained:
        cat = MIXED
    else:
        cat = CLEARLY_ABOVE
    return {"category": cat, "above_target_seconds": round(above_sec),
            "total_valid_seconds": round(total), "max_zone_delta": max_delta,
            "share_in_target": share_in, "sustained_2plus": sustained}


# ExecutionFit-atoom-teksten per categorie × metriek × (rustig/algemeen). Athlete-veilig, geen %.
_FIT_TEXT = {
    ("hartslag", True): {
        ON_TARGET: "Op hartslag bleef je netjes binnen het rustige bereik dat voor deze training bedoeld was.",
        MOSTLY_ON_TARGET: "Het grootste deel van de training bleef je binnen je rustige hartslagbereik; op sommige stukken liep de intensiteit wat op.",
        MIXED: "De training was op hartslag grotendeels rustig, maar er zat ook een duidelijk stuk boven het geplande bereik in.",
        CLEARLY_ABOVE: "De intensiteit lag op hartslag een duidelijk deel van de training hoger dan voor deze rustige sessie bedoeld was.",
    },
    ("hartslag", False): {
        ON_TARGET: "Op hartslag zat je netjes in de geplande zone.",
        MOSTLY_ON_TARGET: "Op hartslag zat je grotendeels in de geplande zone, met een enkel stuk erboven.",
        MIXED: "Op hartslag zat je grotendeels in de geplande zone, maar er zat ook een duidelijk stuk boven in.",
        CLEARLY_ABOVE: "Op hartslag lag een duidelijk deel van de training hoger dan de geplande zone.",
    },
    ("tempo", True): {
        ON_TARGET: "Qua tempo bleef je netjes binnen het rustige bereik dat voor deze training bedoeld was.",
        MOSTLY_ON_TARGET: "Het grootste deel van de training bleef je qua tempo in je rustige bereik; op sommige stukken liep het wat op.",
        MIXED: "Qua tempo was de training grotendeels rustig, maar er zat ook een duidelijk stuk sneller in.",
        CLEARLY_ABOVE: "Qua tempo lag een duidelijk deel van de training sneller dan voor deze rustige sessie bedoeld was.",
    },
    ("tempo", False): {
        ON_TARGET: "Qua tempo zat je netjes in de afgesproken zone.",
        MOSTLY_ON_TARGET: "Qua tempo zat je grotendeels in de afgesproken zone, met een enkel stuk erbuiten.",
        MIXED: "Qua tempo zat je grotendeels in de afgesproken zone, maar er zat ook een duidelijk stuk sneller in.",
        CLEARLY_ABOVE: "Qua tempo lag een duidelijk deel van de training sneller dan de afgesproken zone.",
    },
}
# Optionele, neutrale coaching-cue bij normale opgelopen intensiteit (geen berisping).
_FIT_CUE = {
    "hartslag": "Voor de volgende rustige duurloop is het vooral zaak om het grootste deel weer ontspannen te houden.",
    "tempo": "Voor de volgende rustige duurloop is het vooral zaak om het grootste deel weer ontspannen te houden.",
}


def _fit_atom(fit_category, metric_nl, easy):
    txt = _FIT_TEXT.get((metric_nl, bool(easy)), {}).get(fit_category)
    return _atom(f"fit_{metric_nl}_{fit_category.lower()}", txt, "plan_execution", 60,
                 "HR" if metric_nl == "hartslag" else "PACE", ["execution_fit"]) if txt else None


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
    fit = None                                               # ExecutionFit (v8.1), gezet in de plan-execution-branch

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

    # C. PLAN VS UITVOERING — v8.1 ExecutionFit op de PRIMAIRE metriek (continue trainingen).
    # Normale afwijking naar één aangrenzende zone wordt proportioneel beschreven (grotendeels binnen,
    # op sommige stukken liep het op), niet als compliance-failure. Absolute taal ('bleef binnen')
    # alleen bij ON_TARGET. Elke ExecutionFit-categorie is AUTO_SAFE-geschikt (deterministisch feit).
    fit = None
    if not is_structured and not rec and MA.carries_compliance_judgment(authority):
        prim = authority["primary"]
        if prim == MA.HR and hr_zones and authority["hr_target_zones"]:
            ceil = max(authority["hr_target_zones"])
            fit = execution_fit(laps, hr_zones, is_pace=False, target_upper=ceil)
            a = _fit_atom(fit["category"], "hartslag", ceil <= 2) if fit else None
            if a:
                atoms.append(a)
                if fit["category"] in (MOSTLY_ON_TARGET, MIXED) and ceil <= 2:
                    atoms.append(_atom("fit_cue", _FIT_CUE["hartslag"], "context", 15, "HR", ["execution_fit"]))
        elif prim == MA.PACE and pace_zones and authority["pace_target_zones"]:
            ceil = max(authority["pace_target_zones"])
            fit = execution_fit(laps, pace_zones, is_pace=True, target_upper=ceil)
            a = _fit_atom(fit["category"], "tempo", ceil <= 2) if fit else None
            if a:
                atoms.append(a)
                if fit["category"] in (MOSTLY_ON_TARGET, MIXED) and ceil <= 2:
                    atoms.append(_atom("fit_cue", _FIT_CUE["tempo"], "context", 15, "PACE", ["execution_fit"]))
        elif prim == MA.DUAL and hr_zones and pace_zones \
                and authority["hr_target_zones"] and authority["pace_target_zones"]:
            # DUAAL: beide tellen → neem de STRENGSTE ExecutionFit van HR en tempo.
            hf = execution_fit(laps, hr_zones, False, max(authority["hr_target_zones"]))
            pf = execution_fit(laps, pace_zones, True, max(authority["pace_target_zones"]))
            order = [ON_TARGET, MOSTLY_ON_TARGET, MIXED, CLEARLY_ABOVE]
            cands = [f for f in (hf, pf) if f]
            if cands:
                worst = max(cands, key=lambda f: order.index(f["category"]))
                metric_nl = "hartslag" if worst is hf else "tempo"
                fit = worst
                a = _fit_atom(worst["category"], metric_nl, max(authority["hr_target_zones"]) <= 2)
                if a:
                    atoms.append(a)

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
    elif "structured_block_coupling_insufficient" in reasons and not content:
        status = REVIEW_REQUIRED
    elif not content:
        reasons.append("no_supported_content")
        status = REVIEW_REQUIRED
    else:
        status = AUTO_SAFE

    text = assemble(atoms) if status == AUTO_SAFE else ""
    if status == AUTO_SAFE:
        # defense in depth: elke zin moet een geregistreerd atoom zijn + de guards halen, én absolute
        # taal ('bleef binnen'/'volledig'/'precies volgens plan'/'de hele training') mag NOOIT verschijnen
        # wanneer er materieel boven-target tijd was (ExecutionFit != ON_TARGET) — de directe Rick-fix.
        _absolute_ok = not (fit and fit.get("category") != ON_TARGET and _ABSOLUTE_RE.search(text))
        if not _final_is_atoms_only(text, atoms) or not _passes_guards(text, atext) or not _absolute_ok:
            status, text, reasons = REVIEW_REQUIRED, "", reasons + ["defense_in_depth_failed"]
    return {"status": status, "atoms": atoms, "authority": authority, "reasons": reasons,
            "execution_fit": fit, "text": text}


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
