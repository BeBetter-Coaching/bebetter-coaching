"""Feedback Evidence Arbitration & Message Coverage — v3 + v4 (athlete-facing zone simplification).

Eén deterministische VERPLICHTINGEN-laag vóór de generatie. GEEN nieuwe fetch, GEEN store,
GEEN AI, GEEN downstream rewriter: puur een projectie over data die AL is vergaard
(zoneverdeling, geplande target, atleetbericht, actieve signalen). Ze maakt de prompt
STRENGER én simpeler, zodat het model:

  v4 (kern) — GEEN zonepercentages of distributie-breuken naar de atleet. De exacte verdeling
    bleef bij het model onbetrouwbaar (live: 23%→27%, 57%→71%, 56%→50% — drie van de drie fout).
    Percentages blijven INTERN bruikbaar (Masterbrein/QA/classificatie), maar de athlete-facing
    tekst krijgt KWALITATIEVE duiding + exacte blok/lap-AANTALLEN i.p.v. percentages.
  - een zone-duiding aan een MODALITEIT (tempo/hartslag) koppelt en bij verschil niet stil het
    geruststellende verhaal kiest;
  - een atleet-claim ('ik dacht Z1-Z2') NIET met 'Klopt' bevestigt als de bron dat niet draagt —
    zonder percentages, kwalitatief;
  - een materiële bericht-verplichting (kan niet komen, vraag, pijn, schemaverzoek) niet negeert;
  - een actieve klacht bij relevante belasting DETERMINISTISCH een neutrale check-in oplevert.

Schone case → LEEG blok (kort/coachend). De laag rekent uitsluitend met de bestaande
deterministische zone-classificatie (fs_client.classify_pace_hr_zone); geen nieuwe zone-math.
"""
from __future__ import annotations

import re

# Een zone-aandeel >= dit percentage is 'materieel' — intern (nooit in athlete-facing tekst).
_MATERIAL_SHARE = 10

_MODALITY_NL = {"tempo": "op tempo", "hartslag": "op hartslag"}
_MODALITY_ZONE = {"tempo": "tempozone", "hartslag": "hartslagzone"}

# Totaliteits-claim van de atleet ('alles ging in Z2', 'precies volgens plan').
_TOTALITY_RE = re.compile(r"\b(alles|helemaal|volledig|precies|de\s+hele|hele\s+tijd|constant|steeds)\b", re.I)

# Atleet kan/gaat een komende (genoemde) sessie NIET doen.
_UNAVAIL_RE = re.compile(
    r"er\s+.{0,20}?niet\s+bij|niet\s+bij\s+(kunnen\s+)?zijn|kan\s+niet\s+(komen|mee|meedoen|erbij)|"
    r"ben\s+er\s+niet|niet\s+aanwezig|red\s+het\s+niet|haal\s+het\s+niet|sla\s+.{0,20}?\s+over|"
    r"moet\s+.{0,20}?\s+overslaan|mis\s+ik|ben\s+afwezig|niet\s+erbij|"
    r"lukt\s+.{0,20}?\s+niet\s+om\s+te\s+komen", re.I)

# Pijn/klacht die de atleet in DIT bericht zelf noemt.
_PAIN_RE = re.compile(
    r"\bpijn\b|blessure|geblesseerd|zeer|ontsteking|scheenbeen|scheen|knie|hiel|kuit|achilles|"
    r"hamstring|lies|voet|enkel|rug|last\s+van|stijf|stijfheid|\bziek\b|griep|koorts", re.I)

# Verzoek om schema-/wedstrijdwijziging.
_SCHEDULE_RE = re.compile(
    r"kun\s+je.*(aanpas|verzet|verplaats|wijzig|schuif)|schema.*(aanpas|verzet|wijzig|verander)|"
    r"training.*(verzet|verplaats|verschuif)|kan\s+.*\s+verzet|wil\s+.*\s+(verzet|aanpas)", re.I)

_ZONE_TOKEN_RE = re.compile(r"z(?:one)?\s*([1-5])\b", re.I)
_ZONE_RANGE_RE = re.compile(r"z(?:one)?\s*([1-5])\s*(?:[-–—]|tot|en|/|,)\s*z?(?:one)?\s*([1-5])", re.I)


def zone_shares(laps, zones, is_pace):
    """DETERMINISTISCHE zoneverdeling (aandeel per zone) uit de per-lap classificatie
    (`fs_client.classify_pace_hr_zone`) — GEEN nieuwe zone-math/-grenzen. INTERN bewijs
    (Masterbrein/QA/classificatie); v4 exposeert deze percentages NOOIT athlete-facing. Elke lap
    weegt met zijn afstand; ontbreekt de afstand overal, dan telt elke lap even zwaar. Geeft
    `(shares, any_dist, used)`; shares = {"Z1": 74, ..., "buiten de zones": n}. < 2 laps → ({}, ..)."""
    if not laps or not zones or is_pace is None:
        return {}, False, 0
    import fs_client as _fs
    from collections import defaultdict
    per: dict = defaultdict(float)
    tot = 0.0
    used = 0
    any_dist = False
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        d = _fs._safe_float(lap.get("amount"))
        if d is None:
            d = _fs._safe_float(lap.get("distance_display"))
        if d and d > 0:
            any_dist = True
        if is_pace:
            _pm = _fs._pace_to_float(lap.get("pace_display") or "")
            val = _pm * 60 if _pm not in (0, float("inf")) else None
        else:
            val = _fs._safe_float(lap.get("hr_avg"))
        if val is None:
            continue
        cls = _fs.classify_pace_hr_zone(zones, val, is_pace=is_pace)
        if not cls:
            continue
        key = f"Z{cls['num']}" if cls.get("status") == "IN_ZONE" else "buiten de zones"
        w = d if (d and d > 0) else 1.0
        per[key] += w
        tot += w
        used += 1
    if tot <= 0 or used < 2:
        return {}, any_dist, used
    shares = {k: round(v / tot * 100) for k, v in per.items()}
    return shares, any_dist, used


def block_zone_counts(blocks, zones, is_pace, zone_type):
    """Deterministische, VOORAF berekende werkblok-evidence (v6): de exacte VOLGORDE van zones per
    werkblok (Z3, Z4, Z3, Z4, Z4) én de TELLING per zone (AANTALLEN, geen percentages). Beide zijn
    één immutable feit — het MODEL mag zelf niet tellen of classificeren (regel 12), het neemt deze
    regel letterlijk over. Alleen ACTIVE werkblokken; classificeert de gemeten waarde van de
    classificeerbare zonetabel via de bestaande classifier. Geeft '' bij < 2 telbare blokken."""
    if not blocks or not zones or is_pace is None or zone_type not in ("tempo", "hartslag"):
        return ""
    import fs_client as _fs
    from collections import Counter
    seq = []
    cnt: Counter = Counter()
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") in ("WARMUP", "REST", "COOLDOWN"):
            continue
        if zone_type == "hartslag":
            val = _fs._safe_float(b.get("observed_hr"))
        else:
            pm = _fs._pace_to_float(b.get("observed_pace") or "")
            val = pm * 60 if pm not in (0, float("inf")) else None
        if val is None:
            continue
        cls = _fs.classify_pace_hr_zone(zones, val, is_pace=is_pace)
        label = f"Z{cls['num']}" if (cls and cls.get("status") == "IN_ZONE") else "buiten"
        seq.append(label)
        cnt[cls["num"] if (cls and cls.get("status") == "IN_ZONE") else "buiten"] += 1
    total = len(seq)
    if total < 2 or not cnt:
        return ""
    mod = _MODALITY_NL.get(zone_type, "")
    volgorde = ", ".join("buiten de zones" if s == "buiten" else s for s in seq)
    parts = [f"{cnt[z]} in Z{z}" for z in sorted(k for k in cnt if k != "buiten")]
    if cnt.get("buiten"):
        parts.append(f"{cnt['buiten']} buiten de zones")
    telling = ", ".join(parts)
    return ("\n\nWERKBLOK-EVIDENCE (deterministisch door de app berekend — neem LETTERLIJK over, tel "
            "of classificeer zelf NIETS, geen percentages):\n"
            f"- Blokvolgorde {mod}: {volgorde}.\n"
            f"- Telling {mod}: van de {total} werkblokken {telling}.\n"
            "Je mag deze volgorde/aantallen noemen (bijv. 'drie van de vijf werkblokken in Z4') of het "
            "verloop kwalitatief beschrijven; verander de getallen niet en leid zelf niets nieuws af.")


def _numbered(shares: dict) -> dict:
    """Alleen de genummerde zones (Z1..Z5) → {num:int -> pct:int}."""
    out = {}
    for k, v in (shares or {}).items():
        m = re.fullmatch(r"Z([1-5])", str(k))
        if m:
            out[int(m.group(1))] = int(v)
    return out


def above_easy(shares: dict, ceiling: int = 2) -> bool:
    """True als er een MATERIEEL aandeel (>= _MATERIAL_SHARE) in een zone BOVEN `ceiling` zit
    (intern; voor de continue easy/recovery divergentie-guard)."""
    return any(z > ceiling and p >= _MATERIAL_SHARE for z, p in _numbered(shares).items())


def _claimed_zones(text: str) -> set:
    """Zone-nummers die de atleet zelf noemt (los + als bereik). Leeg = geen expliciete claim."""
    zs: set = set()
    for a, b in _ZONE_RANGE_RE.findall(text or ""):
        lo, hi = sorted((int(a), int(b)))
        zs.update(range(lo, hi + 1))
    for z in _ZONE_TOKEN_RE.findall(text or ""):
        zs.add(int(z))
    return zs


def _zone_qualitative_section(modality: str, numbered: dict, ceiling, has_plan_target: bool,
                              is_structured: bool) -> str:
    """v4 — KWALITATIEVE zone-duiding, ZONDER percentages. Vuurt alleen bij >= 2 materiële zones
    (dan is een verkeerde totaal-duiding een reëel risico). Vertaalt de interne verdeling naar
    coachtaal: materieel deel boven target eerlijk benoemen, geruststellend totaalverhaal vermijden
    bij gestructureerd werk, modaliteit labelen. NOOIT een getal/percentage/breuk."""
    if not numbered:
        return ""
    material = {z: p for z, p in numbered.items() if p >= _MATERIAL_SHARE}
    if len(material) < 2:
        return ""
    mod = _MODALITY_NL.get(modality, "op tempo/hartslag")
    regels = [
        "ZONE-DUIDING (kwalitatief — GEEN percentages of breuken in je bericht):",
        f"- Beschrijf de intensiteit KWALITATIEF en label de modaliteit ('{mod}'). Noem GEEN "
        "zonepercentages en ook geen distributie-breuken ('de helft', 'een derde', 'bijna "
        "driekwart'); gebruik voor gestructureerd werk exacte blok/lap-aantallen.",
    ]
    if is_structured:
        regels.append(
            "- Dit is gestructureerd werk: beoordeel PER WERKBLOK (zie blok-analyse/werkblok-telling) "
            "en trek GEEN geruststellende totaalconclusie over de hele sessie. Vertellen hartslag en "
            "tempo een verschillend verhaal, kies dan niet stil de geruststellende kant, maar benoem "
            "het verschil.")
        return "\n".join(regels)
    if ceiling is not None:
        boven = sorted(z for z in material if z > ceiling)
        anker = f"de geplande zone {ceiling}" if has_plan_target else f"het rustige bereik (t/m zone {ceiling})"
        if boven:
            regels.append(
                f"- Een MATERIEEL deel lag boven {anker} (in {', '.join('Z' + str(z) for z in boven)}). "
                f"Bevestig daarom NIET dat het helemaal binnen dat bereik bleef; benoem dat deel "
                f"eerlijk en kwalitatief (bijv. 'grootste deel bleef rustig, maar er zat ook een stuk "
                f"boven je rustige bereik in'). Dit is geen waarschuwing als de uitvoering verder "
                f"binnen plan valt, wel volledigheid.")
        else:
            regels.append(
                f"- De uitvoering bleef in hoofdzaak binnen {anker}; je mag kwalitatief bevestigen dat "
                f"het overwegend binnen het bedoelde bereik bleef, zonder percentages.")
    else:
        regels.append(
            "- De intensiteit lag verspreid over meerdere zones; beschrijf dat kwalitatief en kies "
            "niet stil één geruststellende zone.")
    return "\n".join(regels)


def _claim_section(modality: str, numbered: dict, claimed: set, athlete_text: str) -> str:
    """Verifieer een deterministisch checkbare atleet-zoneclaim vóór instemming — v4 ZONDER
    percentages. Vuurt alleen als de atleet zelf een zone noemt ÉN de bron de claim niet volledig
    draagt (anders geen ruis)."""
    if not numbered or not claimed:
        return ""
    material = {z for z, p in numbered.items() if p >= _MATERIAL_SHARE}
    if not material:
        return ""
    dominant = max(numbered, key=lambda z: numbered[z])
    totality = bool(_TOTALITY_RE.search(athlete_text or ""))
    missed_material = sorted(material - claimed)
    if dominant not in claimed:
        status = "CONTRADICTED"
    elif missed_material:
        status = "CONTRADICTED" if totality else "PARTIALLY_SUPPORTED"
    else:
        status = "SUPPORTED"
    if status == "SUPPORTED":
        return ""                                        # atleet had gelijk → normale flow bevestigt prima
    mod = _MODALITY_NL.get(modality, "")
    claim_txt = "/".join(f"Z{z}" for z in sorted(claimed))
    regels = [
        f"ATLEET-CLAIM (verifieer vóór je instemt): de atleet duidt de intensiteit als {claim_txt}. "
        f"Status volgens de bron: {status}.",
    ]
    if missed_material:
        hoog = ", ".join(f"Z{z}" for z in missed_material)
        regels.append(
            f"- De bron laat {mod} ook een materieel deel in {hoog} zien, dat de atleet niet noemt "
            f"(kwalitatief benoemen, GEEN percentages).".replace("  ", " "))
    regels.append(
        "- Bevestig deze interpretatie daarom NIET met 'Klopt', 'Precies' of 'Inderdaad'. Erken kort "
        "wat de atleet dacht en beschrijf daarna eerlijk, KWALITATIEF, wat de data laat zien "
        "(bijv. 'grootste deel was rustig, maar qua tempo zat er ook een stuk boven Z2 in, dus "
        "helemaal Z1-Z2 was het niet'). Rustig en coachend; geen probleem als het binnen plan viel.")
    return "\n".join(regels)


def _divergence_section(divergence) -> str:
    """v5 — continue easy/recovery HR/tempo-divergentie: één modaliteit bleef rustig, de andere kwam
    er materieel bovenuit. Verbiedt blanket geruststelling ('precies goed'/'je zat er gewoon goed
    in') zonder het verschil te benoemen. Kwalitatief, geen percentages. Alleen bij een echt
    gedetecteerde divergentie (beide modaliteiten geclassificeerd) — nooit geforceerd."""
    if not divergence:
        return ""
    above = _MODALITY_NL.get(divergence.get("above"), "op de ene modaliteit")
    easy = _MODALITY_NL.get(divergence.get("easy"), "op de andere modaliteit")
    return ("CONTINU-DUIDING — HARTSLAG/TEMPO-VERSCHIL (kwalitatief, geen percentages):\n"
            f"- Dit is een rustige/hersteltraining: {easy} bleef het rustig, maar {above} zat er ook "
            f"een stuk BOVEN je rustige bereik in. Concludeer daarom NIET dat het 'precies goed', "
            f"'helemaal volgens plan' of 'je zat er gewoon goed in' was; benoem eerlijk en kwalitatief "
            f"dat hartslag en tempo hier niet hetzelfde verhaal vertellen (bijv. '{easy} bleef het "
            f"rustig, maar qua tempo zat er ook een stuk boven je rustige bereik in'). Geen percentages "
            f"of breuken.")


def _message_section(athlete_text: str) -> str:
    """Bounded bericht-verplichtingen: adresseer materiële punten (kan niet komen, pijn,
    schemaverzoek, directe vraag). Vuurt alleen bij een gedetecteerd punt (geen ruis)."""
    t = athlete_text or ""
    punten = []
    if _UNAVAIL_RE.search(t):
        punten.append(
            "De atleet geeft aan een KOMENDE sessie niet te kunnen doen. Erken die afwezigheid kort "
            "('Jammer dat je er niet bij kunt zijn', 'dank dat je het laat weten'); wens haar/hem daar "
            "GEEN plezier of succes voor alsof zij/hij er wél bij is, en instrueer niet om zich erop "
            "voor te bereiden. KOPIEER het tijdswoord uit haar bericht ('morgen'/'straks') NIET "
            "letterlijk; dat hoort bij het moment van haar bericht, niet bij nu.")
    if _PAIN_RE.search(t):
        punten.append(
            "De atleet noemt zelf pijn/klacht. Adresseer dat met een korte, neutrale check (geen "
            "diagnose, geen oorzaak, geen behandeladvies).")
    if _SCHEDULE_RE.search(t):
        punten.append(
            "De atleet vraagt om een schema-/wedstrijdwijziging. Bevestig eerlijk dat je het ziet en "
            "houd het bij een voorwaardelijke vervolgstap; zeg NIET toe dat je het omzet (coach-agency).")
    if "?" in t and not punten:
        punten.append("De atleet stelt een directe vraag. Beantwoord die concreet; laat hem niet liggen.")
    elif "?" in t:
        punten.append("Beantwoord ook de directe vraag van de atleet.")
    if not punten:
        return ""
    return "BERICHT-VERPLICHTINGEN (niet negeren):\n" + "\n".join("- " + p for p in punten)


def _signal_section(complaint_areas, load_elevated, intensity_high, has_upcoming) -> str:
    """Signaal-verplichting: een actieve klacht MOET bij relevante belasting (zware/afwijkende
    uitvoering OF zware/lange sessie op komst) een NEUTRALE check-in opleveren — deterministisch en
    testbaar (Douwe's scheenklacht werd 3× live genegeerd). Medisch terughoudend. Vuurt niet bij een
    stale/achtergrond-klacht zonder relevante belasting."""
    areas = [str(a) for a in (complaint_areas or []) if a]
    coachrelevant = bool(intensity_high or has_upcoming)
    regels = []
    if areas and coachrelevant:
        al = ", ".join(sorted(set(areas)))
        deel = al if len(areas) == 1 else "klacht"
        regels.append(
            f"Er is een ACTIEVE klacht ({al}) en deze en/of de eerstvolgende sessie is zwaar. NEEM een "
            f"korte, NEUTRALE check-in op over de {deel} (bijv. 'hou even in de gaten hoe je {deel} "
            f"hierop reageert' of 'hoe reageert je {deel} hier nu op?'). Verhoog de belasting deze week "
            f"niet en wees voorzichtig richting de eerstvolgende zware of lange sessie. Wees medisch "
            f"terughoudend: geen diagnose, geen oorzaak, geen behandeladvies, geen wegwuivende "
            f"geruststelling.")
    if load_elevated and coachrelevant:
        regels.append(
            "De recente belasting is VERHOOGD in combinatie met een zware uitvoering of een zware "
            "sessie op komst. Laat dat meewegen (voorzichtige vervolgstap of herstel prioriteren), "
            "zonder vals gerust te stellen en zonder diagnose.")
    if not regels:
        return ""
    return "SIGNAAL-VERPLICHTING (veilig laten meewegen):\n" + "\n".join("- " + r for r in regels)


def build(*, modality: str = "", shares: dict | None = None, planned_target_zones=None,
          athlete_text: str = "", is_structured: bool = False, complaint_areas=None,
          load_elevated: bool = False, intensity_high: bool = False,
          has_upcoming: bool = False, divergence=None) -> dict:
    """Bouw de deterministische verplichtingen-projectie en render de bindende promptsectie
    (v4: KWALITATIEF, geen athlete-facing percentages). Alleen ACTIEVE sub-secties komen in het
    blok; niets te arbitreren → `prompt_block` LEEG (schone cases blijven kort). Nooit fataal.
    v5: `divergence` (of None) = een gedetecteerd HR/tempo-verschil op een continue easy/recovery-run."""
    try:
        numbered = _numbered(shares or {})
        target = set(int(z) for z in (planned_target_zones or []) if z)
        claimed = _claimed_zones(athlete_text)
        ceiling = max(target) if target else (max(claimed) if claimed else None)
        zone_sec = _zone_qualitative_section(modality, numbered, ceiling, bool(target), is_structured)
        div_sec = _divergence_section(divergence)
        claim_sec = _claim_section(modality, numbered, claimed, athlete_text)
        msg_sec = _message_section(athlete_text)
        sig_sec = _signal_section(complaint_areas, load_elevated, intensity_high, has_upcoming)
    except Exception:
        return {"prompt_block": "", "sections": []}
    sections = [s for s in (zone_sec, div_sec, claim_sec, msg_sec, sig_sec) if s]
    if not sections:
        return {"prompt_block": "", "sections": []}
    block = ("━━━ EVIDENCE-CONTRACT & VERPLICHTINGEN (deterministisch — bindend, ga hier niet "
             "tegenin) ━━━\n" + "\n\n".join(sections))
    return {"prompt_block": block, "sections": sections}
