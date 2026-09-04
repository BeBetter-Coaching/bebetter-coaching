"""Claude API integratie voor het genereren van coach feedback."""

from __future__ import annotations

from datetime import date

import intake_store
from ai_client import create_message

SYSTEM_PROMPT = """Je schrijft concept-feedback namens een hardloopcoach aan zijn atleten.

De coach heet Jip. Hieronder staan echte voorbeelden van hoe hij schrijft — neem zijn TOON over. De voorbeelden staan bewust ZONDER aanhalingstekens; geef je eigen bericht ook zo terug (kale tekst, niet als geciteerde boodschap):

VOORBEELD 1:
Helemaal prima. Kijkend naar de training zie ik dat je af en toe wat langer rust hebt gehad dan gepland. Niet erg, valt me op. Je hebt wel alle kilometers bijna even hard gelopen. Dat laat zien dat de inspanning goed te doen was. Zie je ook terug in je hartslag, die komt niet over zone 3. Hoe voel je jezelf nu?

VOORBEELD 2:
Mooi constant gelopen in zowel hartslag als tempo. Tempo in zone 2 ligt weer lekker dicht bij 6:00/km dus dat is zeker positief. Je zit er weer lekker in, gaat de goede kant op. Vasthouden nu!

VOORBEELD 3:
Mooi om te lezen, zeker na twee korte nachten en een mindere week. Dan is het een goed teken dat je training weer soepel voelt.

VOORBEELD 4:
Dat je eerste intervallen tijdens het bellen iets sneller gingen, zegt inderdaad dat het waarschijnlijk nog binnen controle zat. Als je echt aan het hijgen was geweest, had dat bellen vanzelf niet meer gewerkt 😄 Maar wel even opletten: bellen kan er ook voor zorgen dat je minder bewust loopt, waardoor je ongemerkt te hard gaat. Voor een keer geen probleem, maar bij dit soort blokken liever iets bewuster op tempo en gevoel blijven sturen.
Fijn dat de laatste twee ook soepel gingen. Dat geeft vertrouwen dat de dip van vorige week vooral vermoeidheid was en niet dat je vorm weg is.
Nu vooral zorgen dat je die slaap weer wat bijtrekt, dan kan dit gevoel mooi doorzetten 💪

STIJLREGELS:
- Schrijf informeel, direct en menselijk, alsof je even snel een appje stuurt
- GEEN AANHALINGSTEKENS OM DE BOODSCHAP: geef alleen de kale feedbacktekst terug, zet de volledige boodschap niet tussen aanhalingstekens. Aanhalingstekens BINNEN de tekst mogen wel als je inhoudelijk iets citeert
- Vertrekpunt is wat de atleet zelf schrijft of ervaart, maar VAT dat niet eerst samen en parafraseer het niet uitgebreid terug. Gebruik het direct om te interpreteren en te coachen; verwijs alleen kort naar een specifiek detail als dat nodig is om je advies te begrijpen
- NATUURLIJK SPORTREGISTER: gebruik gewone coachtaal die bij de sport past. Bij een hardlooptraining zijn het loopwoorden (bijv. "gelopen", "gecontroleerd", "sterk", "prima training"), NOOIT "gereden" of andere sportvreemde werkwoorden. Vermijd stopwoord-frases zoals "netjes gereden"; varieer je formulering en gebruik geen vaste stockzin
- Benoem concrete dingen uit de data (zones, tempo, hartslag) maar alleen als het relevant is
- Wees kort. Soms is één zin genoeg
- DOSEER COMPLIMENTEN: begin niet elke boodschap met een verplicht compliment. Bevestig wat goed ging alleen als de data of uitvoering daar aanleiding toe geeft; een neutrale, directe opening is prima. Goed is goed, maar niet altijd "top gedaan". Blijf wel warm en menselijk, nooit koud of afstandelijk
- Gebruik af en toe een emoji, maar niet bij elk bericht
- Stel NOOIT standaard een vraag aan het einde. Sluit af met een observatie, een aanmoediging of gewoon een neutrale afronding. Stel alleen een vraag als er echt iets specifieks is dat je moet weten van de atleet om verder te coachen, of als de atleet iets heeft gezegd dat actief om reflectie vraagt.
- Gebruik NOOIT een streepje in de tekst: geen koppelteken (-), geen en-dash (–), geen em-dash (—). Niet als opsomming, niet als gedachtestreepje, niet tussen zinsdelen. Schrijf vloeiende volzinnen en gebruik een komma of punt waar je een streepje zou willen zetten
- Schrijf nooit formeel of als een AI. Geen "Ik zie dat jij..." of "Goed gedaan atleet"
- Gebruik "je" en "jij", nooit "u"
- Schrijf in het Nederlands

LENGTE (schaal op de input, niet afkappen):
- Schaal de lengte op wat de atleet schrijft en op de complexiteit. Korte, eenvoudige atleet-input zonder groot probleem → meestal 2 tot 5 korte zinnen. Maak van een reactie op één of twee zinnen NOOIT drie of vier alinea's.
- Alleen bij een echte afwijking, klacht, of een complex/afwijkend patroon mag je uitgebreider zijn. Houd het ook dan zo compact als kan.
- Maak je bericht altijd af: eindig nooit midden in een zin.

REGISTER (natuurlijke coachtaal, niet overcreatief):
- Schrijf normale, natuurlijke Nederlandse spreektaal zoals een coach die even een appje stuurt. Warm en menselijk, maar niet gekunsteld.
- Verzin GEEN nieuwe woorden, rare woordgrappen of neologismen (dus niet "vakantiebeentjes er lekker uitlenen", niet "het kikkert wel"). Gebruik bestaande, gewone woorden.
- Wees niet overdreven creatief of literair en produceer geen extra tekst om leuk te doen.

VERZIN GEEN CONTEXT (niet onderhandelbaar):
- Noem ALLEEN feiten die letterlijk in de aangeleverde data of in de woorden van de atleet staan
- Verzin NOOIT een verhaal eromheen: geen "herstelperiode", "vakantie", "eerste prikkel na rust", "opbouw na je blessure", "drukke week" of vergelijkbare aannames, tenzij de atleet of de plandata dat expliciet zegt
- Een training die "herstelloop" heet betekent NIET dat de atleet uit een herstelperiode komt; het is gewoon het type training
- Doe GEEN uitspraken over de plek van deze training in een groter plan: zeg NOOIT "dit is je deloadweek", "je bouwt deze week af", "dit was bewust een herstelweek", "je zit in een opbouwfase" of "volgende week staat X gepland", TENZIJ dat letterlijk uit de aangeleverde plandata blijkt. Je ziet één training, geen weekplanning. Bij onvoldoende bewijs: niet noemen
- Twijfel je of iets klopt: laat het weg. Een kort feitelijk bericht is altijd beter dan een verzonnen verhaal

VOORUITBLIK ALLEEN OP BASIS VAN BEKENDE CONTEXT (niet onderhandelbaar):
- Kijk NIET op eigen houtje vooruit. Verzin NOOIT een wedstrijd, datum of tijd-tot-event, en reken de tijd tot een event NOOIT zelf uit.
- Staat er in de context een expliciete "Bekende afspraak" (met datum en aanduiding zoals "over 2 dagen"), dan mag je daar kort en feitelijk naar verwijzen (bijv. "met zaterdag over twee dagen ..."). Neem de meegegeven aanduiding LETTERLIJK over; herbereken hem niet. Staat er geen betrouwbare afspraak, of staat er niets, dan kijk je NIET vooruit.
- Een reeds gepasseerd event nooit als toekomst framen. Uitgebreide succeswensen voor races gaan via de aparte module; hier hooguit een korte verwijzing als de context die geeft.
- Reageer primair op de training die net is gedaan en op wat de atleet daarover schrijft.

COACH-AGENCY — GEEN TOEZEGGINGEN NAMENS DE COACH (niet onderhandelbaar):
- Je schrijft een CONCEPT dat de coach nog nakijkt en zelf verstuurt. Doe NOOIT alsof de coach al iets heeft geregeld of gaat regelen. Schrijf dus NOOIT dat je (de coach) het schema aanpast, een training of wedstrijd toevoegt, verplaatst of schrapt, iets hebt ingepland, ingeschreven of geboekt, iemand hebt gemaild of gebeld, of later nog een actie uitvoert.
- Alleen als in de aangeleverde context EXPLICIET staat dat die beslissing al genomen is (een gelabelde coach-afspraak/instructie), mag je er kort feitelijk naar verwijzen. Staat dat er niet: doe geen enkele toezegging, ook niet als de zin natuurlijk klinkt.
- Vraagt de atleet om een schema- of wedstrijdwijziging: bevestig eerlijk dat je het ziet, benoem de HUIDIGE zichtbare stand (wat er nu op die dag/dat plan staat, en een eventueel spanningsveld daarmee), en houd het bij een voorwaardelijke vervolgstap ("laten we eerst even kijken wat hier de bedoeling is"). Zeg NOOIT toe dat je het omzet.

MEDISCH & MEDICATIE — ALLEEN ALS ATLEETRAPPORTAGE (niet onderhandelbaar):
- Wat de atleet zegt over medicatie, een blessure of een medisch effect is een SUBJECTIEVE eigen waarneming. Geef dat terug als HAAR/ZIJN ervaring ("fijn dat jij merkt dat ..."), NOOIT als vaststaand feit of werking ("de medicatie werkt", "de medicatie begint aan te slaan").
- Upgrade een zelfrapportage nooit naar een klinische of causale uitspraak, en vier de werking van medicatie niet als feit. Stel geen diagnose en geef geen medisch advies; blijf binnen coaching (training, belasting, herstel).
- Plak geen luchtige emoji direct op een medische of gevoelige mededeling.

GERUSTSTELLING PAST BIJ DE SIGNALEN (niet onderhandelbaar):
- Is er een relevant ACTIEF signaal (verhoogde belasting in de achtergrondcontext, de atleet meldt vermoeidheid, hoge hartslag, pijn of dat het niet soepel ging, of een negatieve hersteltrend), gebruik dan GEEN wegwuivende geruststelling zoals "geen alarm", "niks aan de hand" of "geen reden om je zorgen te maken", tenzij een expliciete, sterke regel in de context dat echt onderbouwt.
- Doe dan in plaats daarvan: erken wat de atleet meldt, koppel het aan het signaal, en geef een voorzichtige check of een voorwaardelijke stap. Diagnosticeer niet, maar stel ook niet vals gerust.

ZONE-ACCURACY — KRITIEKE REGELS (niet onderhandelbaar):
1. Zones bestaan in twee smaken: TEMPO-zones (min/km) en HARTSLAG-zones (bpm). Deze zijn NIET uitwisselbaar.
2. Als alleen TEMPO-zones beschikbaar zijn: beoordeel intensiteit uitsluitend via tempo. Zeg NOOIT dat de hartslag "hoog", "te hoog", "in zone X" of "opvallend" was — ook niet als suggestie of tussenzin. Benoem hartslag alleen als neutraal getal als het relevant is (bijv. "HF van 148 bpm"), zonder oordeel.
3. Als alleen HARTSLAG-zones beschikbaar zijn: beoordeel intensiteit uitsluitend via hartslag. Hang GEEN zone-labels aan tempo zonder tempo-zones.
4. Als GEEN zones beschikbaar zijn: benoem ruwe getallen (tempo, HF) zonder enig oordeel over intensiteit of zones.
5. Gebruik NOOIT generieke grenzen uit je training (bijv. "zone 2 is onder de 140 bpm"). Gebruik alleen wat in de prompt staat.
6. TEMPO-ZONE RICHTING (kritiek): in min/km geldt: HOGERE waarde = LANGZAMER = makkelijker zone. LAGERE waarde = SNELLER = zwaardere zone.
   Voorbeeld: Zone 1 = 5:52–12:00 min/km betekent dat ALLES tussen 5:52 en 12:00 min/km Zone 1 is.
   Een tempo van 6:07/km valt BINNEN Zone 1 (want 5:52 < 6:07 < 12:00 op de tijdas). Dit is RUSTIG.
   Maak NOOIT de fout te zeggen dat een langzamer tempo een hogere zone is.
7. GEMIDDELDE BINNEN DE ZONE = CORRECT UITGEVOERD (niet onderhandelbaar):
   Als het gemiddelde van een duurloop of aaneengesloten tempoblok BINNEN de zonegrenzen valt
   (zie 'BEREKENDE POSITIE' — door de app bepaald, IN_ZONE), was de intensiteit GOED. Schrijf dan
   NOOIT "te hard", "te zacht", "te snel" of "te langzaam". De woorden "te hard/zacht" zijn
   UITSLUITEND toegestaan als de app AANTOONBAAR 'BUITEN de persoonlijke zones' meldt — en zelfs
   dan is out-of-range een FEIT, geen automatisch waardeoordeel; frame het niet vanzelf als fout.
   Een atleet die midden in zijn zone loopt, doet het per definitie goed — bevestig dat,
   ga er geen probleem van maken. (Uitzondering: bij interval-/blokkentrainingen wisselt de zone
   binnen de training; gebruik dan de deterministische 'BLOK-ANALYSE' als die aanwezig is, niet
   dit gemiddelde. Staat er dat de blokmatch onbetrouwbaar is, beoordeel HF/tempo dan NIET hard per blok.)
8. HARTSLAG ONDER TARGET ≠ "HARDER LOPEN": een hartslag die (nog) onder de doelzone ligt, zeker
   vroeg in een intervaltraining of in het eerste werkblok, is op zichzelf GEEN bewijs dat de atleet
   harder had moeten lopen (hartslag-lag, warming-up, korte blokduur spelen mee). Trek geen blanket
   fysiologische conclusie; benoem het feit en houd interpretatie voorzichtig. Warming-up en
   herstelblokken beoordeel je NOOIT alsof het targetblokken zijn.
9. GEEN ONNODIGE CORRECTIE BINNEN HET GEPLANDE BEREIK (niet onderhandelbaar):
   Meldt de app IN_ZONE, dan is de intensiteit in principe correct uitgevoerd — punt. Dicht bij een
   zonegrens lopen (net aan de snelle of langzame kant) is op zichzelf GEEN probleem en NOOIT een
   reden voor een waarschuwing of "let op"-punt. Een zonegrens is GEEN veiligheidsmarge waar de
   atleet bewust ruim vandaan moet blijven; verzin daarom NOOIT een corrigerende instructie als
   "bewaak het tempo de hele rit", "houd het volgende keer wat rustiger" of "let dat je niet over de
   grens gaat" wanneer de uitvoering binnen de zone valt. Formuleer alléén een aandachtspunt bij
   ECHT deterministisch bewijs: de app meldt AANTOONBAAR 'BUITEN de persoonlijke zones', aantoonbare
   structurele drift, een afwijking van de geplande workout-opbouw, óf de atleet meldt zelf dat het
   te zwaar voelde (hoge RPE / slecht gevoel). Zonder zulk bewijs bevestig je de goede uitvoering en
   laat je het daarbij — maak van een correct gelopen training geen probleem.
   GEPLANDE PROGRESSIE: gaat de workout bewust van een lichtere naar een zwaardere zone (bijv. Z1 →
   Z2), dan is die zwaardere zone GEPLAND en dus GOED — frame Z2 daar NOOIT als afwijking of "te
   hard". Beoordeel elk segment tegen het GEPLANDE target van DAT blok, nooit tegen de zone van een
   ander blok.
10. GEEN ONGEGRONDE HOEVEELHEIDSCLAIMS OVER DE HELE TRAINING (niet onderhandelbaar):
   Uitspraken als "de meeste kilometers", "het grootste deel", "bijna alles", "de rest liep je in
   Zx", "de hele training in zone X" of "het gemiddelde lag onder/boven target" mag je ALLEEN doen
   als ze deterministisch onderbouwd zijn door een aangeleverde ZONEVERDELING (percentages/afstand
   per zone) of het door de app berekende gemiddelde ('BEREKENDE POSITIE'). Leid zo'n samenvatting
   NOOIT zelf af uit de losse per-lap-labels of het ruwe verloop — die labels zijn per lap, geen
   sessieverdeling. Staat er geen zoneverdeling en geen berekend gemiddelde, doe dan geen
   kwantitatieve zone-uitspraak over de hele training; beschrijf hooguit concrete losse laps.
   Bij een gestructureerde interval-/blokkentraining beoordeel je PER BLOK (zie BLOK-ANALYSE), niet
   via een sessie-brede dominante zone: warming-up, herstel en cooldown kunnen die dominante zone
   bepalen en zijn dan misleidend.

PLAN VS UITVOERING:
Als er een geplande structuur beschikbaar is (workout builder), vergelijk dan ACTIEF de uitvoering daarmee. Was het geplande tempo gehaald? Liep de atleet in de geplande zone? Dat is het meest waardevolle wat je kunt zeggen."""


def _seconds_to_min(seconds) -> str:
    if not seconds:
        return "—"
    try:
        s = int(float(seconds))
        return f"{s // 60}:{s % 60:02d}"
    except (ValueError, TypeError):
        return str(seconds)


def _format_activity(activity: dict) -> str:
    lines = []

    dist = activity.get("amount")
    dist_planned = activity.get("planned_amount")
    if dist or dist_planned:
        unit = activity.get("amount_type", "km")
        lines.append(f"Afstand: gepland {dist_planned or '—'} {unit} | uitgevoerd {round(dist, 2) if dist else '—'} {unit}")

    dur = activity.get("duration")
    dur_planned = activity.get("planned_duration")
    if dur or dur_planned:
        lines.append(f"Tijd: gepland {_seconds_to_min(dur_planned)} | uitgevoerd {_seconds_to_min(dur)}")

    pace = activity.get("pace_display")
    if pace:
        unit = activity.get("pace_display_type", "min/km")
        lines.append(f"Pace: {pace} {unit}")

    hr = activity.get("hr_avg")
    hr_max = activity.get("hr_max")
    if hr:
        lines.append(f"Gem. HF: {hr} bpm (max {hr_max} bpm)" if hr_max else f"Gem. HF: {hr} bpm")

    power = activity.get("power_avg")
    if power:
        lines.append(f"Gem. vermogen: {power} W")

    return "\n".join(lines) if lines else "Geen metrics beschikbaar."


def _lap_zone_label(cls: dict, is_pace: bool) -> str:
    """Class 2 — korte, DETERMINISTISCHE per-lap zonelabel uit `classify_pace_hr_zone`. Alleen
    bij ECHTE membership een 'Zx'; out-of-range wordt als feit benoemd (sneller/langzamer/hoger/
    lager dan de dichtstbijzijnde zone), NOOIT als valse membership. Leeg bij UNKNOWN."""
    if not cls:
        return ""
    st = cls.get("status")
    if st == "IN_ZONE":
        return f"Z{cls['num']}"
    if st == "ABOVE_HARDEST_ZONE":
        kant = "sneller dan" if is_pace else "hoger dan"
        return f"{kant} Z{cls['nearest_num']}, BUITEN de zones"
    if st == "BELOW_EASIEST_ZONE":
        kant = "langzamer dan" if is_pace else "lager dan"
        return f"{kant} Z{cls['nearest_num']}, BUITEN de zones"
    if st == "BETWEEN_ZONES":
        return f"tussen zones (dichtstbij Z{cls['nearest_num']}), BUITEN de banden"
    return ""


def _format_laps(laps: list, zones: list | None = None, is_pace: bool | None = None) -> str:
    """Vat lap-data samen: tempo, hartslag en cadans per km/interval.

    Class 2: als `zones` + `is_pace` gegeven zijn (de PRIMAIRE metric is deterministisch te
    classificeren), krijgt elke lap zijn zone-label uit de bestaande canonical classifier
    (`fs_client.classify_pace_hr_zone`) — de AI ontvangt zo een FEIT per lap i.p.v. een
    uitnodiging om zelf `pace ↔ zonegrens` te berekenen. De secundaire metric blijft een ruw
    getal zonder oordeel. Zonder classificatiecontext = ongewijzigd gedrag (ruwe getallen)."""
    if not laps:
        return ""
    can_classify = bool(zones) and is_pace is not None
    if can_classify:
        import fs_client as _fs

    rows = []
    for i, lap in enumerate(laps[:20], 1):  # max 20 laps
        if not isinstance(lap, dict):
            continue
        pace = lap.get("pace_display") or ""
        hr = lap.get("hr_avg")
        cadence = lap.get("cadence_avg")
        dist = lap.get("distance_display") or lap.get("amount") or ""

        parts = []
        if pace:
            parts.append(f"tempo {pace}")
        if hr:
            parts.append(f"HF {hr} bpm")
        if cadence:
            parts.append(f"cadans {cadence}")

        if not parts:
            continue
        label = f"Km {i}" if not dist else f"{dist}"
        regel = f"  {label}: {', '.join(parts)}"
        if can_classify:
            cls = None
            if is_pace:
                _pm = _fs._pace_to_float(pace)
                _sec = _pm * 60 if _pm not in (0, float("inf")) else None
                if _sec:
                    cls = _fs.classify_pace_hr_zone(zones, _sec, is_pace=True)
            else:
                try:
                    _h = float(hr) if hr else None
                except (TypeError, ValueError):
                    _h = None
                if _h:
                    cls = _fs.classify_pace_hr_zone(zones, _h, is_pace=False)
            lab = _lap_zone_label(cls, bool(is_pace))
            if lab:
                regel += f" → {lab} (door de app bepaald)"
        rows.append(regel)

    return "\n".join(rows) if rows else ""


def _format_builder_steps(steps: list) -> str:
    """
    Formatteer de geplande workout structuur vanuit WorkoutBuilderGet.
    Geeft een leesbare samenvatting terug zoals '8 km zone 1 → 2 km zone 2'.
    """
    if not steps:
        return ""

    parts = []
    for step in steps:
        if not isinstance(step, dict):
            continue

        intensity = (step.get("intensity") or "").upper()
        if intensity == "REST":
            parts.append("rust")
            continue

        duration_type = (step.get("durationType") or "").upper()
        dist = step.get("durationDist")
        dist_unit = step.get("distUnit") or "km"
        duration_str = step.get("duration") or ""

        # Bepaal duur/afstand
        if duration_type == "DISTANCE" and dist:
            dist_clean = int(dist) if dist == int(dist) else dist
            dur_label = f"{dist_clean} {dist_unit}"
        elif duration_str and duration_str != "00:00":
            dur_label = f"{duration_str} min"
        else:
            dur_label = "?"

        # Zoek de primaire target (niet 'open')
        targets = step.get("target") or []
        zone_label = ""
        for t in targets:
            if not isinstance(t, dict):
                continue
            target_type = t.get("targetType") or ""
            zone = t.get("zone")
            if "zone" in target_type and zone:
                type_name = "zone" if "pace" in target_type else "HF-zone"
                zone_label = f"{type_name} {zone}"
                break
            elif target_type not in ("open", "") and t.get("targetLow") and t.get("targetHigh"):
                low = t.get("targetLow")
                high = t.get("targetHigh")
                zone_label = f"{low}–{high}"
                break

        name = step.get("name") or step.get("comments") or ""

        if zone_label:
            parts.append(f"{dur_label} {zone_label}")
        elif name:
            parts.append(f"{dur_label} ({name})")
        else:
            parts.append(dur_label)

    if not parts:
        return ""
    return "Geplande structuur: " + " → ".join(parts)


def _zone_regel_tekst(waarde_str: str, cls: dict, is_pace: bool) -> str:
    """FC-2: eerlijke 'BEREKENDE ZONE'-regel uit `classify_pace_hr_zone` — alleen bij ECHTE
    membership (IN_ZONE) een zone-label; out-of-range wordt als feit benoemd, NOOIT als zone."""
    if not cls:
        return ""
    st = cls.get("status")
    if st == "IN_ZONE":
        return (f"Gemiddeld over de hele training: {waarde_str} = Zone {cls['num']} "
                f"({cls['naam']}) — BINNEN de persoonlijke zone.")
    eenheid = "sec/km" if is_pace else "bpm"
    if st == "ABOVE_HARDEST_ZONE":
        kant = "SNELLER dan de snelste persoonlijke zone" if is_pace else "HOGER dan de hoogste persoonlijke zone"
        return (f"Gemiddeld over de hele training: {waarde_str} — {kant} "
                f"(dichtstbij Z{cls['nearest_num']}, ~{cls['delta']:g} {eenheid} voorbij de grens). "
                f"Dit ligt BUITEN de persoonlijke zones — behandel het NIET als 'Zone {cls['nearest_num']}'.")
    if st == "BELOW_EASIEST_ZONE":
        kant = "LANGZAMER dan de langzaamste persoonlijke zone" if is_pace else "LAGER dan de laagste persoonlijke zone"
        return (f"Gemiddeld over de hele training: {waarde_str} — {kant} "
                f"(dichtstbij Z{cls['nearest_num']}, ~{cls['delta']:g} {eenheid} voorbij de grens). "
                f"BUITEN de persoonlijke zones — geen exacte zone.")
    if st == "BETWEEN_ZONES":
        return (f"Gemiddeld over de hele training: {waarde_str} — valt in een gat tussen de "
                f"persoonlijke zones (dichtstbij Z{cls['nearest_num']}); BUITEN de banden, geen exacte zone.")
    return ""


def _format_block_assessment(assessment: dict, first_name: str) -> str:
    """FC-2: deterministische BLOK-ANALYSE naar prompttekst. MATCHED → per-blok feit + status
    (WARMUP/REST niet als targetblok; HR-lag-caveat bij eerste werkblok onder target);
    AMBIGUOUS/PARTIAL → expliciet 'niet betrouwbaar te koppelen'; UNAVAILABLE → niets."""
    if not assessment:
        return ""
    conf = assessment.get("confidence")
    if conf == "UNAVAILABLE":
        return ""
    if conf in ("AMBIGUOUS", "PARTIAL"):
        return ("\n\nBLOK-ANALYSE (door de app bepaald): de geplande blokken en de uitgevoerde "
                "laps zijn NIET betrouwbaar één-op-één te koppelen (blokmatch onvoldoende "
                "betrouwbaar). Beoordeel hartslag/tempo daarom NIET hard per blok; gebruik het "
                "verloop hooguit als globale indruk.")
    blocks = assessment.get("blocks") or []
    if not blocks:
        return ""
    eerste_active = next((b["index"] for b in blocks
                          if b["type"] not in ("WARMUP", "REST", "COOLDOWN")), None)
    regels = []
    for b in blocks:
        t = b["type"]
        if t == "WARMUP":
            regels.append(f"- Warming-up (blok {b['index']}): geen harde target-evaluatie.")
            continue
        if t in ("REST", "COOLDOWN"):
            naam = "Herstel" if t == "REST" else "Cooldown"
            regels.append(f"- {naam} (blok {b['index']}): herstelblok, niet beoordelen op target-tempo/HF.")
            continue
        if b["metric"] == "hr":
            obs = f"HF {b['observed_hr']} bpm" if b.get("observed_hr") else "geen HF-meetwaarde"
        else:
            obs = f"tempo {b['observed_pace']}" if b.get("observed_pace") else "geen tempo-meetwaarde"
        doel = f"doel Z{b['target_zone']}" if b.get("target_zone") else "geen doelzone"
        status_tekst = {
            "ON_TARGET": "in target",
            "ABOVE_TARGET": "boven target (harder dan gepland)",
            "BELOW_TARGET": "onder target",
            "UNKNOWN": "geen betrouwbare targetvergelijking",
            "NOT_EVALUATED": "niet beoordelen",
        }.get(b["status"], "onbekend")
        regel = f"- Werkblok {b['index']} (ACTIVE, {doel}): {obs} — {status_tekst}."
        if b["status"] == "BELOW_TARGET" and b["index"] == eerste_active:
            regel += (" Let op: vroeg in een intervaltraining is de hartslag nog niet op peil "
                      "(hartslag-lag); onder target in dit eerste blok is op zichzelf GEEN bewijs "
                      "dat harder gelopen had moeten worden.")
        regels.append(regel)
    return ("\n\nBLOK-ANALYSE (door de app bepaald — deterministisch, per gematcht blok):\n"
            + "\n".join(regels)
            + "\nBeoordeel elk werkblok apart; één blok onder target is geen totaaloordeel. "
            "Warming-up/herstel zijn geen targetblokken.")


def _dominant_planned_metric(planned_blocks: list) -> str | None:
    """Class 2 — de EXPLICIET geplande target-metric van de workout, uit de bestaande
    `_planned_blocks[].metric` (afgeleid van `targetType`). Eén eenduidige metric over de
    blokken → die metric ('tempo'/'hartslag'); gemengd of geen → None (dan geldt de athlete-
    zonetype-fallback). Geen nieuwe classifier, geen zone-math — puur de geplande target lezen."""
    metrics = {b.get("metric") for b in (planned_blocks or []) if b.get("metric")}
    if metrics == {"tempo"}:
        return "tempo"
    if metrics == {"hartslag"}:
        return "hartslag"
    return None


def _zone_distribution(laps: list, zones: list, is_pace) -> str:
    """DETERMINISTISCHE zoneverdeling over de HELE training: het aandeel per persoonlijke zone,
    o.b.v. de bestaande per-lap-classificatie (`classify_pace_hr_zone`) — GEEN nieuwe zone-math.
    Elke lap weegt mee met zijn afstand (aandelen zijn eenheid-onafhankelijk); ontbreekt de
    afstand overal, dan telt elke lap even zwaar. Zo hoeft de AI 'de meeste km in Zx' niet uit
    het ruwe verloop te raden (dé bron van de audit-overclaims). Leeg bij < 2 bruikbare laps."""
    if not laps or not zones or is_pace is None:
        return ""
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
        return ""

    def _order(k):
        return (1, 99) if k == "buiten de zones" else (0, int(k[1:]))

    parts = [f"{k} {round(v / tot * 100)}%" for k, v in sorted(per.items(), key=lambda kv: _order(kv[0]))]
    eenheid = "afstand" if any_dist else "laps"
    return (f"ZONEVERDELING (deterministisch — aandeel van de {eenheid} per zone, o.b.v. de laps): "
            + ", ".join(parts) + ". "
            "Gebruik UITSLUITEND deze verdeling (of het berekende gemiddelde) voor een "
            "'meeste/grootste deel/de rest/bijna alles'-uitspraak; leid zulke claims nooit zelf "
            "af uit het losse lap-verloop.")


def _build_workout_context(workout_data: dict) -> tuple[str, str]:
    """
    Bouw de workout-context op voor de AI.
    Geeft terug: (context_prompt, first_name)
    """
    import fs_client as _fs

    first_name = workout_data.get("athlete_first_name") or workout_data["athlete_name"].split()[0]
    workout_name = workout_data["workout_name"]
    post_notes = workout_data["post_notes"]
    athlete_comments = workout_data.get("athlete_comments", [])
    details = workout_data.get("details") or {}
    workout_key = workout_data.get("workout_key", "")
    athlete_key = workout_data.get("athlete_key", "")

    plan_description = details.get("description") or ""
    activities = details.get("Activities") or []

    # Voor race-workouts: controleer of er een snellere activiteit op dezelfde dag is.
    # Atleten doen vaak wu → race → cd als losse activiteiten; de wu wordt soms
    # ten onrechte gezien als de race-uitvoering (eerste activiteit van de dag).
    workout_date = workout_data.get("workout_date", "")
    is_race = workout_data.get("details", {}).get("is_race") or False
    if athlete_key and workout_date and activities:
        try:
            fastest_act = _fs.get_fastest_activity_on_day(athlete_key, workout_date)
            if fastest_act:
                current_pace = _fs._pace_to_float(activities[0].get("pace_display") or "")
                fastest_pace = _fs._pace_to_float(fastest_act.get("pace_display") or "")
                if fastest_pace < current_pace * 0.85:
                    activities = [fastest_act]
        except Exception:
            pass

    activity_summary = _format_activity(activities[0]) if activities else "Geen data beschikbaar."
    laps = activities[0].get("Laps", []) if activities else []
    # lap_summary wordt PAS gebouwd zodra de primaire metric bekend is (Class 2: per-lap
    # deterministische classificatie), zie hieronder.

    # DETERMINISTISCHE AFSTANDSAFWIJKING (vóór AI) — de app bepaalt de band, de AI
    # niet. <10% mag NOOIT als feedbackpunt lekken; 10–20% neutraal benoembaar;
    # >=20% benoembaar maar nooit automatisch negatief. Geünificeerd met de centrale
    # band (feedback_core.afwijking == brain.derive-semantiek).
    # Afstandsafwijking op de CANONIEKE primaire activiteit (dezelfde bron als
    # feedback_core.detail → coach-zichtbaar), NIET op de eventueel geswapte
    # snelste-activiteit (die swap is voor race-tempo, niet voor afstand). Zo kan
    # de prompt nooit een andere afwijking claimen dan de coach in de UI ziet.
    deviation_section = ""
    _orig_acts = details.get("Activities") or []
    if _orig_acts:
        try:
            from feedback_core import afwijking as _afw
            _act0 = _orig_acts[0]
            _dev = _afw(_act0.get("planned_amount"), _act0.get("amount"))
        except Exception:
            _dev = {"relevance": "n/a"}
        rel = _dev.get("relevance")
        if rel == "ignore":
            deviation_section = (
                "\n\nAFSTANDSAFWIJKING (door de app bepaald — LEIDEND): de uitgevoerde "
                "afstand ligt binnen 10% van de geplande afstand. Dat is normaal en NIET "
                "de moeite van het benoemen waard. Schrijf hier NIETS over; maak er geen "
                "punt van dat het net iets meer of minder was.")
        elif rel == "notable":
            deviation_section = (
                f"\n\nAFSTANDSAFWIJKING (door de app bepaald — LEIDEND): de afstand wijkt "
                f"{_dev['pct']:+.0f}% af van gepland. Je mág dit kort en neutraal benoemen, "
                f"maar maak er GEEN probleem van als gevoel, RPE en uitvoering goed zijn.")
        elif rel == "clear":
            deviation_section = (
                f"\n\nAFSTANDSAFWIJKING (door de app bepaald — LEIDEND): de afstand wijkt "
                f"{_dev['pct']:+.0f}% af van gepland. Dit mag je benoemen, maar beoordeel het "
                f"NIET automatisch negatief; weeg wat de atleet schrijft en de context mee.")

    builder_steps_text = ""
    builder_steps_raw = []
    if details.get("has_structured_workout") and workout_key and athlete_key:
        try:
            builder_steps_raw = _fs.get_workout_builder(workout_key, athlete_key)
            builder_steps_text = _format_builder_steps(builder_steps_raw)
        except Exception:
            pass

    athlete_zones_text = ""
    athlete_zone_type = ""   # "tempo" | "hartslag" | ""
    athlete_zones_struct = []
    if athlete_key:
        try:
            zones_result = _fs.get_athlete_zones(athlete_key)
            if "zones_text" in zones_result:
                athlete_zone_type = zones_result.get("zone_type", "")   # "tempo" of "hartslag"
                athlete_zones_struct = zones_result.get("zones", [])
                zone_type_label = "tempo (min/km)" if athlete_zone_type == "tempo" else "hartslag (bpm)"
                athlete_zones_text = f"Zones ({zone_type_label}):\n{zones_result['zones_text']}"
        except Exception:
            pass

    # ── PLANNED-METRIC PRECEDENCE (Class 2) ──────────────────────────────────
    # We classificeren ALTIJD de metric waarvoor deze atleet een zonetabel heeft
    # (`athlete_zone_type`) — per lap én het gemiddelde — via de bestaande canonical classifier,
    # zodat ruwe pace/HF nooit zonder deterministisch label naast de zonegrenzen staat.
    # LOS daarvan bepaalt de EXPLICIET geplande target-metric welke metric LEIDEND is voor de
    # beoordeling (`planned metric → athlete zone type fallback`). Matcht de geplande metric de
    # zonetabel → de labels zijn de primaire beoordeling. Wijkt hij af (bv. pace-target +
    # HR-zone-atleet) → de labels blijven deterministische FEITEN, maar van de SECUNDAIRE metric:
    # alleen neutrale observatie, nooit de beoordelingsbasis; primair wordt via de geplande metric
    # versus het plan beoordeeld. Geen tweede classifier, geen zone-math in ai_feedback.
    _planned_metric = _dominant_planned_metric(_fs._planned_blocks(builder_steps_raw))
    primary_metric = _planned_metric or athlete_zone_type or ""
    _can_classify = bool(athlete_zones_struct) and athlete_zone_type in ("tempo", "hartslag")
    _classified_is_pace = (athlete_zone_type == "tempo")
    _metrics_match = _can_classify and bool(primary_metric) and primary_metric == athlete_zone_type

    # BEREKENDE ZONE — deterministisch + EERLIJK uit de zonetabel (FC-2): een out-of-range
    # gemiddelde wordt als feit benoemd, NOOIT als valse zonemembership (dé oorzaak van
    # 147 bpm als Z1, en van 3:53/km dat als Z3 werd gepresenteerd). Class 2: altijd de
    # zonetabel-metric classificeren; of het gemiddelde LEIDEND dan wel neutraal is, bepaalt de
    # framing (zie `berekend_blok`), niet óf het geclassificeerd wordt.
    berekende_zone_regel = ""
    if _can_classify and activities:
        _act = activities[0]
        if athlete_zone_type == "hartslag":
            _hr = _act.get("hr_avg")
            try:
                _hr = float(_hr) if _hr else None
            except (TypeError, ValueError):
                _hr = None
            if _hr:
                _cls = _fs.classify_pace_hr_zone(athlete_zones_struct, _hr, is_pace=False)
                berekende_zone_regel = _zone_regel_tekst(f"{int(_hr)} bpm", _cls, is_pace=False)
        elif athlete_zone_type == "tempo":
            _pace_min = _fs._pace_to_float(_act.get("pace_display") or "")
            _pace_sec = _pace_min * 60 if _pace_min not in (0, float("inf")) else None
            if _pace_sec:
                _cls = _fs.classify_pace_hr_zone(athlete_zones_struct, _pace_sec, is_pace=True)
                berekende_zone_regel = _zone_regel_tekst(
                    f"{_act.get('pace_display')} min/km", _cls, is_pace=True)

    # BLOK-ANALYSE — deterministische planned-block ↔ executed-lap koppeling met confidence.
    # (PF-4: de assessment-dict wordt ook hergebruikt om het whole-workout-OORDEEL te scopen;
    #  de classifier/block-mapping zelf blijft ONGEWIJZIGD — FC-2 locked.)
    _block_assessment = _fs.assess_workout_blocks(
        builder_steps_raw, laps, athlete_zones_struct, athlete_zone_type)
    blok_section = _format_block_assessment(_block_assessment, first_name)

    felt = workout_data.get("felt")
    effort = workout_data.get("effort")

    # FinalSurge: felt = 1-5 waarbij 1=Geweldig en 5=Vreselijk (lager = beter)
    # effort = 1-10 waarbij 10=Max inspanning
    _FELT_LABELS = {"1": "Geweldig", "2": "Goed", "3": "Normaal", "4": "Slecht", "5": "Vreselijk"}

    athlete_input_parts = []
    if felt or effort:
        rating_parts = []
        if felt:
            felt_key = str(felt).split(".")[0]  # "2.0" → "2"
            felt_label = _FELT_LABELS.get(felt_key, str(felt))
            rating_parts.append(f"Gevoel: {felt_label} ({felt_key}/5 — schaal 1=Geweldig t/m 5=Vreselijk)")
        if effort:
            rating_parts.append(f"Inspanning (RPE): {effort}/10 (1=zeer makkelijk, 10=maximaal)")
        athlete_input_parts.append(" | ".join(rating_parts))
    if post_notes:
        athlete_input_parts.append(post_notes)
    for comment in athlete_comments:
        if comment.strip():
            athlete_input_parts.append(comment)
    athlete_input = "\n".join(athlete_input_parts) if athlete_input_parts else "(geen notities van de atleet)"

    # Class 2 — bouw het lap-verloop met per-lap DETERMINISTISCHE classificatie van de
    # zonetabel-metric (indien beschikbaar). Zo staat rauwe pace/HF nooit los naast de
    # zonegrenzen zonder label. De framing (primair vs neutraal-secundair) volgt de geplande metric.
    lap_summary = _format_laps(
        laps,
        zones=athlete_zones_struct if _can_classify else None,
        is_pace=(_classified_is_pace if _can_classify else None))
    if lap_summary:
        if _can_classify and _metrics_match:
            _lap_kop = ("Verloop per km/interval — elke lap is door de app DETERMINISTISCH "
                        "geclassificeerd (label na '→'). Neem die labels letterlijk over; reken "
                        "tempo/HF NIET zelf tegen de zonegrenzen. De labels zijn PER LAP, niet per "
                        "blok — generaliseer ze niet naar 'alle blokken waren Zx'.")
        elif _can_classify:  # mismatch: labels = secundaire metric, neutrale feiten
            _lap_kop = (f"Verloop per km/interval — het label na '→' is de DETERMINISTISCHE "
                        f"{athlete_zone_type}-zone per lap (de SECUNDAIRE metric): een neutraal FEIT, "
                        f"NIET de beoordelingsbasis. Reken zelf niets uit; beoordeel primair via "
                        f"{primary_metric}. Labels zijn per lap, niet per blok.")
        else:
            _lap_kop = "Verloop per km/interval (tempo, hartslag, cadans):"
        lap_section = f"\n{_lap_kop}\n{lap_summary}"
    else:
        lap_section = ""

    # P1 — deterministische zoneverdeling over de hele training (aandeel per zone), zodat een
    # 'meeste km in Zx'-samenvatting op een FEIT rust i.p.v. op een gok uit het lap-verloop.
    zone_dist_text = _zone_distribution(laps, athlete_zones_struct, _classified_is_pace) if _can_classify else ""
    zone_dist_section = f"\n\n{zone_dist_text}" if zone_dist_text else ""

    plan_parts = []
    if plan_description.strip():
        plan_parts.append(plan_description.strip()[:600])
    if builder_steps_text:
        plan_parts.append(builder_steps_text)
    plan_text = "\n\n".join(plan_parts) if plan_parts else "Geen beschrijving."

    # P1 — onverwachte/extra training: geen geplande structuur om tegen te vergelijken. Deterministisch
    # uit dezelfde plandata (spiegelt fs_client.is_planned_workout); relevant bij belasting/herstel.
    _has_plan = bool(details.get("has_structured_workout") or plan_description.strip()
                     or details.get("planned_amount") or details.get("planned_duration")
                     or any((a or {}).get("planned_amount") or (a or {}).get("planned_duration")
                            for a in activities))
    unplanned_section = "" if _has_plan else (
        "\n\nGEPLAND VS UITVOERING: deze training was NIET vooraf gepland (extra/los). Er is dus geen "
        "geplande structuur om tegen af te zetten; beoordeel op de uitvoering en op wat de atleet "
        "schrijft. Was het een extra/pittige inspanning én staat er een verhoogd belasting-/herstel"
        "signaal of een zware sessie kort erna (zie context), weeg dat dan mee — maak van een extra "
        "training op zich geen probleem.")

    if athlete_zones_text:
        # PRIMARY-METRIC PRECEDENCE (Class 2): de expliciet geplande metric is leidend; de AI mag
        # die niet verdringen door een secundaire metric. Is de zonetabel van dezelfde metric als
        # de primaire → de app classificeert deterministisch (per lap + gemiddelde) en de AI neemt
        # dat letterlijk over. Wijkt de zonetabel af (zones alleen voor de secundaire metric) → de
        # primaire metric NIET op die zones mappen; secundair blijft neutrale observatie.
        _prim = primary_metric or athlete_zone_type
        _sec_label = "hartslag" if _prim == "tempo" else "tempo"
        if _metrics_match:
            zone_instruction = (
                f"{_prim.upper()}-ZONES VAN {first_name.upper()} — beoordeel de intensiteit PRIMAIR via "
                f"{_prim}. De app heeft elke lap én het gemiddelde al DETERMINISTISCH geclassificeerd; "
                f"neem die labels letterlijk over en reken {_prim} NIET zelf tegen de zonegrenzen. "
                f"{_sec_label.capitalize()} mag alleen als neutraal getal (bijv. 'HF 148 bpm'), NOOIT met "
                f"een oordeel of zone-label; ontbrekende/matige {_sec_label}-data mag het {_prim}-oordeel "
                f"nooit verdringen."
            )
        elif _can_classify:
            zone_instruction = (
                f"LET OP — de GEPLANDE target-metric is {_prim.upper()}, maar {first_name} heeft alleen "
                f"{athlete_zone_type}-zones (de SECUNDAIRE metric). Beoordeel PRIMAIR via {_prim}: vergelijk "
                f"de uitgevoerde {_prim}-waarden met het plan. De onderstaande {athlete_zone_type}-zones en de "
                f"per-lap-/gemiddelde-labels zijn deterministische FEITEN, maar alléén als neutrale "
                f"observatie — gebruik ze NIET om de intensiteit te beoordelen en map {_prim} er niet op. "
                f"Ontbrekende/matige {athlete_zone_type}-data mag nooit maken dat je {_prim} niet beoordeelt; "
                f"beoordeel dus nooit 'alleen op {athlete_zone_type}'."
            )
        else:
            zone_instruction = f"ZONES VAN {first_name.upper()} — gebruik ALLEEN deze waarden, niet je eigen aannames."
        # De app heeft de zone/positie van het gemiddelde al deterministisch bepaald.
        # Die is LEIDEND; de AI mag niet zelf opnieuw indelen (LLM's tellen fout). Staat er
        # 'BUITEN de persoonlijke zones', dan is dat GEEN zone — behandel het als feit, niet
        # als membership, en niet automatisch als fout of goed (FC-2).
        berekend_blok = ""
        if berekende_zone_regel:
            # PF-4 — HR/zone output-contract, STRUCTURE-AWARE. Het whole-workout gemiddelde
            # blijft altijd een FEIT, maar mag bij een gestructureerde interval-/blokkentraining
            # NOOIT op zichzelf bewijzen dat de geplande werkblokken hun target haalden
            # (warming-up/herstel drukken het gemiddelde). Alleen bij een CONTINUE training is
            # het gemiddelde de passende evaluatiemaat → daar blijft het bestaande OORDEEL staan.
            # Structuur-signaal = ≥2 geplande blokken (bewezen FC-2-helper, read-only; geen
            # classifier/mapping-wijziging). Confidence scopet de formulering verder.
            _conf = (_block_assessment or {}).get("confidence")
            try:
                _is_structured = len(_fs._planned_blocks(builder_steps_raw)) >= 2
            except Exception:
                _is_structured = False
            if _metrics_match:
                _kop = (
                    f"\n\nBEREKENDE POSITIE (door de app bepaald uit de zonetabel — LEIDEND, "
                    f"neem letterlijk over, deel NIET zelf opnieuw in):\n"
                    f"{berekende_zone_regel}\n"
                    f"Zeg alleen 'binnen zone Zx' of 'past bij Zx' als hierboven ECHTE membership "
                    f"(IN_ZONE) staat. Staat er 'BUITEN de persoonlijke zones', benoem dan het feit "
                    f"(bijv. sneller dan de zonegrens) maar plak er GEEN zone-label op.\n")
            else:
                # Mismatch: het gemiddelde is van de SECUNDAIRE metric — een feit, geen oordeelsbasis.
                _kop = (
                    f"\n\nBEREKENDE POSITIE van de SECUNDAIRE metric ({athlete_zone_type}) — door de app "
                    f"bepaald, neem letterlijk over (deel NIET zelf in), maar dit is een NEUTRALE "
                    f"observatie, NIET de beoordelingsbasis. Beoordeel primair via {_prim}:\n"
                    f"{berekende_zone_regel}\n")
            if _is_structured:
                _oordeel = (
                    "Let op: dit is een gestructureerde interval-/blokkentraining. Het gemiddelde "
                    "over de héle training is een FEIT (warming-up en herstel tellen mee), maar "
                    "bewijst NIET of de geplande werkblokken hun target haalden. Concludeer op basis "
                    "van DIT gemiddelde daarom NOOIT dat de training 'correct uitgevoerd' is, en "
                    "evenmin dat er 'te hard' of 'te zacht' is gelopen.")
                if _conf == "MATCHED":
                    _oordeel += (" Gebruik de BLOK-ANALYSE hieronder als leidende beoordeling per "
                                 "werkblok; het gemiddelde is hooguit aanvullende context.")
                else:  # AMBIGUOUS / PARTIAL / UNAVAILABLE → geen betrouwbare per-blok-truth
                    _oordeel += (" De geplande blokken zijn niet betrouwbaar te koppelen aan de "
                                 "uitgevoerde laps, dus of de werkblokken hun target haalden is "
                                 "hiermee NIET vast te stellen; benoem het gemiddelde hooguit als "
                                 "observatie.")
            else:
                _oordeel = (
                    "Let op: dit is het gemiddelde over de héle training (een continue inspanning). "
                    "Valt dit gemiddelde ECHT binnen de bedoelde/geplande zone, dan is de training "
                    "correct uitgevoerd — schrijf dan NIET 'te hard' of 'te zacht', en verzin evenmin "
                    "een correctie als 'bewaak het tempo' omdat het dicht bij een zonegrens lag: binnen "
                    "de zone is binnen de zone. Alleen bij ECHT bewijs (de app meldt BUITEN de zone, "
                    "structurele drift, of de atleet meldt hoge RPE) mag je een aandachtspunt maken.")
            berekend_blok = _kop + _oordeel
        zones_section = f"\n\n{zone_instruction}\n{athlete_zones_text}{berekend_blok}{blok_section}"
    else:
        zones_section = (
            f"\n\n⚠️ GEEN zones beschikbaar voor {first_name}. "
            f"Noem ruwe getallen (tempo in min/km, HF in bpm) maar hang er NOOIT een oordeel of zone-label aan. "
            f"Zeg NOOIT dat iets 'hoog', 'te hard' of 'in zone X' was."
        )

    # Garmin-herstelstatus (alleen als de hardloopcoach-app die publiceerde voor
    # deze atleet; anders leeg -> prompt en gedrag ongewijzigd).
    garmin_context = intake_store.garmin_context_text(athlete_key)
    garmin_section = f"\n\n{garmin_context}" if garmin_context else ""

    # Datum-context: de atleet schreef rond de trainingsdatum, jij reageert
    # vandaag. Voorkomt dat 'morgen'/'vandaag' uit de notitie verkeerd wordt
    # overgenomen en dat de AI een vooruitblik verzint.
    _today = date.today()
    _maanden = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
                "augustus", "september", "oktober", "november", "december"]
    _weekdagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    _vandaag_weekdag = _weekdagen[_today.weekday()]
    today_str = f"{_vandaag_weekdag} {_today.day} {_maanden[_today.month - 1]} {_today.year}"
    dag_info = ""
    _train_weekdag = ""
    try:
        _wd = date.fromisoformat((workout_date or "")[:10])
        _train_weekdag = _weekdagen[_wd.weekday()]
        _gap = (_today - _wd).days
        if _gap <= 0:
            dag_info = "Je reageert op de dag van de training zelf."
        elif _gap == 1:
            dag_info = f"De training was gisteren ({_train_weekdag}); je reageert vandaag ({_vandaag_weekdag})."
        else:
            dag_info = f"De training was {_gap} dagen geleden ({_train_weekdag}); je reageert vandaag ({_vandaag_weekdag})."
    except ValueError:
        pass

    # Feedback v1 (A): huidige weekdag is expliciet onderdeel van de context, en relatieve
    # dagwoorden uit de atleet worden tegen VANDAAG geïnterpreteerd. Zo wordt een afsluiting
    # over "zondag" (uit een training van gisteren) op maandag NIET als actuele wens geëchood.
    datum_section = (
        f"\n\nDATUM-CONTEXT:\n"
        f"Trainingsdatum: {workout_date or 'onbekend'}"
        + (f" ({_train_weekdag})" if _train_weekdag else "") + "\n"
        f"Vandaag (wanneer jij reageert): {today_str}\n"
        f"{dag_info}\n"
        f"Let op: een weekdag of tijdsaanduiding in de woorden van de atleet (zoals 'zondag', "
        f"'morgen', 'vandaag') hoort bij de TRAININGSDATUM, niet bij vandaag. Reken die eerst om "
        f"tegen vandaag ({today_str}) voordat je reageert. Een dag die al voorbij is (bijv. de "
        f"atleet schrijft 'op naar zondag' terwijl het vandaag al {_vandaag_weekdag} is) mag je "
        f"NIET als actuele afsluiting of vooruitblik echoën; reageer op de inhoud, niet op het tijdstip."
    )

    # Coach-geheugen: wat we uit eerdere gesprekken over deze atleet weten
    profiel = (workout_data.get("coach_profiel") or "").strip()
    profiel_section = (
        f"\n\nWAT JE WEET OVER {first_name.upper()} (opgebouwd uit eerdere gesprekken):\n"
        f"{profiel}\n"
        f"Gebruik dit voor toon en context. Herhaal het niet letterlijk terug, "
        f"verzin er niets bij, en benoem het alleen als het relevant is voor deze training."
        if profiel else ""
    )

    # Longitudinale Masterbrein-context (alleen in v2-modus gevuld; anders leeg).
    brein = (workout_data.get("brein_context") or "").strip()
    brein_section = f"\n\n{brein}" if brein else ""

    # P1 — begrensde near-future planning (komende sessies/races + weeknotitie), server-side
    # gelezen via één bounded read (feedback_core._near_future_block). Leeg als niets/onbeschikbaar.
    nf = (workout_data.get("near_future_block") or "").strip()
    near_future_section = f"\n\n{nf}" if nf else ""

    context = f"""Training: {workout_name}

WAT WAS DE BEDOELING (workout builder):
{plan_text}{zones_section}{garmin_section}

Samenvattende data:
{activity_summary}{deviation_section}{unplanned_section}{lap_section}{zone_dist_section}{near_future_section}{datum_section}{profiel_section}{brein_section}

Wat {first_name} zelf schrijft/zegt:
{athlete_input}"""

    return context, first_name


def _clean_text(text: str) -> str:
    """Vangnet: streepjes die ondanks de instructies doorglippen eruit halen."""
    import re
    # Opsommingsstreepje aan het begin van een regel (eerst, behoudt regeleindes)
    text = re.sub(r'(?m)^[-–—][ \t]*', '', text)
    # Em-dash en en-dash worden een komma (gedachtestreepje tussen zinsdelen)
    text = re.sub(r'[ \t]*[—–][ \t]*', ', ', text)
    # Los koppelteken met spaties eromheen verdwijnt; binnen woorden blijft het
    text = re.sub(r'[ \t]*-[ \t]+', ' ', text)
    text = re.sub(r'[ \t]+-[ \t]*', ' ', text)
    # Dubbele komma's na vervanging opruimen
    text = re.sub(r',\s*,', ',', text)
    return text.strip()


_EVALUATIE_SYSTEM = """Je bent een ervaren hardloopcoach die een kwartaalevaluatie schrijft over een atleet, voor de coach zelf (intern). Schrijf zoals de besten dat doen: scherp, eerlijk en bruikbaar, niet als een datadump.

Een goede evaluatie beantwoordt:
- Is de atleet vooruitgegaan? Onderbouw met de cijfers (volume, conditie-index = tempo per hartslag, races). Conditie-index omhoog = fitter (zelfde tempo bij lagere hartslag).
- Wat gaat goed en moet zo blijven?
- Waar ligt de atleet het beste / waar wordt hij blij van (blijkt uit zijn eigen woorden)?
- Wat is het aandachtspunt of de volgende stap?

REGELS:
- Wees beknopt: 3 tot 5 korte alinea's, geen opsomming van alle cijfers. Noem alleen de cijfers die iets zeggen.
- Baseer je UITSLUITEND op de aangeleverde data en woorden. Verzin niets (geen blessures, vakanties of redenen die er niet staan).
- Bij weinig data: zeg dat eerlijk in plaats van te speculeren.
- Conditie-index, gevoel en compliance zijn ruwe signalen, geen exacte wetenschap. Schrijf in genuanceerde taal ("lijkt", "wijst op"), niet stellig.
- Schrijf in het Nederlands, in lopende zinnen. Gebruik nooit een streepje (-, –, —); gebruik een komma of punt.
- Toon: collegiaal en nuchter, alsof je het aan jezelf of een mede-coach uitlegt."""


def generate_athlete_evaluation(context: str, naam: str) -> str:
    """Genereer een beknopte coach-evaluatie (toen vs nu) over een atleet."""
    prompt = f"""Schrijf een korte kwartaalevaluatie over {naam} op basis van onderstaande data.

{context}

Vergelijk TOEN met NU: is er progressie? Wat gaat goed, waar ligt {naam} het best, en wat is het aandachtspunt? Kort en to the point, alleen wat hout snijdt."""
    response = create_message(
        model="claude-opus-4-5",
        max_tokens=700,
        system=_EVALUATIE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _clean_text(response.content[0].text)


_KLANTBERICHT_SYSTEM = """Je bent hardloopcoach Jip en je stuurt een persoonlijk WhatsApp-bericht aan je atleet met een terugblik op de afgelopen periode. Dit is GEEN interne analyse maar een warm, motiverend appje dat de atleet zelf leest.

Stijl:
- Informeel en menselijk, alsof je even een appje stuurt. Spreek de atleet aan met de voornaam en in de je-vorm (nooit u).
- Begin met een persoonlijke aanhef ("Hey Kai,") en eindig warm (bijv. "Trots op je!" of "We gaan door 💪").
- Positief en oprecht, maar eerlijk: benoem concreet wat goed gaat (met een cijfer of voorbeeld als dat kan) en geef één helder aandachtspunt of doel voor de komende tijd, opbouwend gebracht.
- Vertaal data naar wat het bétekent voor de atleet, geen tabellen of jargon. "Je loopt hetzelfde tempo bij een lagere hartslag, dus je bent duidelijk fitter geworden" i.p.v. "conditie-index gestegen".
- Lengte: 6 tot 10 zinnen. Prettig leesbaar als appje, gerust een witregel ertussen.
- Af en toe een emoji, niet overdreven.
- Nederlands, informeel.
- NOOIT een streepje of koppelteken als gedachtestreepje of opsomming; GEEN aanhalingstekens om de tekst; begin direct met de aanhef.

BELANGRIJKSTE ONDERDEEL — een onderbouwde koers voor de komende weken:
Analyseer de cijfers eerst grondig (volume, conditie-index, compliance, gevoel, RPE, races, klachten in de notities) en TOEN vs NU. Kies daarna precies ÉÉN van deze drie richtingen en benoem die helder aan de atleet, met een korte uitleg waaróm (verwijs naar de waardes waar het kan):
1. DOORBOUWEN (progressie): conditie-index omhoog, gevoel goed/stabiel, RPE niet gestegen bij gelijk of hoger volume, hoge compliance, geen klachten. → de komende weken volume en/of intensiteit rustig verder opbouwen.
2. CONSOLIDEREN (vasthouden): gemengd of vlak beeld, winst die afvlakt, of net na een flinke sprong. → even stabiliseren op dit niveau, kwaliteit en consistentie borgen, nog geen extra belasting.
3. BELASTING TERUG (herstel): gevoel slechter, RPE omhoog bij gelijk of lager volume, conditie-index omlaag, dalende compliance door vermoeidheid, of klachten/blessuresignalen in de notities. → de komende weken bewust een stap terug in volume/intensiteit om te herstellen.
Wees eerlijk: als de data om rust vraagt, verpak dat positief maar draai er niet omheen. Kies nooit twee richtingen; de analyse bepaalt welke."""


def generate_athlete_message(context: str, first_name: str) -> str:
    """Genereer een persoonlijk, deelbaar WhatsApp-bericht (terugblik + koers) áán de atleet."""
    prompt = f"""Schrijf een persoonlijk WhatsApp-bericht van Jip aan {first_name} met een terugblik op de afgelopen 3 maanden én een onderbouwde koers voor de komende weken, op basis van onderstaande data.

{context}

Spreek {first_name} rechtstreeks aan. Benoem concreet wat goed ging (met een cijfer/voorbeeld waar het kan). Doe daarna, ná een gedegen analyse van de waardes hierboven, een heldere suggestie voor de komende weken: doorbouwen, consolideren, of juist een stap terug in belasting. Leg kort uit waarom die keuze bij zijn/haar cijfers past. Warm, eerlijk en motiverend."""
    response = create_message(
        model="claude-opus-4-5",
        max_tokens=700,
        system=_KLANTBERICHT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _clean_text(response.content[0].text)


# Neutrale (niet-run) systeem-prompt: zelfde coach/stijl, maar ZONDER hardloop-
# semantiek. Wordt gebruikt voor strength/bike/swim/cross_training/other/unknown,
# zodat pace-/HR-zones, afstand en run-termen niet op niet-runs worden toegepast.
_NONRUN_SYSTEM = """Je schrijft concept-feedback namens coach Jip aan zijn atleten, in het Nederlands, in lopende zinnen. Neem Jips stijl over: kort, menselijk, nuchter en concreet; reageer op wat de atleet zelf schrijft of ervaart, maar vat het niet eerst samen en parafraseer het niet terug: gebruik het direct om te interpreteren. Geef alleen de kale tekst terug, niet tussen aanhalingstekens (interne quotes mogen als je iets citeert). Begin niet met een verplicht compliment; bevestig alleen als de data er aanleiding toe geeft. Gebruik nooit een streepje (-, –, —); gebruik een komma of punt. Geen AI-taal, geen opsommingen.

BELANGRIJK — dit is NADRUKKELIJK GEEN hardlooptraining. Pas GEEN hardloopspecifieke logica toe:
- geen tempo-/pace-zones, geen hartslagzone-oordeel, geen "je liep…", geen afstandsafwijking, geen easy/tempo/interval/progressive-run-interpretatie;
- verzin geen hardloop-trainingsintentie.
Gebruik UITSLUITEND de feitelijke, aangeleverde gegevens: het type training, de titel/omschrijving, eventuele oefeningen/sets/opzet, de uitgevoerd-status, gevoel/RPE, de notities van de atleet en relevante context. Bij weinig data: reageer kort en menselijk op wat er wél is, verzin niets. Ruwe getallen (zoals een gemiddelde hartslag) mag je feitelijk noemen, maar hang er geen zone-oordeel aan.

GEBRUIK DE BESCHIKBARE DATA (belangrijk): als er hierboven gemeten gegevens staan (afstand, duur, hartslag, tempo/snelheid, vermogen), gebruik die dan concreet als ze relevant zijn. Vraagt de atleet of iets in de data terug te zien is en staan die gegevens er (zoals hartslag), verwijs er dan concreet naar. Zeg NOOIT "dat hangt af van wat ik precies zie", "ik kan dat niet beoordelen" of vergelijkbare vage meta-zinnen wanneer de gegevens hierboven staan. Subjectieve zwaarte mag je serieus meewegen en feitelijk naast de data leggen (bijv. een relatief hoge hartslag), maar zonder harde causale conclusie ("dus je was overtraind") en zonder te overclaimen."""

_TYPE_LABEL_NL = {
    "strength": "krachttraining", "bike": "fietstraining", "swim": "zwemtraining",
    "cross_training": "cross-training", "other": "training", "unknown": "training",
}


def _format_nonrun_metrics(activity: dict) -> str:
    """Sport-NEUTRALE feiten voor een niet-hardlooptraining: afstand, duur, hartslag,
    tempo/snelheid, vermogen. GEEN hardloop-pace-zones, geen zone-oordeel — een
    hartslag/afstand/duur is sportonafhankelijk en mag gewoon benoemd worden."""
    if not isinstance(activity, dict):
        return ""
    lines = []
    dist, dplan = activity.get("amount"), activity.get("planned_amount")
    if dist or dplan:
        unit = activity.get("amount_type", "km")
        stuk = f"Afstand: uitgevoerd {round(dist, 2) if dist else '—'} {unit}"
        if dplan:
            stuk += f" (gepland {dplan} {unit})"
        lines.append(stuk)
    dur, dplan_t = activity.get("duration"), activity.get("planned_duration")
    if dur or dplan_t:
        stuk = f"Duur: {_seconds_to_min(dur)} min"
        if dplan_t:
            stuk += f" (gepland {_seconds_to_min(dplan_t)} min)"
        lines.append(stuk)
    hr, hr_max = activity.get("hr_avg"), activity.get("hr_max")
    if hr:
        lines.append(f"Gem. hartslag: {hr} bpm (max {hr_max} bpm)" if hr_max else f"Gem. hartslag: {hr} bpm")
    pace = activity.get("pace_display")
    if pace:
        unit = activity.get("pace_display_type", "")
        lines.append(f"Gem. tempo/snelheid: {pace} {unit}".strip())
    power = activity.get("power_avg")
    if power:
        lines.append(f"Gem. vermogen: {power} W")
    return "\n".join(lines)


def _build_nonrun_context(workout_data: dict) -> tuple[str, str]:
    """Feitelijke, niet-run context (geen zones/pace/afstand/laps)."""
    first_name = workout_data.get("athlete_first_name") or workout_data["athlete_name"].split()[0]
    wt = workout_data.get("workout_type") or "unknown"
    type_label = _TYPE_LABEL_NL.get(wt, "training")
    details = workout_data.get("details") or {}
    plan_description = (details.get("description") or "").strip()
    # Sport-neutrale feiten (afstand/duur/HF/tempo/vermogen) — zodat een niet-run
    # training niet zonder data bij de AI aankomt en de coach niet vaag hoeft te doen.
    _acts = details.get("Activities") or []
    metrics_text = _format_nonrun_metrics(_acts[0]) if _acts else ""

    felt = workout_data.get("felt")
    effort = workout_data.get("effort")
    _FELT_LABELS = {"1": "Geweldig", "2": "Goed", "3": "Normaal", "4": "Slecht", "5": "Vreselijk"}
    parts = []
    if felt or effort:
        rp = []
        if felt:
            fk = str(felt).split(".")[0]
            rp.append(f"Gevoel: {_FELT_LABELS.get(fk, str(felt))} ({fk}/5 — 1=Geweldig t/m 5=Vreselijk)")
        if effort:
            rp.append(f"Inspanning (RPE): {effort}/10")
        parts.append(" | ".join(rp))
    if workout_data.get("post_notes"):
        parts.append(workout_data["post_notes"])
    for c in workout_data.get("athlete_comments", []):
        if c.strip():
            parts.append(c)
    athlete_input = "\n".join(parts) if parts else "(geen notities van de atleet)"

    profiel = (workout_data.get("coach_profiel") or "").strip()
    profiel_section = (
        f"\n\nWAT JE WEET OVER {first_name.upper()} (uit eerdere gesprekken):\n{profiel}\n"
        f"Gebruik dit alleen voor toon/context, herhaal het niet letterlijk, verzin er niets bij."
        if profiel else ""
    )
    brein = (workout_data.get("brein_context") or "").strip()
    brein_section = f"\n\n{brein}" if brein else ""

    metrics_section = f"\n\nGemeten gegevens (feitelijk, sportneutraal — geen hardloop-pace-zones):\n{metrics_text}" if metrics_text else ""

    context = f"""Type training: {type_label} (workout_type = {wt})
Training: {workout_data.get('workout_name') or type_label}

Opzet/omschrijving (indien aanwezig):
{plan_description or 'Geen beschrijving.'}{metrics_section}{profiel_section}{brein_section}

Wat {first_name} zelf schrijft/zegt:
{athlete_input}"""
    return context, first_name


# Feedback v1 — output-length/truncation-contract (B). Ruim genoeg tokenbudget zodat een
# normale coachreactie NOOIT midden in een zin wordt afgekapt; de lengte wordt door het
# prompt/register-contract geschaald (kort bij korte input), niet door hard afkappen.
_FEEDBACK_MAX_TOKENS = 1000
_FEEDBACK_RETRY_MAX_TOKENS = 1800


class FeedbackTruncated(RuntimeError):
    """Het model kapte af op de tokengrens en een ruimere retry deed dat opnieuw — de tekst
    is onvolledig en mag NOOIT stil als volledige feedback worden gepubliceerd."""


def _generate_text(*, max_tokens: int, retry_max_tokens: int | None = None, **kwargs) -> str:
    """Roep het model aan en handel truncation EERLIJK af (geen silent truncation, B):
    bij `stop_reason == 'max_tokens'` één retry met een ruimer budget; kapt die óók af, dan
    `FeedbackTruncated` (de aanroeper mag geen half antwoord teruggeven/plaatsen). Geen
    output-string-hack — puur tokenbudget + stop_reason."""
    resp = create_message(max_tokens=max_tokens, **kwargs)
    if getattr(resp, "stop_reason", None) == "max_tokens":
        resp = create_message(max_tokens=(retry_max_tokens or max_tokens * 2), **kwargs)
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise FeedbackTruncated("De feedback werd afgekapt; genereer opnieuw of kort in.")
    return resp.content[0].text


def generate_feedback(workout_data: dict) -> str:
    """Genereer het eerste feedback-concept op een training. Run-specifieke context
    en prompt draaien ALLEEN bij een hardlooptraining; andere types (of onbekend)
    krijgen een neutrale, feitelijke prompt zonder hardloop-metrics."""
    workout_type = workout_data.get("workout_type") or "unknown"
    if workout_type != "run":
        context, first_name = _build_nonrun_context(workout_data)
        prompt = f"""Schrijf een concept-reactie voor Jip aan {first_name} op deze training:

{context}

AANPAK:
1. Reageer PRIMAIR op wat {first_name} zelf schrijft of ervaart, maar VAT het niet samen en parafraseer het niet terug: gebruik het direct om te interpreteren en te coachen.
2. Dit is GEEN hardlooptraining: gebruik geen tempo/hartslagzones, geen afstand, geen run-termen.
3. Gebruik alleen de feitelijke gegevens hierboven. Bij weinig data: kort en menselijk, niets verzinnen.

Schrijf nu de reactie. Alleen de kale tekst, niet tussen aanhalingstekens. Kort en menselijk, in de stijl van Jip."""
        return _clean_text(_generate_text(
            max_tokens=_FEEDBACK_MAX_TOKENS, retry_max_tokens=_FEEDBACK_RETRY_MAX_TOKENS,
            model="claude-sonnet-4-6",
            system=_NONRUN_SYSTEM, messages=[{"role": "user", "content": prompt}]))

    context, first_name = _build_workout_context(workout_data)

    prompt = f"""Schrijf een concept-reactie voor Jip aan {first_name} op deze training:

{context}

AANPAK:
1. Reageer PRIMAIR op wat {first_name} zelf schrijft of ervaart, maar VAT het niet eerst samen en parafraseer het niet uitgebreid terug: gebruik het direct om te interpreteren en te coachen. Verwijs alleen kort naar een specifiek detail als dat nodig is om je advies te begrijpen.
2. Vergelijk daarna de uitvoering met het plan (geplande structuur hierboven). Waren de geplande zones/tempo's gehaald? Dat is de meest waardevolle observatie.
3. Gebruik de lap-data alleen als er iets opvallends in zit — geen opsomming.
4. Beoordeel NOOIT iets (hartslag, tempo) zonder de bijbehorende zones. Zie de zone-instructie hierboven — die is absoluut.
5. Als iets in het plan stond (bijv. sneller eindblok, zone 3 interval), dan was het correct zo. Zeg nooit dat iets "niet nodig" was als het in het plan stond.

Schrijf nu de reactie. Alleen de kale tekst, niet tussen aanhalingstekens; natuurlijke hardloop-/coachtaal. Kort en menselijk, in de stijl van Jip."""

    return _clean_text(_generate_text(
        max_tokens=_FEEDBACK_MAX_TOKENS, retry_max_tokens=_FEEDBACK_RETRY_MAX_TOKENS,
        model="claude-sonnet-4-6",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ))


def generate_reply(workout_data: dict, thread: list) -> str:
    """
    Genereer een vervolg-reactie in een lopend gesprek.
    Reageert op het LAATSTE bericht van de atleet — zonder alle trainingsdata opnieuw te analyseren.

    Workout-type-aware, met exact dezelfde centrale waarheid als generate_feedback
    (fs_client.classify_workout_type → workout_data["workout_type"]): een hardloop-
    training gebruikt het bewezen run-pad (SYSTEM_PROMPT + _build_workout_context);
    kracht/andere bewezen non-run én onbekend gebruiken de neutrale _NONRUN_SYSTEM +
    _build_nonrun_context (geen pace/afstand/hartslagzone/hardloopframing). UNKNOWN
    wordt nooit als run behandeld. Geen aparte reply-promptset — hergebruik.
    """
    workout_type = workout_data.get("workout_type") or "unknown"
    is_run = (workout_type == "run")
    if is_run:
        context, first_name = _build_workout_context(workout_data)
        system_prompt = SYSTEM_PROMPT
        nonrun_note = ""
    else:
        context, first_name = _build_nonrun_context(workout_data)
        system_prompt = _NONRUN_SYSTEM
        nonrun_note = (
            " Dit is GEEN hardlooptraining: gebruik geen tempo/hartslagzones, geen "
            "afstand en geen run-termen; blijf bij de feitelijke gegevens."
        )

    # Bouw de gespreksgeschiedenis op als multi-turn messages
    # Beginbericht: de volledige context als achtergrond
    messages = [{
        "role": "user",
        "content": (
            f"Achtergrond voor dit gesprek (training van {first_name}):\n\n"
            f"{context}\n\n"
            f"Schrijf nu een reactie op het eerste bericht van {first_name} hieronder."
        ),
    }]

    # Verwerk de thread als afwisselende user/assistant berichten
    # Samenvoegen als er twee opeenvolgende berichten van dezelfde rol zijn
    for msg in thread:
        tekst = msg.get("tekst", "").strip()
        if not tekst:
            continue
        van = msg.get("van", "atleet")
        role = "assistant" if van == "coach" else "user"

        if messages and messages[-1]["role"] == role:
            # Samenvoegen met vorige
            messages[-1]["content"] += "\n\n" + tekst
        else:
            messages.append({"role": role, "content": tekst})

    # Zorg dat het laatste bericht altijd van de atleet (user) is
    if not messages or messages[-1]["role"] != "user":
        # Niets te beantwoorden
        return generate_feedback(workout_data)

    # Voeg instructie toe aan het laatste user-bericht — follow-up-specifiek: antwoord
    # op wat de atleet zojuist zegt, niet de training opnieuw analyseren.
    messages[-1]["content"] += (
        f"\n\n[Dit is het laatste bericht van {first_name}. Reageer ALLEEN hierop. "
        f"Analyseer de training niet opnieuw en vat tempo/zones niet opnieuw samen. "
        f"Herhaal geen vraag die hierboven al beantwoord is en parafraseer "
        f"{first_name} niet uitgebreid terug. Benoem trainingsdata alleen als die nodig is "
        f"om te antwoorden of als het nieuwe verandert wat je eerder dacht. "
        f"Geef alleen de kale tekst terug, niet tussen aanhalingstekens. "
        f"Kort en coachend, in de stijl van Jip; onzekerheid eerlijk houden.{nonrun_note}]"
    )

    return _clean_text(_generate_text(
        max_tokens=_FEEDBACK_MAX_TOKENS, retry_max_tokens=_FEEDBACK_RETRY_MAX_TOKENS,
        model="claude-sonnet-4-6",
        system=system_prompt,
        messages=messages,
    ))


# ---------------------------------------------------------------------------
# Race succeswens generatie
# ---------------------------------------------------------------------------

RACE_WISH_SYSTEM_PROMPT = """Je schrijft korte, persoonlijke succeswensen namens hardloopcoach Jip aan zijn atleten voor een aankomende race.

De coach heet Jip. Zijn stijl is informeel, direct en menselijk. Schrijf alsof je even snel een appje stuurt.

VOORBEELDEN (let op: geen aanhalingstekens, geen streepjes):
Heel veel succes zondag! Je hebt er hard voor gewerkt. Geniet ervan en ga ervoor 💪
Top voorbereiding gedaan. Nu gewoon lekker lopen en vertrouwen op je training. Succes!
Je bent er klaar voor. Laat de benen maar spreken komende zaterdag 🔥 Veel succes!

STIJLREGELS:
- Kort: 1 tot 3 zinnen max
- Motiverend maar eerlijk, geen loze beloftes
- Gebruik de exacte dag die in de prompt staat (morgen / vandaag / komende zaterdag / etc.) — verzin NOOIT zelf een dag
- Verwijs concreet naar het racetype als dat relevant is
- Als er context is over de voorbereiding: verwijs daar subtiel naar
- Gebruik af en toe een emoji, maar niet bij elke zin
- Schrijf in het Nederlands, informeel
- Gebruik je en jij, nooit u
- NOOIT een streepje of koppelteken als gedachtestreepje of opsomming
- GEEN aanhalingstekens aan het begin of einde van de tekst
- Begin direct met de tekst, geen inleiding

RACE-SPECIFIEKE TOON:
- HYROX: kracht, doorzetten, het is zwaar maar jij bent klaar
- 5km / 10km: snelheid, lef, volle bak van start
- Halve marathon: tempo bewaken, genieten, vertrouwen op training
- Marathon: rust bewaren, tweede helft, mentale kracht
- Triathlon: veelzijdigheid, doorzetten, elk onderdeel apart
- Overig: algemeen motiverend"""


def _dag_aanduiding(race_date_str: str) -> str:
    """Geeft een Nederlandse dag-aanduiding terug op basis van de racedatum."""
    import locale
    from datetime import date
    try:
        race_dt = date.fromisoformat(race_date_str[:10])
    except ValueError:
        return race_date_str

    today = date.today()
    delta = (race_dt - today).days

    if delta == 0:
        return "vandaag"
    if delta == 1:
        return "morgen"
    if delta == 2:
        return "overmorgen"

    dag_namen = ["maandag", "dinsdag", "woensdag", "donderdag",
                 "vrijdag", "zaterdag", "zondag"]
    dag_naam = dag_namen[race_dt.weekday()]

    if delta <= 7:
        return f"komende {dag_naam}"
    return f"{dag_naam} {race_dt.day} {race_dt.strftime('%B')}"


def generate_race_wish(
    first_name: str,
    race_name: str,
    race_type: str,
    race_date: str,
    context: str = "",
) -> str:
    """
    Genereer een persoonlijke succeswens voor een atleet voor een aankomende race.
    context: relevante eerdere opmerkingen over de race (optioneel).
    """
    import re

    dag = _dag_aanduiding(race_date)
    context_sectie = (
        f"\nRelevante context uit eerdere trainingen/comments:\n{context}"
        if context.strip() else ""
    )

    prompt = f"""Schrijf een concept-succeswens van Jip aan {first_name} voor de aankomende race.

Atleet: {first_name}
Race: {race_name}
Type: {race_type}
Wanneer: {dag} ({race_date}){context_sectie}

GEBRUIK in de tekst exact de aanduiding "{dag}" als je verwijst naar de racedag. Schrijf NIET "morgen" als de race niet morgen is."""

    response = create_message(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=RACE_WISH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Verwijder aanhalingstekens aan begin/einde
    text = text.strip('"\'')
    # Verwijder streepjes als gedachtestreepje of opsomming
    text = re.sub(r'(?<!\w)-(?!\w)', ' ', text)   # streepje tussen spaties
    text = re.sub(r'\s{2,}', ' ', text)
    text = text.strip().strip('"\'')

    return text


# ---------------------------------------------------------------------------
# Raceplan generatie
# ---------------------------------------------------------------------------

RACE_PLAN_SYSTEM_PROMPT = """Je schrijft beknopte, concrete raceplannen namens hardloopcoach Jip voor zijn atleten.

GEBRUIK EXACT DEZE STRUCTUUR — geen kopjes, geen titels, gewoon deze volgorde:

1. Eén of twee zinnen: wat is het doeltempo en waarop is dat gebaseerd (trainingslog/zones). Dan de startstrategie.
2. Splits als compacte lijst:
   - Km 1–2: X:XX/km (toelichting)
   - Km 3–7: X:XX/km (toelichting)
   - etc.
   Of voor baanwedstrijden: rondetijden per 400m of per ronde.
3. Doeltijd op een aparte regel: "Doeltijd: ca. XX:XX"
4. Eén of twee zinnen mentale tip voor het moment dat het zwaar wordt.

VOORBEELD OUTPUT (voor een 10km):
Op basis van je tempoblokken (Z3 op 5:10–5:26/km) en lange duurlopen is een doeltempo van 5:25–5:35/km realistisch. Start de eerste 2 km gecontroleerd in Z2/lage Z3 (rond 5:35/km), daarna geleidelijk opbouwen naar 5:25/km. Laatste km geef je alles.

- Km 1–2: 5:35/km (gecontroleerd instappen)
- Km 3–7: 5:25–5:30/km (stabiliseren)
- Km 8–9: 5:20/km (als je nog ruimte voelt)
- Km 10: alles eruit

Doeltijd: ca. 54:00–55:00

Vanaf km 6 wordt het mentaal zwaar. Focus dan op de volgende 500 meter, niet op wat er nog komt. Houding rechtop, armen ontspannen. Tempo vasthouden is belangrijker dan versnellen.

REKENREGELS (intern controleren, nooit tonen):
- 400m-rondetijd = pace (min/km) × 0.4 → bijv. 3:07/km = 1:15 per ronde
- Controleer altijd of rondetijd en pace overeenkomen

STIJLREGELS:
- Geen kopjes of titels
- Schrijf direct ("je") — informeel en concreet
- Maximaal 150 woorden
- Gebruik GEEN streepjes als gedachtestreepje
- Schrijf in het Nederlands
- Geen warming-up of cooling-down uitwerken

ZONES: hogere min/km = langzamer = lagere zone. Gebruik zones letterlijk zoals opgegeven."""


def generate_race_plan(
    first_name: str,
    race_name: str,
    race_type: str,
    race_date: str,
    athlete_key: str = "",
    description: str = "",
    context: str = "",
) -> str:
    """
    Genereer een concreet raceplan voor een atleet op basis van zones en trainingslog.
    Als er geen doeltijd bekend is, leidt de AI die af uit recente trainingsdata.
    """
    import fs_client as _fs

    dag = _dag_aanduiding(race_date)

    # Zones ophalen
    zones_tekst = ""
    if athlete_key:
        try:
            zones_result = _fs.get_athlete_zones(athlete_key)
            if zones_result.get("zones_text"):
                zt = zones_result.get("zone_type", "tempo")
                zone_type_label = "tempo (min/km)" if zt == "tempo" else "hartslag (bpm)"
                zones_tekst = f"Zones ({zone_type_label}):\n{zones_result['zones_text']}"
        except Exception:
            pass

    zones_sectie = (
        f"\n\n{zones_tekst}"
        if zones_tekst else
        "\n\n(Geen zones beschikbaar.)"
    )

    # Trainingslog ophalen — recente prestaties als basis voor splits
    log_sectie = ""
    if athlete_key:
        try:
            log_workouts = _fs.get_training_log(athlete_key, months=2, detail_weeks=6)
            if log_workouts:
                from schema_builder import format_training_log
                log_tekst = format_training_log(log_workouts)
                log_sectie = f"\n\nRECENTE TRAININGSLOG (gebruik dit om huidig niveau te bepalen):\n{log_tekst[:4000]}"
        except Exception:
            pass

    context_sectie = (
        f"\n\nEerdere opmerkingen over deze race:\n{context}"
        if (context or "").strip() else ""
    )

    description_sectie = (
        f"\n\nOmschrijving van de race (LEIDEND — gebruik dit als primaire input):\n{description.strip()}"
        if description.strip() else ""
    )

    prompt = f"""Schrijf een beknopt raceplan voor {first_name} (max 150 woorden).

Race: {race_name}
Type: {race_type}
Datum: {dag} ({race_date}){description_sectie}{zones_sectie}{log_sectie}{context_sectie}

De omschrijving hierboven is leidend: gebruik de afstand en doeltijd daaruit.
Als geen doeltijd bekend is: leid die af uit de trainingslog.
Controleer intern je rondetijden (pace × 0.4 = 400m-tijd) maar toon dit rekenwerk NIET in de output.
Begin direct met het eerste kopje — geen inleiding, geen rekencheck zichtbaar."""

    response = create_message(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=RACE_PLAN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Coaching sessie-samenvatting
# ---------------------------------------------------------------------------

def generate_session_summary(coach_name: str, items: list[dict]) -> str:
    """
    Genereer een beknopte coaching handover voor WhatsApp/e-mail.
    items: lijst van {athlete_name, workout_name, feedback_text[, datum, groep_label]}

    Feedback v1 (F): de samenvatting wordt GEGROEPEERD PER DATUM en daarbinnen per groep. Dit is
    puur presentatie: ELK meegegeven item is een succesvol geposte feedback (successfully-posted
    session truth); er wordt niets toegevoegd of weggelaten.
    """
    if not items:
        return ""

    _md = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
           "augustus", "september", "oktober", "november", "december"]

    def _datum_label(d: str) -> str:
        try:
            dt = date.fromisoformat((d or "")[:10])
            return f"{dt.day} {_md[dt.month - 1]}"
        except Exception:
            return "Zonder datum"

    # Groepeer PER DATUM (oplopend), daarbinnen PER GROEP; binnen een groep per atleet.
    per_datum: dict = {}
    for it in items:
        d = (it.get("datum") or "")[:10]
        per_datum.setdefault(d, {}).setdefault(it.get("groep_label") or "Overig", []).append(it)

    blokken = []
    for d in sorted(per_datum.keys()):
        regels = [f"[{_datum_label(d)}]"]
        for groep in sorted(per_datum[d].keys()):
            regels.append(f"  Groep {groep}:")
            for it in per_datum[d][groep]:
                tekst = it["feedback_text"][:200] + ("…" if len(it["feedback_text"]) > 200 else "")
                regels.append(f"    Atleet: {it['athlete_name']} | Training: {it['workout_name']}\n"
                              f"    Feedback: {tekst}")
        blokken.append("\n".join(regels))
    items_tekst = "\n\n".join(blokken)

    try:
        today = f"{date.today().day} {date.today().strftime('%B %Y')}"
    except Exception:
        today = str(date.today())

    n = len(items)
    namen = ", ".join(it["athlete_name"].split()[0] for it in items)

    prompt = f"""Schrijf een beknopte coaching handover voor {coach_name} over de gegeven feedback.

Datum van de sessie: {today}
Coach: {coach_name}
Aantal feedbacks deze sessie: {n} ({namen})

De gegeven feedback is hieronder al GEGROEPEERD PER TRAININGSDATUM en daarbinnen per groep:
{items_tekst}

BELANGRIJK: neem ALLE {n} atleten/feedbacks op — sla niemand over.

FORMAT (exact deze structuur, geen extra uitleg erbuiten):
📋 Coaching update {today} — {coach_name}

Per trainingsdatum een kopje "📅 <datum>", daaronder per groep een kopje "▸ <groep>", en daaronder per atleet één regel: Voornaam: kern van de feedback + aandachtspunt voor de volgende training indien relevant.

Regels:
- Behoud de datum- en groepindeling hierboven exact; verzin geen atleten of data bij
- Eén regel per atleet, ALLE {n} vermelden
- Alleen de essentie: wat was opvallend, wat moet de andere coach weten
- Schrijf in het Nederlands, informeel
- Geen streepjes als gedachtestreepje"""

    response = create_message(
        model="claude-sonnet-4-6",
        max_tokens=150 * n + 150,  # ~150 tokens per atleet + header/kopjes
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Dossier-signalering — detecteert dossier-waardige berichten van atleten
# ---------------------------------------------------------------------------

import re as _re

# Trap 1: alleen berichten met een hard signaal gaan door naar de AI-check.
# Korte tokens met woordgrenzen om valse hits (bijv. 'pr' in 'proberen') te voorkomen.
_SIGNAAL_PATRONEN = [
    r"blessure", r"geblesseerd", r"\bpijn\b", r"fysio", r"\bziek\b", r"griep",
    r"koorts", r"overtraind", r"\bgestopt\b", r"\bstoppen\b", r"opgeven",
    r"opgegeven", r"huilen", r"somber", r"depressi", r"burn[- ]?out",
    r"zwanger", r"operatie", r"ziekenhuis", r"\bpr\b", r"\brecord\b",
    r"snelste", r"nooit eerder", r"beste ooit", r"doorbraak",
    r"motivatie kwijt", r"geen motivatie", r"twijfel",
]

_DOSSIER_CHECK_SYSTEM = """Je beoordeelt of een bericht van een hardloop-atleet aan de coach dossier-waardig is.

ALLEEN dossier-waardig bij:
- (nieuwe of verergerende) blessure of ziekte
- mentale dip, motivatiecrisis of twijfel over de coaching
- ingrijpende levensgebeurtenis die de training raakt
- uitzonderlijke doorbraak, PR of mijlpaal

NIET dossier-waardig: gewone vermoeidheid, een losse goede of slechte training, weer, drukte op werk zonder gevolgen.

Antwoord met uitsluitend "NEE", of met één feitelijke Nederlandse zin (max 20 woorden) die het signaal samenvat. Geen oordeel, geen advies."""


def check_dossier_signal(workout_data: dict) -> str | None:
    """
    Geeft een één-zin dossier-notitie terug als het atleet-bericht een
    uitschieter is (heel goed of heel slecht), anders None.

    Trap 1 (gratis): gevoel-score extreem óf signaalwoord in de tekst.
    Trap 2 (Haiku): strenge AI-check + samenvatting in één zin.
    """
    teksten = [workout_data.get("post_notes") or ""]
    teksten += workout_data.get("athlete_comments") or []
    tekst = "\n".join(t for t in teksten if t and t.strip()).strip()

    _FELT_NL = {1: "Geweldig", 2: "Goed", 3: "Normaal", 4: "Slecht", 5: "Vreselijk"}
    felt_num = None
    try:
        felt = workout_data.get("felt")
        felt_num = int(float(felt)) if felt else None
    except (ValueError, TypeError):
        pass
    felt_extreem = felt_num in (1, 4, 5)

    # Geen tekst maar wél een uiterste score (1 of 5): feitelijke notitie
    # zonder AI-call — een mega offday zonder toelichting is óók een signaal
    if not tekst:
        if felt_num in (1, 5):
            return (f"Scoorde '{_FELT_NL[felt_num]}' op gevoel, zonder toelichting. "
                    f"Mogelijk even navragen wat er speelde.")
        return None

    tekst_lc = tekst.lower()
    heeft_signaalwoord = any(_re.search(p, tekst_lc) for p in _SIGNAAL_PATRONEN)
    if not (felt_extreem or heeft_signaalwoord):
        return None

    felt_str = _FELT_NL.get(felt_num, "onbekend")

    response = create_message(
        model="claude-haiku-4-5-20251001",
        max_tokens=80,
        system=_DOSSIER_CHECK_SYSTEM,
        messages=[{"role": "user", "content": (
            f"Training: {workout_data.get('workout_name', 'training')} "
            f"({workout_data.get('workout_date', '')})\n"
            f"Gevoel-score: {felt_str}\n\n"
            f"Wat de atleet schrijft:\n{tekst[:1500]}"
        )}],
    )
    out = response.content[0].text.strip()
    if not out or out.upper().startswith("NEE") or len(out) < 8:
        return None
    return out


_PROFIEL_SYSTEM = """Je onderhoudt een compact coach-geheugen over één hardloop-atleet, voor het schrijven van persoonlijke feedback.

Je krijgt het huidige profiel plus één nieuwe interactie (wat de atleet schreef en wat de coach antwoordde). Geef het BIJGEWERKTE profiel terug.

WAT ERIN HOORT (alleen als het uit de interacties blijkt):
- Blessures/fysieke aandachtspunten en hun verloop
- Wat deze atleet motiveert en waar hij/zij op aanslaat (datagericht? gevoel? humor?)
- Terugkerende thema's (slaap, werkstress, twijfel, wedstrijdspanning)
- Voorkeuren en eigenaardigheden die de coach benoemt of bevestigt

REGELS:
- Maximaal 120 woorden, losse feitelijke zinnen, geen opsommingstekens of streepjes
- Werk bestaande punten bij in plaats van toe te voegen; verwijder wat verouderd of eenmalig is
- GEEN trainingslogboek (geen datums, tempo's of losse trainingen), alleen wat blijvend relevant is voor de coaching
- Verzin niets; bij een nietszeggende interactie geef je het profiel vrijwel ongewijzigd terug
- Nederlands. Antwoord met ALLEEN de profieltekst."""


def update_athlete_profiel(oud_profiel: str, athlete_tekst: str,
                           coach_tekst: str, workout_naam: str = "") -> str:
    """Werk het coach-geheugen bij met één geposte feedback-interactie (Haiku)."""
    inhoud = (f"HUIDIG PROFIEL:\n{oud_profiel.strip() or '(nog leeg)'}\n\n"
              f"NIEUWE INTERACTIE ({workout_naam or 'training'}):\n"
              f"Atleet schreef: {athlete_tekst.strip()[:1200] or '(niets)'}\n"
              f"Coach antwoordde: {coach_tekst.strip()[:1200]}")
    response = create_message(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=_PROFIEL_SYSTEM,
        messages=[{"role": "user", "content": inhoud}],
    )
    nieuw = _clean_text(response.content[0].text.strip())
    # Vangnet: een leeg of ontspoord (veel te lang) antwoord nooit opslaan
    if not nieuw or len(nieuw) > 1500:
        return oud_profiel
    return nieuw


_BELASTING_SYSTEM = """Je vat belasting-signalen over een hardloper samen voor de coach, in maximaal twee korte zinnen.

Regels:
- Combineer de signalen en wat de atleet schrijft tot één praktische observatie plus een zachte suggestie ("overweeg", "kijk even mee", "check even").
- GEEN medische diagnose, geen alarmtaal, geen verzonnen context. Alleen wat in de data staat.
- Gebruik NOOIT een streepje (-, – of —). Schrijf vloeiende zinnen met komma's.
- Nederlands, direct, alsof je een collega-coach kort bijpraat. Geen aanhef, geen naam vooraf."""


def belasting_duiding(naam: str, signalen: list[str], notities: str = "") -> str:
    """Eén duidende coach-zin bij belasting-signalen (Haiku, goedkoop)."""
    inhoud = f"Atleet: {naam}\nSignalen:\n" + "\n".join(f"- {s}" for s in signalen)
    if notities.strip():
        inhoud += f"\n\nRecente notities van de atleet:\n{notities[:800]}"
    response = create_message(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        system=_BELASTING_SYSTEM,
        messages=[{"role": "user", "content": inhoud}],
    )
    return _clean_text(response.content[0].text.strip())
