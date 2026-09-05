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


def clean_draft(text: str) -> str:
    """Deterministische CopyQuality-opschoning. Schrapt systeemtaal/defensieve zinnen, ontdubbelt
    exact + semantisch (klacht/follow-up per onderwerp één keer), houdt de rest in volgorde."""
    out = []
    seen_norm = set()
    seen_complaint_area = set()
    for s in _sentences(text):
        low = s.lower()
        if any(t in low for t in _SYSTEM_TERMS):
            continue                                         # interne/technische zin → weg
        if any(d in low for d in _DEFENSIVE):
            continue                                         # generieke defensieve disclaimer → weg
        norm = re.sub(r"\s+", " ", low).strip(" .!?")
        if norm in seen_norm:
            continue                                         # exacte dubbel
        area = _complaint_area(s)
        if area is not None:
            if area in seen_complaint_area:
                continue                                     # semantische dubbel: 2e klacht-zin zelfde onderwerp
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
                         r"pijn|niet lopen|rust nemen)\b", re.I)
_DATA_ASK = re.compile(r"\b(hartslag|zone|tempo|pace|hoe hard|hoeveel|gemiddelde|zat ik|liep ik|data|cijfers)\b", re.I)
_COMPLAINT_WORD = re.compile(
    r"\bpijn\b|blessure|geblesseerd|zeer|ontsteking|scheen|knie|hiel|kuit|achilles|hamstring|lies|"
    r"\bvoet\b|enkel|\brug\b|last van|stijf", re.I)


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
            "complaint_active": complaint, "data_needed": data_needed, "max_data_points": max_data_points}
