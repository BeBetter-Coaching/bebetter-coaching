"""Claude API integratie voor het genereren van coach feedback."""

import anthropic
from datetime import date

client = anthropic.Anthropic()

SYSTEM_PROMPT = """Je schrijft concept-feedback namens een hardloopcoach aan zijn atleten.

De coach heet Jip. Hieronder staan echte voorbeelden van hoe hij schrijft — neem zijn stijl exact over:

VOORBEELD 1:
"Helemaal prima. Kijkand naar de training zie ik dat je wel af en toe wat langer rust hebt gehad dan gepland. Niet erg, valt me op. Daarentegen heb je wel netjes alle kilometers bijna even hard gelopen. Dat laat wel zien dat de inspanning goed te doen was. Zie je ook terug in je hartslag, die komt niet over zone 3. Goed gedaan! Hoe voel je jezelf nu?"

VOORBEELD 2:
"Mooi constant gelopen in zowel hartslag als tempo. Tempo in zone 2 ligt weer lekker dicht bij 6:00/km dus dat is zeker positief. Je zit er weer lekker in, gaat de goede kant op. Vasthouden nu!"

VOORBEELD 3:
"Mooi om te lezen, zeker na twee korte nachten en een mindere week. Dan is het een goed teken dat je training weer soepel voelt."

VOORBEELD 4:
"Dat je eerste intervallen tijdens het bellen iets sneller gingen, zegt inderdaad dat het waarschijnlijk nog binnen controle zat. Als je echt aan het hijgen was geweest, had dat bellen vanzelf niet meer gewerkt 😄 Maar wel even opletten: bellen kan er ook voor zorgen dat je minder bewust loopt, waardoor je ongemerkt te hard gaat. Voor een keer geen probleem, maar bij dit soort blokken liever iets bewuster op tempo en gevoel blijven sturen.
Fijn dat de laatste twee ook soepel gingen. Dat geeft vertrouwen dat de dip van vorige week vooral vermoeidheid was en niet dat je vorm weg is.
Goede training dus. Nu vooral zorgen dat je die slaap weer wat bijtrekt, dan kan dit gevoel mooi doorzetten 💪"

STIJLREGELS:
- Schrijf informeel, direct en menselijk — alsof je even snel een appje stuurt
- Focus altijd op wat de atleet zelf schrijft of ervaart. Dat is het vertrekpunt
- Benoem concrete dingen uit de data (zones, tempo, hartslag) maar alleen als het relevant is
- Wees kort. Soms is één zin genoeg
- Gebruik af en toe een emoji, maar niet bij elk bericht
- Stel NOOIT standaard een vraag aan het einde. Sluit af met een observatie of aanmoediging. Stel alleen een vraag als er echt iets specifieks is dat je moet weten van de atleet om verder te coachen, of als de atleet iets heeft gezegd dat actief om reflectie vraagt.
- Gebruik NOOIT een streepje (-) in de tekst. Niet als opsomming, niet als gedachtestreepje, nergens. Schrijf altijd in lopende zinnen
- Schrijf nooit formeel of als een AI. Geen "Ik zie dat jij..." of "Goed gedaan atleet"
- Gebruik "je" en "jij", nooit "u"
- Schrijf in het Nederlands

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


def _format_laps(laps: list) -> str:
    """Vat lap-data samen: tempo, hartslag en cadans per km/interval."""
    if not laps:
        return ""

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

        if parts:
            label = f"Km {i}" if not dist else f"{dist}"
            rows.append(f"  {label}: {', '.join(parts)}")

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
    lap_summary = _format_laps(laps)

    builder_steps_text = ""
    if details.get("has_structured_workout") and workout_key and athlete_key:
        try:
            builder_steps = _fs.get_workout_builder(workout_key, athlete_key)
            builder_steps_text = _format_builder_steps(builder_steps)
        except Exception:
            pass

    athlete_zones_text = ""
    athlete_zone_type = ""   # "tempo" | "hartslag" | ""
    if athlete_key:
        try:
            zones_result = _fs.get_athlete_zones(athlete_key)
            if "zones_text" in zones_result:
                athlete_zone_type = zones_result.get("zone_type", "")   # "tempo" of "hartslag"
                zone_type_label = "tempo (min/km)" if athlete_zone_type == "tempo" else "hartslag (bpm)"
                athlete_zones_text = f"Zones ({zone_type_label}):\n{zones_result['zones_text']}"
        except Exception:
            pass

    felt = workout_data.get("felt")
    effort = workout_data.get("effort")

    athlete_input_parts = []
    if felt or effort:
        rating_parts = []
        if felt:
            rating_parts.append(f"Gevoel: {felt}")
        if effort:
            rating_parts.append(f"Inspanning: {effort}/10")
        athlete_input_parts.append(" | ".join(rating_parts))
    if post_notes:
        athlete_input_parts.append(post_notes)
    for comment in athlete_comments:
        if comment.strip():
            athlete_input_parts.append(comment)
    athlete_input = "\n".join(athlete_input_parts) if athlete_input_parts else "(geen notities van de atleet)"

    lap_section = f"\nVerloop per km/interval (tempo, hartslag, cadans):\n{lap_summary}" if lap_summary else ""

    plan_parts = []
    if plan_description.strip():
        plan_parts.append(plan_description.strip()[:600])
    if builder_steps_text:
        plan_parts.append(builder_steps_text)
    plan_text = "\n\n".join(plan_parts) if plan_parts else "Geen beschrijving."

    if athlete_zones_text:
        if athlete_zone_type == "tempo":
            zone_instruction = (
                f"TEMPO-ZONES VAN {first_name.upper()} — beoordeel intensiteit UITSLUITEND via tempo. "
                f"Zeg NOOIT dat de hartslag hoog/laag/te hard is of in een zone zit. "
                f"Hartslag mag alleen als neutraal getal (bijv. 'HF 148 bpm'), nooit met oordeel."
            )
        elif athlete_zone_type == "hartslag":
            zone_instruction = (
                f"HARTSLAG-ZONES VAN {first_name.upper()} — beoordeel intensiteit UITSLUITEND via hartslag. "
                f"Hang GEEN zone-labels aan tempo zonder tempo-zones."
            )
        else:
            zone_instruction = f"ZONES VAN {first_name.upper()} — gebruik ALLEEN deze waarden, niet je eigen aannames."
        zones_section = f"\n\n{zone_instruction}\n{athlete_zones_text}"
    else:
        zones_section = (
            f"\n\n⚠️ GEEN zones beschikbaar voor {first_name}. "
            f"Noem ruwe getallen (tempo in min/km, HF in bpm) maar hang er NOOIT een oordeel of zone-label aan. "
            f"Zeg NOOIT dat iets 'hoog', 'te hard' of 'in zone X' was."
        )

    context = f"""Training: {workout_name}

WAT WAS DE BEDOELING (workout builder):
{plan_text}{zones_section}

Samenvattende data:
{activity_summary}{lap_section}

Wat {first_name} zelf schrijft/zegt:
{athlete_input}"""

    return context, first_name


def _clean_text(text: str) -> str:
    import re
    text = re.sub(r'\s*-\s+', ' ', text)
    text = re.sub(r'\s+-\s*', ' ', text)
    return text.strip()


def generate_feedback(workout_data: dict) -> str:
    """Genereer het eerste feedback-concept op een training."""
    context, first_name = _build_workout_context(workout_data)

    prompt = f"""Schrijf een concept-reactie voor Jip aan {first_name} op deze training:

{context}

AANPAK:
1. Reageer PRIMAIR op wat {first_name} zelf schrijft of ervaart — dat is het vertrekpunt.
2. Vergelijk daarna de uitvoering met het plan (geplande structuur hierboven). Waren de geplande zones/tempo's gehaald? Dat is de meest waardevolle observatie.
3. Gebruik de lap-data alleen als er iets opvallends in zit — geen opsomming.
4. Beoordeel NOOIT iets (hartslag, tempo) zonder de bijbehorende zones. Zie de zone-instructie hierboven — die is absoluut.
5. Als iets in het plan stond (bijv. sneller eindblok, zone 3 interval), dan was het correct zo. Zeg nooit dat iets "niet nodig" was als het in het plan stond.

Schrijf nu de reactie. Kort en menselijk, in de stijl van Jip."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    return _clean_text(response.content[0].text)


def generate_reply(workout_data: dict, thread: list) -> str:
    """
    Genereer een vervolg-reactie in een lopend gesprek.
    Reageert op het LAATSTE bericht van de atleet — zonder alle trainingsdata opnieuw te analyseren.
    """
    context, first_name = _build_workout_context(workout_data)

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

    # Voeg instructie toe aan het laatste user-bericht
    messages[-1]["content"] += (
        f"\n\n[Dit is het laatste bericht van {first_name}. "
        f"Reageer ALLEEN op dit bericht. Je hoeft de training niet opnieuw te analyseren. "
        f"Houd het kort en persoonlijk, in de stijl van Jip.]"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return _clean_text(response.content[0].text)


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

    response = client.messages.create(
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

    response = client.messages.create(
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
    items: lijst van {athlete_name, workout_name, feedback_text}
    """
    if not items:
        return ""

    items_tekst = "\n\n".join(
        f"Atleet: {it['athlete_name']}\nTraining: {it['workout_name']}\nFeedback gegeven:\n{it['feedback_text']}"
        for it in items
    )

    today = date.today().strftime("%-d %B %Y") if hasattr(date.today(), 'strftime') else str(date.today())
    try:
        today = date.today().strftime("%d %B %Y").lstrip("0")
    except Exception:
        today = str(date.today())

    prompt = f"""Schrijf een beknopte coaching handover voor {coach_name} over de feedback die vandaag gegeven is.

Datum: {today}
Coach: {coach_name}

Gegeven feedback deze sessie:
{items_tekst}

FORMAT (exact dit, geen kopjes, geen uitleg erbuiten):
📋 Coaching update {today} — {coach_name}

[Per atleet één regel: Naam: kern van de feedback + eventuele aandachtspunten voor volgende training]

[Sluit af met één zin algemene opmerking als dat relevant is, anders weglaten]

Regels:
- Maximaal 1 zin per atleet
- Alleen de essentie: wat was opvallend, wat moet de andere coach weten
- Schrijf in het Nederlands, informeel
- Geen streepjes als gedachtestreepje"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()
