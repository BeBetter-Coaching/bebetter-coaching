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
        out.append(s)
    return " ".join(out).strip()


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
