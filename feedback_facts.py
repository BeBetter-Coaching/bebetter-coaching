"""Deterministic Coaching Facts + Guarded Composer (v7).

Architectuur: DETERMINISTISCHE feiten eerst → de LLM schrijft alleen eromheen → een deterministische
VALIDATOR keurt het concept vóór acceptatie (fail-closed, geen rewrite, geen hergeneratie).

Deze module levert:
- `sport_profile(workout_type)`   — canonieke sportsoort + is_running (voor de sporttaal-guard);
- `build_fact_pack(...)`          — een niet-persistente set VERPLICHTE, athlete-veilige NL-zinnen
                                    (coach_sentence door code gebouwd, NIET door de LLM);
- `validate_draft(...)`           — fail-closed controle: verboden interne taal, zonepercentages,
                                    ontbrekende/gewijzigde verplichte feiten, stale relatieve dag,
                                    en — de harde productregel — een hardloopactiviteit die als
                                    'rit'/'ritje'/'fietsrit' wordt omschreven.

Geen nieuwe store, geen FinalSurge-fetch, puur en goedkoop. De sentences vermijden streepjes zodat
`ai_feedback._clean_text` ze niet wijzigt (anders zou de verbatim-check ze niet terugvinden).
"""
from __future__ import annotations

import re

_RUN_TYPES = ("run", "running", "hardlopen")

# Interne pipeline-taal die NOOIT athlete-facing mag lekken (fail-closed reject).
_INTERNAL_VOCAB = (
    "blokmatch", "matched", "possible", "unknown", "brein_context", "source health",
    "source-health", "provenance", "context laden", "context laadt", "pipeline",
    "ambiguous", "readiness", "obligations", "fact_pack", "zoneverdeling",
)

# Cycling-context zodat een LEGITIEME kruistraining-verwijzing (aparte fietsrit) niet vals wordt
# geblokkeerd — alleen de HUIDIGE run mag geen 'rit' heten.
_CYCLING_CTX = re.compile(r"\b(fiets|fietsen|gefietst|wieler|wielren|bike|mtb|gravel|spinning|zwift)\w*", re.I)

_REL_DAY = re.compile(r"\b(gisteren|eergisteren|morgen|overmorgen)\b", re.I)
_RIT = re.compile(r"\brit\b|\britje\b", re.I)
_FIETSRIT = re.compile(r"\bfietsrit\w*", re.I)
# zone-gebonden percentage (athlete-facing verboden); losse '100% hersteld' blijft toegestaan.
_ZONE_PCT = re.compile(r"(zone|z[1-5]|tempo|hartslag).{0,15}\d+\s*%|\d+\s*%.{0,15}(zone|z[1-5]|tempo|hartslag)", re.I)

_ZWORD = {"hartslag": "hartslag", "tempo": "tempo"}


def sport_profile(workout_type) -> dict:
    """Canonieke sportsoort voor de generation/validation path."""
    ct = str(workout_type or "").lower().strip()
    is_running = ct in _RUN_TYPES
    return {"canonical_type": "running" if is_running else (ct or "unknown"),
            "is_running": is_running}


# ── deterministische coach-zinnen (door code, athlete-veilig, geen streepjes) ────
def divergence_sentence(divergence: dict) -> str:
    """Sophie-achtig: HR rustig, tempo boven het rustige bereik (of andersom). Kwalitatief, geen %."""
    easy = _ZWORD.get((divergence or {}).get("easy"), "hartslag")
    above = _ZWORD.get((divergence or {}).get("above"), "tempo")
    return (f"Op {easy} bleef het rustig, maar qua {above} zat er ook een stuk boven je "
            f"rustige bereik in.")


def _zseq_join(labels: list) -> str:
    """['Z3','Z4','Z3','Z4','Z4'] → 'Z3, Z4, Z3, Z4 en Z4'."""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " en " + labels[-1]


def block_sequence_sentence(blocks, zones, is_pace, zone_type) -> str | None:
    """Jordi-achtig: exacte, vooraf berekende werkblok-VOLGORDE als één coach-zin. Alleen als ELK
    werkblok schoon IN een zone valt (anders geen feit: het model bespreekt dan geen per-blok-verloop).
    De LLM telt/klasseert zelf niets."""
    if not blocks or not zones or is_pace is None or zone_type not in ("tempo", "hartslag"):
        return None
    import fs_client as _fs
    labels = []
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") in ("WARMUP", "REST", "COOLDOWN"):
            continue
        if zone_type == "hartslag":
            val = _fs._safe_float(b.get("observed_hr"))
        else:
            pm = _fs._pace_to_float(b.get("observed_pace") or "")
            val = pm * 60 if pm not in (0, float("inf")) else None
        if val is None:
            return None
        cls = _fs.classify_pace_hr_zone(zones, val, is_pace=is_pace)
        if not cls or cls.get("status") != "IN_ZONE":
            return None                                      # niet schoon → geen feit
        labels.append(f"Z{cls['num']}")
    if len(labels) < 2:
        return None
    mod = "hartslag" if zone_type == "hartslag" else "tempo"
    return f"Op {mod} kwamen je werkblokken uit op {_zseq_join(labels)}."


# recovery/herstel-claim: 'weer in Z1', 'rustblok in Z1', 'herstel ... Z1'
_RECOVERY_Z1_CLAIM = re.compile(
    r"(rust|herstel)\w*[^.]{0,40}\bz\s*1\b|\bz\s*1\b[^.]{0,40}(rust|herstel)|weer\s+in\s+z\s*1|"
    r"terug\s+(in|naar)\s+z\s*1", re.I)


def recovery_claim_contradiction(blocks, zones, athlete_msg) -> str | None:
    """Douwe-achtig: atleet claimt dat de herstel/rustblokken in Z1 kwamen, maar de deterministische
    classificatie van de REST-blokken zegt een hogere zone. Bouwt dan de VERPLICHTE correctie-zin.
    Alleen bij HR-zones (herstel wordt op hartslag beoordeeld)."""
    if not blocks or not zones or not athlete_msg:
        return None
    if not _RECOVERY_Z1_CLAIM.search(athlete_msg):
        return None
    import fs_client as _fs
    rest_zones = []
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") != "REST":
            continue
        val = _fs._safe_float(b.get("observed_hr"))
        if val is None:
            continue
        cls = _fs.classify_pace_hr_zone(zones, val, is_pace=False)
        if cls and cls.get("status") == "IN_ZONE":
            rest_zones.append(cls["num"])
    if not rest_zones or any(z <= 1 for z in rest_zones):
        return None                                          # geen tegenspraak (of raakte wél Z1)
    from collections import Counter
    dominant = Counter(rest_zones).most_common(1)[0][0]
    return (f"Je herstelblokken bleven op hartslag in Z{dominant}, niet in Z1 zoals je dacht.")


_COMPLAINT_AREA_NL = {
    "scheen": "scheen", "scheenbeen": "scheen", "knie": "knie", "hiel": "hiel", "kuit": "kuit",
    "achilles": "achillespees", "hamstring": "hamstring", "lies": "lies", "voet": "voet",
    "enkel": "enkel", "rug": "rug",
}


def complaint_sentence(complaint_areas) -> str | None:
    """Neutrale, verplichte check-in-zin bij een actieve klacht (geen diagnose/oorzaak/behandeling)."""
    for a in (complaint_areas or []):
        area = _COMPLAINT_AREA_NL.get(str(a).lower().strip())
        if area:
            return f"Hou ook even in de gaten hoe je {area} hierop reageert."
    return None


# Verboden (tegenstrijdige) vrije-tekst-claims per verplicht feit — deterministisch checkbaar.
# Bij een recovery-Z1-correctie mag de vrije tekst NIET alsnog beweren dat het herstel naar Z1 ging.
_RECOVERY_Z1_AFFIRM = (r"(rust|herstel)\w*[^.]{0,45}\bz\s*1\b|weer\s+in\s+z\s*1|"
                       r"terug\w*\s+(naar|in|op)\s+z\s*1|in\s+z\s*1\s+(kwam|kwamen|zat|zaten|bleef|bleven|geraakt|gekomen)")
# Bij een HR/tempo-divergentie mag de vrije tekst NIET blanket geruststellen alsof alles op target was.
_BLANKET_REASSURE = (r"precies (de bedoeling|goed|volgens plan|zoals gepland)|"
                     r"helemaal (volgens plan|goed uitgevoerd|top|zoals gepland|goed)|"
                     r"(gewoon|er)\s+goed\s+in|perfect uitgevoerd|helemaal op target|precies op target")


def build_fact_pack(*, workout_type, divergence=None, block_sequence=None,
                    recovery_contradiction=None, complaint_line=None) -> dict:
    """Bouw de niet-persistente fact-pack: sportprofiel + de VERPLICHTE coach-zinnen (max een paar,
    door CODE gebouwd) + de deterministisch-checkbare VERBODEN tegenspraak-claims. Lege pack =
    schone case. De app voegt de verplichte zinnen zelf in (assemble_spine); de LLM kopieert ze niet."""
    sport = sport_profile(workout_type)
    mandatory = []
    forbidden = []
    # prioriteit: claim-correctie → divergentie → blokvolgorde → klacht-verplichting
    if recovery_contradiction:
        mandatory.append({"id": "recovery_claim", "sentence": recovery_contradiction})
        forbidden.append({"id": "recovery_z1", "pattern": _RECOVERY_Z1_AFFIRM})
    if divergence:
        mandatory.append({"id": "divergence", "sentence": divergence_sentence(divergence)})
        forbidden.append({"id": "blanket_reassure", "pattern": _BLANKET_REASSURE})
    if block_sequence:
        mandatory.append({"id": "block_sequence", "sentence": block_sequence})
    if complaint_line:
        mandatory.append({"id": "complaint", "sentence": complaint_line})
    return {"sport": sport, "mandatory": mandatory, "forbidden_claims": forbidden}


def assemble_spine(prose: str, pack: dict) -> str:
    """v7.1 — APPLICATION-OWNED factual spine: voeg de verplichte deterministische zin(nen) ACHTER
    de (LLM-)opener/duiding toe, zodat ze NOOIT kunnen ontbreken (de LLM hoeft ze niet te kopiëren).
    Al aanwezige zinnen worden niet gedupliceerd (whitespace-genormaliseerd). Lege pack → prose zoals
    hij is (schone case blijft kort)."""
    prose = (prose or "").strip()
    mand = (pack or {}).get("mandatory") or []
    if not mand:
        return prose
    nt = _norm(prose)
    add = [m["sentence"].strip() for m in mand if _norm(m.get("sentence", "")) and _norm(m["sentence"]) not in nt]
    if not add:
        return prose
    tail = " ".join(add)
    if prose and prose[-1] not in ".!?…":
        prose += "."
    return (prose + " " + tail).strip() if prose else tail


def fact_prompt_section(pack: dict) -> str:
    """v7.1 — instructie: de APP voegt de feitelijke zin(nen) zelf toe. De LLM schrijft ALLEEN een
    korte opener/duiding eromheen en mag deze feiten NIET zelf herhalen of tegenspreken (geen eigen
    zone-/blok-/herstel-uitspraak over dit punt)."""
    mand = (pack or {}).get("mandatory") or []
    if not mand:
        return ""
    regels = "\n".join(f"- {m['sentence']}" for m in mand)
    return ("\n\n━━━ FEITELIJKE ZINNEN (de APP voegt deze automatisch aan je bericht toe — jij hoeft "
            "ze NIET te typen) ━━━\n" + regels
            + "\nSchrijf jij alleen een korte, warme opener en eventueel een beknopte duiding of vraag "
            "eromheen (reageer op wat de atleet schrijft). HERHAAL deze feiten niet zelf en spreek ze "
            "NOOIT tegen: doe zelf GEEN eigen uitspraak over de zones, werkblokken of het herstel van "
            "dit punt (bijv. niet zelf zeggen dat het herstel wél naar Z1 ging). De app zorgt voor de "
            "feitelijke zinnen; jij zorgt voor de menselijke toon eromheen.")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def validate_draft(text: str, *, is_running: bool = False, mandatory=None,
                   forbidden_claims=None, athlete_message: str = "") -> dict:
    """Fail-closed VALIDATOR (geen fixer, geen rewrite) over EXACT de tekst die persistent wordt.
    Geeft {ok, kind, detail}:
      kind == 'sport'   → 'Concept geblokkeerd — onjuiste sporttaal.'
      kind == 'content' → 'Concept geblokkeerd — inhoudelijke controle niet gehaald.'
    Accepteert (ok=True) alleen als ALLE regels slagen."""
    t = text or ""
    low = t.lower()

    # 1. interne pipeline-taal
    for term in _INTERNAL_VOCAB:
        if term in low:
            return {"ok": False, "kind": "content", "detail": f"intern:{term}"}
    # 2. zone-gebonden percentage
    if _ZONE_PCT.search(t):
        return {"ok": False, "kind": "content", "detail": "zone%"}
    # 3. verplichte feiten letterlijk aanwezig (whitespace-genormaliseerd). Na assemble_spine is dit
    #    per constructie waar; blijft als vangnet zodat een lek nooit stil verstuurbaar wordt.
    nt = _norm(t)
    for m in (mandatory or []):
        s = _norm(m.get("sentence", ""))
        if s and s not in nt:
            return {"ok": False, "kind": "content", "detail": f"missing_fact:{m.get('id')}"}
    # 4. TEGENSPRAAK: vrije tekst mag een verplicht feit niet tegenspreken. Strip eerst de exacte
    #    feit-zinnen (die bevatten bewust de ontkenning) en scan de REST op een verboden claim.
    scan = nt
    for m in (mandatory or []):
        s = _norm(m.get("sentence", ""))
        if s:
            scan = scan.replace(s, " ")
    for fc in (forbidden_claims or []):
        pat = fc.get("pattern")
        if pat and re.search(pat, scan, re.I):
            return {"ok": False, "kind": "content", "detail": f"contradiction:{fc.get('id')}"}
    # 5. stale relatieve dag (v6)
    if _REL_DAY.search(low):
        return {"ok": False, "kind": "content", "detail": "relative_day"}
    # 6. sporttaal: een RUN mag nooit een 'rit'/'ritje'/'fietsrit' heten (harde productregel)
    if is_running:
        if _RIT.search(t):
            return {"ok": False, "kind": "sport", "detail": "rit"}
        if _FIETSRIT.search(t) and not _CYCLING_CTX.search(athlete_message or ""):
            return {"ok": False, "kind": "sport", "detail": "fietsrit"}
    return {"ok": True, "kind": "", "detail": ""}


def block_message(kind: str) -> str:
    """Veilige coach-facing status bij een fail-closed reject."""
    if kind == "sport":
        return "Concept geblokkeerd — onjuiste sporttaal."
    return "Concept geblokkeerd — inhoudelijke controle niet gehaald."
