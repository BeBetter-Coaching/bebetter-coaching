"""Feedback Coachability — CopyQuality-opschoning + CoachingIntent (athlete-first, data-second).

Deterministische, LLM-vrije nabewerking die de output COACHBAAR maakt zonder de veiligheid te raken:
- verwijdert intern/technisch/systeemtaal-zinnen (blokkoppeling, lapdata, dominante beeld, execution
  fit, compliance, metriek, pipeline, ...);
- verwijdert defensieve 'dat kan ik niet uit de data halen'-zinnen;
- ontdubbelt exacte ÉN semantisch-equivalente zinnen (max één klacht-/follow-up-zin per onderwerp);
- houdt de tekst kort.

Plus een simpele CoachingIntent-classifier (deterministisch) die stuurt of/hoeveel data nodig is.
Geen nieuwe store/cache/truth-pad. Wordt toegepast op zowel AUTO_SAFE-assemblage als REVIEW-drafts.
"""
from __future__ import annotations

import re

# Athlete-facing VERBODEN intern/technisch taalgebruik → zin met zo'n term wordt geschrapt.
_SYSTEM_TERMS = (
    "blokkoppeling", "blokmatch", "lapdata", "lap-data", "dominante beeld", "dominant beeld",
    "door de bank", "onvoldoende uit de data", "niet uit de data", "koppeling niet strak",
    "brondata", "metriek", "execution fit", "executionfit", "compliance", "zonechip",
    "pipeline", "readiness", "source health", "provenance", "matched", "ambiguous",
    "review_required", "auto_safe", "context laden", "context laadt",
)
# Defensieve 'kan ik niet zeggen'-frases → schrappen (tenzij de atleet er letterlijk om vroeg; die
# nuance laten we aan de LLM-prompt, hier verwijderen we de generieke variant).
_DEFENSIVE = (
    "dat kan ik niet uit de data halen", "op basis van de beschikbare data niet te zeggen",
    "geeft daar geen duidelijk antwoord", "kan ik niet met zekerheid zeggen op basis van",
    "dat is uit de data niet",
)

# Klacht-/follow-up-zin (semantische dedupe per lichaamsdeel): 'hou ... in de gaten hoe je X ...',
# 'hoe reageert je X', etc.
_COMPLAINT_SENT = re.compile(
    r"(hou.*in de gaten hoe je (\w+)|hoe reageert je (\w+)|let op.*je (\w+)|hoe voelt je (\w+))", re.I)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list:
    return [s.strip() for s in _SENT_SPLIT.split((text or "").strip()) if s.strip()]


def _complaint_area(sentence: str):
    m = _COMPLAINT_SENT.search(sentence or "")
    if not m:
        return None
    for g in m.groups()[1:]:
        if g:
            return g.lower()
    return "_algemeen"


def _norm_ws(sentence: str) -> str:
    """Alleen witruimte normaliseren — identiek aan `feedback_facts._norm` (de verbatim-toets)."""
    return re.sub(r"\s+", " ", (sentence or "")).strip()


def _key(sentence: str) -> str:
    """Losse sleutel voor ontdubbeling: hoofdletter- en interpunctie-ongevoelig."""
    return re.sub(r"\s+", " ", (sentence or "").lower()).strip(" .!?")


def clean_draft(text: str, protected=()) -> str:
    """Deterministische CopyQuality-opschoning. Schrapt systeemtaal/defensieve zinnen, ontdubbelt
    exact + semantisch (klacht/follow-up per onderwerp één keer), houdt de rest in volgorde.

    `protected` = de APPLICATION-OWNED zinnen uit de fact-pack (assemble_spine). Die zijn na de
    generatie VERPLICHT en worden verbatim gevalideerd (`feedback_facts.validate_draft`), dus deze
    opschoning mag ze NOOIT verwijderen. Zonder die bescherming botsten twee contracten: schreef het
    model zelf een variant van de klacht-check-in, dan zag de dedupe de APP-zin als tweede zin over
    hetzelfde onderwerp en gooide hem weg — waarna de validator de verplichte zin miste en het
    concept blokkeerde ('inhoudelijke controle niet gehaald') terwijl er inhoudelijk niets mis was.
    Botst een vrije zin met een beschermde, dan sneuvelt de VRIJE zin, ongeacht de volgorde."""
    # Beschermd = VERBATIM (alleen witruimte genormaliseerd) gelijk aan een verplichte zin: precies
    # de vergelijking die `validate_draft` straks doet. Een variant met andere hoofdletters of
    # interpunctie is dus NIET de verplichte zin en telt hier als vrije tekst.
    # Coachstem eerst: de tekst gaat NAMENS de coach naar de atleet, dus een zin die over
    # 'de coach' praat alsof dat iemand anders is, wordt hier al omgezet — vóór de dedupe,
    # zodat twee van zulke zinnen samen één blijven.
    text = naar_coachstem(text)
    prot_exact = {_norm_ws(p) for p in (protected or []) if _norm_ws(p)}
    prot_loose = {_key(p) for p in (protected or []) if _key(p)}
    prot_areas = {a for a in (_complaint_area(p) for p in (protected or [])) if a is not None}
    out = []
    seen_norm = set()
    seen_complaint_area = set()
    for s in _sentences(text):
        low = s.lower()
        norm = _key(s)
        beschermd = _norm_ws(s) in prot_exact
        if norm in seen_norm:
            continue                                         # exacte dubbel (ook een tweede app-zin)
        if not beschermd:
            if any(t in low for t in _SYSTEM_TERMS):
                continue                                     # interne/technische zin → weg
            if any(d in low for d in _DEFENSIVE):
                continue                                     # generieke defensieve disclaimer → weg
            if norm in prot_loose:
                continue                                     # variant van een verplichte zin → wijkt
        area = _complaint_area(s)
        if area is not None:
            # Een vrije zin over een onderwerp waarover ook een BESCHERMDE zin bestaat, wijkt: de
            # app-eigen formulering is de waarheid en moet verbatim overleven.
            if not beschermd and (area in seen_complaint_area or area in prot_areas):
                continue
            seen_complaint_area.add(area)
        seen_norm.add(norm)
        out.append((s, beschermd))
    return " ".join(_focus(out, len(prot_exact))).strip()


# Een coachreactie is geen analyseverslag. De LENGTE was tot nu toe uitsluitend een
# promptinstructie, terwijl diezelfde prompt tientallen voorwaardelijke 'noem dit ook'-
# regels bevat; het model loste dat op door over élk onderwerp een zin te schrijven
# (live: negen zinnen over voeding, taper, herstel én een schemawijziging op één
# rommelige duurloop). Dit is het deterministische vangnet daaronder, geen stijlregel:
# vijf vrije zinnen, plus ruimte voor elke APPLICATION-OWNED feitzin die er sowieso in
# moet. Complexere cases hebben per constructie meer verplichte zinnen en krijgen dus
# vanzelf meer ruimte. Bewust GEEN tekenlimiet: die kapt een nuttig antwoord middenin af.
_VRIJE_ZINNEN = 5


def _focus(zinnen, aantal_beschermd: int) -> list:
    """Snoei een uitgelopen concept terug tot zijn kern. De SLOTZIN blijft altijd staan:
    daar zit de vervolgstap of de check-in, en een bericht dat abrupt ophoudt is erger dan
    een lange. Er verdwijnt dus alleen middenmoot, precies waar de algemene uitweiding zit."""
    budget = _VRIJE_ZINNEN + aantal_beschermd
    vrij = [i for i, (_, beschermd) in enumerate(zinnen) if not beschermd]
    over = len(vrij) - budget
    if over <= 0:
        return [z for z, _ in zinnen]
    # Van achteren naar voren schrappen, maar de LAATSTE vrije zin overslaan.
    weg = set()
    for i in reversed(vrij[:-1]):
        if over <= 0:
            break
        weg.add(i)
        over -= 1
    return [z for i, (z, _) in enumerate(zinnen) if i not in weg]


# ── Coachstem: de tekst gaat NAMENS de coach naar de atleet ──────────────────
# De systeemprompt zette de schrijver naast de coach ("je schrijft namens een
# hardloopcoach ... de coach heet Jip ... neem zijn TOON over") en zei nergens dat je
# DE COACH BENT. Het model schreef daardoor over hem in de derde persoon — live:
# "dit is een beslissing die de coach zelf met je door moet nemen voordat hij iets
# aanpast in het schema". Voor de atleet leest dat als een systeem dat over haar coach
# praat. De structurele oplossing zit in de prompt (ik-vorm als rolcontract); dit is het
# deterministische vangnet eronder.
#
# `als je coach ...` en `ik ben je coach` zijn juist WEL eerste persoon en blijven staan.
_DERDE_COACH = re.compile(
    r"(?<!als )(?<!ben )\b(?:de|je|jouw|jullie|zijn|haar)\s+coach\b"
    r"|(?<!je )(?<!de )\bcoach\s+(?:moet|kan|zal|gaat|wil|bepaalt|bekijkt|bespreekt)\b", re.I)

# De app-eigen vervanging. Eén canonieke zin in plaats van een woord-voor-woord-omzetting:
# Nederlandse werkwoordcongruentie is met patronen niet betrouwbaar te repareren
# ("voordat hij iets aanpast" -> "voordat ik iets aanpas" vergt een zinsontleding), en een
# half omgezette zin is erger dan geen. Deze zin behoudt de BEDOELING van elke variant die
# we zien — de beslissing eerst samen bespreken — in directe coachstem, en claimt niets
# over het schema. Zelfde mechanisme als de verplichte feitzinnen: de app bezit de zin.
COACH_DELEGATIE_ZIN = "Laten we dit eerst samen doornemen voordat we iets veranderen."


def derde_persoon_coach(text: str) -> bool:
    """Spreekt deze tekst over de coach alsof dat iemand anders is?"""
    return bool(_DERDE_COACH.search(text or ""))


def naar_coachstem(text: str) -> str:
    """Vervang elke zin die over de coach in de derde persoon spreekt door de app-eigen
    eerste-persoonszin. Meerdere van zulke zinnen worden er samen één."""
    uit, gezet = [], False
    for zin in _sentences(text):
        if not derde_persoon_coach(zin):
            uit.append(zin)
            continue
        if not gezet:
            uit.append(COACH_DELEGATIE_ZIN)
            gezet = True
    return " ".join(uit).strip()


# ── Minimum usefulness: waar gaat de atleet het over? ────────────────────────
# `safe_fallback` bouwde uitsluitend uit de eigen atomen van de app. Had een training geen
# bruikbare atomen (geen structuur, geen laps), dan bleef er letterlijk één zin over:
# "Dank je voor je bericht, ik neem mee wat je over deze training schrijft." Veilig, maar
# de atleet had net drie dingen gemeld. Deze functie levert de ENIGE bron die dan nog
# betrouwbaar is: de eigen woorden van de atleet, letterlijk — geen interpretatie, geen
# samenvatting, geen woordenlijst.
_KERNPUNT_MAX = 140


def kernpunten(athlete_text: str) -> list:
    """De inhoudelijke zinnen uit het atleetbericht, letterlijk, op VOLGORDE VAN BELANG.

    Een VRAAG staat vooraan: die moet sowieso beantwoord worden. Daarna de overige
    inhoudelijke zinnen in de volgorde waarin de atleet ze schreef. Het is een LIJST en geen
    enkele keuze, omdat de eigen woorden van de atleet een output-guard kunnen raken (een
    vraag over 'morgen' botst met de dagwoord-guard). De aanroeper die de validator-context
    bezit loopt de kandidaten af; hier wordt niets geïnterpreteerd of samengevat."""
    zinnen = [_norm_ws(z) for z in _sentences(athlete_text) if _norm_ws(z)]
    inhoud = [z for z in zinnen if len(_WORD.findall(z)) >= _SUBSTANTIVE_MIN_WORDS]
    vragen = [z for z in inhoud if "?" in z]
    rest = [z for z in inhoud if "?" not in z]
    return [_kort(z) for z in (vragen + rest) if _kort(z)]


def kernpunt(athlete_text: str) -> str:
    """De meest sturende zin uit het atleetbericht (de eerste kandidaat), of ""."""
    k = kernpunten(athlete_text)
    return k[0] if k else ""


def _kort(zin: str) -> str:
    if len(zin) <= _KERNPUNT_MAX:
        return zin
    kort = zin[:_KERNPUNT_MAX].rsplit(" ", 1)[0].rstrip(" ,;:")
    return kort + "..." if kort else ""


# Een concept dat ALLEEN bedankt voor het bericht zegt inhoudelijk niets. Bewust smal
# gedefinieerd: niet 'is deze tekst rijk genoeg' (dat is een oordeel), maar 'bestaat hij
# uitsluitend uit een generieke bedank-/erkenningszin' (dat is te bewijzen).
_GENERIEKE_ACK = re.compile(
    r"^(dank\w*|bedankt|fijn|goed|top)\b[^.!?]*\b(bericht|berichtje|update|reactie|melding)\b[^.!?]*$",
    re.I)


def is_generieke_erkenning(text: str) -> bool:
    """Bestaat het hele concept uitsluitend uit generieke erkenning zonder inhoud?"""
    zinnen = [_norm_ws(z).rstrip(" .!?") for z in _sentences(text) if _norm_ws(z)]
    return bool(zinnen) and all(_GENERIEKE_ACK.match(z) for z in zinnen)


def has_system_language(text: str) -> bool:
    low = (text or "").lower()
    return any(t in low for t in _SYSTEM_TERMS) or any(d in low for d in _DEFENSIVE)


# ── CoachingIntent (athlete-first, data-second) ───────────────────────────────
ACKNOWLEDGE, ANSWER, REASSURE, COACH_CUE, PLAN_ADJUST, REVIEW_DATA = \
    "ACKNOWLEDGE", "ANSWER", "REASSURE", "COACH_CUE", "PLAN_ADJUST", "REVIEW_DATA"

_Q = re.compile(r"\?")
_DOUBT = re.compile(r"\b(twijfel|onzeker|weet niet zeker|bang dat|klopt dat wel|te (hard|langzaam|snel)\?|"
                    r"ging het wel|was dit goed|deed ik het)\b", re.I)
_PLAN_WORDS = re.compile(r"\b(schema|aanpass|verzet|volgende week|planning|fysio|blessure|geblesseerd|"
                         r"niet lopen|rust nemen)\b|pijn", re.I)
_DATA_ASK = re.compile(r"\b(hartslag|zone|tempo|pace|hoe hard|hoeveel|gemiddelde|zat ik|liep ik|data|cijfers)\b", re.I)
# 'pijn' zonder linker-woordgrens: het Nederlands plakt de klacht aan het lichaamsdeel
# (hoofdpijn, spierpijn, buikpijn). Met `\bpijn\b` viel precies de gemelde case ('hoofdpijn')
# buiten élke klacht-herkenning. Een woordgrens die het echte vocabulaire uitsluit is een fout
# in de grens, geen reden om woorden te gaan opsommen.
_COMPLAINT_WORD = re.compile(
    r"pijn|blessure|geblesseerd|zeer|ontsteking|scheen|knie|hiel|kuit|achilles|hamstring|lies|"
    r"\bvoet\b|enkel|\brug\b|last van|stijf", re.I)

# Een bericht is INHOUDELIJK zodra het meer is dan een korte beleefdheid ('top', 'lekker gelopen').
# Bewust een LENGTE-grens en géén woordenlijst: elke opsomming van 'relevante' woorden mist de
# volgende formulering (precies hoe 'hoofdpijn' en 'niet fit' door alle filters glipten). Wat de
# atleet inhoudelijk meldt hoeft de app niet te BEGRIJPEN om te weten dat er op gereageerd moet
# worden — alleen dát er iets gemeld is.
_SUBSTANTIVE_MIN_WORDS = 4
_WORD = re.compile(r"\w+", re.UNICODE)


def is_substantive(athlete_text: str) -> bool:
    """Schreef de atleet meer dan een korte beleefdheid? Dan moet de coachreactie daarop aansluiten."""
    return len(_WORD.findall(athlete_text or "")) >= _SUBSTANTIVE_MIN_WORDS


def classify_intent(athlete_text: str) -> dict:
    """Eenvoudige deterministische coaching-intentie. Stuurt of data nodig is en hoeveel."""
    t = (athlete_text or "").strip()
    present = bool(t)
    question = bool(_Q.search(t))
    complaint = bool(_COMPLAINT_WORD.search(t))
    plan = bool(_PLAN_WORDS.search(t))
    data_ask = bool(_DATA_ASK.search(t))
    if question:
        primary = ANSWER
    elif plan:
        primary = PLAN_ADJUST
    elif _DOUBT.search(t):
        primary = REASSURE
    elif present:
        primary = ACKNOWLEDGE
    else:
        primary = REVIEW_DATA                                # geen atleetbericht → data mag leiden
    data_needed = bool(data_ask or question or primary in (PLAN_ADJUST, REVIEW_DATA))
    max_data_points = 2 if data_ask else (1 if data_needed else 0)
    return {"primary": primary, "athlete_message_present": present, "question_present": question,
            "complaint_active": complaint, "data_needed": data_needed,
            "substantive": is_substantive(t), "max_data_points": max_data_points}
