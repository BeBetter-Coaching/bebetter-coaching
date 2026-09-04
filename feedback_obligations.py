"""Feedback Evidence Arbitration & Message Coverage v3 (P0/P1).

Eén deterministische VERPLICHTINGEN-laag vóór de generatie. GEEN nieuwe fetch, GEEN store,
GEEN AI, GEEN downstream rewriter: puur een projectie over data die AL is vergaard
(zoneverdeling, geplande target, atleetbericht, actieve signalen). Ze maakt de prompt
STRENGER, zodat het model:
  - een zone-% claim aan een MODALITEIT (tempo/hartslag) koppelt;
  - EXACTE percentages gebruikt en NIET afrondt/verzint (33% blijft 33%, geen 'helft' voor 56%);
  - geen materiële (gelijk-of-hogere) zone weglaat uit een zone-samenvatting;
  - een atleet-claim ('ik dacht Z1-Z2') NIET met 'Klopt' bevestigt als de bron dat niet draagt;
  - een materiële bericht-verplichting (kan niet komen, vraag, pijn, schemaverzoek) niet negeert;
  - een actief klacht-/belastingsignaal daadwerkelijk laat meewegen (veilig, geen diagnose).

Als er niets te arbitreren valt (schone case) is het blok LEEG — schone PASS-cases blijven
kort en coachend (P2). De laag verzint nooit een percentage: ze rekent uitsluitend met de
bestaande, deterministische zone-classificatie (fs_client.classify_pace_hr_zone).
"""
from __future__ import annotations

import re

# Een zone-aandeel >= dit percentage is 'materieel' — het mag niet stil uit een samenvatting
# verdwijnen (Sophie: 13% Z3 verdween terwijl het even groot was als de wél genoemde 13% Z2).
_MATERIAL_SHARE = 10

_MODALITY_NL = {"tempo": "op tempo", "hartslag": "op hartslag"}
_MODALITY_ZONE = {"tempo": "tempozone", "hartslag": "hartslagzone"}

# Instemmings-woorden die een atleet-interpretatie als WAAR bevestigen — verboden als de bron
# de claim niet (volledig) draagt.
_AFFIRM_WORDS = ("klopt", "precies", "inderdaad", "helemaal goed", "exact", "klopt helemaal")

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
    (`fs_client.classify_pace_hr_zone`) — GEEN nieuwe zone-math/-grenzen. Elke lap weegt met
    zijn afstand (aandelen zijn eenheid-onafhankelijk); ontbreekt de afstand overal, dan telt
    elke lap even zwaar. Geeft `(shares, any_dist, used)` terug:
      shares = {"Z1": 74, ..., "buiten de zones": n}  (afgerond percentage, zelfde afronding
               als ai_feedback._zone_distribution — dat delegeert hiernaartoe: één bron).
    < 2 bruikbare laps → ({}, any_dist, used<2). Nooit fataal buiten deze pure berekening."""
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


def _numbered(shares: dict) -> dict:
    """Alleen de genummerde zones (Z1..Z5) → {num:int -> pct:int}."""
    out = {}
    for k, v in (shares or {}).items():
        m = re.fullmatch(r"Z([1-5])", str(k))
        if m:
            out[int(m.group(1))] = int(v)
    return out


def _claimed_zones(text: str) -> set:
    """Zone-nummers die de atleet zelf noemt (los + als bereik). Leeg = geen expliciete claim."""
    zs: set = set()
    for a, b in _ZONE_RANGE_RE.findall(text or ""):
        lo, hi = sorted((int(a), int(b)))
        zs.update(range(lo, hi + 1))
    for z in _ZONE_TOKEN_RE.findall(text or ""):
        zs.add(int(z))
    return zs


def _zone_evidence_section(modality: str, shares: dict, target_zones: set) -> str:
    """Bindende zone-evidence: modaliteit labelen, exacte %, geen materiële (hogere) zone
    weglaten. Vuurt alleen bij >= 2 materiële genummerde zones (dan is verwarring/omissie een
    reëel risico); één dominante zone (bv. Z1 95%) heeft geen arbitrage nodig → geen ruis."""
    numbered = _numbered(shares)
    if not numbered:
        return ""
    material = {z: p for z, p in numbered.items() if p >= _MATERIAL_SHARE}
    if len(material) < 2:
        return ""
    mod = _MODALITY_NL.get(modality, "")
    zone_woord = _MODALITY_ZONE.get(modality, "zone")
    volgorde = ", ".join(f"Z{z} {numbered[z]}%" for z in sorted(numbered))
    regels = [
        f"ZONE-EVIDENCE (deterministisch — de exacte {zone_woord}-verdeling): {volgorde}.",
        f"- Noem een zone-percentage ALTIJD met de modaliteit ('{mod or 'op tempo/hartslag'}'), zodat "
        f"tempo en hartslag niet verward worden.",
        "- Gebruik deze EXACTE percentages. Rond NIET af (33% is 33%, niet 40%) en vervang een "
        "percentage niet door een vage maat ('de helft', 'grootste deel') zonder het exacte getal.",
        f"- Laat GEEN materiële zone weg: elke zone met minstens {_MATERIAL_SHARE}% hoort in je "
        "samenvatting. Noem een zone niet 'een klein stukje' terwijl een even grote of grotere "
        "HOGERE zone onbenoemd verdwijnt.",
    ]
    if target_zones:
        boven = sorted(z for z in material if z > max(target_zones))
        if boven:
            zlist = ", ".join(f"Z{z}" for z in boven)
            regels.append(
                f"- Let op: {zlist} ligt BOVEN het geplande target (Z{max(target_zones)}). Met een "
                f"materieel aandeel daar mag je NIET bevestigen dat het 'helemaal rustig' of 'precies "
                f"volgens plan' bleef; benoem dat deel eerlijk. (Dit is geen waarschuwing als de "
                f"uitvoering verder binnen het plan valt, wel volledigheid.)")
    return "\n".join(regels)


def _claim_section(modality: str, shares: dict, athlete_text: str) -> str:
    """Verifieer een deterministisch checkbare atleet-zoneclaim vóór instemming. Vuurt alleen als
    de atleet zelf een zone noemt ÉN de bron de claim niet volledig draagt (anders geen ruis)."""
    numbered = _numbered(shares)
    if not numbered:
        return ""
    claimed = _claimed_zones(athlete_text)
    if not claimed:
        return ""
    material = {z for z, p in numbered.items() if p >= _MATERIAL_SHARE}
    if not material:
        return ""
    dominant = max(numbered, key=lambda z: numbered[z])
    totality = bool(_TOTALITY_RE.search(athlete_text or ""))
    missed_material = sorted(material - claimed)
    # Status bepalen (deterministisch, alleen op zones/afstand/verdeling — geen NL-semantiek breed).
    if dominant not in claimed:
        status = "CONTRADICTED"
    elif missed_material:
        status = "CONTRADICTED" if totality else "PARTIALLY_SUPPORTED"
    else:
        # atleet dekt alle materiële zones; bij totaliteitsclaim moet dat exact kloppen
        status = "SUPPORTED"
    if status == "SUPPORTED":
        return ""                                        # atleet had gelijk → normale flow bevestigt prima
    mod = _MODALITY_NL.get(modality, "")
    verdeling = ", ".join(f"Z{z} {numbered[z]}%" for z in sorted(numbered))
    claim_txt = "/".join(f"Z{z}" for z in sorted(claimed))
    regels = [
        f"ATLEET-CLAIM (verifieer vóór je instemt): de atleet duidt de intensiteit als {claim_txt}. "
        f"De deterministische verdeling {mod} is: {verdeling}. Status: {status}.".replace("  ", " "),
    ]
    if missed_material:
        hoog = ", ".join(f"Z{z} ({numbered[z]}%)" for z in missed_material)
        regels.append(f"- De atleet noemt {hoog} niet, terwijl dat een materieel aandeel is.")
    regels.append(
        "- Bevestig deze interpretatie daarom NIET met 'Klopt', 'Precies' of 'Inderdaad'. Erken kort "
        "wat de atleet dacht en beschrijf daarna eerlijk wat de data laat zien. Doe dit rustig en "
        "coachend, maak er geen probleem van als de uitvoering binnen het plan viel.")
    return "\n".join(regels)


def _message_section(athlete_text: str) -> str:
    """Bounded bericht-verplichtingen: adresseer materiële punten (kan niet komen, pijn,
    schemaverzoek, directe vraag). Vuurt alleen bij een gedetecteerd punt (geen ruis)."""
    t = athlete_text or ""
    punten = []
    if _UNAVAIL_RE.search(t):
        punten.append(
            "De atleet geeft aan een KOMENDE sessie niet te kunnen doen. Erken die afwezigheid; "
            "wens haar/hem daar GEEN plezier of succes voor alsof zij/hij er wél bij is, en instrueer "
            "niet om zich erop voor te bereiden.")
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
    """Signaalverplichting: een actief klacht-/belastingsignaal MOET de feedback sturen wanneer
    coachrelevant (zware/afwijkende uitvoering of zware/lange sessie op komst). Medisch
    terughoudend (geen diagnose/oorzaak/behandeling). Vuurt alleen wanneer relevant."""
    areas = [str(a) for a in (complaint_areas or []) if a]
    coachrelevant = bool(intensity_high or has_upcoming)
    regels = []
    if areas and coachrelevant:
        al = ", ".join(sorted(set(areas)))
        regels.append(
            f"Er is een ACTIEVE klacht ({al}) en deze/of de eerstvolgende sessie is zwaar. Adresseer "
            f"de klacht met een korte, neutrale check-in; verhoog de belasting deze week niet en wees "
            f"voorzichtig richting de eerstvolgende zware of lange sessie. Wees medisch terughoudend: "
            f"geen diagnose, geen oorzaak, geen behandeladvies, en geen wegwuivende geruststelling.")
    if load_elevated and coachrelevant:
        regels.append(
            "De recente belasting is VERHOOGD in combinatie met een zware uitvoering of een zware "
            "sessie op komst. Laat dat meewegen (voorzichtige vervolgstap of herstel prioriteren), "
            "zonder vals gerust te stellen en zonder diagnose.")
    if not regels:
        return ""
    return "SIGNAAL-VERPLICHTING (veilig laten meewegen):\n" + "\n".join("- " + r for r in regels)


def build(*, modality: str = "", shares: dict | None = None, any_dist: bool = False,
          planned_target_zones=None, athlete_text: str = "", complaint_areas=None,
          load_elevated: bool = False, intensity_high: bool = False,
          has_upcoming: bool = False) -> dict:
    """Bouw de deterministische evidence-contract/verplichtingen-projectie en render de bindende
    promptsectie. Alleen ACTIEVE sub-secties komen in het blok; is er niets te arbitreren, dan is
    `prompt_block` LEEG (schone cases blijven kort). Nooit fataal: bij een interne fout leeg."""
    try:
        shares = shares or {}
        target = set(int(z) for z in (planned_target_zones or []) if z)
        zone_sec = _zone_evidence_section(modality, shares, target)
        claim_sec = _claim_section(modality, shares, athlete_text)
        msg_sec = _message_section(athlete_text)
        sig_sec = _signal_section(complaint_areas, load_elevated, intensity_high, has_upcoming)
    except Exception:
        return {"prompt_block": "", "sections": []}
    sections = [s for s in (zone_sec, claim_sec, msg_sec, sig_sec) if s]
    if not sections:
        return {"prompt_block": "", "sections": []}
    block = ("━━━ EVIDENCE-CONTRACT & VERPLICHTINGEN (deterministisch — bindend, ga hier niet "
             "tegenin) ━━━\n" + "\n\n".join(sections))
    return {"prompt_block": block, "sections": sections}
